"""FastAPI + WebSocket Pro Web Application for the Exam Cheating Detection System."""

import asyncio
import base64
from contextlib import asynccontextmanager
import ctypes
import gc
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import threading
import time
from typing import Any
import uuid

import cv2
from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import numpy as np
from pydantic import BaseModel

from src.auth.auth_manager import AuthManager
from src.reporting.report_generator import ReportGenerator
from src.scoring.engine import DetectionEngine
from src.scoring.models import Event
from src.scoring.session import MonitoringSession
from src.sources.video_source import VideoFileSource
from src.storage.database import DatabaseManager
from src.storage.evidence_saver import EvidenceSaver
from src.utils.config import AppConfig
from src.utils.exceptions import ExamMonitorError

config = AppConfig()
config.ensure_directories()

# Load local .env if present (kept gitignored/dockerignored; cloud hosts use Space/Env Secrets)
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    for _raw in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _raw.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

db = DatabaseManager(config.db_path)
auth_manager = AuthManager(db)
_admin_email = os.getenv("ADMIN_EMAIL", "").strip()
_admin_password = os.getenv("ADMIN_PASSWORD", "").strip()
if _admin_email and _admin_password:
    auth_manager.ensure_admin_account(
        email=_admin_email,
        password=_admin_password,
        full_name="HABUSH System Administrator",
        campus="Central Campus",
    )
report_gen = ReportGenerator(db, config.reports_dir, evidence_dir=config.evidence_dir)

_MODEL_INIT_LOCK = threading.Lock()
_INFER_LOCK = threading.Lock()
_SHARED_MODELS: dict[str, Any] = {}


def _trim_process_memory() -> None:
    """Release unused Python/libc heap pages back to the OS on Linux hosts."""
    gc.collect()
    try:
        if os.name == "posix":
            ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def _get_or_init_shared_models() -> dict[str, Any]:
    """Load and warm the single process-wide YOLO + MediaPipe runtime once."""
    if _SHARED_MODELS.get("ready"):
        return _SHARED_MODELS
    with _MODEL_INIT_LOCK:
        if _SHARED_MODELS.get("ready"):
            return _SHARED_MODELS
        cv2.setNumThreads(2)

        from src.analysis.mediapipe_models import (
            create_face_landmarker,
            create_hand_landmarker,
        )

        model_path = config.models_dir / config.yolo_model_name
        onnx_path = model_path.with_suffix(".onnx")
        if onnx_path.exists() and onnx_path.stat().st_size > 0:
            yolo_model = cv2.dnn.readNetFromONNX(str(onnx_path))
        else:
            import torch
            from ultralytics import YOLO

            torch.set_num_threads(2)
            yolo_ref = str(model_path) if model_path.exists() else config.yolo_model_name
            yolo_model = YOLO(yolo_ref)
        face_mesh = create_face_landmarker(config.models_dir)
        hands = create_hand_landmarker(config.models_dir)

        # Run one tiny dummy warmup frame so first user request avoids JIT/fusion stall.
        warm_engine = DetectionEngine(
            config=config,
            shared_yolo_model=yolo_model,
            shared_face_mesh=face_mesh,
            shared_hands=hands,
            infer_lock=_INFER_LOCK,
        )
        dummy = np.zeros((240, 320, 3), dtype=np.uint8)
        warm_engine.process_frame(dummy, 0.0)
        warm_engine.close()

        _SHARED_MODELS["yolo_model"] = yolo_model
        _SHARED_MODELS["face_mesh"] = face_mesh
        _SHARED_MODELS["hands"] = hands
        _SHARED_MODELS["ready"] = True
        _trim_process_memory()
    return _SHARED_MODELS


