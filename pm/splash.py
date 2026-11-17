"""Ekran wczytywania (tylko w zbudowanym exe).

Exe w jednym pliku musi się przy każdym starcie rozpakować do folderu tymczasowego –
to trwa najdłużej. PyInstaller pokazuje wtedy obrazek splash.png, a ten moduł
dopisuje pod nim, który etap startu właśnie trwa. Przy uruchomieniu ze źródeł
(python planning_manager.py) nic nie robi.

Moduł celowo nie importuje niczego ciężkiego.
"""
try:
    import pyi_splash  # dostępny wyłącznie wewnątrz exe zbudowanego ze splashem
except Exception:
    pyi_splash = None

TOTAL_STEPS = 3


def step(number, text):
    if pyi_splash is None:
        return
    try:
        if pyi_splash.is_alive():
            pyi_splash.update_text(f"{text}   ({number}/{TOTAL_STEPS})")
    except Exception:
        pass


def close():
    if pyi_splash is None:
        return
    try:
        if pyi_splash.is_alive():
            pyi_splash.close()
    except Exception:
        pass
