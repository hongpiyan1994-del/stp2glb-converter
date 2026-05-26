# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置
# 注意：Blender 不打包在内，用户需自行下载 blender.exe 放在 EXE 同目录

import sys
import os

block_cipher = None

a = Analysis(
    ['converter_gui.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'dearpygui',
        'dearpygui.dearpygui',
        'struct',
        'threading',
        'subprocess',
        'pathlib',
        're',
        'json',
        'time',
        'importlib',
        'importlib.util',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'PIL',
        'cv2',
        'torch',
        'tensorflow',
        'IPython',
        'notebook',
        'jupyter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='STP2GLB_Converter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='STP2GLB_Converter',
)