"""Export: choose outputs → progress → results with slicing instructions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import plate, slicer
from ..export import ExportOptions, ExportResult, colour_plan_lines, cura_steps
from ..model import Printer, Template, colour_changes
from .workers import export_job


class ExportDialog(QDialog):
    def __init__(self, template: Template, printer: Printer, rows, deck_name: str, parent=None,
                 total: int | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export for printing")
        self.setMinimumSize(620, 560)
        self.template, self.printer, self.rows = template, printer, rows
        self.total = total
        self.job = None
        self.result: ExportResult | None = None
        self.qs = QSettings()
        self.stack = QStackedWidget()
        v = QVBoxLayout(self)
        v.addWidget(self.stack)
        self.stack.addWidget(self._options_page(deck_name))
        self.stack.addWidget(self._progress_page())
        self.stack.addWidget(self._done_page())

    # -- page 1 --------------------------------------------------------------
    def _options_page(self, deck_name: str) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        t, p = self.template, self.printer
        pk = plate.pack(t.card.width, t.card.height, p)
        n = len(self.rows)
        plates = -(-n // pk.capacity) if pk.capacity else 0
        title = QLabel(f"{n} cards → {plates} plate{'s' if plates != 1 else ''}")
        title.setObjectName("Big")
        v.addWidget(title)
        changes = colour_changes(t, p)
        sub = (f"{pk.capacity} per plate on {p.name} ({p.bed_width:g} × {p.bed_depth:g} mm) · "
               f"{len(changes)} filament change{'s' if len(changes) != 1 else ''}")
        lab = QLabel(sub)
        lab.setObjectName("Muted")
        v.addWidget(lab)

        v.addWidget(QLabel("Save to", objectName="Section"))
        row = QHBoxLayout()
        default_root = Path(self.qs.value("export/root", str(Path.home() / "Cardsmith")))
        self.folder = QLineEdit(str(default_root / _slug(deck_name)))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        v.addLayout(row)

        v.addWidget(QLabel("What to make", objectName="Section"))
        o = ExportOptions()
        saved = lambda k, d: self.qs.value(f"export/{k}", d, type=bool)  # noqa: E731
        self.c_plates = QCheckBox("Plates for filament swaps  –  plate_01.3mf …  (recommended)")
        self.c_plates.setChecked(saved("plates_3mf", o.plates_3mf))
        self.c_colour = QCheckBox("Plates split by colour  –  for AMS / MMU / multi-extruder printers")
        self.c_colour.setChecked(saved("plates_colour_3mf", o.plates_colour_3mf))
        self.c_stl = QCheckBox("Plates as STL too")
        self.c_stl.setChecked(saved("plates_stl", o.plates_stl))
        self.c_single = QCheckBox("Every card as its own STL")
        self.c_single.setChecked(saved("singles_stl", o.singles_stl))
        self.c_single3 = QCheckBox("Every card as its own 3MF (split by colour)")
        self.c_single3.setChecked(saved("singles_3mf", o.singles_3mf))
        for c in (self.c_plates, self.c_colour, self.c_stl, self.c_single, self.c_single3):
            v.addWidget(c)

        v.addWidget(QLabel("Colour plan", objectName="Section"))
        plan = QLabel("<br>".join(_md_bold(line) for line in colour_plan_lines(t, p)))
        plan.setWordWrap(True)
        plan.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(plan)
        v.addStretch(1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        go = QPushButton("Export")
        go.setObjectName("Primary")
        go.setDefault(True)
        go.setEnabled(pk.capacity > 0 and n > 0)
        go.clicked.connect(self._start)
        btns.addWidget(cancel)
        btns.addWidget(go)
        v.addLayout(btns)
        return w

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Export folder", str(Path(self.folder.text()).parent))
        if d:
            self.folder.setText(d)

    # -- page 2 --------------------------------------------------------------
    def _progress_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addStretch(1)
        self.p_label = QLabel("Starting…")
        self.p_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.p_bar = QProgressBar()
        self.p_bar.setRange(0, 1000)
        v.addWidget(self.p_label)
        v.addWidget(self.p_bar)
        row = QHBoxLayout()
        row.addStretch(1)
        self.p_cancel = QPushButton("Cancel")
        self.p_cancel.clicked.connect(self._cancel)
        row.addWidget(self.p_cancel)
        row.addStretch(1)
        v.addLayout(row)
        v.addStretch(1)
        return w

    def _start(self) -> None:
        opts = ExportOptions(self.c_plates.isChecked(), self.c_colour.isChecked(), self.c_stl.isChecked(),
                             self.c_single.isChecked(), self.c_single3.isChecked())
        if not any(vars(opts).values()):
            QMessageBox.information(self, "Nothing to export", "Tick at least one kind of output.")
            return
        for k, val in vars(opts).items():
            self.qs.setValue(f"export/{k}", val)
        out = Path(self.folder.text()).expanduser()
        self.qs.setValue("export/root", str(out.parent))
        self.stack.setCurrentIndex(1)
        self.job = export_job(self.template, self.printer, self.rows, out, opts, self.total)
        self.job.signals.progress.connect(self._progress)
        self.job.signals.done.connect(self._done)
        self.job.signals.failed.connect(self._failed)
        self.job.start()

    def _progress(self, f: float, msg: str) -> None:
        self.p_bar.setValue(int(f * 1000))
        self.p_label.setText(msg)

    def _cancel(self) -> None:
        if self.job:
            self.job.cancelled = True
            self.p_label.setText("Cancelling…")

    def _failed(self, msg: str) -> None:
        if msg == "cancelled":
            self.stack.setCurrentIndex(0)
            QMessageBox.information(self, "Export cancelled",
                                    "The export was stopped part-way, so the folder may hold an incomplete "
                                    "set of plates. Export again before printing.")
            return
        QMessageBox.critical(self, "Export failed", msg)
        self.stack.setCurrentIndex(0)

    # -- page 3 --------------------------------------------------------------
    def _done_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.d_title = QLabel()
        self.d_title.setObjectName("Big")
        self.d_sub = QLabel()
        self.d_sub.setObjectName("Muted")
        self.d_sub.setWordWrap(True)
        v.addWidget(self.d_title)
        v.addWidget(self.d_sub)
        self.d_text = QTextBrowser()
        self.d_text.setOpenExternalLinks(True)
        v.addWidget(self.d_text, 1)
        row = QHBoxLayout()
        self.b_folder = QPushButton("Open folder")
        self.b_folder.clicked.connect(self._open_folder)
        self.b_copy = QPushButton("Copy layer numbers")
        self.b_copy.clicked.connect(self._copy_layers)
        self.b_cura = QPushButton("Open plate 1 in Cura")
        self.b_cura.setObjectName("Primary")
        self.b_cura.clicked.connect(self._open_cura)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(self.b_folder)
        row.addWidget(self.b_copy)
        row.addStretch(1)
        row.addWidget(close)
        row.addWidget(self.b_cura)
        v.addLayout(row)
        return w

    def _done(self, res: ExportResult) -> None:
        self.result = res
        self.d_title.setText(f"✓ {res.cards} cards on {res.plates} plate{'s' if res.plates != 1 else ''}")
        self.d_sub.setText(f"Saved to {res.out_dir}  ·  {len(res.files)} files in {res.seconds:.1f} s")
        t, p = self.template, self.printer
        md = ["### Colour plan", *(f"- {line}" for line in colour_plan_lines(t, p)), "",
              "### In Cura", cura_steps(t, p), ""]
        if res.problem_cards:
            md += ["### Cards worth a second look", ""]
            md += [f"- **#{i + 1} {label}** – {msg}" for i, label, msg in res.problem_cards[:30]]
            if len(res.problem_cards) > 30:
                md.append(f"- … and {len(res.problem_cards) - 30} more (see PRINT_GUIDE.md)")
        md += ["", "Everything above is also saved in **PRINT_GUIDE.md** next to the files."]
        self.d_text.setMarkdown("\n".join(md))
        has_plate = any(f.suffix == ".3mf" and f.parent.name == "plates" for f in res.files)
        self.b_cura.setVisible(has_plate)
        self.b_cura.setEnabled(slicer.find_cura() is not None)
        if not self.b_cura.isEnabled():
            self.b_cura.setToolTip("Cura wasn't found. Set CARDSMITH_CURA to its path to enable this.")
        self.b_copy.setVisible(bool(res.changes))
        self.stack.setCurrentIndex(2)

    def _first_plate(self) -> Path | None:
        if not self.result:
            return None
        plates = sorted(f for f in self.result.files if f.parent.name == "plates" and f.suffix == ".3mf")
        plain = [f for f in plates if not f.stem.endswith("_colours")]
        return (plain or plates or [None])[0]

    def _open_cura(self) -> None:
        f = self._first_plate()
        if f and not slicer.open_in_cura([f]):
            QMessageBox.warning(self, "Cura", "Couldn't start Cura.")

    def _open_folder(self) -> None:
        if self.result:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result.out_dir)))

    def _copy_layers(self) -> None:
        if self.result:
            QGuiApplication.clipboard().setText(",".join(str(c.layer) for c in self.result.changes))
            self.b_copy.setText("Copied ✓")

    def reject(self) -> None:
        if self.job and self.stack.currentIndex() == 1:
            self._cancel()
            return
        super().reject()


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^\w\-]+", "-", s).strip("-") or "cards"


def _md_bold(s: str) -> str:
    import html
    import re
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return s

