"""Authentication manager supporting registration, login, and email OTP verification."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import hmac
import re
import secrets
from typing import Any, Optional

from src.auth.email_service import EmailService
from src.storage.database import DatabaseManager

_EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_OTP_EXPIRY_MINUTES = 10
_MAX_OTP_ATTEMPTS = 5


@dataclass(frozen=True)
class AuthResult:
    """Result returned by authentication and OTP verification operations."""

    success: bool
    message: str
    requires_verification: bool = False
    email: str = ""
    user: Optional[dict[str, Any]] = None
    demo_otp: Optional[str] = None


class AuthManager:
    """Handles user registration, password hashing, and email OTP verification."""

    def __init__(
        self,
        db: DatabaseManager,
        email_service: Optional[EmailService] = None,
    ) -> None:
        self._db = db
        self._email_service = email_service or EmailService()

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            100_000,
        )
        return dk.hex()

    @staticmethod
    def _hash_otp(code: str) -> str:
        return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()

    @staticmethod
    def _generate_otp() -> str:
        return f"{secrets.randbelow(900_000) + 100_000:06d}"

    def register(
        self,
        full_name: str,
        email: str,
        password: str,
        campus: str = "",
    ) -> AuthResult:
        """Create a new account and send a 6-digit email verification code."""
        clean_name = full_name.strip()
        clean_email = email.strip().lower()
        clean_campus = campus.strip()

        if len(clean_name) < 2:
            return AuthResult(False, "Please enter your full name.")
        if not _EMAIL_REGEX.match(clean_email):
            return AuthResult(False, "Please enter a valid email address.")
        if len(password) < 6:
            return AuthResult(False, "Password must be at least 6 characters long.")

        existing = self._db.get_user_by_email(clean_email)
        if existing is not None:
            if existing.get("is_verified"):
                return AuthResult(
                    False, "An account with this email already exists. Please sign in."
                )
            if clean_campus:
                self._db.update_user_campus(clean_email, clean_campus)
            # Re-send verification code for an unverified account.
            return self.send_verification_otp(clean_email, purpose="verify")

        salt = secrets.token_hex(16)
        pw_hash = self._hash_password(password, salt)
        self._db.create_user(
            clean_name,
            clean_email,
            pw_hash,
            salt,
            campus=clean_campus,
        )
        return self.send_verification_otp(clean_email, purpose="verify")

    def ensure_admin_account(
        self,
        email: str,
        password: str,
        full_name: str = "System Administrator",
        campus: str = "Main Campus",
    ) -> None:
        """Seed the privileged account once without overwriting user-changed passwords."""
        clean_email = email.strip().lower()
        existing = self._db.get_user_by_email(clean_email)
        if existing is None:
            salt = secrets.token_hex(16)
            pw_hash = self._hash_password(password, salt)
            self._db.create_user(
                full_name=full_name,
                email=clean_email,
                password_hash=pw_hash,
                salt=salt,
                campus=campus,
                is_admin=1,
                is_verified=1,
            )
            return
        self._db.ensure_user_admin_flags(clean_email)

    def change_password(
        self,
        email: str,
        current_password: str,
        new_password: str,
    ) -> AuthResult:
        """Change password for a signed-in user after verifying current password."""
        clean_email = email.strip().lower()
        user = self._db.get_user_by_email(clean_email)
        if user is None:
            return AuthResult(False, "User account not found.")

        cur_hash = self._hash_password(current_password, str(user["salt"]))
        if not hmac.compare_digest(cur_hash, str(user["password_hash"])):
            return AuthResult(False, "Current password is incorrect.")

        if len(new_password) < 6:
            return AuthResult(False, "New password must be at least 6 characters long.")
        if current_password == new_password:
            return AuthResult(False, "New password must be different from current password.")

        new_salt = secrets.token_hex(16)
        new_hash = self._hash_password(new_password, new_salt)
        self._db.update_user_password(clean_email, new_hash, new_salt)
        return AuthResult(True, "Password updated successfully.", email=clean_email)

    def send_verification_otp(self, email: str, purpose: str = "verify") -> AuthResult:
        """Generate and email a fresh 6-digit OTP to an existing user."""
        clean_email = email.strip().lower()
        user = self._db.get_user_by_email(clean_email)
        if user is None:
            return AuthResult(False, "No account found for this email address.")

        code = self._generate_otp()
        expires_at = (
            datetime.now() + timedelta(minutes=_OTP_EXPIRY_MINUTES)
        ).strftime("%Y-%m-%d %H:%M:%S")
        self._db.create_otp(clean_email, self._hash_otp(code), purpose, expires_at)

        send_res = self._email_service.send_otp_email(
            recipient_email=clean_email,
            full_name=str(user.get("full_name", "User")),
            code=code,
            purpose=purpose,
        )
        if not send_res.success:
            return AuthResult(False, send_res.message)

        return AuthResult(
            success=True,
            message=send_res.message,
            requires_verification=True,
            email=clean_email,
            demo_otp=send_res.demo_code,
        )

    def verify_otp(
        self, email: str, code: str, purpose: str = "verify"
    ) -> AuthResult:
        """Verify a 6-digit OTP code, mark account verified, and return user."""
        clean_email = email.strip().lower()
        clean_code = code.strip()
        if not clean_code.isdigit() or len(clean_code) != 6:
            return AuthResult(False, "Please enter the 6-digit verification code.")

        record = self._db.get_latest_active_otp(clean_email, purpose)
        if record is None:
            return AuthResult(
                False, "No active verification code found. Please request a new code."
            )

        if int(record["attempts"]) >= _MAX_OTP_ATTEMPTS:
            self._db.mark_otp_used(int(record["id"]))
            return AuthResult(
                False, "Too many incorrect attempts. Please request a new code."
            )

        expires_at = datetime.strptime(record["expires_at"], "%Y-%m-%d %H:%M:%S")
        if datetime.now() > expires_at:
            self._db.mark_otp_used(int(record["id"]))
            return AuthResult(
                False, "Verification code has expired. Please request a new code."
            )

        expected_hash = str(record["code_hash"])
        if not hmac.compare_digest(self._hash_otp(clean_code), expected_hash):
            self._db.increment_otp_attempts(int(record["id"]))
            remaining = _MAX_OTP_ATTEMPTS - (int(record["attempts"]) + 1)
            return AuthResult(
                False, f"Invalid verification code. {remaining} attempt(s) remaining."
            )

        self._db.mark_otp_used(int(record["id"]))
        self._db.mark_user_verified(clean_email)
        user = self._db.get_user_by_email(clean_email)
        return AuthResult(
            success=True,
            message="Email verified successfully!",
            requires_verification=False,
            email=clean_email,
            user=user,
        )

    def login_with_password(self, email: str, password: str) -> AuthResult:
        """Authenticate using email + password, enforcing email verification."""
        clean_email = email.strip().lower()
        user = self._db.get_user_by_email(clean_email)
        if user is None:
            return AuthResult(False, "Invalid email or password.")

        pw_hash = self._hash_password(password, str(user["salt"]))
        if not hmac.compare_digest(pw_hash, str(user["password_hash"])):
            return AuthResult(False, "Invalid email or password.")

        if not user.get("is_verified"):
            otp_res = self.send_verification_otp(clean_email, purpose="verify")
            return AuthResult(
                success=False,
                message=(
                    "Your email is not verified yet. "
                    + otp_res.message
                ),
                requires_verification=True,
                email=clean_email,
                demo_otp=otp_res.demo_otp,
            )

        return AuthResult(
            success=True,
            message="Signed in successfully.",
            email=clean_email,
            user=user,
        )
