"""Wygląd aplikacji: własny motyw jasny / ciemny (niezależny od systemu) i ikony w kolorze motywu.

- apply(app, name)  – ustawia styl Fusion, paletę i arkusz stylów dla całej aplikacji,
- icon(name)        – ikona z pm/assets/icons w kolorze tekstu (zaznaczona: kolor na akcencie),
- color(key)        – kolor z bieżącego motywu (np. do rysowania).
Wybrany motyw jest zapamiętany dla użytkownika (QSettings).
"""
import os

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPalette, QPixmap

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
ICON_DIR = os.path.join(ASSETS, "icons")
LOGO = os.path.join(ASSETS, "logo.png")

PALETTES = {
    "dark": {
        "bg": "#10151b", "surface": "#171f28", "surface2": "#1f2a36", "hover": "#273544",
        "border": "#2c3a49", "text": "#e6edf3", "muted": "#8d9cad", "accent": "#00b4f0",
        "accent_text": "#03141c", "selection": "#1d4a63", "sidebar": "#0b1015", "sidebar_text": "#c9d6e3",
        "danger": "#e5534b", "warning": "#e67e22", "black": "#000000",
    },
    "light": {
        "bg": "#eef2f6", "surface": "#ffffff", "surface2": "#f4f7fa", "hover": "#e3ebf3",
        "border": "#d3dce6", "text": "#17212b", "muted": "#5c6b7b", "accent": "#0091c9",
        "accent_text": "#ffffff", "selection": "#cde9f7", "sidebar": "#16212d", "sidebar_text": "#c9d6e3",
        "danger": "#c93c37", "warning": "#d35400", "black": "#000000",
    },
}

current = dict(PALETTES["dark"])
current_name = "dark"
persist = True          # testy wyłączają zapis wybranego motywu
_icon_cache = {}


def saved_theme():
    if not persist:
        return current_name
    try:
        value = QSettings("PlanningManager", "PlanningManager").value("theme", "dark")
    except Exception:
        value = "dark"
    return value if value in PALETTES else "dark"


def save_theme(name):
    if not persist:
        return
    try:
        QSettings("PlanningManager", "PlanningManager").setValue("theme", name)
    except Exception:
        pass


def color(key):
    return current[key]


def tinted_pixmap(name, color_hex, size=64):
    path = os.path.join(ICON_DIR, f"{name}.png")
    source = QImage(path)
    if source.isNull():
        return QPixmap()
    source = source.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    image = QImage(source.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(color_hex))
    painter = QPainter(image)
    painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, source)
    painter.end()
    return QPixmap.fromImage(image)


def icon(name, color_key="text", checked_key="accent_text"):
    """Ikona w kolorze motywu; w stanie zaznaczonym (np. aktywny widok) w kolorze tekstu na akcencie."""
    key = (current_name, name, color_key, checked_key)
    if key not in _icon_cache:
        result = QIcon()
        normal = tinted_pixmap(name, current[color_key])
        result.addPixmap(normal, QIcon.Normal, QIcon.Off)
        result.addPixmap(tinted_pixmap(name, current["muted"]), QIcon.Disabled, QIcon.Off)
        result.addPixmap(tinted_pixmap(name, current[checked_key]), QIcon.Normal, QIcon.On)
        _icon_cache[key] = result
    return _icon_cache[key]


def white_icon(name):
    """Ikona biała – na kolorowych nagłówkach (hale, Ziek, Naar Huis)."""
    key = ("white", name)
    if key not in _icon_cache:
        _icon_cache[key] = QIcon(tinted_pixmap(name, "#ffffff"))
    return _icon_cache[key]


