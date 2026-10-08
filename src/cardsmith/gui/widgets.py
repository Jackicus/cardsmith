"""Small reusable widgets."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class Section(QFrame):
    """A collapsible group: click the header to show or hide its contents.

    ``checkable`` adds an on/off switch to the header (e.g. "Border"); the
    contents are greyed out while it's off. The open/closed state is
    remembered per ``key`` between sessions.
    """

    toggled = Signal(bool)

    def __init__(self, title: str, *, key: str, expanded: bool = False, checkable: bool = False,
                 hint: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Collapsible")
        self._key = f"ui/section/{key}"
        expanded = QSettings().value(self._key, expanded, type=bool)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(4, 2, 6, 2)
        self.arrow = QToolButton()
        self.arrow.setObjectName("SectionHeader")
        self.arrow.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.arrow.setCheckable(True)
        self.arrow.setChecked(expanded)
        self.arrow.setText(title.replace("&", "&&"))
        self.arrow.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.arrow.toggled.connect(self.set_expanded)
        self.arrow.setSizePolicy(self.arrow.sizePolicy().Policy.Expanding, self.arrow.sizePolicy().Policy.Fixed)
        head.addWidget(self.arrow, 1)
        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        head.addWidget(self.summary)
        self.checkbox: QCheckBox | None = None
        if checkable:
            self.checkbox = QCheckBox()
            self.checkbox.setToolTip(f"Turn {title.lower()} on or off")
            self.checkbox.toggled.connect(self._on_checked)
            head.addWidget(self.checkbox)
        v.addLayout(head)

        self.body = QWidget()
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(10, 2, 8, 10)
        if hint:
            lab = QLabel(hint)
            lab.setWordWrap(True)
            lab.setObjectName("Muted")
            bl.addWidget(lab)
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self.form.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.form_host)
        v.addWidget(self.body)
        self.body.setVisible(expanded)

    def set_expanded(self, on: bool) -> None:
        self.arrow.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.body.setVisible(on)
        if self.arrow.isChecked() != on:
            self.arrow.setChecked(on)
        QSettings().setValue(self._key, on)

    def _on_checked(self, on: bool) -> None:
        self.form_host.setEnabled(on)
        self.toggled.emit(on)

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)
