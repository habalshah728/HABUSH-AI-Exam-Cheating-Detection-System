"""SQLite persistence layer for sessions, persons, events, reports, and auth."""

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Optional

from src.detection.tracker import TrackedPerson
from src.scoring.models import Event
from src.utils.exceptions import DatabaseError
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseManager:
    """Encapsulates all SQLite database operations for the monitoring system."""

    def __init__(self, db_path: Path | str = "data/sessions.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn: Optional[sqlite3.Connection] = None
        try:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            yield conn
            conn.commit()
        except sqlite3.Error as exc:
            if conn is not None:
                conn.rollback()
            raise DatabaseError(f"SQLite operation failed: {exc}") from exc
        finally:
            if conn is not None:
                conn.close()

    def _init_schema(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    duration_sec REAL DEFAULT 0,
                    total_people INTEGER DEFAULT 0,
                    total_events INTEGER DEFAULT 0,
                    max_risk TEXT DEFAULT 'Low',
                    user_email TEXT DEFAULT '',
                    campus TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS persons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    track_id INTEGER NOT NULL,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    track_id INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    risk_score INTEGER NOT NULL,
                    risk_level TEXT NOT NULL,
                    timestamp_sec REAL NOT NULL,
                    wall_time TEXT NOT NULL,
                    screenshot_path TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    pdf_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    campus TEXT DEFAULT '',
                    is_admin INTEGER DEFAULT 0,
                    is_verified INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS otp_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    attempts INTEGER DEFAULT 0,
                    is_used INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_email TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            user_cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(users)").fetchall()
            }
            if "campus" not in user_cols:
                conn.execute("ALTER TABLE users ADD COLUMN campus TEXT DEFAULT ''")
            if "is_admin" not in user_cols:
                conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")

            session_cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
            }
            if "campus" not in session_cols:
                conn.execute("ALTER TABLE sessions ADD COLUMN campus TEXT DEFAULT ''")

    # ------------------------------------------------------------------
    # Monitoring sessions, persons, events, and reports
    # ------------------------------------------------------------------

    def create_session(
        self,
        mode: str,
        source_name: str,
        duration_sec: float = 0.0,
        user_email: str = "",
        campus: str = "",
    ) -> int:
        """Insert a new monitoring session and return its ID."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO sessions (mode, source_name, start_time, duration_sec, user_email, campus)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (mode, source_name, now, float(duration_sec), user_email, campus.strip()),
            )
            return int(cur.lastrowid)

    def finalize_session(
        self,
        session_id: int,
        duration_sec: float,
        total_people: int,
        total_events: int,
        max_risk: str,
    ) -> None:
        """Update session totals when monitoring finishes."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET end_time = ?, duration_sec = ?, total_people = ?,
                    total_events = ?, max_risk = ?
                WHERE id = ?
                """,
                (now, float(duration_sec), total_people, total_events, max_risk, session_id),
            )

    def save_persons(self, session_id: int, persons: list[TrackedPerson]) -> None:
        """Persist tracked person lifetimes for a session."""
        if not persons:
            return
        with self._connection() as conn:
            conn.executemany(
                """
                INSERT INTO persons (session_id, track_id, first_seen, last_seen)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (session_id, p.track_id, p.first_seen, p.last_seen)
                    for p in persons
                ],
            )

    def add_event(self, session_id: int, event: Event) -> int:
        """Insert a single flagged event and return its ID."""
        with self._connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO events (
                    session_id, track_id, category, risk_score, risk_level,
                    timestamp_sec, wall_time, screenshot_path, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    event.track_id,
                    event.category,
                    event.risk_score,
                    event.risk_level,
                    event.timestamp_sec,
                    event.wall_time,
                    event.screenshot_path,
                    event.notes,
                ),
            )
            return int(cur.lastrowid)

    def add_report(self, session_id: int, pdf_path: str) -> int:
        """Record a generated PDF report in the database."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO reports (session_id, pdf_path, created_at)
                VALUES (?, ?, ?)
                """,
                (session_id, pdf_path, now),
            )
            return int(cur.lastrowid)

    def get_sessions(self, user_email: str | None = None) -> list[dict[str, Any]]:
        """Return monitoring sessions ordered newest first (optionally filtered by user)."""
        with self._connection() as conn:
            if user_email is not None:
                rows = conn.execute(
                    "SELECT * FROM sessions WHERE LOWER(user_email) = LOWER(?) ORDER BY id DESC",
                    (user_email.strip(),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM sessions ORDER BY id DESC"
                ).fetchall()
            return [dict(row) for row in rows]

    def get_session(self, session_id: int) -> Optional[dict[str, Any]]:
        """Return a single session record by ID."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_event_with_owner(self, event_id: int) -> Optional[dict[str, Any]]:
        """Return a single event with its parent session's owner email."""
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT e.*, s.user_email
                FROM events e
                JOIN sessions s ON s.id = e.session_id
                WHERE e.id = ?
                """,
                (event_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_session_events(self, session_id: int) -> list[dict[str, Any]]:
        """Return all flagged events belonging to a session."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE session_id = ? ORDER BY timestamp_sec ASC, id ASC",
                (session_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_recent_events(
        self, limit: int = 15, user_email: str | None = None
    ) -> list[dict[str, Any]]:
        """Return recent events joined with their session source name."""
        with self._connection() as conn:
            if user_email is not None:
                rows = conn.execute(
                    """
                    SELECT e.*, s.source_name, s.mode
                    FROM events e
                    JOIN sessions s ON s.id = e.session_id
                    WHERE LOWER(s.user_email) = LOWER(?)
                    ORDER BY e.id DESC
                    LIMIT ?
                    """,
                    (user_email.strip(), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT e.*, s.source_name, s.mode
                    FROM events e
                    JOIN sessions s ON s.id = e.session_id
                    ORDER BY e.id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [dict(row) for row in rows]

    def delete_session(self, session_id: int) -> Optional[dict[str, Any]]:
        """Delete a monitoring session and cascade-delete its persons, events, and reports."""
        with self._connection() as conn:
            exists = conn.execute(
                "SELECT id FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if exists is None:
                return None

            shot_rows = conn.execute(
                "SELECT screenshot_path FROM events WHERE session_id = ? AND screenshot_path != ''",
                (session_id,),
            ).fetchall()
            report_rows = conn.execute(
                "SELECT pdf_path FROM reports WHERE session_id = ?",
                (session_id,),
            ).fetchall()

            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return {
                "session_id": session_id,
                "screenshot_paths": [str(r["screenshot_path"]) for r in shot_rows],
                "pdf_paths": [str(r["pdf_path"]) for r in report_rows],
            }

    def delete_event(self, event_id: int) -> Optional[dict[str, Any]]:
        """Delete a single flagged event and recalculate parent session totals."""
        risk_order = {"Low": 0, "Medium": 1, "High": 2}
        with self._connection() as conn:
            row = conn.execute(
                "SELECT session_id, screenshot_path FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                return None

            session_id = int(row["session_id"])
            screenshot_path = str(row["screenshot_path"] or "")
            conn.execute("DELETE FROM events WHERE id = ?", (event_id,))

            rem_rows = conn.execute(
                "SELECT risk_level FROM events WHERE session_id = ?",
                (session_id,),
            ).fetchall()
            total_events = len(rem_rows)
            max_risk = "Low"
            for r in rem_rows:
                lvl = str(r["risk_level"] or "Low")
                if risk_order.get(lvl, 0) > risk_order.get(max_risk, 0):
                    max_risk = lvl

            conn.execute(
                "UPDATE sessions SET total_events = ?, max_risk = ? WHERE id = ?",
                (total_events, max_risk, session_id),
            )

            still_used = 0
            if screenshot_path:
                still_used = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM events WHERE screenshot_path = ?",
                        (screenshot_path,),
                    ).fetchone()[0]
                )

            return {
                "event_id": event_id,
                "session_id": session_id,
                "screenshot_path": screenshot_path,
                "delete_file": bool(screenshot_path and still_used == 0),
                "total_events": total_events,
                "max_risk": max_risk,
            }

    def get_dashboard_stats(self, user_email: str | None = None) -> dict[str, int]:
        """Compute aggregate summary metrics for the Main Dashboard."""
        with self._connection() as conn:
            if user_email is not None:
                clean = user_email.strip()
                videos_count = conn.execute(
                    "SELECT COUNT(*) FROM sessions WHERE mode = 'video' AND LOWER(user_email) = LOWER(?)",
                    (clean,),
                ).fetchone()[0]
                sessions_count = conn.execute(
                    "SELECT COUNT(*) FROM sessions WHERE LOWER(user_email) = LOWER(?)",
                    (clean,),
                ).fetchone()[0]
                people_count = conn.execute(
                    "SELECT COALESCE(SUM(total_people), 0) FROM sessions WHERE LOWER(user_email) = LOWER(?)",
                    (clean,),
                ).fetchone()[0]
                events_count = conn.execute(
                    """
                    SELECT COUNT(*) FROM events e
                    JOIN sessions s ON s.id = e.session_id
                    WHERE LOWER(s.user_email) = LOWER(?)
                    """,
                    (clean,),
                ).fetchone()[0]
                phone_count = conn.execute(
                    """
                    SELECT COUNT(*) FROM events e
                    JOIN sessions s ON s.id = e.session_id
                    WHERE LOWER(e.category) LIKE '%phone%' AND LOWER(s.user_email) = LOWER(?)
                    """,
                    (clean,),
                ).fetchone()[0]
            else:
                videos_count = conn.execute(
                    "SELECT COUNT(*) FROM sessions WHERE mode = 'video'"
                ).fetchone()[0]
                sessions_count = conn.execute(
                    "SELECT COUNT(*) FROM sessions"
                ).fetchone()[0]
                people_count = conn.execute(
                    "SELECT COALESCE(SUM(total_people), 0) FROM sessions"
                ).fetchone()[0]
                events_count = conn.execute(
                    "SELECT COUNT(*) FROM events"
                ).fetchone()[0]
                phone_count = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE LOWER(category) LIKE '%phone%'"
                ).fetchone()[0]
        return {
            "videos_analysed": int(videos_count),
            "monitoring_sessions": int(sessions_count),
            "people_detected": int(people_count),
            "suspicious_activities": int(events_count),
            "phone_detections": int(phone_count),
        }

    # ------------------------------------------------------------------
    # Authentication & OTP verification helpers
    # ------------------------------------------------------------------

    def get_user_by_email(self, email: str) -> Optional[dict[str, Any]]:
        """Fetch a user record by normalized email."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE LOWER(email) = LOWER(?)",
                (email.strip(),),
            ).fetchone()
            return dict(row) if row else None

    def create_user(
        self,
        full_name: str,
        email: str,
        password_hash: str,
        salt: str,
        campus: str = "",
        is_admin: int = 0,
        is_verified: int = 0,
    ) -> int:
        """Create a new user account."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (
                    full_name, email, password_hash, salt, campus, is_admin, is_verified, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    full_name.strip(),
                    email.strip().lower(),
                    password_hash,
                    salt,
                    campus.strip(),
                    int(is_admin),
                    int(is_verified),
                    now,
                ),
            )
            return int(cur.lastrowid)

    def mark_user_verified(self, email: str) -> None:
        """Mark an existing user's email address as verified."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE users SET is_verified = 1 WHERE LOWER(email) = LOWER(?)",
                (email.strip(),),
            )

    def update_user_campus(self, email: str, campus: str) -> None:
        """Update a user's stored campus name when non-empty."""
        clean_campus = campus.strip()
        if not clean_campus:
            return
        with self._connection() as conn:
            conn.execute(
                "UPDATE users SET campus = ? WHERE LOWER(email) = LOWER(?)",
                (clean_campus, email.strip()),
            )

    def update_user_password(self, email: str, password_hash: str, salt: str) -> None:
        """Update password hash and salt for an existing user."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE LOWER(email) = LOWER(?)",
                (password_hash, salt, email.strip()),
            )

    def ensure_user_admin_flags(self, email: str) -> None:
        """Ensure a designated account keeps verified + privileged flags."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE users SET is_admin = 1, is_verified = 1 WHERE LOWER(email) = LOWER(?)",
                (email.strip(),),
            )

    def get_all_users(self, include_admins: bool = False) -> list[dict[str, Any]]:
        """List registered accounts with session/event statistics (no password hashes)."""
        filter_clause = "" if include_admins else "WHERE COALESCE(u.is_admin, 0) = 0"
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT u.id, u.full_name, u.email, COALESCE(u.campus, '') AS campus,
                       u.is_verified, COALESCE(u.is_admin, 0) AS is_admin, u.created_at,
                       COUNT(DISTINCT s.id) AS sessions_count,
                       COUNT(DISTINCT e.id) AS events_count
                FROM users u
                LEFT JOIN sessions s ON LOWER(s.user_email) = LOWER(u.email)
                LEFT JOIN events e ON e.session_id = s.id
                {filter_clause}
                GROUP BY u.id
                ORDER BY u.id DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get_sessions_with_owner(self) -> list[dict[str, Any]]:
        """Return all sessions enriched with owner full_name, campus, and screenshot count."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT s.*,
                       COALESCE(u.full_name, '') AS owner_name,
                       CASE WHEN COALESCE(s.campus, '') != '' THEN s.campus ELSE COALESCE(u.campus, '') END AS effective_campus,
                       COUNT(DISTINCT CASE WHEN e.screenshot_path != '' THEN e.id END) AS screenshot_count
                FROM sessions s
                LEFT JOIN users u ON LOWER(u.email) = LOWER(s.user_email)
                LEFT JOIN events e ON e.session_id = s.id
                GROUP BY s.id
                ORDER BY s.id DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_user(self, user_id: int) -> Optional[dict[str, Any]]:
        """Delete a non-privileged user account by ID."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id, email, COALESCE(is_admin, 0) AS is_admin FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            if int(row["is_admin"]):
                return {"error": "protected"}
            email = str(row["email"])
            conn.execute("DELETE FROM auth_tokens WHERE LOWER(user_email) = LOWER(?)", (email,))
            conn.execute("DELETE FROM otp_codes WHERE LOWER(email) = LOWER(?)", (email,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            return {"id": user_id, "email": email}

    def create_otp(
        self, email: str, code_hash: str, purpose: str, expires_at: str
    ) -> int:
        """Invalidate prior unused OTPs for this email/purpose and store a new one."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE otp_codes
                SET is_used = 1
                WHERE LOWER(email) = LOWER(?) AND purpose = ? AND is_used = 0
                """,
                (email.strip(), purpose),
            )
            cur = conn.execute(
                """
                INSERT INTO otp_codes (email, code_hash, purpose, expires_at, attempts, is_used, created_at)
                VALUES (?, ?, ?, ?, 0, 0, ?)
                """,
                (email.strip().lower(), code_hash, purpose, expires_at, now),
            )
            return int(cur.lastrowid)

    def get_latest_active_otp(
        self, email: str, purpose: str
    ) -> Optional[dict[str, Any]]:
        """Return the latest unused OTP record for an email and purpose."""
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM otp_codes
                WHERE LOWER(email) = LOWER(?) AND purpose = ? AND is_used = 0
                ORDER BY id DESC
                LIMIT 1
                """,
                (email.strip(), purpose),
            ).fetchone()
            return dict(row) if row else None

    def increment_otp_attempts(self, otp_id: int) -> None:
        """Increment failed verification attempt counter."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE otp_codes SET attempts = attempts + 1 WHERE id = ?",
                (otp_id,),
            )

    def mark_otp_used(self, otp_id: int) -> None:
        """Mark an OTP record as consumed."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE otp_codes SET is_used = 1 WHERE id = ?",
                (otp_id,),
            )

    def store_auth_token(self, token_hash: str, user_email: str) -> None:
        """Persist a hashed web session token so logins survive server restarts."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO auth_tokens (token_hash, user_email, created_at)
                VALUES (?, ?, ?)
                """,
                (token_hash, user_email.strip().lower(), now),
            )

    def get_user_by_token_hash(self, token_hash: str) -> Optional[dict[str, Any]]:
        """Look up the verified user associated with a hashed session token."""
        if not token_hash:
            return None
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT u.*
                FROM auth_tokens t
                JOIN users u ON LOWER(u.email) = LOWER(t.user_email)
                WHERE t.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            return dict(row) if row else None

    def revoke_auth_token(self, token_hash: str) -> None:
        """Remove a web session token on logout."""
        if not token_hash:
            return
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM auth_tokens WHERE token_hash = ?",
                (token_hash,),
            )
