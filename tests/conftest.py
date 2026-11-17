import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pm import config, db, theme  # noqa: E402

theme.persist = False   # testy nie zmieniają zapisanego motywu użytkownika


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Każdy test dostaje własną, pustą bazę w katalogu tymczasowym."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(config, "ARCHIVE_DIR", str(tmp_path / "archive"))
    db.init_db()
    return tmp_path


def make_employee(lastname="Test", firstname="Anna", department="Buffer",
                  work_hours="06:00-15:00", shift="Ochtend", computed_hours=8.0, **extra):
    data = {
        "lastname": lastname, "firstname": firstname, "department": department,
        "work_hours": work_hours, "shift": shift, "computed_hours": computed_hours,
    }
    data.update(extra)
    return db.insert_employee_to_db(data)
