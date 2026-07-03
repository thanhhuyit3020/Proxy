# PyInstaller spec cho Proxy Manager.
# Build: pyinstaller proxy_manager.spec
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("proxy_manager", includes=["web/static/*"])

a = Analysis(
    ["src/proxy_manager/cli.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="proxy-manager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    # Layer B (Giai doan 2) se can uac_admin=True khi WinDivert duoc tich hop,
    # vi Layer A (bay gio) khong can quyen admin nen de False.
    uac_admin=False,
)
