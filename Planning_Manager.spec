# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller Planning_Manager.spec --noconfirm

a = Analysis(
    ['planning_manager.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['openpyxl'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'scipy', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.Qt3DCore', 'PySide6.QtMultimedia'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# Ekran wczytywania widoczny podczas rozpakowywania exe (tekst etapów: pm/splash.py)
splash = Splash(
    'splash.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(34, 232),
    text_size=11,
    text_color='white',
    always_on_top=False,
)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    splash.binaries,
    a.binaries,
    a.datas,
    [],
    name='PlanningManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon=['icon.ico'],
)
