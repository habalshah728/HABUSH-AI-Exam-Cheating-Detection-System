@echo off
cd /d "%~dp0"
echo Starting HABUSH CMS Exam Monitor (FastAPI + AI Backend)...
start "HABUSH Server" cmd /k ".\venv\Scripts\uvicorn.exe web_app:app --host 0.0.0.0 --port 8000"
timeout /t 3 /nobreak >nul
echo Creating Public HTTPS Live URL via Cloudflare Tunnel...
"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://127.0.0.1:8000 --no-autoupdate
pause
