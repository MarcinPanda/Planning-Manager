"""Zakładka Loginy: numery 001–299, przypisanie do osoby, statusy, import z podglądem."""
import pandas as pd
import pytest

from pm import db
from conftest import make_employee


def _row(number):
    return next(r for r in db.load_login_numbers() if r["number"] == number)


def _login_of(lastname):
    return next(e.login for e in db.load_employees_from_db() if e.lastname == lastname)


def test_numbers_001_to_299_start_free(temp_db):
    rows = db.load_login_numbers()
    assert [r["number"] for r in rows][:2] == ["001", "002"] and rows[-1]["number"] == "299"
    assert {db.login_status(r) for r in rows} == {"free"}


def test_assign_moves_and_releases(temp_db):
    make_employee(lastname="Dijk", firstname="Jan van")
    assert db.assign_login("012", "Jan van Dijk") == []
    assert _login_of("Dijk") == "012"

    # drugi numer dla tej samej osoby: stary się zwalnia
    warnings = db.assign_login("013", "Jan van Dijk")
    assert "012" in warnings[0] and db.login_status(_row("012")) == "free"
    assert _login_of("Dijk") == "013"

    # zajęty numer nie przechodzi do innej osoby
    with pytest.raises(ValueError, match="already given"):
        db.assign_login("013", "Ewa Nowak")

    db.release_login("013")
    assert _login_of("Dijk") == ""


def test_same_person_fixes_spelling(temp_db):
    """Plik loginów „AHMAD-NICOLAE KHALAF", plan „Ahmad Khalaf Junior": potwierdzenie = ta sama osoba."""
    make_employee(lastname="Khalaf Junior", firstname="Ahmad")
    db.assign_login("180", "AHMAD-NICOLAE KHALAF")
    assert _login_of("Khalaf Junior") == ""
    db.assign_login("180", "Ahmad Khalaf Junior", same_person=True)
    assert _login_of("Khalaf Junior") == "180" and _row("180")["name"] == "Ahmad Khalaf Junior"


def test_states_block_assignment(temp_db):
    db.set_login_state("020", "blocked", "scanner broken")
    row = _row("020")
    assert db.login_status(row) == "blocked" and row["note"] == "scanner broken"
    with pytest.raises(ValueError, match="blocked"):
        db.assign_login("020", "Ewa Nowak")
    db.set_login_state("020", "ok")
    assert db.assign_login("020", "Ewa Nowak") == []


def test_import_preview_skips_conflicts(temp_db):
    db.assign_login("007", "Somebody Else")
    path = str(temp_db / "inlognamen.xlsx")
    rows = [["Nummer-1", "Naam", "Noord", "Zuid", "Reach"],
            ["7", "Jan van Dijk", "N007P", "Z007P", "R007R"],     # numer zajęty
            ["8", "Ewa Nowak", "N008P", "Z008P", "R008R"],        # nowy
            ["8", "Piet Twice", "N008P", "Z008P", "R008R"],       # numer drugi raz w pliku
            ["450", "Out Of Range", "N450P", "", ""],             # spoza 001–299
            ["", "Only Zuid", "", "Z030P", ""]]                   # tylko Z…P – nieużywane, pomijamy
    pd.DataFrame(rows).to_excel(path, sheet_name="Inlognamen", header=False, index=False)

    preview = {r["name"]: r for r in db.preview_logins_import(path)}
    assert "Only Zuid" not in preview
    assert preview["Ewa Nowak"]["action"] == "new"
    assert preview["Jan van Dijk"]["action"] == "skip" and "Somebody Else" in preview["Jan van Dijk"]["detail"]
    assert preview["Piet Twice"]["action"] == "skip"
    assert preview["Out Of Range"]["action"] == "skip"

    assert db.apply_logins_import(list(preview.values())) == 1
    assert _row("008")["name"] == "Ewa Nowak" and _row("007")["name"] == "Somebody Else"


