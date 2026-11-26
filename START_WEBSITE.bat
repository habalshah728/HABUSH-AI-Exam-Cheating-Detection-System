@echo off
cd /d "%~dp0"
echo Starting HABUSH CMS Exam Monitor (FastAPI + AI Backend)...
start "" http://localhost:8000
.\venv\Scripts\uvicorn.exe web_app:app --host 0.0.0.0 --port 8000
pause
