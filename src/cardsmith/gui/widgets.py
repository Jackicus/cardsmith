"""Small reusable widgets."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class Segmented(QFrame):
    """A row of mutually exclusive buttons in a rounded track (like a web segmented control)."""

    changed = Signal(int)

    def __init__(self, labels: list[str], tips: list[str] | None = None, *, expand: bool = True,
                 parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Segmented")
        h = QHBoxLayout(self)
        h.setContentsMargins(3, 3, 3, 3)
        h.setSpacing(2)
        self.group = QButtonGroup(self)
        for i, label in enumerate(labels):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if tips:
                b.setToolTip(tips[i])
            self.group.addButton(b, i)
            h.addWidget(b, 1 if expand else 0)
        self.group.button(0).setChecked(True)
        self.group.idClicked.connect(self.changed.emit)

    def index(self) -> int:
        return self.group.checkedId()

    def set_index(self, i: int) -> None:
        b = self.group.button(i)
        if b is not None:
            b.setChecked(True)

    def button(self, i: int) -> QPushButton:
        return self.group.button(i)


def floating(widget: QFrame) -> QFrame:
    """Style ``widget`` as a bar floating over the canvas, with a soft shadow."""
    widget.setObjectName("Float")
    fx = QGraphicsDropShadowEffect(widget)
    fx.setBlurRadius(24)
    fx.setOffset(0, 4)
    fx.setColor(QColor(0, 0, 0, 38))
    widget.setGraphicsEffect(fx)
    return widget


def divider() -> QFrame:
    """A thin vertical rule for separating groups inside a bar."""
    d = QFrame()
    d.setObjectName("Divider")
    d.setFixedSize(1, 20)
    return d


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
        head.setContentsMargins(0, 0, 0, 0)
        self.arrow = QToolButton()
        self.arrow.setObjectName("SectionHeader")
        self.arrow.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.arrow.setCheckable(True)
        self.arrow.setChecked(expanded)
        self.arrow.setText(title.replace("&", "&&"))
        self.arrow.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        self.arrow.setToolTip("Show or hide")
        self.arrow.toggled.connect(self.set_expanded)
        self.arrow.setSizePolicy(self.arrow.sizePolicy().Policy.Expanding, self.arrow.sizePolicy().Policy.Fixed)
        head.addWidget(self.arrow, 1)
        self.checkbox: QCheckBox | None = None
        if checkable:
            self.checkbox = QCheckBox()
            self.checkbox.setToolTip(f"Turn {title.lower()} on or off")
            self.checkbox.toggled.connect(self._on_checked)
            head.addWidget(self.checkbox)
        v.addLayout(head)

        self.body = QWidget()
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 0, 12)
        bl.setSpacing(8)
        if hint:
            lab = QLabel(hint)
            lab.setWordWrap(True)
            lab.setObjectName("Muted")
            bl.addWidget(lab)
        self.form_host = QWidget()
        self.form_host.setObjectName("FormHost")
        self.form = QFormLayout(self.form_host)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setHorizontalSpacing(12)
        self.form.setVerticalSpacing(8)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
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

