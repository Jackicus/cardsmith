"""Deck table: every data row, with a checkbox to include it in the print."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..data import Deck


class DeckModel(QAbstractTableModel):
    includedChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.deck: Deck | None = None
        self.flags_by_row: dict[int, str] = {}

    def set_deck(self, deck: Deck | None) -> None:
        self.beginResetModel()
        self.deck = deck
        self.flags_by_row = {}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if self.deck is None or parent.isValid() else len(self.deck.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if self.deck is None else len(self.deck.columns) + 1

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole or self.deck is None:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return "#" if section == 0 else self.deck.columns[section - 1]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if self.deck is None or not index.isValid():
            return None
        r, c = index.row(), index.column()
        if c == 0:
            if role == Qt.ItemDataRole.CheckStateRole:
                return Qt.CheckState.Checked if self.deck.included[r] else Qt.CheckState.Unchecked
            if role == Qt.ItemDataRole.DisplayRole:
                flag = self.flags_by_row.get(r)
                return f"{r + 1}{'  ⚠' if flag else ''}"
            if role == Qt.ItemDataRole.ToolTipRole:
                return self.flags_by_row.get(r)
            if role == Qt.ItemDataRole.ForegroundRole and self.flags_by_row.get(r):
                return QColor("#E0533D")
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return self.deck.rows[r].get(self.deck.columns[c - 1], "")
        if role == Qt.ItemDataRole.ForegroundRole and not self.deck.included[r]:
            return QColor("#999999")
        return None

    def flags(self, index):
        f = super().flags(index)
        if index.column() == 0:
            f |= Qt.ItemFlag.ItemIsUserCheckable
        return f

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0 and self.deck:
            self.deck.included[index.row()] = Qt.CheckState(value) == Qt.CheckState.Checked
            self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), self.columnCount() - 1))
            self.includedChanged.emit()
            return True
        return False

    def set_all(self, rows: list[int], value: bool) -> None:
        if not self.deck:
            return
        for r in rows:
            self.deck.included[r] = value
        self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))
        self.includedChanged.emit()

    def set_flags(self, flags: dict[int, str]) -> None:
        self.flags_by_row = flags
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, 0))


class _Filter(QSortFilterProxyModel):
    def filterAcceptsRow(self, row, parent) -> bool:
        pat = self.filterRegularExpression().pattern()
        if not pat:
            return True
        m: DeckModel = self.sourceModel()
        if m.deck is None:
            return True
        pat = pat.lower()
        return any(pat in str(v).lower() for v in m.deck.rows[row].values()) or pat == str(row + 1)


class DeckPanel(QWidget):
    rowActivated = Signal(int)
    openRequested = Signal()
    includedChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.title = QLabel("No deck loaded")
        self.title.setObjectName("Title")
        self.count = QLabel()
        self.count.setObjectName("Muted")
        openb = QPushButton("Open…")
        openb.setToolTip("Open a CSV, TSV, Anki export or JSON file")
        openb.clicked.connect(self.openRequested.emit)
        head.addWidget(self.title, 1)
        head.addWidget(openb)
        v.addLayout(head)
        v.addWidget(self.count)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search cards…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        alln = QPushButton("All")
        alln.setToolTip("Include all shown cards")
        alln.clicked.connect(lambda: self._set_shown(True))
        none = QPushButton("None")
        none.setToolTip("Exclude all shown cards")
        none.clicked.connect(lambda: self._set_shown(False))
        tools.addWidget(self.search, 1)
        tools.addWidget(alln)
        tools.addWidget(none)
        v.addLayout(tools)

        self.model = DeckModel()
        self.model.includedChanged.connect(self._included)
        self.proxy = _Filter()
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.selectionModel().currentRowChanged.connect(self._current)
        v.addWidget(self.table, 1)

    def set_deck(self, deck: Deck | None) -> None:
        self.model.set_deck(deck)
        self.title.setText(deck.name if deck else "No deck loaded")
        self.table.resizeColumnsToContents()
        for c in range(1, self.model.columnCount()):
            self.table.setColumnWidth(c, min(self.table.columnWidth(c), 160))
        self._included()

    def select_row(self, row: int) -> None:
        src = self.model.index(row, 0)
        idx = self.proxy.mapFromSource(src)
        if idx.isValid():
            self.table.blockSignals(True)
            self.table.selectionModel().blockSignals(True)
            self.table.setCurrentIndex(idx)
            self.table.scrollTo(idx)
            self.table.selectionModel().blockSignals(False)
            self.table.blockSignals(False)

    def _current(self, cur, _prev) -> None:
        if cur.isValid():
            self.rowActivated.emit(self.proxy.mapToSource(cur).row())

    def _filter(self, text: str) -> None:
        self.proxy.setFilterRegularExpression(text.strip())

    def _set_shown(self, value: bool) -> None:
        rows = [self.proxy.mapToSource(self.proxy.index(r, 0)).row() for r in range(self.proxy.rowCount())]
        self.model.set_all(rows, value)

    def _included(self) -> None:
        d = self.model.deck
        if d is None:
            self.count.setText("Open a spreadsheet to start – any columns work.")
        else:
            n = sum(d.included)
            self.count.setText(f"{n} of {len(d)} cards selected · {len(d.columns)} columns")
        self.includedChanged.emit()
