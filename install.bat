@echo off
chcp 65001 > nul
echo 스마트 캡쳐 설치 중...
pip install -r requirements.txt
echo.
echo 설치 완료!
echo 실행: python capture.py
pause
