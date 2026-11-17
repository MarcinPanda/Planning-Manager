"""Uruchomienie aplikacji."""
import sys

from PySide6.QtWidgets import QApplication

from . import db
from .main_window import MainWindow


def main(with_monitoring=False):
    db.init_db()
    db.backup_db()

    app = QApplication(sys.argv)

    main_window = MainWindow(with_monitoring=with_monitoring)
    main_window.showMaximized()

    sys.exit(app.exec())
