"""Etap 4: strefy w bazie (Edit zones…) i ułożenie klocków tablicy (klocek za nagłówek)."""
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


def test_block_order_is_kept_and_reset(temp_db, app):
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


def _send_block_drop(widget, key, title, app):
    """Upuszczenie klocka na widżet (np. listę osób innego klocka) – tak jak robi to Qt przy przeciąganiu."""
    import json
    from PySide6.QtCore import QMimeData, QPoint
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from pm.monitoring import ZONE_MIME_TYPE

    mime = QMimeData()
    mime.setData(ZONE_MIME_TYPE, json.dumps({"column": key, "title": title}).encode("utf-8"))
    point = QPoint(5, 5)
    enter = QDragEnterEvent(point, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    app.sendEvent(widget, enter)
    drop = QDropEvent(point, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    app.sendEvent(widget, drop)
    return enter.isAccepted(), drop.isAccepted()


def test_block_moves_by_title_without_any_mode(temp_db, app):
    view = MonitoringView(layout_store=MemoryLayoutStore())
    key = "North:Reachtruck"
    target = view.position_zones[("Reachtruck", "Extra")]
    # karty osób działają jak zwykle, a klocek przyjmuje upuszczony klocek nawet nad listą osób
    assert target.list.dragEnabled() and target.list.acceptDrops() and target.acceptDrops()
    assert _send_block_drop(target.list.viewport(), key, "Noord", app) == (True, True)
    app.processEvents()
    assert view.zone_order(key).index("Noord") == 4

    # klocek z innej kolumny – nie
    picking = view.position_zones[("Orderpicker", "Choco (12)")]
    assert _send_block_drop(picking.list.viewport(), key, "Replenish", app)[1] is False


def test_dragging_a_block_lifts_the_others_in_its_column(temp_db, app):
    view = MonitoringView(layout_store=MemoryLayoutStore())
    source = view.position_zones[("Reachtruck", "Noord")]
    other = view.position_zones[("Reachtruck", "Extra")]
    picking = view.position_zones[("Orderpicker", "Choco (12)")]
    view._show_drop_targets("North:Reachtruck", "Noord", True)
    assert other.property("dropTarget") and other.graphicsEffect() is None
    assert not source.property("dropTarget") and source.graphicsEffect() is not None   # przygaszony
    assert picking.graphicsEffect() is None
    view._show_drop_targets("North:Reachtruck", "Noord", False)
    assert not other.property("dropTarget")
    assert source.graphicsEffect() is None


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


def test_board_operations_on_zones(temp_db):
    assert db.add_zone("Reachtruck", "Mars NL", "South") == []
    reach = _reach()
    assert reach[[n for n, _ in reach].index("Reflex") + 1] == ("Mars NL", "South")   # na końcu hali South
    assert config.hall_of("Reachtruck", "Mars NL") == "South"

    emp_id = _reacher("Mars NL")
    assert db.rename_zone("Reachtruck", "Mars NL", "Mars Nederland") == []
    assert _emp(emp_id).positions == ["Mars Nederland"]
    assert db.set_zone_hall("Reachtruck", "Mars Nederland", "North") == []
    assert config.hall_of("Reachtruck", "Mars Nederland") == "North"
    assert db.remove_zone("Reachtruck", "Mars Nederland")                 # ktoś w niej jest
    db.set_positions_in_db(emp_id, ["Noord"])
    assert db.remove_zone("Reachtruck", "Mars Nederland") == []
    assert "Mars Nederland" not in config.SUB_POSITIONS["Reachtruck"]


def test_added_department_on_board_and_in_hours(temp_db):
    assert db.add_department("Inbound 6", "Inbound", "Lossen - inslag controle") == []
    assert db.add_department("Sorteren", "Other", "") == []
    assert db.add_department("laden", "Other", "") and db.add_department("  ", "Other", "")
    assert "Inbound 6" in config.TEAM_LIST and config.is_inbound("Inbound 6")
    assert config.HOURS_COLUMN_MAP["Inbound 6"] == "Lossen - inslag controle"
    assert "Sorteren" not in config.HOURS_COLUMN_MAP                      # kolumna wybierana przy zapisie

    emp_id = make_employee(department="Sorteren")
    assert db.load_employees_from_db()[0].active_department == "Sorteren"
    assert db.remove_department("Laden")                                  # wbudowanego nie
    assert db.remove_department("Sorteren")                               # ktoś w nim jest
    assert db.move_employees_in_db([emp_id], "Laden", "", "07:00", from_start=True) == []
    assert db.remove_department("Sorteren") == []
    assert "Sorteren" not in config.TEAM_LIST


def test_board_shows_added_blocks(temp_db, app):
    view = MonitoringView(layout_store=MemoryLayoutStore())
    columns = {c.key: c for c in view.columns}
    assert all(hasattr(c, "add_button") for c in columns.values())       # „+" przy każdej kolumnie
    asked = []
    view.board_edit_requested.connect(lambda action, params: asked.append((action, params)))

    db.add_zone("Orderpicker", "Lidl", "North")
    db.add_department("Inbound 6", "Inbound", "")
    view.update_zones()
    assert "Lidl" in view.zone_order("North:Orderpicker")
    assert "Inbound 6" in view.zone_order("Both:Inbound")
    assert "Inbound 6" not in view.zone_order("Both:Other")
