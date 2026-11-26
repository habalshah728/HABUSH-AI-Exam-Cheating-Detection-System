# HABUSH CMS — AI-Based Smart Exam Cheating Detection System (PFAI)

**Course:** Programming for AI (PFAI) — Semester Term Project  
**Team Members:** Syed Hablillah Shah (`09-136252-054`) & Malik Muhammad Hassan (`09-136252-017`)  
**Domain:** Computer Vision & Applied AI — Exam Integrity Monitoring  

> **Responsible AI Disclaimer:** Every alert flagged by this system is a *suspicious indicator only*. Human verification is always required before any action. The system does not perform facial identity recognition and never issues a final cheating verdict.

---

## 1. Live Deployed & Running Setup

### Live Cloud Production Website (24/7 Online)
- **Live Portal URL:** `https://habush-exam-monitor-production.up.railway.app`
- **Health Endpoint:** `https://habush-exam-monitor-production.up.railway.app/healthz`
- **Cloud Host:** Railway (`Docker` container built from `Dockerfile`)
- **GitHub Repository:** `https://github.com/habalshah728/HABUSH-AI-Exam-Cheating-Detection-System` (`main` branch)
- **Live Email OTP Delivery:** Google Apps Script HTTPS Webhook (`EMAIL_WEBHOOK_URL`) connected to your configured sender mailbox over HTTPS port `443` (bypasses cloud outbound SMTP blocks, with automatic Demo Mode fallback if unconfigured).

### Local PC Setup (With Real Gmail SMTP & Cloudflare Tunnel Support)
- **FastAPI Web Portal:** `http://localhost:8000` (`START_WEBSITE.bat` or `uvicorn web_app:app --host 0.0.0.0 --port 8000`)
- **Streamlit Dashboard:** `http://localhost:8501` (`streamlit run app.py`)
- **1-Click Public HTTPS Tunnel:** `START_LIVE_TUNNEL.bat` (starts FastAPI + Cloudflare Quick Tunnel)
- **Local Email Delivery:** Gmail SMTP (`smtp.gmail.com:587`, STARTTLS) configured in `.env` and `.streamlit/secrets.toml` (git-ignored).

---

## 2. Core Features & Proposal Alignment

1. **Dual-Mode Shared AI Pipeline (`src/scoring/engine.py` — `DetectionEngine`):**
   - **Upload Examination Video:** Supports `.mp4` and `.avi`, frame-skip slider (`1–10`, default `3`), detection confidence (`0.20–0.85`, default `0.40`), alert cooldown (`1–15s`, default `5s`), live annotated stream, colour-coded **Activity Timeline**, and PDF download.
   - **Live Camera Monitoring:** Supports **IP / Network Camera URL** (`rtsp://`, `http://`, `rtmp://`) via server-side OpenCV AND **Browser WebRTC Camera** over HTTPS.
2. **Pretrained AI Models (`models/`):**
   - `models/yolov8n.pt`: Ultralytics YOLOv8n (`person` + `cell phone` COCO classes) with **ByteTrack** (`lap`) persistent track IDs.
   - `models/face_landmarker.task`: MediaPipe FaceLandmarker (`head yaw` via OpenCV `solvePnP` + lip oscillation ratio).
   - `models/hand_landmarker.task`: MediaPipe HandLandmarker (rapid/unusual wrist displacement).
3. **Explainable 30-Second Sliding Window Risk Scorer (`src/scoring/risk_scorer.py`):**
   - Phone visible for 3+ seconds: **+40**
   - 3 or more side-looks in 30 seconds (`|yaw| >= 22°`): **+25**
   - Possible talking (repeated lip oscillations): **+15**
   - Close neighbour interaction (`distance <= 1.65 × width`, turned heads): **+15**
   - Unusual hand movement: **+10**
   - **Risk Levels (cap 100):** Low (`0–29`), Medium (`30–59`), High (`60–100`).
