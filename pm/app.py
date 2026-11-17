"""Uruchomienie aplikacji."""
import os
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from . import config, db, splash, theme
from .main_window import MainWindow


def check_database_location():
    """Baza może leżeć na dysku sieciowym (settings.ini). Gdy folder jest niedostępny – jasny komunikat,
    nigdy nie tworzymy po cichu nowej, pustej bazy w innym miejscu. Zwraca False = zamknij program."""
    shared = os.path.normcase(config.DB_FOLDER) != os.path.normcase(config.BASE_DIR)
    while not os.path.isdir(config.DB_FOLDER):
        splash.close()
        box = QMessageBox(QMessageBox.Critical, "Database not reachable",
                          f"The database folder cannot be reached:\n{config.DB_FOLDER}\n\n"
                          "Check the network drive (VPN / cable / login) and try again.\n"
                          f"The folder is set in:\n{config.SETTINGS_PATH}")
        retry = box.addButton("Try again", QMessageBox.AcceptRole)
        box.addButton("Close", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not retry:
            return False
    if shared and not os.path.exists(config.DB_PATH):
        splash.close()
        reply = QMessageBox.question(
            None, "No database yet",
            f"There is no database in the shared folder yet:\n{config.DB_FOLDER}\n\nCreate a new, empty one there?",
        )
        if reply != QMessageBox.Yes:
            return False
    return True


def main():
    app = QApplication(sys.argv)
    theme.apply(app)   # zapamiętany motyw (jasny / ciemny), ten sam wygląd na każdym komputerze

    splash.step(2, "Opening database...")
    if not check_database_location():
        sys.exit(1)
    db.init_db()
    db.backup_db()

    splash.step(3, "Building the window...")
    main_window = MainWindow()
    main_window.showMaximized()
    splash.close()

    sys.exit(app.exec())
