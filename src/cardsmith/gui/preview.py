"""Live card and plate preview (QGraphicsView, units = mm)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView

from ..fonts import to_multipolygon
from ..layout import CardLayout
from ..model import Template, height_bands
from ..plate import PlateLayout
from . import theme


def geom_path(g, height: float) -> QPainterPath:
    """Shapely geometry (y up) → painter path in scene coords (y down)."""
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.OddEvenFill)
    for poly in to_multipolygon(g).geoms:
        for ring in (poly.exterior, *poly.interiors):
            path.addPolygon(QPolygonF([QPointF(x, height - y) for x, y in ring.coords]))
            path.closeSubpath()
    return path


def _shade(hex_colour: str, factor: int) -> QColor:
    c = QColor(hex_colour)
    return c.darker(factor) if factor > 100 else c.lighter(200 - factor)


class CardItem(QGraphicsItem):
    """Paints one card: base, raised parts with a soft emboss, overlays."""

    def __init__(self, lay: CardLayout, template: Template, bands, show_issues=True, show_guides=True,
                 selected_slot: int | None = None, number: str | None = None) -> None:
        super().__init__()
        self.lay = lay
        self.w, self.h = lay.width, lay.height
        self.bands = bands
        self.show_issues = show_issues
        self.show_guides = show_guides
        self.selected_slot = selected_slot
        self.number = number
        self.padding = template.card.padding
        self.paths = [(f, geom_path(f.geom, self.h)) for f in lay.features]
        self.thin = geom_path(lay.thin, self.h) if not lay.thin.is_empty else None
        self.gaps = geom_path(lay.gaps, self.h) if not lay.gaps.is_empty else None
        self.boxes = {b.slot_index: QRectF(b.bounds[0], self.h - b.bounds[3],
                                           b.bounds[2] - b.bounds[0], b.bounds[3] - b.bounds[1])
                      for b in lay.boxes}

    def boundingRect(self) -> QRectF:
        return QRectF(-2, -2, self.w + 4, self.h + 4)

    def colour(self, band: int) -> str:
        return self.bands[band].colour if band < len(self.bands) else "#999999"

    def paint(self, p: QPainter, option, widget=None) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        lod = option.levelOfDetailFromTransform(p.worldTransform())
        px = 1 / max(lod, 1e-6)  # one screen pixel in mm
        base = [x for x in self.paths if x[0].kind == "base"]
        raised = sorted((x for x in self.paths if x[0].kind != "base"), key=lambda x: x[0].z1)

        # Card drop shadow and body.
        for f, path in base:
            p.save()
            p.translate(0.6, 0.9)
            p.fillPath(path, QColor(0, 0, 0, 45))
            p.restore()
            col = self.colour(f.band)
            p.fillPath(path, QColor(col))
            p.setPen(QPen(_shade(col, 125), 1.2 * px))
            p.drawPath(path)

        # Raised parts: shadow down-right, highlight up-left, then the face.
        for f, path in raised:
            col = self.colour(f.band)
            relief = max(f.z1 - f.z0, 0.2)
            off = min(0.12 + relief * 0.25, 0.45)
            p.save()
            p.translate(off, off)
            p.fillPath(path, QColor(0, 0, 0, 70))
            p.restore()
            p.save()
            p.translate(-off * 0.35, -off * 0.35)
            p.fillPath(path, QColor(255, 255, 255, 60))
            p.restore()
            p.fillPath(path, QColor(col))

        if self.show_guides and self.padding > 0:
            pen = QPen(QColor(theme.ACCENT), 1 * px, Qt.PenStyle.DashLine)
            pen.setDashPattern([4, 4])
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(self.padding, self.padding, self.w - 2 * self.padding, self.h - 2 * self.padding))

        if self.show_issues:
            if self.thin is not None:
                p.fillPath(self.thin, QColor(230, 30, 60, 210))
            if self.gaps is not None:
                p.fillPath(self.gaps, QColor(255, 150, 0, 200))

        if self.selected_slot is not None and self.selected_slot in self.boxes:
            r = self.boxes[self.selected_slot].adjusted(-0.8, -0.8, 0.8, 0.8)
            pen = QPen(QColor(theme.ACCENT), 1.5 * px)
            p.setPen(pen)
            p.setBrush(QColor(224, 83, 61, 22))
            p.drawRoundedRect(r, 0.8, 0.8)

        if self.number:
            p.setPen(QColor(255, 255, 255, 230))
            f = QFont()
            f.setPointSizeF(4)
            f.setBold(True)
            p.setFont(f)
            r = QRectF(self.w - 9, self.h - 6.5, 8, 5)
            p.setBrush(QColor(0, 0, 0, 120))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, 1.5, 1.5)
            p.setPen(QColor("white"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.number)

    def slot_at(self, pt: QPointF) -> int | None:
        hits = [(r.width() * r.height(), i) for i, r in self.boxes.items() if r.adjusted(-1, -1, 1, 1).contains(pt)]
        return min(hits)[1] if hits else None


class BedItem(QGraphicsItem):
    def __init__(self, w: float, d: float, margin: float, label: str) -> None:
        super().__init__()
        self.w, self.d, self.margin, self.label = w, d, margin, label

    def boundingRect(self) -> QRectF:
        return QRectF(-6, -10, self.w + 12, self.d + 16)

    def paint(self, p: QPainter, option, widget=None) -> None:
        c = theme.colours()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        lod = option.levelOfDetailFromTransform(p.worldTransform())
        px = 1 / max(lod, 1e-6)
        bed = QRectF(0, 0, self.w, self.d)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawRoundedRect(bed.translated(1.5, 2), 6, 6)
        p.setBrush(QColor("#2B2F3A") if theme.is_dark() else QColor("#3A3F4B"))
        p.drawRoundedRect(bed, 6, 6)
        grid = QPen(QColor(255, 255, 255, 22), 1 * px)
        p.setPen(grid)
        step = 10
        x = step
        while x < self.w:
            p.drawLine(QPointF(x, 0), QPointF(x, self.d))
            x += step
        y = step
        while y < self.d:
            p.drawLine(QPointF(0, y), QPointF(self.w, y))
            y += step
        pen = QPen(QColor(255, 255, 255, 90), 1 * px, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        m = self.margin
        p.drawRoundedRect(QRectF(m, m, self.w - 2 * m, self.d - 2 * m), 3, 3)
        f = QFont()
        f.setPointSizeF(3.6)
        p.setFont(f)
        p.setPen(QColor(c["muted"]))
        p.drawText(QRectF(0, -8, self.w, 7), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.label)


class Preview(QGraphicsView):
    slotClicked = Signal(int)
    slotDragged = Signal(int, float, float)  # slot, dx, dy in mm (scene, y down)
    dragFinished = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.card: CardItem | None = None
        self._drag_slot: int | None = None
        self._drag_last: QPointF | None = None
        self._pan_last = None
        self._auto_fit = True
        self._scene_rect = QRectF()
        self.apply_theme()

    def apply_theme(self) -> None:
        self.setBackgroundBrush(QBrush(QColor(theme.colours()["canvas"])))

    # -- content ----------------------------------------------------------
    def show_card(self, lay: CardLayout, template: Template, printer, *, show_issues=True,
                  show_guides=True, selected_slot=None) -> None:
        bands = height_bands(template, printer)
        self.scene().clear()
        self.card = CardItem(lay, template, bands, show_issues, show_guides, selected_slot)
        self.scene().addItem(self.card)
        self._set_rect(QRectF(-8, -8, lay.width + 16, lay.height + 16))

    def show_plate(self, layouts: list[tuple[int, CardLayout]], packing: PlateLayout, template: Template,
                   printer, label: str) -> None:
        bands = height_bands(template, printer)
        self.scene().clear()
        self.card = None
        bed = BedItem(packing.bed_w, packing.bed_d, printer.margin, label)
        self.scene().addItem(bed)
        # Bed Y runs away from the viewer; scene Y runs down, so flip.
        for (idx, lay), slot in zip(layouts, packing.slots, strict=False):
            item = CardItem(lay, template, bands, show_issues=False, show_guides=False, number=str(idx + 1))
            self.scene().addItem(item)
            if slot.rotated:
                # Card rotated 90° CCW on the bed (seen from above).
                tr = QTransform()
                tr.translate(slot.x, packing.bed_d - slot.y)
                tr.rotate(-90)
                item.setTransform(tr)
            else:
                item.setPos(slot.x, packing.bed_d - slot.y - lay.height)
        self._set_rect(QRectF(-8, -12, packing.bed_w + 16, packing.bed_d + 22))

    def clear_message(self, text: str) -> None:
        self.scene().clear()
        self.card = None
        t = self.scene().addText(text)
        t.setDefaultTextColor(QColor(theme.colours()["muted"]))
        self._set_rect(t.boundingRect())

    def _set_rect(self, r: QRectF) -> None:
        self.setSceneRect(r.adjusted(-2000, -2000, 2000, 2000))
        changed = r != self._scene_rect
        self._scene_rect = r
        if self._auto_fit or changed:
            self.fit()

    def fit(self) -> None:
        if self._scene_rect.isNull():
            return
        self.fitInView(self._scene_rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._auto_fit = True

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self._auto_fit:
            self.fit()

    # -- interaction --------------------------------------------------------
    def wheelEvent(self, e) -> None:
        f = 1.0015 ** e.angleDelta().y()
        self.scale(f, f)
        self._auto_fit = False

    def mouseDoubleClickEvent(self, e) -> None:
        self.fit()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.card is not None:
            pt = self.card.mapFromScene(self.mapToScene(e.position().toPoint()))
            hit = self.card.slot_at(pt)
            if hit is not None:
                self._drag_slot = hit
                self._drag_last = pt
                self.slotClicked.emit(hit)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
        if e.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._pan_last = e.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        if self._drag_slot is not None and self.card is not None:
            pt = self.card.mapFromScene(self.mapToScene(e.position().toPoint()))
            d = pt - self._drag_last
            step = 0.1 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.5
            dx, dy = round(d.x() / step) * step, round(d.y() / step) * step
            if dx or dy:
                self._drag_last = QPointF(self._drag_last.x() + dx, self._drag_last.y() + dy)
                self.slotDragged.emit(self._drag_slot, dx, dy)
            return
        if self._pan_last is not None:
            delta = e.position() - self._pan_last
            self._pan_last = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            self._auto_fit = False
            return
        if self.card is not None:
            pt = self.card.mapFromScene(self.mapToScene(e.position().toPoint()))
            over = self.card.slot_at(pt) is not None
            self.setCursor(Qt.CursorShape.OpenHandCursor if over else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if self._drag_slot is not None:
            self._drag_slot = None
            self.dragFinished.emit()
        self._pan_last = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(e)

    def update_selection(self, slot: int | None) -> None:
        if self.card is not None:
            self.card.selected_slot = slot
            self.card.update()
