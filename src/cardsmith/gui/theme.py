"""Look and feel: Fusion with a warm light or ink-dark palette."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#E0533D"  # vermilion, like a hanko stamp
HERE = Path(__file__).parent

LIGHT = {
    "window": "#F3F1EC",
    "panel": "#FBFAF7",
    "base": "#FFFFFF",
    "alt": "#F5F3EE",
    "text": "#1E2230",
    "muted": "#6B6F7B",
    "border": "#DDD8CE",
    "canvas": "#E6E2D9",
    "canvas_grid": "#D9D4C9",
    "button": "#FFFFFF",
}
DARK = {
    "window": "#16181F",
    "panel": "#1C1F27",
    "base": "#12141A",
    "alt": "#20232C",
    "text": "#E7E9EE",
    "muted": "#9298A6",
    "border": "#2E323D",
    "canvas": "#0F1116",
    "canvas_grid": "#1B1E26",
    "button": "#252934",
}


def is_dark() -> bool:
    forced = os.environ.get("CARDSMITH_THEME", "").lower()
    if forced in ("dark", "light"):
        return forced == "dark"
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return QGuiApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128


def colours() -> dict[str, str]:
    return DARK if is_dark() else LIGHT


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    c = colours()
    pal = QPalette()
    role = QPalette.ColorRole
    pal.setColor(role.Window, QColor(c["window"]))
    pal.setColor(role.WindowText, QColor(c["text"]))
    pal.setColor(role.Base, QColor(c["base"]))
    pal.setColor(role.AlternateBase, QColor(c["alt"]))
    pal.setColor(role.Text, QColor(c["text"]))
    pal.setColor(role.Button, QColor(c["button"]))
    pal.setColor(role.ButtonText, QColor(c["text"]))
    pal.setColor(role.ToolTipBase, QColor(c["panel"]))
    pal.setColor(role.ToolTipText, QColor(c["text"]))
    pal.setColor(role.PlaceholderText, QColor(c["muted"]))
    pal.setColor(role.Highlight, QColor(ACCENT))
    pal.setColor(role.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(role.Link, QColor(ACCENT))
    pal.setColor(role.Mid, QColor(c["border"]))
    pal.setColor(QPalette.ColorGroup.Disabled, role.Text, QColor(c["muted"]))
    pal.setColor(QPalette.ColorGroup.Disabled, role.ButtonText, QColor(c["muted"]))
    pal.setColor(QPalette.ColorGroup.Disabled, role.WindowText, QColor(c["muted"]))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(c))


def stylesheet(c: dict[str, str]) -> str:
    up = (HERE / "arrow-up.svg").as_posix()
    down = (HERE / "arrow-down.svg").as_posix()
    return f"""
    QAbstractSpinBox {{ padding-right: 20px; }}
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
        subcontrol-origin: border; width: 20px; border: none; border-left: 1px solid {c['border']};
        background: transparent; }}
    QAbstractSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 6px; }}
    QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 6px; }}
    QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {c['alt']}; }}
    QAbstractSpinBox::up-arrow {{ image: url({up}); width: 10px; height: 10px; }}
    QAbstractSpinBox::down-arrow {{ image: url({down}); width: 10px; height: 10px; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox::down-arrow {{ image: url({down}); width: 10px; height: 10px; }}
    QMainWindow, QDialog {{ background: {c['window']}; }}
    QToolTip {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']};
                padding: 6px; border-radius: 6px; }}
    QToolButton::menu-indicator, QPushButton::menu-indicator {{ image: none; width: 0; }}
    QFrame#Collapsible {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 10px; }}
    QToolButton#SectionHeader {{ border: none; background: transparent; font-weight: 600; padding: 6px 2px;
                                 text-align: left; }}
    QToolButton#SectionHeader:hover {{ color: {ACCENT}; }}
    QToolButton#SectionHeader:checked {{ background: transparent; color: {c['text']}; }}
    QPushButton#Pill {{ border-radius: 14px; padding: 5px 14px; font-weight: 600; }}
    QPushButton#PillOk {{ border-radius: 14px; padding: 5px 14px; font-weight: 600; color: #2E7D32;
                          border-color: rgba(46,125,50,90); }}
    QPushButton#PillWarn {{ border-radius: 14px; padding: 5px 14px; font-weight: 600; color: #B9471F;
                            border-color: {ACCENT}; background: rgba(224,83,61,24); }}
    QFrame#Welcome {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 16px; }}
    QLabel#Step {{ background: {ACCENT}; color: white; border-radius: 13px; font-weight: 700; }}
    QWidget#Panel {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 10px; }}
    QLabel#Title {{ font-size: 15px; font-weight: 600; }}
    QLabel#Muted, QLabel[muted="true"] {{ color: {c['muted']}; }}
    QLabel#Section {{ color: {c['muted']}; font-size: 11px; font-weight: 600;
                      letter-spacing: 1px; padding-top: 8px; }}
    QLabel#Big {{ font-size: 22px; font-weight: 700; }}
    QGroupBox {{ border: 1px solid {c['border']}; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {c['muted']};
                        font-weight: 600; }}
    QGroupBox::indicator {{ width: 14px; height: 14px; }}
    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{ background: transparent; color: {c['muted']}; padding: 8px 12px; border: none;
                    border-bottom: 2px solid transparent; font-weight: 600; }}
    QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {ACCENT}; }}
    QTabBar::tab:hover {{ color: {c['text']}; }}
    QPushButton, QToolButton {{ background: {c['button']}; border: 1px solid {c['border']}; border-radius: 7px;
                                padding: 5px 12px; }}
    QPushButton:hover, QToolButton:hover {{ border-color: {ACCENT}; }}
    QPushButton:pressed, QToolButton:pressed {{ background: {c['alt']}; }}
    QPushButton:checked, QToolButton:checked {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}
    QPushButton:disabled {{ color: {c['muted']}; }}
    QPushButton#Primary {{ background: {ACCENT}; color: white; border: none; font-weight: 600; padding: 7px 16px; }}
    QPushButton#Primary:hover {{ background: #EA6550; }}
    QPushButton#Primary:disabled {{ background: {c['border']}; color: {c['muted']}; }}
    QToolBar {{ background: {c['window']}; border: none; spacing: 6px; padding: 6px 8px; }}
    QToolBar QToolButton {{ padding: 5px 10px; }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
        background: {c['base']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 4px 6px;
        selection-background-color: {ACCENT}; }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
    QListWidget, QTableView, QTreeWidget, QTextBrowser {{ background: {c['base']}; border: 1px solid {c['border']};
        border-radius: 8px; }}
    QListWidget::item {{ padding: 5px 4px; border-radius: 5px; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{ background: {ACCENT}; color: white; }}
    QHeaderView::section {{ background: {c['alt']}; color: {c['muted']}; border: none;
        border-bottom: 1px solid {c['border']}; padding: 5px; font-weight: 600; }}
    QTableView {{ gridline-color: {c['border']}; }}
    QTableView::item:selected {{ background: {ACCENT}; color: white; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ width: 10px; background: transparent; }}
    QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px; min-height: 30px; }}
    QScrollBar:horizontal {{ height: 10px; background: transparent; }}
    QScrollBar::handle:horizontal {{ background: {c['border']}; border-radius: 5px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QSplitter::handle {{ background: transparent; }}
    QStatusBar {{ color: {c['muted']}; }}
    QProgressBar {{ border: 1px solid {c['border']}; border-radius: 6px; text-align: center; background: {c['base']}; }}
    QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
    """
