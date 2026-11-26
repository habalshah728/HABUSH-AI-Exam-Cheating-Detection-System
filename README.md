# HABUSH CMS — AI-Based Smart Exam Cheating Detection System

**Bahria University (H-11 Campus, Islamabad) — Programming for AI (PFAI) Term Project**  
**Team:** Syed Hablillah Shah (`09-136252-054`) & Malik Muhammad Hassan (`09-136252-017`)

> **Live Deployed Portal:** https://habush-exam-monitor-production.up.railway.app  
> **Responsible AI Notice:** Every flagged alert is a *suspicious indicator only* requiring human verification. The system never performs facial identity recognition and never issues a final cheating verdict.

---

## Key Capabilities

- **Dual-Mode Shared AI Engine (`DetectionEngine`):** Identical pipeline for **Upload Video** (`.mp4` / `.avi`) and **Live Camera** (IP/RTSP streams & HTTPS Browser WebRTC).
- **Pretrained Computer Vision Models (`models/`):** YOLOv8n (`person` + `cell phone` + ByteTrack IDs), MediaPipe `FaceLandmarker` (OpenCV `solvePnP` head yaw + lip oscillation), and MediaPipe `HandLandmarker`.
- **Explainable 30s Sliding-Window Risk Scorer (`RiskScorer`):** Phone visible 3+ s (`+40`), Repeated side-looking (`+25`), Possible talking (`+15`), Close neighbour interaction (`+15`), Unusual hand movement (`+10`).
- **Authentication & OTP Verification:** Registration, PBKDF2-HMAC-SHA256 salted password hashes, 6-digit email OTP verification (HTTPS Webhook / Brevo / Resend / SMTP with Demo fallback), and hidden env-configured Admin console.
- **SQLite Evidence & ReportLab PDF Reports:** Session logs, cropped frame evidence attachments, delete controls, and downloadable PDF reports with embedded evidence screenshots.

---

## Project Structure

```text
├── web_app.py                      # FastAPI + WebSocket production web portal
├── app.py                          # Streamlit dashboard entry point
├── Dockerfile                      # Production CPU Docker container (Railway/Render)
├── render.yaml                     # Cloud deployment blueprint
├── PROJECT_DETAILS.md              # Detailed technical documentation
├── .env.example                    # Non-secret environment template
├── .streamlit/secrets.toml.example # Streamlit SMTP secrets template
├── models/                         # yolov8n.pt, face_landmarker.task, hand_landmarker.task
├── static/                         # HABUSH CMS frontend (index.html, styles.css, app.js)
├── tests/                          # Pytest test suite (9 tests)
└── src/                            # Modular OOP Python backend packages
```

---

## Quick Start (Local)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # Optional: configure SMTP / ADMIN_* variables
pytest -v
uvicorn web_app:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` in your browser (or launch Streamlit via `streamlit run app.py`). See `PROJECT_DETAILS.md` for full setup and deployment notes.
