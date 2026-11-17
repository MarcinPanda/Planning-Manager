"""Uruchomienie aplikacji."""
import sys

from PySide6.QtWidgets import QApplication

from . import db, splash
from .main_window import MainWindow


def main():
    splash.step(2, "Opening database...")
    db.init_db()
    db.backup_db()

    splash.step(3, "Building the window...")
    app = QApplication(sys.argv)

    main_window = MainWindow()
    main_window.showMaximized()
    splash.close()

    sys.exit(app.exec())
