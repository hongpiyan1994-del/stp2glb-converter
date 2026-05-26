# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置
# 用法: pyinstaller converter.spec --noconfirm

import sys
import os
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# DearPyGUI 数据文件
dpg_datas = collect_data_files(" dearpygui")

a = Analysis(
    ['converter_gui.py'],
    pathex=[],
    binaries=[],
    datas=[] + dpg_datas,
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
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Blender 目录作为数据文件打包
# 打包后 Blender 位于 _MEIPASS/blender/
blender_src = os.path.join(os.path.dirname(sys.argv[0]), 'blender')
if os.path.exists(blender_src):
    a.datas += Tree(blender_src, prefix='blender')

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
    console=False,          # GUI 程序，无控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico' if os.path.exists('icon.ico') else None,
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
