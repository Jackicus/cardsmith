"""Cardsmith desktop app."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings, QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, plate, settings
from ..data import Deck, load_deck
from ..layout import CardLayout, layout_card
from ..model import Printer, Template
from . import theme
from .deck import DeckPanel
from .export_dialog import ExportDialog
from .help import HelpDialog
from .panels import CardPanel, ColoursPanel, PrinterPanel, SlotsPanel
from .preview import Preview
from .workers import check_job, deck_check_job

HERE = Path(__file__).parent
ICON = HERE / "icon.svg"
LEVEL_ICON = {"error": "⛔", "warning": "⚠", "info": "ℹ"}


def _sample_deck() -> Path | None:
    for p in (Path(__file__).parents[1] / "samples" / "jlpt-n5-kanji.tsv",
              Path(__file__).parents[3] / "examples" / "japanese" / "jlpt-n5-kanji.tsv"):
        if p.exists():
            return p
    return None


class MainWindow(QMainWindow):
    def __init__(self, deck_path: str | None = None) -> None:
        super().__init__()
        self.qs = QSettings()
        self.template: Template = settings.default_template()
        self.template_path: Path | None = None
        self.printer: Printer = Printer()
        self.deck: Deck | None = None
        self.index = 0
        self.mode = "card"
        self.plate_no = 0
        self.dirty = False
        self._generation = 0
        self._dragging = False
        self._cache: dict[int, CardLayout] = {}
        self._history: list[dict] = []
        self._hpos = -1
        self._restoring = False
        self._deck_job = None
        self._last_lay: CardLayout | None = None

        self.setWindowTitle("Cardsmith")
        if ICON.exists():
            self.setWindowIcon(QIcon(str(ICON)))
        self.resize(1440, 900)
        self._render_timer = QTimer(self, singleShot=True, interval=20, timeout=self._render)
        self._check_timer = QTimer(self, singleShot=True, interval=220, timeout=self._check_current)
        self._history_timer = QTimer(self, singleShot=True, interval=500, timeout=self._push_history)
        self._save_timer = QTimer(self, singleShot=True, interval=1500, timeout=self._autosave)
        self._build_ui()
        self._build_toolbar()
        self._restore_session(deck_path)

        self._refresh_all()
        self._push_history()
        self._render()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(8)
        self.setCentralWidget(split)

        # Left: editing tabs.
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        get_t = lambda: self.template  # noqa: E731
        get_p = lambda: self.printer  # noqa: E731
        self.card_panel = CardPanel(get_t)
        self.slots_panel = SlotsPanel(get_t, lambda: self.deck.columns if self.deck else [])
        self.colours_panel = ColoursPanel(get_t, get_p)
        self.printer_panel = PrinterPanel(get_p, self._set_printer, get_t)
        self.tabs.addTab(self.slots_panel, "Text")
        self.tabs.addTab(self.card_panel, "Card")
        self.tabs.addTab(self.colours_panel, "Colours")
        self.tabs.addTab(self.printer_panel, "Printer")
        for pnl in (self.card_panel, self.slots_panel, self.colours_panel):
            pnl.changed.connect(self._template_changed)
        self.printer_panel.changed.connect(self._printer_changed)
        self.slots_panel.selectedChanged.connect(self._slot_selected)
        self.tabs.setMinimumWidth(340)
        split.addWidget(self.tabs)

        # Centre: preview.
        centre = QWidget()
        cv = QVBoxLayout(centre)
        cv.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        for i, label in enumerate(("Card", "Plate")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setToolTip("Preview one card" if i == 0 else "See how the cards fit on your print bed")
            self.mode_group.addButton(b, i)
            bar.addWidget(b)
        self.mode_group.idClicked.connect(self._set_mode)
        bar.addSpacing(12)
        self.prev_btn = QToolButton(text="◀", toolTip="Previous (Page Up)", clicked=lambda: self._step(-1))
        self.next_btn = QToolButton(text="▶", toolTip="Next (Page Down)", clicked=lambda: self._step(1))
        self.nav_label = QLabel()
        self.nav_label.setObjectName("Title")
        bar.addWidget(self.prev_btn)
        bar.addWidget(self.next_btn)
        bar.addWidget(self.nav_label, 1)
        self.deck_btn = QPushButton("Cards")
        self.deck_btn.setCheckable(True)
        self.deck_btn.setToolTip("Show the list of cards – pick which ones to print")
        self.deck_btn.toggled.connect(lambda on: self._show_drawer(on, 0))
        bar.addWidget(self.deck_btn)
        view = QToolButton(text="View ▾")
        view.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        vm = QMenu(self)
        self.show_issues = QAction("Highlight print problems", self, checkable=True, checked=True)
        self.show_issues.setToolTip("Red: strokes thinner than the nozzle. Orange: gaps that may fill in.")
        self.show_guides = QAction("Show safe area", self, checkable=True, checked=True)
        for a in (self.show_issues, self.show_guides):
            a.toggled.connect(lambda _: self._render())
            vm.addAction(a)
        vm.addSeparator()
        vm.addAction("Fit to window", lambda: self.preview.fit())
        vm.addAction("Show the welcome again", lambda: self._show_welcome(True))
        view.setMenu(vm)
        bar.addWidget(view)
        cv.addLayout(bar)

        stage = QWidget()
        grid = QGridLayout(stage)
        grid.setContentsMargins(0, 0, 0, 0)
        self.preview = Preview()
        self.preview.slotClicked.connect(self._preview_slot_clicked)
        self.preview.slotDragged.connect(self._preview_drag)
        self.preview.dragFinished.connect(self._drag_done)
        grid.addWidget(self.preview, 0, 0)
        self.welcome = self._build_welcome()
        grid.addWidget(self.welcome, 0, 0, Qt.AlignmentFlag.AlignCenter)
        cv.addWidget(stage, 1)

        foot = QHBoxLayout()
        self.pill = QPushButton("✓  Ready to print")
        self.pill.setObjectName("PillOk")
        self.pill.setToolTip("Click to see the details")
        self.pill.clicked.connect(lambda: self._show_drawer(True, 1))
        foot.addWidget(self.pill)
        foot.addStretch(1)
        self.hint = QLabel("Drag text to move it · scroll to zoom")
        self.hint.setObjectName("Muted")
        foot.addWidget(self.hint)
        cv.addLayout(foot)
        split.addWidget(centre)

        # Right: a drawer with the card list and checks, closed until wanted.
        self.drawer = QWidget()
        dvl = QVBoxLayout(self.drawer)
        dvl.setContentsMargins(0, 0, 0, 0)
        self.check_tabs = QTabWidget()
        self.check_tabs.setDocumentMode(True)
        close = QToolButton(text="✕", toolTip="Close")
        close.clicked.connect(lambda: self._show_drawer(False))
        self.check_tabs.setCornerWidget(close)
        self.deck_panel = DeckPanel()
        self.deck_panel.rowActivated.connect(self._go_to)
        self.deck_panel.openRequested.connect(self.open_deck)
        self.deck_panel.includedChanged.connect(self._included_changed)
        self.issue_list = QListWidget()
        self.issue_list.setWordWrap(True)
        self.issue_list.itemClicked.connect(self._issue_clicked)
        deck_tab = QWidget()
        dv = QVBoxLayout(deck_tab)
        dv.setContentsMargins(0, 6, 0, 0)
        dv.addWidget(QLabel("Lay out every selected card and list the ones that need a look.",
                            objectName="Muted", wordWrap=True))
        drow = QHBoxLayout()
        self.check_btn = QPushButton("Check every card")
        self.check_btn.clicked.connect(self._check_deck)
        self.thorough = QCheckBox("Stroke widths too (slower)")
        drow.addWidget(self.check_btn)
        drow.addWidget(self.thorough)
        drow.addStretch(1)
        dv.addLayout(drow)
        self.deck_progress = QProgressBar()
        self.deck_progress.setRange(0, 1000)
        self.deck_progress.setTextVisible(False)
        self.deck_progress.setFixedHeight(6)
        self.deck_progress.hide()
        dv.addWidget(self.deck_progress)
        self.deck_issues = QListWidget()
        self.deck_issues.setWordWrap(True)
        self.deck_issues.itemClicked.connect(lambda it: self._go_to(it.data(Qt.ItemDataRole.UserRole)))
        dv.addWidget(self.deck_issues, 1)
        self.check_tabs.addTab(self.deck_panel, "Cards")
        self.check_tabs.addTab(self.issue_list, "This card")
        self.check_tabs.addTab(deck_tab, "Whole deck")
        dvl.addWidget(self.check_tabs)
        self.check_tabs.currentChanged.connect(
            lambda i: self.deck_btn.setChecked(i == 0) if self.drawer.isVisible() else None)
        self.drawer.setMinimumWidth(300)
        self.drawer.hide()
        split.addWidget(self.drawer)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([380, 760, 380])
        self.splitter = split

        self.status = self.statusBar()
        self.status_plate = QLabel()
        self.status.addPermanentWidget(self.status_plate)

        QShortcut(QKeySequence(Qt.Key.Key_PageDown), self, lambda: self._step(1))
        QShortcut(QKeySequence(Qt.Key.Key_PageUp), self, lambda: self._step(-1))
        QShortcut(QKeySequence("Alt+Right"), self, lambda: self._step(1))
        QShortcut(QKeySequence("Alt+Left"), self, lambda: self._step(-1))

    def _build_welcome(self) -> QFrame:
        w = QFrame()
        w.setObjectName("Welcome")
        w.setMaximumWidth(520)
        v = QVBoxLayout(w)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(12)
        title = QLabel("Welcome to Cardsmith")
        title.setObjectName("Big")
        v.addWidget(title)
        v.addWidget(QLabel("Turn a spreadsheet into 3D-printable flashcards in three steps.", objectName="Muted"))
        steps = (
            ("Open your spreadsheet", "Any CSV, TSV or Anki export. Each column can go on the card."),
            ("Choose what goes where", "Pick a line of text on the left, or just drag it in the preview."),
            ("Export for printing", "You get plates ready for Cura, with the colour changes worked out."),
        )
        for n, (head, sub) in enumerate(steps, start=1):
            row = QHBoxLayout()
            num = QLabel(str(n), objectName="Step")
            num.setFixedSize(26, 26)
            num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(num, 0, Qt.AlignmentFlag.AlignTop)
            txt = QLabel(f"<b>{head}</b><br><span style='color:gray'>{sub}</span>")
            txt.setWordWrap(True)
            row.addWidget(txt, 1)
            v.addLayout(row)
        btns = QHBoxLayout()
        sample = QPushButton("Look around with the sample deck")
        sample.clicked.connect(lambda: self._show_welcome(False))
        mine = QPushButton("Open my spreadsheet…")
        mine.setObjectName("Primary")
        mine.clicked.connect(lambda: (self._show_welcome(False), self.open_deck()))
        btns.addWidget(sample)
        btns.addStretch(1)
        btns.addWidget(mine)
        v.addSpacing(6)
        v.addLayout(btns)
        w.setVisible(not self.qs.value("ui/welcomed", False, type=bool))
        return w

    def _show_welcome(self, on: bool) -> None:
        self.welcome.setVisible(on)
        if not on:
            self.qs.setValue("ui/welcomed", True)

    def _show_drawer(self, on: bool, tab: int | None = None) -> None:
        if tab is not None:
            self.check_tabs.setCurrentIndex(tab)
        if on and not self.drawer.isVisible():
            sizes = self.splitter.sizes()
            self.drawer.show()
            if len(sizes) == 3 and sizes[2] < 200:
                self.splitter.setSizes([sizes[0], max(400, sizes[1] - 340), 340])
        elif not on:
            self.drawer.hide()
        with QSignalBlocker(self.deck_btn):
            self.deck_btn.setChecked(on and self.check_tabs.currentIndex() == 0)
        self.qs.setValue("ui/drawer", on)

    def _update_pill(self, lay: CardLayout) -> None:
        bad = sum(1 for i in lay.issues if i.level in ("error", "warning"))
        if bad:
            self.pill.setText(f"⚠  {bad} thing{'s' if bad != 1 else ''} to check on this card")
            self.pill.setObjectName("PillWarn")
        else:
            self.pill.setText("✓  Ready to print")
            self.pill.setObjectName("PillOk")
        self.pill.style().unpolish(self.pill)
        self.pill.style().polish(self.pill)

    def _update_deck_button(self) -> None:
        if not self.deck:
            self.deck_btn.setText("Cards")
            return
        n, sel = len(self.deck), sum(self.deck.included)
        self.deck_btn.setText(f"{n} cards" if sel == n else f"{sel} of {n} cards")

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        brand = QLabel("  札 <b>Cardsmith</b>  ")
        brand.setStyleSheet(f"font-size:16px; color:{theme.ACCENT};")
        tb.addWidget(brand)

        def act(text, slot, key=None, tip=None):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if key:
                a.setShortcut(QKeySequence(key))
            a.setToolTip(f"{tip or text}" + (f"  ({QKeySequence(key).toString()})" if key else ""))
            return a

        tb.addAction(act("Open deck…", self.open_deck, QKeySequence.StandardKey.Open,
                         "Open a CSV / TSV / Anki export / JSON"))
        tmpl = QToolButton()
        tmpl.setText("Template ▾")
        tmpl.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        menu.addAction(act("Open template…", self.open_template, "Ctrl+Shift+O"))
        menu.addAction(act("Save template", self.save_template, QKeySequence.StandardKey.Save))
        menu.addAction(act("Save template as…", self.save_template_as, QKeySequence.StandardKey.SaveAs))
        menu.addSection("Start from")
        for name, path in settings.builtin_templates().items():
            try:
                label = Template.load(path).name
            except Exception:
                label = name
            menu.addAction(label, lambda p=path: self._load_template(p, builtin=True))
        tmpl.setMenu(menu)
        tb.addWidget(tmpl)
        self.undo_act = act("↶", self.undo, QKeySequence.StandardKey.Undo, "Undo")
        self.redo_act = act("↷", self.redo, QKeySequence.StandardKey.Redo, "Redo")
        tb.addAction(self.undo_act)
        tb.addAction(self.redo_act)
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding,
                             spacer.sizePolicy().verticalPolicy().Preferred)
        tb.addWidget(spacer)
        tb.addAction(act("Help", lambda: HelpDialog(self).exec(), QKeySequence.StandardKey.HelpContents,
                         "How Cardsmith works, and colour changes in Cura"))
        self.export_btn = QPushButton("Export for printing…")
        self.export_btn.setObjectName("Primary")
        self.export_btn.setShortcut(QKeySequence("Ctrl+E"))
        self.export_btn.setToolTip("Build plates and cards for your slicer  (Ctrl+E)")
        self.export_btn.clicked.connect(self.export)
        tb.addWidget(self.export_btn)

    # -------------------------------------------------------------- session
    def _restore_session(self, deck_path: str | None) -> None:
        geo = self.qs.value("window/geometry")
        if isinstance(geo, QByteArray):
            self.restoreGeometry(geo)
        sp = self.qs.value("window/splitter2")
        if isinstance(sp, QByteArray):
            self.splitter.restoreState(sp)
        if self.qs.value("ui/drawer", False, type=bool):
            self._show_drawer(True, 0)
        pr = self.qs.value("printer")
        if pr:
            try:
                self.printer = Printer.from_dict(json.loads(pr))
            except (ValueError, TypeError):
                pass
        session = settings.config_dir() / "session-template.toml"
        if session.exists():
            try:
                self.template = Template.load(session)
                tp = self.qs.value("template/path")
                self.template_path = Path(tp) if tp else None
                self.dirty = self.qs.value("template/dirty", False, type=bool)
            except Exception:
                pass
        path = deck_path or self.qs.value("deck/path")
        if not path or not Path(path).exists():
            sample = _sample_deck()
            path = str(sample) if sample else None
        if path:
            self._load_deck(path, quiet=True)
            if not deck_path and self.deck and self.deck.source == self.qs.value("deck/path"):
                inc = self.qs.value("deck/excluded")
                if inc and self.deck:
                    try:
                        for i in json.loads(inc):
                            if 0 <= i < len(self.deck.included):
                                self.deck.included[i] = False
                        self.deck_panel.set_deck(self.deck)
                    except (ValueError, TypeError):
                        pass
                self.index = min(self.qs.value("deck/index", 0, type=int), max(len(self.deck) - 1, 0))
                self.deck_panel.select_row(self.index)

    def _autosave(self) -> None:
        try:
            self.template.save(settings.config_dir() / "session-template.toml")
        except OSError:
            return
        self.qs.setValue("template/path", str(self.template_path) if self.template_path else "")
        self.qs.setValue("template/dirty", self.dirty)
        self.qs.setValue("printer", json.dumps(self.printer.to_dict()))
        if self.deck:
            self.qs.setValue("deck/path", self.deck.source)
            self.qs.setValue("deck/index", self.index)
            self.qs.setValue("deck/excluded", json.dumps([i for i, v in enumerate(self.deck.included) if not v]))

    def closeEvent(self, e) -> None:
        self._autosave()
        self.qs.setValue("window/geometry", self.saveGeometry())
        self.qs.setValue("window/splitter2", self.splitter.saveState())
        if self._deck_job:
            self._deck_job.cancelled = True
        super().closeEvent(e)

    # ---------------------------------------------------------------- files
    def open_deck(self) -> None:
        start = str(Path(self.deck.source).parent) if self.deck else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Open deck", start,
            "Spreadsheets (*.csv *.tsv *.txt *.tab *.json);;All files (*)")
        if path:
            self._load_deck(path)

    def _load_deck(self, path: str, quiet: bool = False) -> None:
        try:
            deck = load_deck(path)
        except Exception as e:
            if not quiet:
                QMessageBox.critical(self, "Couldn't open deck", f"{path}\n\n{e}")
            return
        self.deck = deck
        self.index = 0
        self._cache.clear()
        self.deck_panel.set_deck(deck)
        self.deck_issues.clear()
        self._update_deck_button()
        missing = self._missing_fields()
        if missing and not quiet:
            QMessageBox.information(
                self, "Match your columns",
                f"This template uses {', '.join('{' + m + '}' for m in missing)}, which this deck doesn't have.\n\n"
                f"Columns in the deck: {', '.join(deck.columns)}\n\n"
                "Pick a slot on the Text tab and use the { } button to choose a column.")
        self._update_title()
        self._schedule()

    def _missing_fields(self) -> list[str]:
        from ..text import fields_in
        if not self.deck:
            return []
        cols = {c.lower() for c in self.deck.columns}
        out = []
        for s in self.template.slots:
            if s.enabled:
                for f in fields_in(s.text):
                    if f not in ("#", "##") and f.lower() not in cols and f not in out:
                        out.append(f)
        return out

    def open_template(self) -> None:
        start = str(self.template_path.parent) if self.template_path else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Open template", start, "Cardsmith templates (*.toml)")
        if path:
            self._load_template(Path(path))

    def _load_template(self, path: Path, builtin: bool = False) -> None:
        if self.dirty and QMessageBox.question(
                self, "Replace template", "Your current template has unsaved changes. Replace it anyway?"
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.template = Template.load(path)
        except Exception as e:
            QMessageBox.critical(self, "Couldn't open template", f"{path}\n\n{e}")
            return
        self.template_path = None if builtin else path
        self.dirty = False
        self._cache.clear()
        self.slots_panel._current = 0
        self._history, self._hpos = [], -1  # undo must not cross into another file
        self._refresh_all()
        self._push_history()
        self._schedule()
        missing = self._missing_fields()
        if missing:
            self.status.showMessage(f"Template fields not in this deck: {', '.join(missing)}", 8000)

    def save_template(self) -> None:
        if self.template_path is None:
            self.save_template_as()
            return
        self.template.save(self.template_path)
        self.dirty = False
        self._update_title()
        self.status.showMessage(f"Saved {self.template_path}", 4000)

    def save_template_as(self) -> None:
        from ..export import safe_name
        start = self.template_path or Path.home() / f"{safe_name(self.template.name)}.toml"
        path, _ = QFileDialog.getSaveFileName(self, "Save template", str(start), "Cardsmith templates (*.toml)")
        if path:
            if not path.endswith(".toml"):
                path += ".toml"
            self.template_path = Path(path)
            self.save_template()

    # --------------------------------------------------------------- export
    def export(self) -> None:
        if not self.deck or not self.deck.selected():
            QMessageBox.information(self, "Nothing to export", "Open a deck and select at least one card.")
            return
        dlg = ExportDialog(self.template, self.printer, self.deck.selected(), self.deck.name, self,
                           total=len(self.deck.rows))
        dlg.exec()

    # ---------------------------------------------------------------- state
    def _set_printer(self, p: Printer) -> None:
        self.printer = p

    def _template_changed(self) -> None:
        self.dirty = True
        self._cache.clear()
        self.slots_panel.update_current_label()
        self.colours_panel.refresh() if self.sender() is not self.colours_panel else None
        self.printer_panel.update_summary(self._n_selected())
        self._update_title()
        self._schedule()
        if not self._restoring:
            self._history_timer.start()

    def _printer_changed(self) -> None:
        self._cache.clear()
        self.colours_panel.refresh()
        self.printer_panel.update_summary(self._n_selected())
        self._schedule()

    def _included_changed(self) -> None:
        self._update_deck_button()
        self.printer_panel.update_summary(self._n_selected())
        if self.mode == "plate":
            self._schedule()
        self._save_timer.start()

    def _n_selected(self) -> int:
        return sum(self.deck.included) if self.deck else 0

    def _refresh_all(self) -> None:
        self.card_panel.refresh()
        self.slots_panel.refresh()
        self.colours_panel.refresh()
        self.printer_panel.refresh()
        self.printer_panel.update_summary(self._n_selected())
        self._update_title()

    def _update_title(self) -> None:
        name = self.template.name
        if self.template_path:
            name = self.template_path.stem
        deck = f" · {Path(self.deck.source).name}" if self.deck else ""
        self.setWindowTitle(f"{'● ' if self.dirty else ''}{name}{deck} — Cardsmith")

    # -------------------------------------------------------------- history
    def _push_history(self) -> None:
        snap = self.template.to_dict()
        if self._history and self._history[self._hpos] == snap:
            return
        self._history = self._history[: self._hpos + 1] + [snap]
        self._history = self._history[-200:]
        self._hpos = len(self._history) - 1
        self._update_undo()
        self._save_timer.start()

    def _restore(self, pos: int) -> None:
        self._hpos = pos
        self._restoring = True
        self.template = Template.from_dict(self._history[pos])
        self._cache.clear()
        self.dirty = True
        self._refresh_all()
        self._restoring = False
        self._update_undo()
        self._schedule()

    def undo(self) -> None:
        self._history_timer.stop()
        self._push_history()
        if self._hpos > 0:
            self._restore(self._hpos - 1)

    def redo(self) -> None:
        if self._hpos < len(self._history) - 1:
            self._restore(self._hpos + 1)

    def _update_undo(self) -> None:
        self.undo_act.setEnabled(self._hpos > 0)
        self.redo_act.setEnabled(self._hpos < len(self._history) - 1)

    # ------------------------------------------------------------ rendering
    def _schedule(self) -> None:
        self._render_timer.start()

    def _rows(self) -> list[tuple[int, dict]]:
        return self.deck.selected() if self.deck else []

    def _row(self, i: int) -> dict:
        if self.deck and 0 <= i < len(self.deck.rows):
            return self.deck.rows[i]
        # No data: show the field names so the layout is still visible.
        from ..text import fields_in
        return {f: f for s in self.template.slots for f in fields_in(s.text)}

    def _layout(self, i: int) -> CardLayout:
        lay = self._cache.get(i)
        if lay is None:
            total = len(self.deck.rows) if self.deck else 1
            lay = layout_card(self.template, self.printer, self._row(i), i, total, check_print=False)
            self._cache[i] = lay
        return lay

    def _render(self) -> None:
        try:
            if self.mode == "card":
                self._render_card()
            else:
                self._render_plate()
        except Exception as e:  # keep the app alive on odd input
            import traceback
            traceback.print_exc()
            self.preview.clear_message(f"Can't draw this card:\n{e}")
        self._save_timer.start()

    def _render_card(self) -> None:
        self._generation += 1  # any check still running is now stale
        n = len(self.deck.rows) if self.deck else 0
        i = self.index
        lay = self._layout(i)
        self._last_lay = lay
        self.preview.show_card(lay, self.template, self.printer, show_issues=self.show_issues.isChecked(),
                               show_guides=self.show_guides.isChecked(),
                               selected_slot=self.slots_panel.current)
        excluded = self.deck is not None and i < len(self.deck.included) and not self.deck.included[i]
        self.nav_label.setText(f"Card {i + 1} of {n}  ·  {lay.label}" + ("  (not selected)" if excluded else "")
                               if n else "Template preview – open a deck to fill it")
        self.prev_btn.setEnabled(i > 0)
        self.next_btn.setEnabled(i < n - 1)
        self._show_issues(lay)
        if not self._dragging:
            self._check_timer.start()
        pk = plate.pack(self.template.card.width, self.template.card.height, self.printer)
        self.status_plate.setText(
            f"{self.template.card.width:g} × {self.template.card.height:g} mm · "
            f"{pk.capacity} per plate on {self.printer.name}")

    def _render_plate(self) -> None:
        rows = self._rows()
        pk = plate.pack(self.template.card.width, self.template.card.height, self.printer)
        if pk.capacity == 0:
            self.preview.clear_message("The card is bigger than the printable bed area.")
            self.nav_label.setText("Doesn't fit")
            return
        chunks = plate.chunk(len(rows), pk.capacity) or [range(0)]
        self.plate_no = max(0, min(self.plate_no, len(chunks) - 1))
        rng = chunks[self.plate_no]
        lays = [(rows[k][0], self._layout(rows[k][0])) for k in rng]
        self.preview.show_plate(lays, pk, self.template, self.printer,
                                f"{self.printer.name} · {pk.bed_w:g} × {pk.bed_d:g} mm · {pk.description}")
        self.nav_label.setText(f"Plate {self.plate_no + 1} of {len(chunks)}  ·  {len(rng)} cards")
        self.prev_btn.setEnabled(self.plate_no > 0)
        self.next_btn.setEnabled(self.plate_no < len(chunks) - 1)

    def _check_current(self) -> None:
        if self.mode != "card":
            return
        self._generation += 1
        gen = self._generation
        total = len(self.deck.rows) if self.deck else 1
        job = check_job(self.template, self.printer, self._row(self.index), self.index, total, gen)
        job.signals.done.connect(self._check_done)
        job.start()

    def _check_done(self, result) -> None:
        gen, lay = result
        if gen != self._generation or self.mode != "card" or self._dragging:
            return
        self._last_lay = lay
        self.preview.show_card(lay, self.template, self.printer, show_issues=self.show_issues.isChecked(),
                               show_guides=self.show_guides.isChecked(), selected_slot=self.slots_panel.current)
        self._show_issues(lay)

    def _show_issues(self, lay: CardLayout) -> None:
        self.issue_list.clear()
        if not lay.issues:
            it = QListWidgetItem("✓  Looks good to print")
            self.issue_list.addItem(it)
        order = {"error": 0, "warning": 1, "info": 2}
        for issue in sorted(lay.issues, key=lambda x: order.get(x.level, 3)):
            it = QListWidgetItem(f"{LEVEL_ICON.get(issue.level, '')}  {issue}")
            it.setData(Qt.ItemDataRole.UserRole, issue.slot)
            self.issue_list.addItem(it)
        bad = sum(1 for i in lay.issues if i.level in ("error", "warning"))
        self.check_tabs.setTabText(1, f"This card ({bad})" if bad else "This card")
        self._update_pill(lay)

    def _issue_clicked(self, it: QListWidgetItem) -> None:
        name = it.data(Qt.ItemDataRole.UserRole)
        for i, s in enumerate(self.template.slots):
            if s.name == name:
                self.tabs.setCurrentWidget(self.slots_panel)
                self.slots_panel.select(i)
                return

    # ----------------------------------------------------------- navigation
    def _set_mode(self, i: int) -> None:
        self.mode = "card" if i == 0 else "plate"
        self.hint.setText("Drag text to move it · scroll to zoom"
                          if self.mode == "card" else
                          "Cards are packed to fit the most per plate · numbers match the deck")
        if self.mode == "plate" and self.deck:
            rows = [r for r, _ in self._rows()]
            pk = plate.pack(self.template.card.width, self.template.card.height, self.printer)
            if self.index in rows and pk.capacity:
                self.plate_no = rows.index(self.index) // pk.capacity
        self.preview._auto_fit = True
        self._render()

    def _step(self, d: int) -> None:
        if self.mode == "card":
            n = len(self.deck.rows) if self.deck else 0
            if n:
                self._go_to(max(0, min(n - 1, self.index + d)))
        else:
            self.plate_no += d
            self._render()

    def _go_to(self, i) -> None:
        if i is None or not self.deck:
            return
        self.index = int(i)
        self.deck_panel.select_row(self.index)
        if self.mode != "card":
            self.mode_group.button(0).setChecked(True)
            self.mode = "card"
        self._render()

    # --------------------------------------------------------- interaction
    def _slot_selected(self, i: int) -> None:
        self.preview.update_selection(i)

    def _preview_slot_clicked(self, i: int) -> None:
        self.tabs.setCurrentWidget(self.slots_panel)
        if self.slots_panel.current != i:
            self.slots_panel.select(i)
        self.preview.update_selection(i)

    def _preview_drag(self, i: int, dx: float, dy: float) -> None:
        if not (0 <= i < len(self.template.slots)):
            return
        self._dragging = True
        s = self.template.slots[i]
        s.y = round(s.y + dy, 2)
        s.x_offset = round(s.x_offset + (-dx if s.align == "right" else dx), 2)
        if s.align == "center" and abs(s.x_offset) < 0.6:
            s.x_offset = 0.0
        self.slots_panel.refresh() if self.slots_panel.current != i else self.slots_panel.b.refresh()
        self._template_changed()
        self._render()

    def _drag_done(self) -> None:
        self._dragging = False
        self._check_timer.start()
        self._history_timer.start()

    # ----------------------------------------------------------- deck check
    def _check_deck(self) -> None:
        if self._deck_job:
            self._deck_job.cancelled = True
            return
        rows = self._rows()
        if not rows:
            return
        self.deck_issues.clear()
        self.deck_progress.show()
        self.check_btn.setText("Stop")
        job = deck_check_job(self.template, self.printer, rows, self.thorough.isChecked(), len(self.deck.rows))
        job.signals.progress.connect(lambda f, m: self.deck_progress.setValue(int(f * 1000)))
        job.signals.done.connect(self._deck_checked)
        job.signals.failed.connect(lambda m: self._deck_checked(([], 0, True)))
        self._deck_job = job.start()

    def _deck_checked(self, outcome) -> None:
        results, checked, stopped = outcome if isinstance(outcome, tuple) else (outcome, 0, True)
        self._deck_job = None
        self.deck_progress.hide()
        self.check_btn.setText("Check every card")
        self.deck_issues.clear()
        flags = {}
        for idx, label, issues in results:
            msg = "; ".join(str(i) for i in issues)
            flags[idx] = msg
            it = QListWidgetItem(f"#{idx + 1}  {label}\n    {msg}")
            it.setData(Qt.ItemDataRole.UserRole, idx)
            self.deck_issues.addItem(it)
        if stopped:
            self.deck_issues.insertItem(0, QListWidgetItem(f"Stopped after {checked} of {len(self._rows())} cards"))
        elif not results:
            self.deck_issues.addItem(QListWidgetItem("✓  Every selected card fits"))
        self.deck_panel.model.set_flags(flags)
        self.check_tabs.setTabText(2, f"Whole deck ({len(results)})" if results else "Whole deck")
        self._show_drawer(True, 2)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    QApplication.setApplicationName("Cardsmith")
    QApplication.setOrganizationName("Cardsmith")
    QApplication.setApplicationVersion(__version__)
    QApplication.setDesktopFileName("cardsmith")
    app = QApplication.instance() or QApplication(argv)
    theme.apply(app)
    if ICON.exists():
        app.setWindowIcon(QIcon(str(ICON)))
    deck = argv[1] if len(argv) > 1 else None
    w = MainWindow(deck)
    w.show()
    try:
        app.styleHints().colorSchemeChanged.connect(lambda _: (theme.apply(app), w.preview.apply_theme()))
    except AttributeError:
        pass
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
