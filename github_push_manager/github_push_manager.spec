# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec cho GitHub Push Manager.
# Build (chạy trên Windows, trong venv đã cài requirements + pyinstaller):
#     pyinstaller github_push_manager.spec
#
# File .exe kết quả nằm ở: dist/GitPushManager.exe

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'keyring.backends.Windows',
        'github',
        'git',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GitPushManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # False = không mở cửa sổ CMD đen phía sau
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='app_icon.ico',  # bỏ comment dòng này nếu bạn có file .ico riêng
)
