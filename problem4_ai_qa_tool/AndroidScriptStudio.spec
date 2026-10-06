# -*- mode: python ; coding: utf-8 -*-
# The writer does not execute Airtest; its Python export contains Airtest imports.
from PyInstaller.utils.hooks import collect_all
datas, binaries, hiddenimports = collect_all('customtkinter')
a = Analysis(['main_recorder.py'], pathex=['.'], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['matplotlib', 'pytest', 'tkinter.test', 'test'], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AndroidScriptStudio', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='AndroidScriptStudio')