def test_old_logins_table_is_moved_once(temp_db):
    conn = db.get_connection()
    conn.executemany("INSERT INTO logins (name_key, name, login) VALUES (?, ?, ?)",
                     [(db.name_key("Jan van Dijk"), "Jan van Dijk", "007"),
                      (db.name_key("Ewa Nowak"), "Ewa Nowak", "007")])   # ten sam numer dwa razy
    conn.execute("UPDATE login_numbers SET name = '', name_key = ''")
    conn.execute("DELETE FROM meta WHERE key = 'logins_migrated'")   # baza sprzed Etapu 5
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()

    db.init_db()
    db.init_db()
    row = _row("007")
    assert row["name"] in ("Jan van Dijk", "Ewa Nowak") and "also in old list" in row["note"]
    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM change_log WHERE action = 'Logins moved'").fetchone()[0] == 1
    conn.close()


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_logins_view_filters_and_counts(app, temp_db):
    from pm.logins_view import COL, LoginsView
    make_employee(lastname="Dijk", firstname="Jan van")
    db.assign_login("012", "Jan van Dijk")
    db.set_login_state("020", "damaged", "cable")
    view = LoginsView()
    view.set_data(db.load_login_numbers(), db.load_employees_from_db())
    assert view.counts() == {"all": 299, "free": 297, "assigned": 1, "damaged": 1, "blocked": 0}
    view.filter_buttons["assigned"].setChecked(True)
    assert view.shown_numbers() == ["012"]
    assert view.table.item(0, COL["Today"]).text() == "✓"
    view.filter_buttons["all"].setChecked(True)
    view.search.setText("cable")
    assert view.shown_numbers() == ["020"]
    assert "020" not in view.free_numbers() and "012" not in view.free_numbers()


def test_add_login_dialog_offers_same_person(app, temp_db):
    from pm.logins_view import LoginForPersonDialog, similar_logins
    db.assign_login("180", "AHMAD-NICOLAE KHALAF")
    db.assign_login("181", "Piet Jansen")
    rows = db.load_login_numbers()
    similar = similar_logins(rows, "Ahmad", "Khalaf")
    assert [r["number"] for r in similar] == ["180"]

    dialog = LoginForPersonDialog("Ahmad Khalaf", ["001", "002"], similar)
    assert dialog.value() == (None, False) and not dialog.ok_button.isEnabled()   # podobne nazwisko: wybór świadomy
    dialog.choices[0][0].setChecked(True)
    assert dialog.value() == ("180", True) and dialog.ok_button.isEnabled()
    dialog.new_radio.setChecked(True)
    assert dialog.value() == ("001", False)          # najniższy wolny numer

    plain = LoginForPersonDialog("Ewa Nowak", ["001"], [])
    assert plain.value() == ("001", False) and plain.ok_button.isEnabled()


def test_older_exe_does_not_rerun_login_move(temp_db):
    """Starsze exe w tym samym folderze ustawiają user_version = 2 – zwolnienia i poprawki pisowni zostają."""
    conn = db.get_connection()
    conn.executemany("INSERT INTO logins (name_key, name, login) VALUES (?, ?, ?)",
                     [(db.name_key("Jan van Dijk"), "Jan van Dijk", "007"),
                      (db.name_key("MARKUS AUKSTARS"), "MARKUS AUKSTARS", "030")])
    conn.commit()
    conn.close()
    db.release_login("007")
    db.assign_login("030", "Markuss Aukstars", same_person=True)
    conn = db.get_connection()
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()

    db.init_db()
    assert db.schema_version() == db.SCHEMA_VERSION
    assert _row("007")["name"] == "" and _row("030")["name"] == "Markuss Aukstars" and _row("030")["note"] == ""


def test_import_skips_damaged_number(temp_db):
    db.set_login_state("008", "damaged", "cable")
    path = str(temp_db / "inlognamen.xlsx")
    pd.DataFrame([["Nummer-1", "Naam"], ["8", "Ewa Nowak"]]).to_excel(path, header=False, index=False)
    preview = db.preview_logins_import(path)
    assert preview[0]["action"] == "skip" and "damaged" in preview[0]["detail"]
