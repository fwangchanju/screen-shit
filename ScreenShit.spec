# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

# EXE 파일 아이콘: 빌드마다 icon.png → icon.ico 항상 덮어쓰기 생성
# 창 실행 중 아이콘은 코드에서 iconphoto(PNG)로 별도 처리
_ico = Path('image/program/icon.ico')
_png = Path('image/program/icon.png')
if _png.exists():
    from PIL import Image
    _img = Image.open(_png).convert('RGBA').resize((256, 256), Image.LANCZOS)
    _img.save(str(_ico), format='ICO', sizes=[(256, 256)])

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('image', 'image'),          # 모든 아이콘·이미지 번들
    ],
    hiddenimports=[
        # pystray Windows 백엔드
        'pystray._win32',
        # pywin32 — 클립보드·창 제어
        'win32clipboard',
        'win32api',
        'win32con',
        'win32gui',
        'win32process',
        # Pillow ImageTk
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ScreenShit',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(_ico),
)
