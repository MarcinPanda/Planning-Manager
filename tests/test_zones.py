"""Etap 4: strefy w bazie (Edit zones…) i ułożenie klocków tablicy (Arrange board)."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from pm import config, db
from pm.monitoring import MemoryLayoutStore, MonitoringView, move_before, ordered

from conftest import make_employee


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _reach():
    return db.load_zones()["Reachtruck"]


def _emp(emp_id):
    return next(e for e in db.load_employees_from_db() if e.employee_id == emp_id)


def _reacher(position, **kw):
    emp_id = make_employee(department="Reachtruck", **kw)
    db.set_positions_in_db(emp_id, [position])
    return emp_id


# ------------------------------------------------------------------ baza
def test_new_database_gets_default_zones(temp_db):
    zones = db.load_zones()
    assert zones == config.DEFAULT_ZONES
    assert ("Zuid", "South") in zones["Reachtruck"] and ("Noord", "North") in zones["Reachtruck"]


def test_add_zone_and_change_hall_and_order(temp_db):
    entries = [("Nieuw", "South")] + [(n, h) for n, h in _reach() if n != "Noord"] + [("Noord", "South")]
    assert db.save_zones("Reachtruck", entries) == []
    assert _reach() == entries
    assert config.SUB_POSITIONS["Reachtruck"][0] == "Nieuw"
    assert config.hall_of("Reachtruck", "Noord") == "South"
    assert config.hall_of("Orderpicker", "Choco (12)") == "North"     # Picking bez zmian


def test_rename_keeps_people_only_in_that_department(temp_db):
    reacher = _reacher("Grenade", lastname="Reach")
    picker = make_employee(lastname="Pick", department="Orderpicker")
    db.set_positions_in_db(picker, ["Grenade"])

    entries = [("Grenade Zuid" if n == "Grenade" else n, h) for n, h in _reach()]
    assert db.save_zones("Reachtruck", entries, {"Grenade": "Grenade Zuid"}) == []
    assert _emp(reacher).positions == ["Grenade Zuid"]
    assert _emp(picker).positions == ["Grenade"]                      # Picking ma własną strefę Grenade


def test_rename_also_updates_saved_consolidation_positions(temp_db):
    reacher = _reacher("Noord")
    conn = db.get_connection()
    conn.execute("INSERT INTO consolidation_prev (employee_id, positions) VALUES (?, ?)", (reacher, "Noord;Zuid"))
    conn.commit()
    conn.close()
    entries = [("North" if n == "Noord" else n, h) for n, h in _reach()]
    assert db.save_zones("Reachtruck", entries, {"Noord": "North"}) == []
    conn = db.get_connection()
    value = conn.execute("SELECT positions FROM consolidation_prev WHERE employee_id = ?", (reacher,)).fetchone()[0]
    conn.close()
    assert value == "North;Zuid"


def test_zone_with_people_cannot_be_removed(temp_db):
    _reacher("Jordan", lastname="Visser", firstname="Tom")
    before = _reach()
    errors = db.save_zones("Reachtruck", [(n, h) for n, h in before if n != "Jordan"])
    assert errors and "Jordan" in errors[0] and "Tom Visser" in errors[0]
    assert _reach() == before                                          # nic nie zapisane


def test_empty_zone_can_be_removed(temp_db):
    entries = [(n, h) for n, h in _reach() if n != "Jordan"]
    assert db.save_zones("Reachtruck", entries) == []
    assert "Jordan" not in config.SUB_POSITIONS["Reachtruck"]


@pytest.mark.parametrize("zone", config.PROTECTED_ZONES)
def test_protected_zones_cannot_be_renamed_or_removed(temp_db, zone):
    before = _reach()
    assert db.save_zones("Reachtruck", [(n, h) for n, h in before if n != zone])
    renamed = [("X" if n == zone else n, h) for n, h in before]
    assert db.save_zones("Reachtruck", renamed, {zone: "X"})
    assert _reach() == before


def test_duplicate_and_empty_names_are_refused(temp_db):
    before = _reach()
    assert db.save_zones("Reachtruck", before + [("noord", "North")])
    assert db.save_zones("Reachtruck", before + [("  ", "North")])
    assert _reach() == before


# ------------------------------------------------------------------ tablica
def test_order_helpers():
    assert ordered(["A", "B", "C"], ["C", "X", "A"]) == ["C", "A", "B"]   # nowe na końcu, nieznane pomijane
    assert move_before(["A", "B", "C"], "A", "C") == ["B", "C", "A"]      # na ostatnie miejsce
    assert move_before(["A", "B", "C"], "C", "A") == ["C", "A", "B"]
    assert move_before(["A", "B"], "A", "A") == ["A", "B"]


def test_arrange_board_moves_and_resets(temp_db, app):
    store = MemoryLayoutStore()
    view = MonitoringView(layout_store=store)
    key = "North:Reachtruck"
    default = view.zone_order(key)
    assert default[:2] == ["Noord", "Replenish"]

    view.move_zone(key, "Noord", "Extra")
    app.processEvents()                       # przebudowa po upuszczeniu idzie przez QTimer
    moved = view.zone_order(key)
    assert moved.index("Noord") == default.index("Extra") and moved[0] == "Replenish"
    assert store.get(key) == moved

    again = MonitoringView(layout_store=store)   # ułożenie zapamiętane
    assert again.zone_order(key) == moved

    view.reset_layout()
    assert view.zone_order(key) == default and store.data == {}


def test_arrange_mode_blocks_moving_people(temp_db, app):
    view = MonitoringView(layout_store=MemoryLayoutStore())
    zone = view.position_zones[("Reachtruck", "Noord")]
    view.set_arranging(True)
    assert not zone.list.dragEnabled() and not zone.list.acceptDrops() and zone.acceptDrops()
    view.set_arranging(False)
    assert zone.list.dragEnabled() and zone.list.acceptDrops() and not zone.acceptDrops()


def test_board_follows_zone_changes(temp_db, app):
    view = MonitoringView(layout_store=MemoryLayoutStore())
    emp_id = _reacher("Noord", lastname="Visser", firstname="Tom")
    view.set_employees(db.load_employees_from_db())

    entries = [("Noord-Oost" if n == "Noord" else n, "South" if n == "Noord" else h) for n, h in _reach()]
    assert db.save_zones("Reachtruck", entries, {"Noord": "Noord-Oost"}) == []
    view.update_zones()
    view.set_employees(db.load_employees_from_db(), force=True)
    assert ("Reachtruck", "Noord") not in view.position_zones
    assert "Noord-Oost" in view.zone_order("South:Reachtruck")
    assert view.position_zones[("Reachtruck", "Noord-Oost")].ids() == [emp_id]


def test_dialog_reports_renames_by_original_name(temp_db, app):
    from pm.zones_dialog import ZonesDialog

    dialog = ZonesDialog(db.load_zones())
    assert dialog.dept_combo.currentData() == "Reachtruck"
    item = dialog.list.item(0)
    assert item.data(Qt.UserRole + 1) == "Noord"
    item.setData(Qt.UserRole + 1, "B")
    item.setData(Qt.UserRole + 1, "C")                 # dwa razy zmieniona nazwa -> {Noord: C}
    dialog.list.setCurrentRow(1)
    dialog.toggle_hall()                               # Replenish -> South
    entries, renames = dialog.changes()["Reachtruck"]
    assert renames == {"Noord": "C"}
    assert entries[:2] == [("C", "North"), ("Replenish", "South")]
    assert db.save_zones("Reachtruck", entries, renames) == []

    kantel = next(i for i in range(dialog.list.count())
                  if dialog.list.item(i).data(Qt.UserRole) == "Kantel/Consolidatie")
    dialog.list.setCurrentRow(kantel)
    assert not dialog.rename_button.isEnabled() and not dialog.remove_button.isEnabled()
