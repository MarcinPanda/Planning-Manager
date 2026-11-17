"""Tnie arkusze ikon z ChatGPT (4×4, czarne na białym) na pojedyncze PNG z przezroczystym tłem.

Użycie:  .venv\\Scripts\\python tools\\cut_icons.py
Źródła:  pm/assets/source/icons_A.webp, icons_B.webp, icons_C.webp, logo.webp
Wynik:   pm/assets/icons/<nazwa>.png (czarny kształt + kanał alfa; kolor nadaje aplikacja),
         pm/assets/logo.png, icon.ico (ikona exe i okna).
Nowy arkusz = nowa lista nazw w SHEETS (kolejność: od lewej do prawej, od góry do dołu).
"""
import os
import sys

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "pm", "assets", "source")
OUT = os.path.join(ROOT, "pm", "assets", "icons")
SIZE = 128   # px – ikony są skalowane w dół w aplikacji

SHEETS = {
    "icons_A.webp": [
        "planning", "monitoring", "consolidation", "logins",
        "hours", "import", "export", "print",
        "undo", "history", "add_employee", "remove_employee",
        "clear", "settings", "help", "mark_mode",
    ],
    "icons_B.webp": [
        "reach", "picking", "inbound", "other",
        "unassigned", "sick", "home", "late",
        "from_start", "from_now", "multi_zone", "hall_north",
        "hall_south", "edit_zones", "move", "bulk",
    ],
    "icons_C.webp": [
        "login_free", "login_assigned", "login_damaged", "login_blocked",
        "login_add", "kantel", "consolidation_done", "driven_in",
        "lane", "comment", "who_busy", "date",
        "sync", "database", "warning", "success",
    ],
}


def to_array(image, fmt):
    image = image.convertToFormat(fmt)
    width, height = image.width(), image.height()
    channels = 1 if fmt == QImage.Format_Grayscale8 else 4
    data = np.frombuffer(image.constBits(), dtype=np.uint8, count=image.sizeInBytes())
    # .copy(): dane obrazu Qt znikają razem z obiektem image
    return data.reshape(height, image.bytesPerLine())[:, :width * channels].reshape(height, width, channels).copy()


def from_rgba(array):
    array = np.ascontiguousarray(array)
    height, width = array.shape[:2]
    return QImage(array.data, width, height, width * 4, QImage.Format_RGBA8888).copy()


def main_segment(present, weight, gap=12):
    """(początek, koniec) ikony w komórce: wszystkie pasy wierszy / kolumn z linią, oprócz małych
    skrawków dotykających krawędzi komórki (to końcówki sąsiednich ikon)."""
    segments, start, last = [], None, None
    for i, on in enumerate(present):
        if on:
            if start is None:
                start = i
            elif i - last > gap:
                segments.append((start, last + 1))
                start = i
            last = i
    if start is not None:
        segments.append((start, last + 1))
    # skrawek sąsiada przecina granicę komórki, więc zaczyna się / kończy dokładnie na jej krawędzi
    heaviest = max(segments, key=lambda s: weight[s[0]:s[1]].sum())
    kept = [s for s in segments if s is heaviest or not (s[0] <= 2 or s[1] >= len(present) - 2)]
    return kept[0][0], kept[-1][1]


def cut_sheet(filename, names):
    gray = to_array(QImage(os.path.join(SOURCE, filename)), QImage.Format_Grayscale8)[:, :, 0]
    ink = 255 - gray.astype(np.int32)            # 0 = tło, 255 = linia
    height, width = ink.shape
    for index, name in enumerate(names):
        row, col = divmod(index, 4)
        cell = ink[row * height // 4:(row + 1) * height // 4, col * width // 4:(col + 1) * width // 4]
        mask = cell > 60
        if not mask.any():
            print("EMPTY:", name)
            continue
        # skrawki sąsiednich ikon przy krawędzi komórki pomijamy: bierzemy najcięższy zwarty pas
        top, bottom = main_segment(mask.any(axis=1), cell.sum(axis=1))
        left, right = main_segment(mask[top:bottom].any(axis=0), cell[top:bottom].sum(axis=0))
        side = max(bottom - top, right - left)
        pad = side // 12
        square = np.zeros((side + 2 * pad, side + 2 * pad), dtype=np.int32)
        oy = pad + (side - (bottom - top)) // 2
        ox = pad + (side - (right - left)) // 2
        square[oy:oy + bottom - top, ox:ox + right - left] = cell[top:bottom, left:right]
        rgba = np.zeros(square.shape + (4,), dtype=np.uint8)
        rgba[:, :, 3] = np.clip(square * 1.15, 0, 255).astype(np.uint8)   # czarny kształt, alfa = linia
        image = from_rgba(rgba).scaled(SIZE, SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        image.save(os.path.join(OUT, f"{name}.png"))


def make_logo():
    rgba = to_array(QImage(os.path.join(SOURCE, "logo.webp")), QImage.Format_RGBA8888).copy()
    white = (rgba[:, :, 0] > 225) & (rgba[:, :, 1] > 225) & (rgba[:, :, 2] > 225)
    rgba[white, 3] = 0                            # białe tło wokół kafla -> przezroczyste
    logo = from_rgba(rgba)
    logo.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(
        os.path.join(ROOT, "pm", "assets", "logo.png"))
    logo.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(os.path.join(ROOT, "icon.ico"))


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    os.makedirs(OUT, exist_ok=True)
    for sheet, sheet_names in SHEETS.items():
        cut_sheet(sheet, sheet_names)
    make_logo()
    print("icons:", len(os.listdir(OUT)))