def _create_session_engine(confidence: float = 0.40, cooldown: float = 5.0) -> DetectionEngine:
    """Create a lightweight per-session DetectionEngine backed by cached models."""
    shared = _get_or_init_shared_models()
    engine = DetectionEngine(
        config=config,
        shared_yolo_model=shared["yolo_model"],
        shared_face_mesh=shared["face_mesh"],
        shared_hands=shared["hands"],
        infer_lock=_INFER_LOCK,
    )
    engine.set_confidence(confidence)
    engine.set_alert_cooldown(cooldown)
    return engine


def _warmup_models() -> None:
    """Pre-warm YOLO + MediaPipe runtimes in a worker thread after server startup."""
    try:
        _get_or_init_shared_models()
    except Exception:
        pass


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    asyncio.create_task(asyncio.to_thread(_warmup_models))
    yield


app = FastAPI(
    title="HABUSH CMS — AI Exam Integrity Platform",
    version="1.1.0",
    lifespan=_lifespan,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/evidence", StaticFiles(directory=str(config.evidence_dir)), name="evidence")

# Uploaded video registry (per-instance upload paths)
_UPLOADS: dict[str, Path] = {}


class RegisterRequest(BaseModel):
    full_name: str
    email: str
    password: str
    campus: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str
    campus: str = ""


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class VerifyOtpRequest(BaseModel):
    email: str
    code: str


class ResendOtpRequest(BaseModel):
    email: str


def _safe_user_payload(user: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": user["id"],
        "full_name": user["full_name"],
        "email": user["email"],
        "campus": str(user.get("campus") or ""),
    }
    if int(user.get("is_admin") or 0) == 1:
        payload["is_admin"] = True
    return payload


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_session_token(user_row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    token = secrets.token_urlsafe(32)
    db.store_auth_token(_hash_token(token), str(user_row["email"]))
    return token, _safe_user_payload(user_row)


def _resolve_token(token: str) -> dict[str, Any] | None:
    clean = token.strip()
    if not clean:
        return None
    user_row = db.get_user_by_token_hash(_hash_token(clean))
    if user_row is None:
        return None
    return _safe_user_payload(user_row)


def _get_current_user(request: Request) -> dict[str, Any]:
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    user = _resolve_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def _require_admin(request: Request) -> dict[str, Any]:
    user = _get_current_user(request)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Access denied.")
    return user


def _encode_jpeg_b64(frame_bgr: np.ndarray, quality: int = 75) -> str:
    ok, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return ""
    return base64.b64encode(buf.tobytes()).decode("ascii")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the Pro UI/UX single-page web application."""
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/healthz")
async def health_check():
    """Lightweight health check endpoint for cloud hosts and keep-alive monitors."""
    return {"status": "ok"}


# ----------------------------------------------------------------------
# Authentication & Email OTP Endpoints
# ----------------------------------------------------------------------


@app.post("/api/auth/register")
async def api_register(payload: RegisterRequest):
    res = auth_manager.register(
        payload.full_name, payload.email, payload.password, campus=payload.campus
    )
    return {
        "success": res.success,
        "message": res.message,
        "requires_verification": res.requires_verification,
        "email": res.email,
        "demo_otp": res.demo_otp,
    }


@app.post("/api/auth/login")
async def api_login(payload: LoginRequest):
    res = auth_manager.login_with_password(payload.email, payload.password)
    if res.success and res.user is not None:
        if payload.campus.strip():
            db.update_user_campus(res.user["email"], payload.campus.strip())
            res.user["campus"] = payload.campus.strip()
        token, safe_user = _create_session_token(res.user)
        return {
            "success": True,
            "message": res.message,
            "token": token,
            "user": safe_user,
        }
    return {
        "success": False,
        "message": res.message,
        "requires_verification": res.requires_verification,
        "email": res.email,
        "demo_otp": res.demo_otp,
    }


@app.post("/api/auth/verify-otp")
async def api_verify_otp(payload: VerifyOtpRequest):
    res = auth_manager.verify_otp(payload.email, payload.code, purpose="verify")
    if res.success and res.user is not None:
        token, safe_user = _create_session_token(res.user)
        return {
            "success": True,
            "message": res.message,
            "token": token,
            "user": safe_user,
        }
    return {"success": False, "message": res.message}


@app.post("/api/auth/resend-otp")
async def api_resend_otp(payload: ResendOtpRequest):
    res = auth_manager.send_verification_otp(payload.email, purpose="verify")
    return {
        "success": res.success,
        "message": res.message,
        "demo_otp": res.demo_otp,
    }


@app.get("/api/auth/me")
async def api_me(request: Request):
    return {"user": _get_current_user(request)}


@app.post("/api/auth/change-password")
async def api_change_password(payload: ChangePasswordRequest, request: Request):
    user = _get_current_user(request)
    res = auth_manager.change_password(
        user["email"], payload.current_password, payload.new_password
    )
    return {"success": res.success, "message": res.message}


@app.post("/api/auth/logout")
async def api_logout(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if token:
        db.revoke_auth_token(_hash_token(token))
    return {"success": True}


# ----------------------------------------------------------------------
# Privileged Overview (Only Accessible After Authorized Sign-In)
# ----------------------------------------------------------------------


@app.get("/api/admin/overview")
async def api_admin_overview(request: Request):
    _require_admin(request)
    accounts = db.get_all_users(include_admins=False)
    reports = db.get_sessions_with_owner()
    for r in reports:
        sid = int(r["id"])
        snap = config.evidence_dir / f"session_{sid}" / "session_snapshot.png"
        r["has_snapshot"] = snap.exists()
    return {
        "total_accounts": len(accounts),
        "verified_accounts": sum(1 for a in accounts if a.get("is_verified")),
        "total_sessions": len(reports),
        "total_events": sum(int(r.get("total_events") or 0) for r in reports),
        "accounts": accounts,
        "reports": reports,
    }


@app.delete("/api/admin/users/{user_id}")
async def api_admin_delete_user(user_id: int, request: Request):
    _require_admin(request)
    res = db.delete_user(user_id)
    if res is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if res.get("error") == "protected":
        raise HTTPException(status_code=400, detail="Protected account cannot be deleted.")
    return {"success": True, **res}


# ----------------------------------------------------------------------
# Dashboard, Sessions, and PDF Reports
# ----------------------------------------------------------------------


def _resolve_screenshot_url(raw_path: str, session_id: int) -> str:
    if not raw_path:
        return ""
    candidate = Path(raw_path)
    if not candidate.exists():
        candidate = config.evidence_dir / f"session_{session_id}" / candidate.name
    if not candidate.exists():
        return ""
    try:
        rel = candidate.resolve().relative_to(config.evidence_dir.resolve())
        return f"/evidence/{rel.as_posix()}"
    except Exception:
        return ""


def _record_live_events(
    session_id: int,
    result: Any,
    evidence_saver: EvidenceSaver,
    max_risk: str,
    risk_order: dict[str, int],
) -> tuple[list[dict[str, Any]], int, int, str]:
    """Persist flagged events and annotated screenshots for live WS streams."""
    for assessment in result.assessments.values():
        if risk_order.get(assessment.level, 0) > risk_order.get(max_risk, 0):
            max_risk = assessment.level

    payload: list[dict[str, Any]] = []
    events_added = 0
    shots_added = 0
    for evt in result.new_events:
        shot_path = evidence_saver.save_screenshot(
            session_id=session_id,
            track_id=evt.track_id,
            category=evt.category,
            timestamp_sec=evt.timestamp_sec,
            frame=result.annotated_frame,
        )
        if shot_path:
            shots_added += 1
        saved_evt = Event(
            timestamp_sec=evt.timestamp_sec,
            wall_time=evt.wall_time,
            track_id=evt.track_id,
            category=evt.category,
            risk_score=evt.risk_score,
            risk_level=evt.risk_level,
            screenshot_path=shot_path,
            notes=evt.notes,
        )
        db.add_event(session_id, saved_evt)
        events_added += 1
        payload.append(
            {
                "timestamp_sec": round(saved_evt.timestamp_sec, 1),
                "track_id": saved_evt.track_id,
                "category": saved_evt.category,
                "risk_score": saved_evt.risk_score,
                "risk_level": saved_evt.risk_level,
            }
        )
    return payload, events_added, shots_added, max_risk


def _can_access_owner(user: dict[str, Any], owner_email: str) -> bool:
    if user.get("is_admin"):
        return True
    return str(owner_email or "").strip().lower() == str(user.get("email", "")).strip().lower()


@app.get("/api/dashboard")
async def api_dashboard(request: Request):
    user = _get_current_user(request)
    scope_email = None if user.get("is_admin") else user["email"]
    recent_events = db.get_recent_events(limit=15, user_email=scope_email)
    for evt in recent_events:
        evt["screenshot_url"] = _resolve_screenshot_url(
            str(evt.get("screenshot_path", "")), int(evt["session_id"])
        )
    return {
        "stats": db.get_dashboard_stats(user_email=scope_email),
        "recent_events": recent_events,
        "sessions": db.get_sessions(user_email=scope_email)[:15],
    }


@app.get("/api/sessions")
async def api_sessions(request: Request):
    user = _get_current_user(request)
    scope_email = None if user.get("is_admin") else user["email"]
    return {"sessions": db.get_sessions(user_email=scope_email)}


@app.get("/api/sessions/{session_id}")
async def api_session_detail(session_id: int, request: Request):
    user = _get_current_user(request)
    session = db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if not _can_access_owner(user, str(session.get("user_email", ""))):
        raise HTTPException(status_code=403, detail="Access denied.")
    events = db.get_session_events(session_id)
    for evt in events:
        evt["screenshot_url"] = _resolve_screenshot_url(
            str(evt.get("screenshot_path", "")), session_id
        )
    snapshot_path = config.evidence_dir / f"session_{session_id}" / "session_snapshot.png"
    snapshot_url = (
        f"/evidence/session_{session_id}/session_snapshot.png"
        if snapshot_path.exists()
        else ""
    )
    return {"session": session, "events": events, "snapshot_url": snapshot_url}


@app.delete("/api/sessions/{session_id}")
async def api_delete_session(session_id: int, request: Request):
    user = _get_current_user(request)
    session = db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if not _can_access_owner(user, str(session.get("user_email", ""))):
        raise HTTPException(status_code=403, detail="Access denied.")
    deleted = db.delete_session(session_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    shutil.rmtree(config.evidence_dir / f"session_{session_id}", ignore_errors=True)
    for sp in deleted.get("screenshot_paths", []):
        if sp:
            Path(sp).unlink(missing_ok=True)
    for rp in deleted.get("pdf_paths", []):
        if rp:
            Path(rp).unlink(missing_ok=True)
    (config.reports_dir / f"exam_report_session_{session_id}.pdf").unlink(missing_ok=True)
    return {"success": True, "session_id": session_id}


@app.delete("/api/events/{event_id}")
async def api_delete_event(event_id: int, request: Request):
    user = _get_current_user(request)
    evt = db.get_event_with_owner(event_id)
    if evt is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    if not _can_access_owner(user, str(evt.get("user_email", ""))):
        raise HTTPException(status_code=403, detail="Access denied.")
    deleted = db.delete_event(event_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    if deleted.get("delete_file") and deleted.get("screenshot_path"):
        Path(deleted["screenshot_path"]).unlink(missing_ok=True)
    return {"success": True, **deleted}


@app.get("/api/reports/{session_id}/pdf")
async def api_download_pdf(session_id: int, token: str = ""):
    user = _resolve_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    session = db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if not _can_access_owner(user, str(session.get("user_email", ""))):
        raise HTTPException(status_code=403, detail="Access denied.")
    try:
        pdf_path = report_gen.generate(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path=str(pdf_path),
        filename=pdf_path.name,
        media_type="application/pdf",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


# ----------------------------------------------------------------------
# Video Upload & WebSocket Real-Time Analysis
# ----------------------------------------------------------------------


@app.post("/api/videos/upload")
async def api_upload_video(request: Request, file: UploadFile = File(...)):
    _get_current_user(request)
    filename = file.filename or "exam_video.mp4"
    ext = Path(filename).suffix.lower()
    if ext not in config.supported_video_extensions:
        raise HTTPException(
            status_code=400,
            detail="Unsupported video format. Please upload an MP4 or AVI file.",
        )

    upload_id = uuid.uuid4().hex[:12]
    safe_name = f"{upload_id}_{Path(filename).name}"
    dest = config.uploads_dir / safe_name
    content = await file.read()
    dest.write_bytes(content)

    preview_b64 = ""
    try:
        probe = VideoFileSource(dest)
        probe.open()
        meta = probe.get_metadata()
        ok_prev, prev_frame, _ = probe.read()
        if ok_prev and prev_frame is not None:
            ph, pw = prev_frame.shape[:2]
            if pw > 640:
                prev_frame = cv2.resize(
                    prev_frame,
                    (640, max(1, int(ph * 640 / float(pw)))),
                    interpolation=cv2.INTER_AREA,
                )
            preview_b64 = _encode_jpeg_b64(prev_frame, quality=72)
        probe.release()
    except ExamMonitorError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _UPLOADS[upload_id] = dest
    return {
        "upload_id": upload_id,
        "filename": filename,
        "duration_sec": meta.duration_sec,
        "width": meta.width,
        "height": meta.height,
        "fps": meta.fps,
        "total_frames": meta.total_frames,
        "size_mb": round(len(content) / (1024 * 1024), 2),
        "preview_image": preview_b64,
    }


@app.websocket("/ws/analyze-video/{upload_id}")
async def ws_analyze_video(
    websocket: WebSocket,
    upload_id: str,
    token: str = "",
    frame_skip: int = 4,
    confidence: float = 0.40,
    cooldown: float = 5.0,
):
    await websocket.accept()
    user = _resolve_token(token)
    video_path = _UPLOADS.get(upload_id)
    if video_path is None:
        video_path = next(config.uploads_dir.glob(f"{upload_id}_*"), None)
    if user is None or video_path is None or not video_path.exists():
        await websocket.send_json({"type": "error", "message": "Invalid session or video."})
        await websocket.close()
        return

    await websocket.send_json({"type": "status", "message": "Initializing AI detection pipeline..."})
    engine = await asyncio.to_thread(_create_session_engine, confidence, cooldown)
    source = VideoFileSource(video_path)
    evidence_saver = EvidenceSaver(config.evidence_dir, cooldown_sec=0.0)
    session = MonitoringSession(
        mode="video",
        source=source,
        engine=engine,
        db=db,
        evidence_saver=evidence_saver,
        frame_skip=frame_skip,
        user_email=user["email"],
        campus=user.get("campus", ""),
    )

    try:
        session_id = session.start()
        await websocket.send_json({"type": "started", "session_id": session_id})

        while True:
            has_more, result = await asyncio.to_thread(session.next_analyzed_step)
            if not has_more:
                break
            if result is None:
                continue

            stats = session.stats
            frame_b64 = _encode_jpeg_b64(result.annotated_frame, quality=72)
            events_payload = [
                {
                    "timestamp_sec": round(e.timestamp_sec, 1),
                    "track_id": e.track_id,
                    "category": e.category,
                    "risk_score": e.risk_score,
                    "risk_level": e.risk_level,
                    "notes": e.notes,
                }
                for e in result.new_events
            ]
            await websocket.send_json(
                {
                    "type": "frame",
                    "image": frame_b64,
                    "timestamp_sec": round(result.timestamp_sec, 1),
                    "progress": round(stats.progress_ratio * 100, 1) if stats else 0,
                    "people": stats.total_people if stats else 0,
                    "events_count": stats.total_events if stats else 0,
                    "phones_found": stats.phones_found if stats else 0,
                    "max_risk": stats.max_risk if stats else "Low",
                    "new_events": events_payload,
                }
            )
            await asyncio.sleep(0.001)

        final_stats = session.stop()
        await websocket.send_json(
            {
                "type": "completed",
                "session_id": session_id,
                "people": final_stats.total_people if final_stats else 0,
                "events_count": final_stats.total_events if final_stats else 0,
                "max_risk": final_stats.max_risk if final_stats else "Low",
            }
        )
    except WebSocketDisconnect:
        session.stop()
    except Exception as exc:
        session.stop()
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        engine.close()
        _trim_process_memory()


# ----------------------------------------------------------------------
# Live Browser Webcam WebSocket (Works Locally & Deployed Live!)
# ----------------------------------------------------------------------


@app.websocket("/ws/live-webcam")
async def ws_live_webcam(websocket: WebSocket, token: str = ""):
    await websocket.accept()
    user = _resolve_token(token)
    if user is None:
        await websocket.send_json({"type": "error", "message": "Authentication required."})
        await websocket.close()
        return

    engine = await asyncio.to_thread(_create_session_engine)
    evidence_saver = EvidenceSaver(config.evidence_dir, cooldown_sec=0.0)
    session_id = db.create_session(
        mode="live",
        source_name="Browser Live Webcam",
        duration_sec=0.0,
        user_email=user["email"],
        campus=user.get("campus", ""),
    )
    start_t = time.monotonic()
    total_events = 0
    evidence_saved = 0
    snapshot_saved = False
    max_risk = "Low"
    risk_order = {"Low": 0, "Medium": 1, "High": 2}

    await websocket.send_json({"type": "started", "session_id": session_id})

    try:
        while True:
            data_url = await websocket.receive_text()
            if data_url == "__STOP__":
                break

            encoded = data_url.split(",", 1)[1] if "," in data_url else data_url
            raw_bytes = base64.b64decode(encoded)
            arr = np.frombuffer(raw_bytes, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                continue

            elapsed = time.monotonic() - start_t
            result = await asyncio.to_thread(engine.process_frame, frame, elapsed)
            if not snapshot_saved:
                evidence_saver.save_session_snapshot(session_id, result.annotated_frame)
                snapshot_saved = True
            if not snapshot_saved:
                evidence_saver.save_session_snapshot(session_id, result.annotated_frame)
                snapshot_saved = True

            new_events_payload, added_ev, added_shots, max_risk = _record_live_events(
                session_id, result, evidence_saver, max_risk, risk_order
            )
            total_events += added_ev
            evidence_saved += added_shots

            await websocket.send_json(
                {
                    "type": "frame",
                    "image": _encode_jpeg_b64(result.annotated_frame, quality=72),
                    "elapsed_sec": round(elapsed, 1),
                    "people_in_view": len(result.persons),
                    "total_events": total_events,
                    "evidence_saved": evidence_saved,
                    "max_risk": max_risk,
                    "new_events": new_events_payload,
                }
            )
    except WebSocketDisconnect:
        pass
    finally:
        duration = time.monotonic() - start_t
        persons = engine.get_tracked_persons()
        db.save_persons(session_id, persons)
        db.finalize_session(
            session_id=session_id,
            duration_sec=duration,
            total_people=len(persons),
            total_events=total_events,
            max_risk=max_risk,
        )
        engine.close()
        gc.collect()
        try:
            await websocket.send_json({"type": "stopped", "session_id": session_id})
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────
# IP / RTSP / HTTP Camera WebSocket
# The browser sends the camera URL; OpenCV reads frames server-side.
# ─────────────────────────────────────────────────────────────────


@app.websocket("/ws/ip-camera")
async def ws_ip_camera(
    websocket: WebSocket,
    token: str = "",
    cam_url: str = "",
):
    await websocket.accept()
    user = _resolve_token(token)
    cam_url = cam_url.strip()
    if user is None or not cam_url:
        await websocket.send_json({"type": "error", "message": "Authentication or camera URL missing."})
        await websocket.close()
        return

    # Open the IP/RTSP/HTTP camera via OpenCV before creating a monitoring session.
    def open_capture():
        src: str | int = int(cam_url) if cam_url.isdigit() else cam_url
        cap_obj = cv2.VideoCapture(src, cv2.CAP_FFMPEG) if isinstance(src, str) else cv2.VideoCapture(src)
        if not cap_obj.isOpened() and isinstance(src, str):
            cap_obj.release()
            cap_obj = cv2.VideoCapture(src)
        if cap_obj.isOpened():
            cap_obj.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap_obj

    cap = await asyncio.to_thread(open_capture)
    if not cap.isOpened():
        cap.release()
        await websocket.send_json(
            {
                "type": "error",
                "message": (
                    f"Cannot connect to camera stream: {cam_url}. "
                    "Verify the RTSP/HTTP URL is reachable from this server."
                ),
            }
        )
        await websocket.close()
        return

    engine = await asyncio.to_thread(_create_session_engine)
    evidence_saver = EvidenceSaver(config.evidence_dir, cooldown_sec=0.0)
    session_id = db.create_session(
        mode="live",
        source_name=f"IP Camera: {cam_url[:60]}",
        duration_sec=0.0,
        user_email=user["email"],
        campus=user.get("campus", ""),
    )
    start_t = time.monotonic()
    total_events = 0
    evidence_saved = 0
    snapshot_saved = False
    max_risk = "Low"
    risk_order = {"Low": 0, "Medium": 1, "High": 2}

    await websocket.send_json({"type": "started", "session_id": session_id})

    running = True
    frame_idx = 0
    failed_reads = 0

    try:
        while running:
            # Check for stop signal from client (non-blocking).
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=0.001)
                if data == "__STOP__":
                    running = False
                    break
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                running = False
                break

            ret, frame = await asyncio.to_thread(cap.read)
            if not ret or frame is None:
                failed_reads += 1
                if failed_reads >= 60:
                    try:
                        await websocket.send_json(
                            {"type": "error", "message": "Camera stream disconnected or ended."}
                        )
                    except Exception:
                        pass
                    break
                await asyncio.sleep(0.05)
                continue

            failed_reads = 0
            frame_idx += 1
            # Skip frames for CPU efficiency
            if frame_idx % config.frame_skip != 1:
                continue

            elapsed = time.monotonic() - start_t
            result = await asyncio.to_thread(engine.process_frame, frame, elapsed)
            if not snapshot_saved:
                evidence_saver.save_session_snapshot(session_id, result.annotated_frame)
                snapshot_saved = True

            new_events_payload, added_ev, added_shots, max_risk = _record_live_events(
                session_id, result, evidence_saver, max_risk, risk_order
            )
            total_events += added_ev
            evidence_saved += added_shots

            try:
                await websocket.send_json({
                    "type": "frame",
                    "image": _encode_jpeg_b64(result.annotated_frame, quality=72),
                    "elapsed_sec": round(elapsed, 1),
                    "people_in_view": len(result.persons),
                    "total_events": total_events,
                    "evidence_saved": evidence_saved,
                    "max_risk": max_risk,
                    "new_events": new_events_payload,
                })
            except WebSocketDisconnect:
                running = False

    finally:
        cap.release()
        duration = time.monotonic() - start_t
        persons = engine.get_tracked_persons()
        db.save_persons(session_id, persons)
        db.finalize_session(
            session_id=session_id,
            duration_sec=duration,
            total_people=len(persons),
            total_events=total_events,
            max_risk=max_risk,
        )
        engine.close()
        gc.collect()
        try:
            await websocket.send_json({"type": "stopped", "session_id": session_id})
        except Exception:
            pass
