from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
datas, binaries = [], []
datas += [(str(root / 'scopa_demo.html'), '.'), (str(root / 'ScopaEngine.exe'), 'engine')]
hiddenimports = ['uvicorn.loops.asyncio', 'uvicorn.protocols.http.h11_impl', 'uvicorn.lifespan.on']
for package in ('playwright', 'playwright_stealth', 'shardx', 'patchright'):
    data, libs, modules = collect_all(package)
    datas += data
    binaries += libs
    hiddenimports += modules
a = Analysis([str(root / 'desktop_app.py')], pathex=[str(root), str(root)],
    binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[str(root / 'desktop_runtime_hook.py')],
    excludes=[], noarchive=False, optimize=0)
# Qt uses the Windows system ICU API. A same-named Poppler ICU in the build
# environment is incompatible and must not shadow the system DLL in the EXE.
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in {'icuuc.dll', 'icudt78.dll', 'icuin78.dll'}]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='QA_Manager',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
    upx_exclude=[], runtime_tmpdir=None, console=False,
    disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None)
