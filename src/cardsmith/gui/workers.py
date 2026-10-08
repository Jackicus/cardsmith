"""Background jobs so the window never freezes."""

from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..export import Cancelled, ExportOptions, export_deck
from ..layout import layout_card
from ..model import Printer, Template


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(float, str)


class Job(QRunnable):
    """Run ``fn(job)`` on the thread pool; results come back as signals."""

    def __init__(self, fn) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _Signals()
        self.cancelled = False
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self.fn(self)
        except Cancelled:
            self.signals.failed.emit("cancelled")
        except Exception as e:  # surfaced to the user in a dialog
            traceback.print_exc()
            self.signals.failed.emit(f"{type(e).__name__}: {e}")
        else:
            self.signals.done.emit(result)

    def start(self) -> Job:
        QThreadPool.globalInstance().start(self)
        return self


def check_job(template: Template, printer: Printer, row: dict, index: int, total: int, generation: int) -> Job:
    t, p = template.copy(), Printer.from_dict(printer.to_dict())

    def work(job):
        return generation, layout_card(t, p, row, index, total, check_print=True)

    return Job(work)


def deck_check_job(template: Template, printer: Printer, rows: list[tuple[int, dict]], thorough: bool,
                   total: int) -> Job:
    t, p = template.copy(), Printer.from_dict(printer.to_dict())

    def work(job):
        out = []
        checked = 0
        for n, (idx, row) in enumerate(rows):
            if job.cancelled:
                break
            lay = layout_card(t, p, row, idx, total, check_print=thorough)
            checked += 1
            bad = [i for i in lay.issues if i.level in ("error", "warning")]
            if bad:
                out.append((idx, lay.label, bad))
            job.signals.progress.emit((n + 1) / len(rows), f"Checked {n + 1} of {len(rows)}")
        return out, checked, job.cancelled

    return Job(work)


def export_job(template: Template, printer: Printer, rows, out_dir, options: ExportOptions,
               total: int | None = None) -> Job:
    t, p = template.copy(), Printer.from_dict(printer.to_dict())

    def work(job):
        return export_deck(t, p, rows, out_dir, options, total_arg=total,
                           progress=lambda f, m: job.signals.progress.emit(f, m),
                           cancelled=lambda: job.cancelled)

    return Job(work)
