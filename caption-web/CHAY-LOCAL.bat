@echo off
chcp 65001 >nul
title Auto Caption Web - Local
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [LOI] Chua thay Python. Cai Python 3.11 tu python.org roi chay lai.
  pause
  exit /b 1
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [LOI] Chua thay FFmpeg. May ban da co FFmpeg o pipeline OctopberAuto,
  echo hay them thu muc chua ffmpeg.exe vao PATH roi chay lai.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo Dang tao moi truong ao .venv ...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo Dang cai / kiem tra thu vien (lan dau mat vai phut)...
pip install -r requirements.txt
if errorlevel 1 (
  echo [LOI] Cai thu vien that bai. Kiem tra mang roi chay lai.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  Web chay o: http://localhost:8000
echo  Mo trinh duyet vao dia chi tren. Tat cua so nay = tat web.
echo ============================================================
start http://localhost:8000
uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
