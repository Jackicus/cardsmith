"""Cardsmith desktop app."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
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
        self._build_ui()
        self._build_toolbar()
        self._restore_session(deck_path)

        self._render_timer = QTimer(self, singleShot=True, interval=20, timeout=self._render)
        self._check_timer = QTimer(self, singleShot=True, interval=220, timeout=self._check_current)
        self._history_timer = QTimer(self, singleShot=True, interval=500, timeout=self._push_history)
        self._save_timer = QTimer(self, singleShot=True, interval=1500, timeout=self._autosave)
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
            b.setToolTip("Preview one card" if i == 0 else "Preview how cards are laid out on the bed")
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
        self.show_issues = QCheckBox("Print problems")
        self.show_issues.setChecked(True)
        self.show_issues.setToolTip("Red: strokes thinner than the nozzle. Orange: gaps that may fill in.")
        self.show_guides = QCheckBox("Guides")
        self.show_guides.setChecked(True)
        self.show_guides.setToolTip("Show the padding (safe area)")
        for c in (self.show_issues, self.show_guides):
            c.toggled.connect(lambda _: self._render())
            bar.addWidget(c)
        fit = QToolButton(text="Fit", toolTip="Fit to window (double-click the preview)")
        bar.addWidget(fit)
        cv.addLayout(bar)
        self.preview = Preview()
        fit.clicked.connect(self.preview.fit)
        self.preview.slotClicked.connect(self._preview_slot_clicked)
        self.preview.slotDragged.connect(self._preview_drag)
        self.preview.dragFinished.connect(self._drag_done)
        cv.addWidget(self.preview, 1)
        self.hint = QLabel("Drag text to move it · scroll to zoom · drag the background to pan")
        self.hint.setObjectName("Muted")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cv.addWidget(self.hint)
        split.addWidget(centre)

        # Right: deck + checks.
        right = QSplitter(Qt.Orientation.Vertical)
        self.deck_panel = DeckPanel()
        self.deck_panel.rowActivated.connect(self._go_to)
        self.deck_panel.openRequested.connect(self.open_deck)
        self.deck_panel.includedChanged.connect(self._included_changed)
        right.addWidget(self.deck_panel)
        checks = QWidget()
        chv = QVBoxLayout(checks)
        chv.setContentsMargins(0, 6, 0, 0)
        self.check_tabs = QTabWidget()
        self.check_tabs.setDocumentMode(True)
        self.issue_list = QListWidget()
        self.issue_list.setWordWrap(True)
        self.issue_list.itemClicked.connect(self._issue_clicked)
        deck_tab = QWidget()
        dv = QVBoxLayout(deck_tab)
        dv.setContentsMargins(0, 4, 0, 0)
        drow = QHBoxLayout()
        self.check_btn = QPushButton("Check every card")
        self.check_btn.setToolTip("Lay out every selected card and list the ones with problems")
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
        self.check_tabs.addTab(self.issue_list, "This card")
        self.check_tabs.addTab(deck_tab, "Whole deck")
        chv.addWidget(self.check_tabs)
        right.addWidget(checks)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 2)
        right.setMinimumWidth(300)
        split.addWidget(right)
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
        self.undo_act = act("Undo", self.undo, QKeySequence.StandardKey.Undo)
        self.redo_act = act("Redo", self.redo, QKeySequence.StandardKey.Redo)
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
        sp = self.qs.value("window/splitter")
        if isinstance(sp, QByteArray):
            self.splitter.restoreState(sp)
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
            if not deck_path:
                inc = self.qs.value("deck/excluded")
                if inc and self.deck:
                    try:
                        for i in json.loads(inc):
                            if 0 <= i < len(self.deck.included):
                                self.deck.included[i] = False
                        self.deck_panel.set_deck(self.deck)
                    except (ValueError, TypeError):
                        pass
                self.index = min(self.qs.value("deck/index", 0, type=int), max(len(self.deck or []) - 1, 0))

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
        self.qs.setValue("window/splitter", self.splitter.saveState())
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
        dlg = ExportDialog(self.template, self.printer, self.deck.selected(), self.deck.name, self)
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
        self._refresh_all()
        self._restoring = False
        self.dirty = True
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
        n = len(self.deck.rows) if self.deck else 0
        i = self.index
        lay = self._layout(i)
        self._last_lay = lay
        self.preview.show_card(lay, self.template, self.printer, show_issues=self.show_issues.isChecked(),
                               show_guides=self.show_guides.isChecked(),
                               selected_slot=self.slots_panel.current)
        excluded = self.deck is not None and not self.deck.included[i]
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
        self.check_tabs.setTabText(0, f"This card ({bad})" if bad else "This card")

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
        self.hint.setText("Drag text to move it · scroll to zoom · drag the background to pan"
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
        job = deck_check_job(self.template, self.printer, rows, self.thorough.isChecked())
        job.signals.progress.connect(lambda f, m: self.deck_progress.setValue(int(f * 1000)))
        job.signals.done.connect(self._deck_checked)
        job.signals.failed.connect(lambda m: self._deck_checked([]))
        self._deck_job = job.start()

    def _deck_checked(self, results) -> None:
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
        if not results:
            self.deck_issues.addItem(QListWidgetItem("✓  Every selected card fits"))
        self.deck_panel.model.set_flags(flags)
        self.check_tabs.setTabText(1, f"Whole deck ({len(results)})" if results else "Whole deck")
        self.check_tabs.setCurrentIndex(1)


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
