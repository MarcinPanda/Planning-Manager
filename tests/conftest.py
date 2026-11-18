import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pm import config, db, monitoring, theme  # noqa: E402

theme.persist = False   # testy nie zmieniają zapisanego motywu użytkownika
monitoring.LayoutStore = monitoring.MemoryLayoutStore   # ani ułożenia tablicy (QSettings)

# Zabezpieczenie: domyślna baza w testach to folder tymczasowy, nigdy prawdziwa planning_data.db
# (nawet gdyby test cofnął podmianę ścieżki).
import tempfile  # noqa: E402

config.use_database_folder(tempfile.mkdtemp(prefix="pm-tests-"))
config.SETTINGS_PATH = os.path.join(config.DB_FOLDER, "settings.ini")


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Każdy test dostaje własną, pustą bazę w katalogu tymczasowym."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(config, "ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setattr(db, "current_shift_id", None)
    db.init_db()
    yield tmp_path
    config.apply_zones(config.DEFAULT_ZONES)   # strefy zmienione w teście nie przechodzą do kolejnych


def make_employee(lastname="Test", firstname="Anna", department="Buffer",
                  work_hours="06:00-15:00", shift="Ochtend", computed_hours=8.0, **extra):
    data = {
        "lastname": lastname, "firstname": firstname, "department": department,
        "work_hours": work_hours, "shift": shift, "computed_hours": computed_hours,
    }
    data.update(extra)
    return db.insert_employee_to_db(data)
