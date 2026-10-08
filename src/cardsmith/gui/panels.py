"""Left-hand editing panels. Each edits the shared Template/Printer in place
and emits ``changed``; ``refresh()`` reloads the widgets from the model."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import fonts, plate, settings
from ..colours import PALETTES, colour_name
from ..model import (
    ALIGNMENTS,
    FIT_MODES,
    HOLE_POSITIONS,
    Printer,
    Slot,
    Template,
    colour_changes,
    height_bands,
)


def _spin(lo, hi, step=0.1, suffix=" mm", decimals=1, tip="") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(decimals)
    s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    s.setToolTip(tip)
    s.setAlignment(Qt.AlignmentFlag.AlignRight)
    s.setMinimumWidth(64)
    s.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return s


def _scroll(inner: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setWidget(inner)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return sa


def _hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setObjectName("Muted")
    return lab


class Binder:
    """Two-way glue between widgets and attributes of a model object."""

    def __init__(self, changed: Callable[[], None]) -> None:
        self.changed = changed
        self.items: list[tuple[QWidget, Callable, str]] = []

    def num(self, w, getobj, attr):
        def on(v):
            o = getobj()
            if o is not None and getattr(o, attr) != v:
                setattr(o, attr, int(v) if isinstance(w, QSpinBox) else float(v))
                self.changed()
        w.valueChanged.connect(on)
        self.items.append((w, getobj, attr))
        return w

    def check(self, w, getobj, attr):
        def on(v):
            o = getobj()
            if o is not None:
                setattr(o, attr, bool(v))
                self.changed()
        w.toggled.connect(on)
        self.items.append((w, getobj, attr))
        return w

    def combo(self, w: QComboBox, getobj, attr):
        def on(_):
            o = getobj()
            v = w.currentData()
            if o is not None and v is not None and getattr(o, attr) != v:
                setattr(o, attr, v)
                self.changed()
        w.currentIndexChanged.connect(on)
        self.items.append((w, getobj, attr))
        return w

    def text(self, w: QLineEdit, getobj, attr):
        def on(v):
            o = getobj()
            if o is not None and getattr(o, attr) != v:
                setattr(o, attr, v)
                self.changed()
        w.textChanged.connect(on)
        self.items.append((w, getobj, attr))
        return w

    def refresh(self) -> None:
        for w, getobj, attr in self.items:
            o = getobj()
            if o is None:
                continue
            v = getattr(o, attr)
            with QSignalBlocker(w):
                if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                    w.setValue(v)
                elif isinstance(w, (QCheckBox, QGroupBox)):
                    w.setChecked(bool(v))
                elif isinstance(w, QComboBox):
                    i = w.findData(v)
                    w.setCurrentIndex(max(0, i))
                elif isinstance(w, QLineEdit):
                    if w.text() != v:
                        w.setText(v)


class Panel(QWidget):
    changed = Signal()

    def __init__(self, get_template: Callable[[], Template], parent=None) -> None:
        super().__init__(parent)
        self.t = get_template
        self.b = Binder(self.changed.emit)

    def refresh(self) -> None:
        self.b.refresh()


# ---------------------------------------------------------------------------


class CardPanel(Panel):
    def __init__(self, get_template, parent=None) -> None:
        super().__init__(get_template, parent)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(4, 4, 8, 4)
        b = self.b
        card = lambda: self.t().card  # noqa: E731
        border = lambda: self.t().border  # noqa: E731
        hole = lambda: self.t().hole  # noqa: E731

        g = QGroupBox("Card")
        f = QFormLayout(g)
        size_row = QHBoxLayout()
        self.w = b.num(_spin(10, 400, 1, " mm", 1, "Card width"), card, "width")
        self.h = b.num(_spin(10, 400, 1, " mm", 1, "Card height"), card, "height")
        swap = QToolButton()
        swap.setText("⇄")
        swap.setToolTip("Swap width and height (portrait / landscape)")
        swap.clicked.connect(self._swap)
        size_row.addWidget(self.w)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.h)
        size_row.addWidget(swap)
        f.addRow("Size", size_row)
        presets = QComboBox()
        presets.addItem("Size presets…", None)
        for name, wh in CARD_PRESETS:
            presets.addItem(f"{name}  ({wh[0]:g} × {wh[1]:g})", wh)
        presets.currentIndexChanged.connect(lambda i: self._preset(presets))
        f.addRow("", presets)
        f.addRow("Thickness", b.num(_spin(0.4, 10, 0.2, " mm", 2,
                                          "Base thickness. Snapped to whole layers when exported."), card, "thickness"))
        f.addRow("Corner radius", b.num(_spin(0, 50, 0.5), card, "corner_radius"))
        f.addRow("Padding", b.num(_spin(0, 50, 0.5, tip="Safe margin kept free of text (dashed line)."),
                                  card, "padding"))
        v.addWidget(g)

        g = QGroupBox("Raised border")
        g.setCheckable(True)
        b.check(g, border, "enabled")
        f = QFormLayout(g)
        f.addRow("Width", b.num(_spin(0.2, 20, 0.2), border, "width"))
        f.addRow("Inset", b.num(_spin(0, 30, 0.2, tip="Gap between the card edge and the border."), border, "inset"))
        f.addRow("Height", b.num(_spin(0.2, 5, 0.2, " mm", 2, "How far it rises above the card."), border, "height"))
        f.addRow("", b.check(QCheckBox("Ring around the hole"), border, "around_hole"))
        v.addWidget(g)

        g = QGroupBox("Hole for a ring / lanyard")
        g.setCheckable(True)
        b.check(g, hole, "enabled")
        f = QFormLayout(g)
        f.addRow("Diameter", b.num(_spin(1, 30, 0.5), hole, "diameter"))
        pos = QComboBox()
        for p in HOLE_POSITIONS:
            pos.addItem(p.replace("-", " ").capitalize(), p)
        f.addRow("Position", b.combo(pos, hole, "position"))
        f.addRow("From edge", b.num(_spin(1, 50, 0.5, tip="Distance from the edge to the hole's centre."),
                                    hole, "offset"))
        v.addWidget(g)
        v.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(_scroll(inner))

    def _swap(self) -> None:
        c = self.t().card
        c.width, c.height = c.height, c.width
        self.refresh()
        self.changed.emit()

    def _preset(self, combo: QComboBox) -> None:
        wh = combo.currentData()
        if wh:
            c = self.t().card
            c.width, c.height = wh
            self.refresh()
            self.changed.emit()
        with QSignalBlocker(combo):
            combo.setCurrentIndex(0)


CARD_PRESETS = [
    ("Credit card", (54.0, 85.6)),
    ("Business card", (55.0, 91.0)),
    ("Poker card", (63.5, 88.9)),
    ("Mini card", (44.0, 63.0)),
    ("Tarot", (70.0, 120.0)),
    ("Square 50", (50.0, 50.0)),
    ("Square 64", (64.0, 64.0)),
    ("Tag", (30.0, 60.0)),
    ("Domino", (25.0, 50.0)),
]


# ---------------------------------------------------------------------------


class SlotsPanel(Panel):
    selectedChanged = Signal(int)

    def __init__(self, get_template, get_columns: Callable[[], list[str]], parent=None) -> None:
        super().__init__(get_template, parent)
        self.columns = get_columns
        self._current = -1
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        top = QWidget()
        tv = QVBoxLayout(top)
        tv.setContentsMargins(4, 4, 8, 0)
        tv.addWidget(_hint("Each slot is a line of raised text. Drag text in the preview to move it."))
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setMaximumHeight(150)
        self.list.currentRowChanged.connect(self._select)
        self.list.itemChanged.connect(self._item_toggled)
        self.list.model().rowsMoved.connect(self._rows_moved)
        tv.addWidget(self.list)
        row = QHBoxLayout()
        self.add_btn = QPushButton("＋ Add")
        self.add_btn.setToolTip("Add a text slot")
        self.add_menu = QMenu(self)
        self.add_btn.setMenu(self.add_menu)
        self.add_menu.aboutToShow.connect(self._fill_add_menu)
        dup = QPushButton("Duplicate")
        dup.clicked.connect(self._duplicate)
        rm = QPushButton("Remove")
        rm.clicked.connect(self._remove)
        row.addWidget(self.add_btn)
        row.addWidget(dup)
        row.addWidget(rm)
        row.addStretch(1)
        tv.addLayout(row)
        outer.addWidget(top)

        self.editor = QWidget()
        ev = QVBoxLayout(self.editor)
        ev.setContentsMargins(4, 0, 8, 4)
        b = self.b
        s = self.slot

        g = QGroupBox("Content")
        f = QFormLayout(g)
        f.addRow("Name", b.text(QLineEdit(), s, "name"))
        trow = QHBoxLayout()
        self.text_edit = b.text(QLineEdit(), s, "text")
        self.text_edit.setPlaceholderText("{column}  or plain text")
        self.text_edit.setToolTip(
            "Use {column} to pull from your data. Filters: {col|kanji} strips furigana, {col|kana} keeps "
            "readings, {col|first} takes the first of a list, {col|upper}. {#} = card number.")
        ins = QToolButton()
        ins.setText("{ }")
        ins.setToolTip("Insert a field or filter")
        ins.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.ins_menu = QMenu(self)
        self.ins_menu.aboutToShow.connect(self._fill_insert_menu)
        ins.setMenu(self.ins_menu)
        trow.addWidget(self.text_edit, 1)
        trow.addWidget(ins)
        f.addRow("Text", trow)
        ev.addWidget(g)

        g = QGroupBox("Font")
        f = QFormLayout(g)
        self.family = QComboBox()
        self.family.setEditable(True)
        self.family.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.family.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.family.setMinimumContentsLength(12)
        self.style_box = QComboBox()
        self.family.activated.connect(self._family_changed)
        self.family.lineEdit().editingFinished.connect(self._family_changed)
        self.style_box.activated.connect(self._style_changed)
        f.addRow("Family", self.family)
        f.addRow("Weight", self.style_box)
        f.addRow("Size", b.num(_spin(1, 200, 0.5, tip="Em size, like CSS font-size."), s, "size"))
        f.addRow("Letter spacing", b.num(_spin(-5, 20, 0.1, " mm", 2), s, "letter_spacing"))
        ev.addWidget(g)

        g = QGroupBox("Position")
        f = QFormLayout(g)
        al = QHBoxLayout()
        self.align_group = QButtonGroup(self)
        for i, (a, label) in enumerate(zip(ALIGNMENTS, ("Centre", "Left", "Right"))):
            btn = QPushButton(label)
            btn.setCheckable(True)
            self.align_group.addButton(btn, i)
            al.addWidget(btn)
        self.align_group.idClicked.connect(self._align)
        f.addRow("Align", al)
        f.addRow("From top", b.num(_spin(-50, 400, 0.5, tip="Vertical centre of the text, from the top edge."),
                                   s, "y"))
        f.addRow("Offset", b.num(_spin(-200, 200, 0.5, tip="Sideways: from centre, or from the padding edge "
                                                            "for left/right alignment."), s, "x_offset"))
        f.addRow("Max width", b.num(_spin(0, 400, 1, tip="0 = full card width minus padding."), s, "max_width"))
        ev.addWidget(g)

        g = QGroupBox("Fitting long text")
        f = QFormLayout(g)
        fit = QComboBox()
        for m, label in zip(FIT_MODES, ("Shrink to fit", "Wrap onto lines", "Leave as is")):
            fit.addItem(label, m)
        f.addRow("Mode", b.combo(fit, s, "fit"))
        f.addRow("Smallest size", b.num(_spin(1, 100, 0.5), s, "min_size"))
        ml = QSpinBox()
        ml.setRange(1, 20)
        ml.setMinimumWidth(64)
        ml.setAlignment(Qt.AlignmentFlag.AlignRight)
        f.addRow("Max lines", b.num(ml, s, "max_lines"))
        f.addRow("Line spacing", b.num(_spin(0.6, 3, 0.05, "×", 2), s, "line_spacing"))
        ev.addWidget(g)

        g = QGroupBox("Printing")
        f = QFormLayout(g)
        f.addRow("Raised by", b.num(_spin(0.2, 5, 0.2, " mm", 2, "Height above the card. Parts with the same "
                                                                  "height print in the same colour."), s, "height"))
        ev.addWidget(g)

        g = QGroupBox("Furigana (ruby text)")
        g.setCheckable(True)
        g.setToolTip("Write readings Anki-style – 漢字[かんじ] – and they appear above the kanji.")
        b.check(g, s, "ruby")
        f = QFormLayout(g)
        f.addRow("Size", b.num(_spin(0.2, 1, 0.05, "×", 2), s, "ruby_scale"))
        f.addRow("Gap", b.num(_spin(-5, 10, 0.1, " mm", 2), s, "ruby_gap"))
        ev.addWidget(g)
        ev.addStretch(1)
        outer.addWidget(_scroll(self.editor), 1)
        self._fill_families()

    # -- model access ------------------------------------------------------
    def slot(self) -> Slot | None:
        slots = self.t().slots
        return slots[self._current] if 0 <= self._current < len(slots) else None

    @property
    def current(self) -> int:
        return self._current

    def refresh(self) -> None:
        slots = self.t().slots
        with QSignalBlocker(self.list):
            self.list.clear()
            for sl in slots:
                it = QListWidgetItem(self._label(sl))
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
                it.setCheckState(Qt.CheckState.Checked if sl.enabled else Qt.CheckState.Unchecked)
                self.list.addItem(it)
            if slots:
                self._current = min(max(self._current, 0), len(slots) - 1)
                self.list.setCurrentRow(self._current)
            else:
                self._current = -1
        self.editor.setEnabled(self.slot() is not None)
        self._refresh_editor()

    def _refresh_editor(self) -> None:
        self.b.refresh()
        sl = self.slot()
        if sl is None:
            return
        ref = fonts.registry.resolve(sl.font)
        fam, _, style = sl.font.partition(":")
        if ref is not None and ":" in sl.font:
            fam = ref.family
        with QSignalBlocker(self.family):
            self.family.setEditText(fam)
        self._fill_styles(fam, style)
        self.align_group.button(ALIGNMENTS.index(sl.align) if sl.align in ALIGNMENTS else 0).setChecked(True)

    def _label(self, sl: Slot) -> str:
        return f"{sl.name}   ·   {sl.text}" if sl.text else sl.name

    def select(self, i: int) -> None:
        if 0 <= i < self.list.count():
            self.list.setCurrentRow(i)

    def _select(self, row: int) -> None:
        self._current = row
        self.editor.setEnabled(self.slot() is not None)
        self._refresh_editor()
        self.selectedChanged.emit(row)

    def _item_toggled(self, it: QListWidgetItem) -> None:
        i = self.list.row(it)
        slots = self.t().slots
        if 0 <= i < len(slots):
            slots[i].enabled = it.checkState() == Qt.CheckState.Checked
            self.changed.emit()

    def _rows_moved(self, *_):
        names = [self.list.item(i).text() for i in range(self.list.count())]
        slots = self.t().slots
        by_label = {}
        for sl in slots:
            by_label.setdefault(self._label(sl), []).append(sl)
        new = [by_label[n].pop(0) for n in names]
        slots[:] = new
        self._current = self.list.currentRow()
        self.changed.emit()

    def update_current_label(self) -> None:
        sl = self.slot()
        it = self.list.item(self._current) if sl else None
        if it is not None:
            with QSignalBlocker(self.list):
                it.setText(self._label(sl))

    # -- add / remove ------------------------------------------------------
    def _fill_add_menu(self) -> None:
        self.add_menu.clear()
        cols = self.columns()
        if cols:
            self.add_menu.addSection("From a column")
            for c in cols:
                self.add_menu.addAction(c, lambda c=c: self._add(c.capitalize(), "{" + c + "}"))
        self.add_menu.addSection("Other")
        self.add_menu.addAction("Fixed text", lambda: self._add("Label", "Text"))
        self.add_menu.addAction("Card number", lambda: self._add("Number", "{#}"))

    def _add(self, name: str, text: str) -> None:
        t = self.t()
        c = t.card
        used = [s.y for s in t.slots]
        y = c.height / 2
        if used:
            y = min(c.height - c.padding - 4, max(used) + 10)
        t.slots.append(Slot(name=name, text=text, font=t.fallback_fonts[0] if t.fallback_fonts else Slot().font,
                            size=6.0, y=y, height=t.slots[-1].height if t.slots else 0.6))
        self._current = len(t.slots) - 1
        self.refresh()
        self.changed.emit()

    def _duplicate(self) -> None:
        sl = self.slot()
        if sl is None:
            return
        import copy
        new = copy.deepcopy(sl)
        new.name = f"{sl.name} copy"
        new.y = sl.y + sl.size * 1.2
        self.t().slots.insert(self._current + 1, new)
        self._current += 1
        self.refresh()
        self.changed.emit()

    def _remove(self) -> None:
        if self.slot() is None:
            return
        del self.t().slots[self._current]
        self.refresh()
        self.changed.emit()

    # -- fields & fonts ----------------------------------------------------
    def _fill_insert_menu(self) -> None:
        m = self.ins_menu
        m.clear()
        m.addSection("Columns")
        for c in self.columns() or []:
            m.addAction("{" + c + "}", lambda c=c: self.text_edit.insert("{" + c + "}"))
        m.addAction("{#}  card number", lambda: self.text_edit.insert("{#}"))
        m.addSection("Filters (add after a column name)")
        for flt, desc in (("kanji", "drop furigana  漢字[かんじ] → 漢字"),
                          ("kana", "readings only  → かんじ"),
                          ("first", "first item of a list"),
                          ("upper", "UPPER CASE"), ("lower", "lower case")):
            m.addAction(f"|{flt}   {desc}", lambda f=flt: self._add_filter(f))

    def _add_filter(self, flt: str) -> None:
        txt = self.text_edit.text()
        pos = self.text_edit.cursorPosition()
        close = txt.rfind("}", 0, max(pos, 1) + 1)
        if close == -1:
            close = txt.find("}")
        if close == -1:
            return
        self.text_edit.setText(txt[:close] + "|" + flt + txt[close:])

    def _fill_families(self) -> None:
        fams = fonts.registry.families()
        self._families = fams
        with QSignalBlocker(self.family):
            self.family.clear()
            # Japanese-capable families first, they're what most people want here.
            ja = [f for f in fams if "CJK JP" in f or f.endswith(" JP") or "Japanese" in f]
            rest = [f for f in fams if f not in ja]
            for f in ja:
                self.family.addItem(f"{f}", f)
            if ja and rest:
                self.family.insertSeparator(self.family.count())
            for f in rest:
                self.family.addItem(f, f)

    def _fill_styles(self, fam: str, want: str) -> None:
        styles = self._families.get(fam, [])
        order = ["thin", "extralight", "light", "demilight", "regular", "book", "medium",
                 "semibold", "demibold", "bold", "extrabold", "heavy", "black"]
        styles = sorted(set(styles), key=lambda s: (order.index(s.lower()) if s.lower() in order else 50, s))
        with QSignalBlocker(self.style_box):
            self.style_box.clear()
            for st in styles:
                self.style_box.addItem(st, st)
            i = self.style_box.findData(want)
            if i < 0:
                for pref in ("Bold", "Regular"):
                    i = self.style_box.findData(pref)
                    if i >= 0:
                        break
            self.style_box.setCurrentIndex(max(0, i))

    def _family_changed(self, *_):
        sl = self.slot()
        if sl is None:
            return
        fam = self.family.currentText().strip()
        if fam not in self._families:
            return
        _, _, style = sl.font.partition(":")
        self._fill_styles(fam, style or "Bold")
        self._style_changed()

    def _style_changed(self, *_):
        sl = self.slot()
        if sl is None:
            return
        fam = self.family.currentText().strip()
        style = self.style_box.currentData() or ""
        new = f"{fam}:{style}" if style else fam
        if new != sl.font:
            sl.font = new
            self.changed.emit()

    def _align(self, i: int) -> None:
        sl = self.slot()
        if sl is not None and sl.align != ALIGNMENTS[i]:
            sl.align = ALIGNMENTS[i]
            sl.x_offset = 0.0 if ALIGNMENTS[i] == "center" else max(sl.x_offset, 0.0)
            self.b.refresh()
            self.changed.emit()


# ---------------------------------------------------------------------------


def _layers(a: int, b: int) -> str:
    return f"layer {a}" if a == b else f"layers {a}–{b}"


def swatch(colour: str, size: int = 18) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(colour))
    return QIcon(pm)


class ColoursPanel(Panel):
    def __init__(self, get_template, get_printer, parent=None) -> None:
        super().__init__(get_template, parent)
        self.p = get_printer
        inner = QWidget()
        self.v = QVBoxLayout(inner)
        self.v.setContentsMargins(4, 4, 8, 4)
        self.v.addWidget(_hint(
            "Each height is a colour band. On a single-nozzle printer you swap filament between bands; "
            "everything that rises into a band shows its colour from above."))
        pal = QComboBox()
        pal.addItem("Palette presets…", None)
        for name, cols in PALETTES.items():
            pal.addItem(swatch(cols[-1]), name, cols)
        pal.currentIndexChanged.connect(lambda _: self._palette(pal))
        self.v.addWidget(pal)
        self.bands_box = QVBoxLayout()
        self.v.addLayout(self.bands_box)
        self.v.addWidget(QLabel("Filament changes", objectName="Section"))
        self.plan = QLabel()
        self.plan.setWordWrap(True)
        self.plan.setTextFormat(Qt.TextFormat.RichText)
        self.v.addWidget(self.plan)
        self.v.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(_scroll(inner))

    def refresh(self) -> None:
        while self.bands_box.count():
            it = self.bands_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        t, p = self.t(), self.p()
        for band in height_bands(t, p):
            row = QWidget()
            row.setObjectName("Panel")
            h = QHBoxLayout(row)
            h.setContentsMargins(8, 6, 8, 6)
            btn = QPushButton()
            btn.setFixedSize(38, 30)
            btn.setStyleSheet(f"background:{band.colour}; border:1px solid rgba(0,0,0,60); border-radius:6px;")
            btn.setToolTip("Pick a colour")
            btn.clicked.connect(lambda _=False, i=band.index: self._pick(i))
            h.addWidget(btn)
            what = ", ".join(band.features)
            lab = QLabel(f"<b>{colour_name(band.colour)}</b> · {what}<br>"
                         f"<span style='color:gray'>{band.z_bottom:g} – {band.z_top:g} mm, "
                         f"{_layers(p.layers_below(band.z_bottom) + 1, p.layers_below(band.z_top))}</span>")
            lab.setWordWrap(True)
            h.addWidget(lab, 1)
            self.bands_box.addWidget(row)
        changes = colour_changes(t, p)
        if changes:
            items = "".join(
                f"<li>Before layer <b>{c.layer}</b> ({c.z:g} mm) → "
                f"<span style='color:{c.colour}'>■</span> {colour_name(c.colour)}</li>" for c in changes)
            layers = ",".join(str(c.layer) for c in changes)
            self.plan.setText(f"<ul style='margin-left:-20px'>{items}</ul>"
                              f"Cura → Filament Change → Layer: <code>{layers}</code>")
        else:
            self.plan.setText("Single colour – no filament changes needed.")

    def _pick(self, i: int) -> None:
        t = self.t()
        while len(t.palette) <= i:
            t.palette.append(height_bands(t, self.p())[len(t.palette)].colour)
        c = QColorDialog.getColor(QColor(t.palette[i]), self, "Band colour")
        if c.isValid():
            t.palette[i] = c.name().upper()
            self.refresh()
            self.changed.emit()

    def _palette(self, combo: QComboBox) -> None:
        cols = combo.currentData()
        if cols:
            self.t().palette = list(cols)
            self.refresh()
            self.changed.emit()
        with QSignalBlocker(combo):
            combo.setCurrentIndex(0)


# ---------------------------------------------------------------------------


class PrinterPanel(QWidget):
    changed = Signal()

    def __init__(self, get_printer: Callable[[], Printer], set_printer: Callable[[Printer], None],
                 get_template, parent=None) -> None:
        super().__init__(parent)
        self.p = get_printer
        self.set_p = set_printer
        self.t = get_template
        self.b = Binder(self.changed.emit)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(4, 4, 8, 4)
        prow = QHBoxLayout()
        self.profiles = QComboBox()
        self.profiles.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.profiles.activated.connect(self._choose)
        save = QToolButton()
        save.setText("Save…")
        save.setToolTip("Save these settings as a printer profile")
        save.clicked.connect(self._save)
        more = QToolButton()
        more.setText("⋯")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        mm = QMenu(self)
        act = QAction("Delete saved profile", self)
        act.triggered.connect(self._delete)
        mm.addAction(act)
        more.setMenu(mm)
        prow.addWidget(self.profiles, 1)
        prow.addWidget(save)
        prow.addWidget(more)
        v.addLayout(prow)

        b = self.b
        p = self.p
        g = QGroupBox("Bed")
        f = QFormLayout(g)
        bed = QHBoxLayout()
        bed.addWidget(b.num(_spin(50, 1000, 1, " mm", 0), p, "bed_width"))
        bed.addWidget(QLabel("×"))
        bed.addWidget(b.num(_spin(50, 1000, 1, " mm", 0), p, "bed_depth"))
        f.addRow("Size", bed)
        f.addRow("Edge margin", b.num(_spin(0, 50, 0.5, tip="Keep cards this far from the bed edge (clips, "
                                                           "skirt, brim)."), p, "margin"))
        f.addRow("Gap between cards", b.num(_spin(0.5, 50, 0.5), p, "gap"))
        f.addRow("", b.check(QCheckBox("Turn cards to fit more"), p, "allow_rotation"))
        mx = QSpinBox()
        mx.setRange(0, 999)
        mx.setMinimumWidth(64)
        mx.setSpecialValueText("as many as fit")
        mx.setAlignment(Qt.AlignmentFlag.AlignRight)
        f.addRow("Max per plate", b.num(mx, p, "max_per_plate"))
        v.addWidget(g)

        g = QGroupBox("Slicing (match Cura)")
        f = QFormLayout(g)
        f.addRow("Nozzle", b.num(_spin(0.1, 2, 0.05, " mm", 2), p, "nozzle"))
        f.addRow("Layer height", b.num(_spin(0.04, 1, 0.02, " mm", 2), p, "layer_height"))
        f.addRow("First layer", b.num(_spin(0.04, 1, 0.02, " mm", 2), p, "first_layer_height"))
        mf = _spin(0, 2, 0.05, " mm", 2, "Strokes or gaps thinner than this are flagged.")
        mf.setSpecialValueText("same as nozzle")
        f.addRow("Min. feature", b.num(mf, p, "min_feature"))
        v.addWidget(g)
        v.addWidget(QLabel("Plate fit", objectName="Section"))
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        v.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(_scroll(inner))
        self._fill_profiles()

    def _fill_profiles(self) -> None:
        with QSignalBlocker(self.profiles):
            self.profiles.clear()
            for pr in settings.load_printers():
                self.profiles.addItem(pr.name, pr)
            i = self.profiles.findText(self.p().name)
            if i < 0:
                self.profiles.insertItem(0, self.p().name, self.p())
                i = 0
            self.profiles.setCurrentIndex(i)

    def _choose(self, i: int) -> None:
        pr = self.profiles.itemData(i)
        if pr is not None:
            self.set_p(Printer.from_dict(pr.to_dict()))
            self.refresh()
            self.changed.emit()

    def _save(self) -> None:
        name, ok = QInputDialog.getText(self, "Save printer", "Profile name:", text=self.p().name)
        if ok and name.strip():
            self.p().name = name.strip()
            settings.save_printer(self.p())
            self._fill_profiles()

    def _delete(self) -> None:
        name = self.p().name
        if QMessageBox.question(self, "Delete profile", f"Delete saved profile “{name}”?") == \
                QMessageBox.StandardButton.Yes:
            settings.delete_printer(name)
            self._fill_profiles()

    def refresh(self) -> None:
        self.b.refresh()
        self._fill_profiles()
        self.update_summary(None)

    def update_summary(self, n_cards: int | None) -> None:
        t, p = self.t(), self.p()
        pk = plate.pack(t.card.width, t.card.height, p)
        if pk.capacity == 0:
            self.summary.setText("<b style='color:#E0533D'>The card doesn't fit on this bed.</b>")
            return
        txt = f"<b>{pk.capacity} cards per plate</b> ({pk.description})"
        if n_cards:
            plates = -(-n_cards // pk.capacity)
            txt += f"<br>{n_cards} selected cards → <b>{plates} plate{'s' if plates != 1 else ''}</b>"
        base = p.snap_base(t.card.thickness)
        if abs(base - t.card.thickness) > 1e-6:
            txt += f"<br><span style='color:gray'>Card thickness snaps to {base:g} mm on these layers.</span>"
        self.summary.setText(txt)
