"""⋯ → Edit zones…: strefy / klienci Reach i Picking (wspólne dla wszystkich komputerów)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from . import config

ORIGINAL = Qt.UserRole        # nazwa w bazie przed edycją ('' = nowa strefa)
NAME = Qt.UserRole + 1
HALL = Qt.UserRole + 2

HELP = (
    "Zones / clients on the Monitoring board – <b>the same for every computer</b>.<br>"
    "Drag a line to change the default order. A zone with people on this shift cannot be removed "
    "(move them first). People stay in a renamed zone.<br>"
    "<i>Kantel/Consolidatie</i> and <i>Reflex</i> are used by the consolidation list and the hours file – "
    "they can be moved, not renamed or removed.<br>"
    "Saved changes are <b>not</b> undone with Ctrl+Z."
)


class ZonesDialog(QDialog):
    def __init__(self, zones, parent=None):
        """zones = {dział: [(nazwa, hala)]} – bieżący stan z bazy."""
        super().__init__(parent)
        self.setWindowTitle("Edit zones")
        self.resize(460, 560)
        self.zones = {dept: list(entries) for dept, entries in zones.items()}
        self.edited = {}          # dział -> lista pozycji z okna (tylko zmienione działy)

        layout = QVBoxLayout(self)
        info = QLabel(HELP)
        info.setWordWrap(True)
        layout.addWidget(info)

        self.dept_combo = QComboBox()
        for dept in config.DEFAULT_ZONES:
            self.dept_combo.addItem(config.SUB_POSITION_TITLES.get(dept, dept), dept)
        self.dept_combo.currentIndexChanged.connect(self._switch)
        layout.addWidget(self.dept_combo)

        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.currentItemChanged.connect(self._update_buttons)
        self.list.itemDoubleClicked.connect(lambda _item: self.rename())
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        self.add_button = QPushButton("Add…")
        self.add_button.clicked.connect(self.add)
        self.rename_button = QPushButton("Rename…")
        self.rename_button.clicked.connect(self.rename)
        self.hall_button = QPushButton("North ⇄ South")
        self.hall_button.clicked.connect(self.toggle_hall)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self.remove)
        for button in (self.add_button, self.rename_button, self.hall_button, self.remove_button):
            row.addWidget(button)
        layout.addLayout(row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self._current = None
        self._switch()

    # ------------------------------------------------------------ lista
    def _item(self, original, name, hall):
        item = QListWidgetItem()
        item.setData(ORIGINAL, original)
        item.setData(NAME, name)
        item.setData(HALL, hall)
        item.setFlags(item.flags() | Qt.ItemIsDragEnabled)
        self._label(item)
        return item

    @staticmethod
    def _label(item):
        name, hall = item.data(NAME), item.data(HALL)
        lock = "   🔒" if item.data(ORIGINAL) in config.PROTECTED_ZONES else ""
        item.setText(f"{name}    ·  {hall}{lock}")

    def _entries_in_list(self):
        return [(self.list.item(i).data(ORIGINAL), self.list.item(i).data(NAME), self.list.item(i).data(HALL))
                for i in range(self.list.count())]

    def _store_current(self):
        if self._current is not None:
            self.edited[self._current] = self._entries_in_list()

    def _switch(self):
        self._store_current()
        dept = self.dept_combo.currentData()
        self._current = dept
        self.list.clear()
        rows = self.edited.get(dept) or [(name, name, hall) for name, hall in self.zones.get(dept, [])]
        for original, name, hall in rows:
            self.list.addItem(self._item(original, name, hall))
        self._update_buttons()

    def _update_buttons(self, *_):
        item = self.list.currentItem()
        protected = item is not None and item.data(ORIGINAL) in config.PROTECTED_ZONES
        self.rename_button.setEnabled(item is not None and not protected)
        self.remove_button.setEnabled(item is not None and not protected)
        self.hall_button.setEnabled(item is not None)

    def _ask_name(self, title, text=""):
        name, ok = QInputDialog.getText(self, title, "Zone / client name:", text=text)
        name = name.strip()
        if not ok or not name:
            return None
        taken = {self.list.item(i).data(NAME).casefold() for i in range(self.list.count())
                 if self.list.item(i) is not self.list.currentItem() or title == "Add zone"}
        if name.casefold() in taken:
            QMessageBox.warning(self, title, f"'{name}' is already on the list.")
            return None
        if name in config.POSITION_RENAMES:
            QMessageBox.warning(self, title, f"'{name}' is an old zone name the program replaces automatically "
                                             f"('{config.POSITION_RENAMES[name]}'). Choose another name.")
            return None
        return name

    def add(self):
        name = self._ask_name("Add zone")
        if name is None:
            return
        item = self._item("", name, "North")
        self.list.addItem(item)
        self.list.setCurrentItem(item)

    def rename(self):
        item = self.list.currentItem()
        if item is None or item.data(ORIGINAL) in config.PROTECTED_ZONES:
            return
        name = self._ask_name("Rename zone", item.data(NAME))
        if name is None:
            return
        item.setData(NAME, name)
        self._label(item)

    def toggle_hall(self):
        item = self.list.currentItem()
        if item is None:
            return
        item.setData(HALL, "South" if item.data(HALL) == "North" else "North")
        self._label(item)

    def remove(self):
        item = self.list.currentItem()
        if item is None or item.data(ORIGINAL) in config.PROTECTED_ZONES:
            return
        self.list.takeItem(self.list.row(item))

    # ------------------------------------------------------------ wynik
    def changes(self):
        """{dział: (entries [(nazwa, hala)], renames {stara: nowa})} – tylko działy, które się zmieniły."""
        self._store_current()
        result = {}
        for dept, rows in self.edited.items():
            entries = [(name, hall) for _, name, hall in rows]
            renames = {original: name for original, name, _ in rows if original and original != name}
            if entries != self.zones.get(dept, []) or renames:
                result[dept] = (entries, renames)
        return result
