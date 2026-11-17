"""Generuje splash.png – obrazek ekranu wczytywania exe.

Uruchom: .venv\\Scripts\\python tools\\make_splash.py
Uwaga: nie ustawiaj QT_QPA_PLATFORM=offscreen – w tym trybie Qt nie widzi czcionek
systemowych i zamiast liter rysuje kwadraty.
Tekst etapu startu (np. "Opening database... (2/3)") dopisuje PyInstaller w miejscu
text_pos z pliku .spec, więc dolny pasek musi zostać pusty.
"""
import os
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication

W, H = 520, 270
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "splash.png")

app = QApplication(sys.argv)

img = QImage(W, H, QImage.Format_RGB32)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
p.setRenderHint(QPainter.TextAntialiasing)

# tło
bg = QLinearGradient(0, 0, W, H)
bg.setColorAt(0, QColor("#1c2735"))
bg.setColorAt(1, QColor("#111821"))
p.fillRect(0, 0, W, H, bg)

# ikonka: siatka 3x3 „kostek" (jak tablica Monitoring)
size, gap, x0, y0 = 14, 5, 36, 52
colors = ["#00BCff", "#2e86b8", "#2e86b8", "#2e86b8", "#00BCff", "#2e86b8", "#2e86b8", "#2e86b8", "#00BCff"]
for i, color in enumerate(colors):
    r, c = divmod(i, 3)
    path = QPainterPath()
    path.addRoundedRect(QRectF(x0 + c * (size + gap), y0 + r * (size + gap), size, size), 3, 3)
    p.fillPath(path, QColor(color))

# nazwa
title_font = QFont("Segoe UI Semibold", 22)
p.setFont(title_font)
p.setPen(QColor("#ffffff"))
p.drawText(QRectF(108, 46, W - 140, 40), Qt.AlignLeft | Qt.AlignVCenter, "Planning Manager")

p.setFont(QFont("Segoe UI", 11))
p.setPen(QColor("#00BCff"))
p.drawText(QRectF(110, 84, W - 140, 24), Qt.AlignLeft | Qt.AlignVCenter, "Planning  ·  Monitoring")

p.setFont(QFont("Segoe UI", 10))
p.setPen(QColor("#8696a8"))
p.drawText(QRectF(36, 150, W - 72, 22), Qt.AlignLeft | Qt.AlignVCenter, "Starting the application, please wait…")

# dolny pasek pod tekst etapu
p.fillRect(0, 210, W, H - 210, QColor("#0c1219"))
p.setPen(QPen(QColor("#00BCff"), 2))
p.drawLine(0, 210, W, 210)

p.end()
img.save(OUT)
print("saved", OUT)