def stylesheet(p):
    return f"""
QWidget {{ background-color: {p['bg']}; color: {p['text']}; }}
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
QToolTip {{ background-color: {p['surface2']}; color: {p['text']}; border: 1px solid {p['border']};
            padding: 5px 8px; border-radius: 4px; }}

QPushButton, QToolButton {{
    background-color: {p['surface2']}; color: {p['text']}; border: 1px solid {p['border']};
    border-radius: 7px; padding: 6px 12px; }}
QPushButton:hover, QToolButton:hover {{ background-color: {p['hover']}; border-color: {p['accent']}; }}
QPushButton:pressed, QToolButton:pressed {{ background-color: {p['selection']}; }}
QPushButton:checked, QToolButton:checked {{
    background-color: {p['accent']}; color: {p['accent_text']}; border-color: {p['accent']}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {p['muted']}; border-color: {p['border']}; }}
QPushButton:default {{ border-color: {p['accent']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton#toolbarButton {{ background: transparent; border: 1px solid transparent; padding: 6px 10px; }}
QToolButton#toolbarButton:hover {{ background-color: {p['hover']}; border-color: {p['border']}; }}
QToolButton#toolbarButton:checked {{ background-color: {p['accent']}; color: {p['accent_text']}; }}
QPushButton#helpButton {{ border-radius: 15px; padding: 0; }}

QLineEdit, QComboBox, QTimeEdit, QSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {{
    background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']};
    border-radius: 6px; padding: 4px 8px; selection-background-color: {p['accent']};
    selection-color: {p['accent_text']}; }}
QLineEdit:focus, QComboBox:focus, QTimeEdit:focus, QSpinBox:focus {{ border-color: {p['accent']}; }}
QComboBox QAbstractItemView {{ background-color: {p['surface']}; border: 1px solid {p['border']};
    selection-background-color: {p['accent']}; selection-color: {p['accent_text']}; }}

QMenu {{ background-color: {p['surface']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 7px 26px 7px 10px; border-radius: 5px; background: transparent; }}
QMenu::item:selected {{ background-color: {p['accent']}; color: {p['accent_text']}; }}
QMenu::item:disabled {{ color: {p['muted']}; }}
QMenu::separator {{ height: 1px; background: {p['border']}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 6px; }}

QTableView, QTableWidget {{
    background-color: {p['surface']}; alternate-background-color: {p['surface2']};
    gridline-color: {p['border']}; border: 1px solid {p['border']}; border-radius: 8px;
    selection-background-color: {p['selection']}; selection-color: {p['text']}; }}
QHeaderView::section {{
    background-color: {p['surface2']}; color: {p['muted']}; border: none;
    border-right: 1px solid {p['border']}; border-bottom: 1px solid {p['border']};
    padding: 6px 4px; font-weight: 600; }}
QTableCornerButton::section {{ background-color: {p['surface2']}; border: none; }}
QListWidget {{ background-color: {p['surface']}; border: 1px solid {p['border']}; border-radius: 6px; }}

QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background: {p['border']}; border-radius: 4px; }}
QScrollBar::handle:vertical {{ min-height: 30px; }}
QScrollBar::handle:horizontal {{ min-width: 30px; }}
QScrollBar::handle:hover {{ background: {p['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; width: 0; height: 0; }}

QGroupBox {{ border: 1px solid {p['border']}; border-radius: 8px; margin-top: 16px; padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {p['muted']}; font-weight: 600; }}
QStatusBar {{ background-color: {p['surface']}; color: {p['muted']}; border-top: 1px solid {p['border']}; }}

/* ---- okno główne ---- */
#sidebar {{ background-color: {p['sidebar']}; }}
#sidebar QLabel {{ color: {p['sidebar_text']}; background: transparent; }}
#sidebar QLabel#appName {{ font-size: 12pt; font-weight: 700; color: #ffffff; }}
#sidebar QLabel#appVersion {{ color: #6f8193; font-size: 8pt; }}
#sidebar QPushButton {{
    color: {p['sidebar_text']}; background: transparent; border: none; border-radius: 8px;
    text-align: left; padding: 10px 12px; font-size: 11pt; }}
#sidebar QPushButton:hover {{ background-color: #1c2835; }}
#sidebar QPushButton:checked {{ background-color: {p['accent']}; color: #03141c; font-weight: 700; }}
#topbar {{ background-color: {p['surface']}; border-bottom: 1px solid {p['border']}; }}
#topbar QLabel#pageTitle {{ font-size: 17pt; font-weight: 700; }}
QLabel#muted, QLabel#hint {{ color: {p['muted']}; }}
QLabel#kpi {{ background-color: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 7px;
              padding: 4px 10px; }}

/* ---- tablica Monitoring ---- */
DropZone {{ background-color: {p['surface']}; border: 1px solid {p['border']}; border-radius: 8px; }}
DropZone[dropTarget="true"] {{ border: 1px dashed {p['accent']}; }}
DropZone[hover="true"] {{ border: 2px solid {p['accent']}; }}
DropZone QLabel#zoneTitle {{ font-weight: 700; }}
DropZone QListWidget {{ background: transparent; border: none; }}
Column, HallSection, #board {{ background: transparent; }}
QLabel#columnHeader {{ font-weight: 700; font-size: 10pt; color: {p['muted']}; letter-spacing: 1px; }}
"""


def palette(p):
    pal = QPalette()
    roles = {
        QPalette.Window: p["bg"], QPalette.WindowText: p["text"], QPalette.Base: p["surface"],
        QPalette.AlternateBase: p["surface2"], QPalette.Text: p["text"], QPalette.Button: p["surface2"],
        QPalette.ButtonText: p["text"], QPalette.Highlight: p["accent"], QPalette.HighlightedText: p["accent_text"],
        QPalette.ToolTipBase: p["surface2"], QPalette.ToolTipText: p["text"], QPalette.PlaceholderText: p["muted"],
        QPalette.Link: p["accent"], QPalette.Mid: p["border"], QPalette.Midlight: p["hover"],
    }
    for role, value in roles.items():
        pal.setColor(role, QColor(value))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(p["muted"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(p["muted"]))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(p["muted"]))
    return pal


def apply(app, name=None):
    global current_name
    name = name if name in PALETTES else saved_theme()
    current_name = name
    current.clear()
    current.update(PALETTES[name])
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setPalette(palette(current))
    app.setStyleSheet(stylesheet(current))
    if os.path.exists(LOGO):
        app.setWindowIcon(QIcon(LOGO))
    save_theme(name)
    return name
