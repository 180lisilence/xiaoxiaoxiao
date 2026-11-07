# -*- mode: python ; coding: utf-8 -*-
"""小笑肖 · 工作台主程序 打包配置

工作台的图形界面是 pywebview（走 WebView2），不依赖 tkinter 作界面；
但 app.py 的 show_error() 用 tkinter 弹错误框 —— 上一版把它放进 excludes，
结果服务没起来时用户什么提示都看不到，程序静默退出。这里一并打进去。

必须用带 tcl/tk 的 Python 打包（本机 E:/pythonpath/python.exe，Tk 9.0）。
"""
import os
import sys

block_cipher = None

_py_root = sys.base_prefix if hasattr(sys, "base_prefix") else sys.prefix
_tcl_dir = os.path.join(_py_root, "tcl")
_dll_dir = os.path.join(_py_root, "DLLs")


def _tk_binaries():
    out = []
    for name in ("_tkinter.pyd", "tcl90.dll", "tcl9tk90.dll",
                 "zlib1.dll", "tcl90t.dll", "tk90.dll"):
        p = os.path.join(_dll_dir, name)
        if os.path.isfile(p):
            out.append((p, "."))
    for name in os.listdir(_tcl_dir):
        if name.lower().endswith(".zip"):
            out.append((os.path.join(_tcl_dir, name), "tcl"))
    return out


def _tk_datas():
    out = []
    for name in ("tcl9.0", "tk9.0", "dde1.4", "registry1.3", "tcl8", "tk8.6"):
        p = os.path.join(_tcl_dir, name)
        if os.path.isdir(p):
            out.append((p, os.path.join("tcl", name)))
    return out


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=_tk_binaries(),
    datas=[
        ('_web', '_web'),
        ('seed.json', '.'),
    ] + _tk_datas(),
    hiddenimports=[
        'server',
        '_dpapi',
        'tkinter',
        'tkinter.messagebox',
        'webview',
        'webview.platforms.edgechromium',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'pandas', 'matplotlib', 'PyQt5', 'PyQt6', 'PIL', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='小笑肖',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    upx_exclude=[], console=False,
    disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None, icon=None,
)

# onedir：onefile 每次启动都要解压到系统盘的 %TEMP%，操作者要求不写 C 盘，
# 改成分目录后直接用，不产生解压临时文件，启动也更快。
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='小笑肖',
)