4. **Authentication, OTP & Hidden Privileged Console:**
   - Open account registration (**Exam Controller** role + user-entered **Campus Name**) with **6-digit Email OTP verification** (`10 min` expiry, max `5` attempts, PBKDF2-HMAC-SHA256 salted password hashes, persistent hashed auth tokens in SQLite).
   - Hidden admin account (`<configured ADMIN_EMAIL>`) configured via `ADMIN_EMAIL` / `ADMIN_PASSWORD` environment secrets — completely invisible on public UI; signing in reveals **Accounts & Security** (registered accounts count/table, all users' PDF reports archive, delete controls, and **Change Portal Password**).
5. **SQLite Database, Delete Controls & PDF Reports with Evidence Screenshots:**
   - SQLite tables (`data/sessions.db`): `sessions`, `persons`, `events`, `reports`, `users`, `otp_codes`, `auth_tokens`.
   - Delete buttons for individual alert events and complete sessions (cascades DB rows + removes evidence screenshots & generated PDFs).
   - **ReportLab PDF (`src/reporting/report_generator.py`):** Session details (including Campus & Controller), summary metrics, category counts, event log with screenshot attachment status, and **all evidence screenshots** embedded cleanly with proportional aspect ratio and timestamps.

---

## 3. Project Structure

```text
├── web_app.py                      # FastAPI + WebSocket backend entry point
├── app.py                          # Streamlit UI entry point
├── Dockerfile                      # Production CPU Docker container (Railway/Render)
├── render.yaml                     # Cloud deployment blueprint
├── requirements.txt                # Python dependencies
├── pytest.ini                      # Test configuration
├── START_WEBSITE.bat               # Launch FastAPI locally
├── START_LIVE_TUNNEL.bat           # Launch FastAPI + Cloudflare HTTPS tunnel
├── PROJECT_DETAILS.md              # Full documentation & live setup guide
├── README.md                       # Project overview
├── sample_videos/                  # Sample MP4 & AVI videos for testing
├── models/                         # yolov8n.pt, face_landmarker.task, hand_landmarker.task
├── static/                         # HABUSH CMS frontend (index.html, styles.css, app.js, bu_crest.svg)
├── tests/                          # Pytest suite (9/9 tests)
└── src/
    ├── auth/                       # AuthManager, EmailService (HTTPS APIs + SMTP + Demo fallback)
    ├── sources/                    # FrameSource (ABC), VideoFileSource, WebcamSource, CameraManager
    ├── detection/                  # Detector (ABC), PersonPhoneDetector, PersonTracker
    ├── analysis/                   # Analyzer (ABC), HeadPoseAnalyzer, TalkingAnalyzer, HandAnalyzer, InteractionAnalyzer
    ├── scoring/                    # RiskScorer, DetectionEngine, MonitoringSession, Event
    ├── storage/                    # DatabaseManager (SQLite), EvidenceSaver
    ├── reporting/                  # ReportGenerator (ReportLab PDF with embedded screenshots)
    ├── ui/                         # Streamlit pages
    └── utils/                      # AppConfig, Logger, Custom Exceptions
```

---

## 4. Environment Variables (`.env` / Railway Variables)

Create a `.env` file locally (never commit secrets to Git) or configure in Railway **Variables**:

```env
ADMIN_EMAIL=<your-admin-email>
ADMIN_PASSWORD=<your-admin-password>

# Cloud HTTPS Email Delivery (for Railway / PaaS where SMTP ports 587/465 are blocked)
EMAIL_WEBHOOK_URL=<your-google-apps-script-web-app-url>
# OR Brevo / Resend HTTPS APIs:
# BREVO_API_KEY=<your-brevo-key>
# RESEND_API_KEY=<your-resend-key>

# Local PC Gmail SMTP (port 587 STARTTLS)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=<your-gmail@gmail.com>
SMTP_PASSWORD=<16-char-google-app-password>
SMTP_FROM=<your-gmail@gmail.com>
```

---

## 5. Quick Start on Any PC

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -v
uvicorn web_app:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` in your browser.

---

## 6. Sample Videos (`sample_videos/`)

For repository size hygiene, sample HD test videos (`1080p` classroom exam, `720p` mobile phone cheating, and `720p` `.avi` test clips) are excluded from Git (see `.gitignore`) and distributed separately in the project release package.
Place any `.mp4` or `.avi` video in `sample_videos/` or upload directly through **Upload Video**.