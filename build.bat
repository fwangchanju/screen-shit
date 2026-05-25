@echo off
echo [1/4] Installing dependencies...
pip install -r requirements.txt --quiet

echo [2/4] Generating icon.ico from icon.png...
python -c "from PIL import Image; img=Image.open('image/program/icon.png').convert('RGBA').resize((256,256),Image.LANCZOS); img.save('image/program/icon.ico', format='ICO', sizes=[(256,256)])"
if errorlevel 1 (
    echo [WARN] icon.ico create fail - check file icon.png
)

echo [3/4] Building...
pyinstaller ScreenShit.spec --clean --noconfirm

echo [4/4] Done!
if exist "dist\ScreenShit.exe" (
    echo.
    echo  Output: dist\ScreenShit.exe
    echo.
) else (
    echo [ERROR] dist\ScreenShit.exe build failed
)
pause
