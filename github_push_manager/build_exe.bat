@echo off
REM Build GitPushManager.exe (Windows only)
REM Chạy file này trong thư mục gốc của project.

echo === Tao virtual environment (neu chua co) ===
if not exist venv (
    python -m venv venv
)
call venv\Scripts\activate.bat

echo === Cai dat dependencies ===
pip install -r requirements.txt
pip install pyinstaller

echo === Build exe ===
pyinstaller github_push_manager.spec --noconfirm

echo.
echo === XONG ===
echo File exe nam o: dist\GitPushManager.exe
pause
