"""Look and feel: a clean, web-app style on top of Fusion, light or dark."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#E0533D"  # vermilion, like a hanko stamp
ACCENT_HOVER = "#EA6550"
HERE = Path(__file__).parent

# Typefaces tried in order for the interface (not the cards); the first one installed wins.
UI_FONTS = ("Inter", "Geist", "SF Pro Text", "Segoe UI Variable Text", "Segoe UI", "Cantarell", "Noto Sans")

LIGHT = {
    "window": "#F4F3F0",  # app background behind the panels
    "surface": "#FFFFFF",  # header, sidebar, floating bars
    "panel": "#F8F7F4",  # cards inside the sidebar
    "base": "#FFFFFF",  # inputs and lists
    "alt": "#F2F1ED",
    "hover": "#F0EEEA",
    "text": "#1A1D26",
    "muted": "#6E7380",
    "border": "#E4E1DB",
    "canvas": "#ECEAE5",
    "canvas_dots": "#D3CFC6",
    "button": "#FFFFFF",
    "ok": "#2E7D32",
}
DARK = {
    "window": "#0F1115",
    "surface": "#171A21",
    "panel": "#1D2029",
    "base": "#12141A",
    "alt": "#20232C",
    "hover": "#242833",
    "text": "#E7E9EE",
    "muted": "#9298A6",
    "border": "#2A2E39",
    "canvas": "#0C0E12",
    "canvas_dots": "#262A34",
    "button": "#222631",
    "ok": "#66BB6A",
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


def _ui_font() -> QFont:
    f = QFont(QGuiApplication.font())
    installed = set(QFontDatabase.families())
    for fam in UI_FONTS:
        if fam in installed:
            f.setFamily(fam)
            break
    f.setPointSizeF(max(f.pointSizeF(), 10.0))
    return f


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setFont(_ui_font())
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
    pal.setColor(role.ToolTipBase, QColor(c["surface"]))
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
    /* -- base controls ------------------------------------------------- */
    QMainWindow, QDialog {{ background: {c['window']}; }}
    QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']};
                padding: 6px 8px; border-radius: 6px; }}
    QPushButton, QToolButton {{ background: {c['button']}; border: 1px solid {c['border']}; border-radius: 8px;
                                padding: 6px 12px; }}
    QPushButton:hover, QToolButton:hover {{ background: {c['hover']}; }}
    QPushButton:pressed, QToolButton:pressed {{ background: {c['alt']}; }}
    QPushButton:checked, QToolButton:checked {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {c['muted']}; }}
    QToolButton::menu-indicator, QPushButton::menu-indicator {{ image: none; width: 0; }}
    QPushButton#Primary {{ background: {ACCENT}; color: white; border: 1px solid {ACCENT}; font-weight: 600;
                           padding: 7px 18px; }}
    QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
    QPushButton#Primary:disabled {{ background: {c['border']}; border-color: {c['border']}; color: {c['muted']}; }}
    QPushButton#Ghost, QToolButton#Ghost {{ background: transparent; border: 1px solid transparent; }}
    QPushButton#Ghost:hover, QToolButton#Ghost:hover {{ background: {c['hover']}; }}
    QPushButton#Ghost:disabled, QToolButton#Ghost:disabled {{ color: {c['border']}; }}
    QPushButton#Link {{ background: transparent; border: none; color: {ACCENT}; padding: 2px 0; font-weight: 600;
                        text-align: left; }}
    QPushButton#Link:hover {{ text-decoration: underline; }}
    QPushButton#Link:checked {{ background: transparent; color: {ACCENT}; border: none; }}

    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
        background: {c['base']}; border: 1px solid {c['border']}; border-radius: 7px; padding: 5px 8px;
        selection-background-color: {ACCENT}; }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
        color: {c['muted']}; background: {c['alt']}; }}
    QAbstractSpinBox {{ padding-right: 22px; }}
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
        subcontrol-origin: border; width: 20px; border: none; background: transparent; }}
    QAbstractSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 7px; }}
    QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 7px; }}
    QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {c['hover']}; }}
    QAbstractSpinBox::up-arrow {{ image: url({up}); width: 9px; height: 9px; }}
    QAbstractSpinBox::down-arrow {{ image: url({down}); width: 9px; height: 9px; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox::down-arrow {{ image: url({down}); width: 10px; height: 10px; }}
    QComboBox QAbstractItemView {{ background: {c['surface']}; border: 1px solid {c['border']};
                                   selection-background-color: {ACCENT}; outline: none; }}
    QMenu {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 4px; }}
    QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {c['hover']}; color: {c['text']}; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 6px; }}
    QCheckBox {{ spacing: 8px; }}

    QListWidget, QTableView, QTreeWidget, QTextBrowser {{ background: {c['base']};
        border: 1px solid {c['border']}; border-radius: 8px; outline: none; }}
    QListWidget::item {{ padding: 6px 6px; border-radius: 6px; }}
    QListWidget::item:hover {{ background: {c['hover']}; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{ background: rgba(224,83,61,30);
                                                              color: {c['text']}; }}
    QHeaderView::section {{ background: {c['alt']}; color: {c['muted']}; border: none;
        border-bottom: 1px solid {c['border']}; padding: 6px; font-weight: 600; }}
    QTableView {{ gridline-color: {c['border']}; selection-background-color: rgba(224,83,61,30);
                  selection-color: {c['text']}; }}
    QTableView::item:selected {{ background: rgba(224,83,61,30); color: {c['text']}; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ width: 8px; background: transparent; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 3px; min-height: 30px; }}
    QScrollBar:horizontal {{ height: 8px; background: transparent; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {c['border']}; border-radius: 3px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        width: 0; height: 0; background: none; }}
    QSplitter::handle {{ background: {c['border']}; }}
    QProgressBar {{ border: none; border-radius: 3px; background: {c['alt']}; text-align: center; }}
    QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{ background: transparent; color: {c['muted']}; padding: 8px 12px; border: none;
                    border-bottom: 2px solid transparent; font-weight: 600; }}
    QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {ACCENT}; }}
    QTabBar::tab:hover {{ color: {c['text']}; }}

    /* -- app chrome ------------------------------------------------------ */
    QFrame#Header {{ background: {c['surface']}; border-bottom: 1px solid {c['border']}; }}
    QLabel#Brand {{ font-size: 16px; font-weight: 700; }}
    QLabel#BrandMark {{ background: {ACCENT}; color: white; border-radius: 8px; font-size: 15px;
                        font-weight: 700; }}
    QFrame#Sidebar, QFrame#Drawer {{ background: {c['surface']}; }}
    QFrame#Sidebar {{ border-right: 1px solid {c['border']}; }}
    QFrame#Drawer {{ border-left: 1px solid {c['border']}; }}
    QFrame#DeckCard {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 12px; }}
    QLabel#DeckIcon {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 9px;
                       font-size: 17px; }}

    /* Segmented control: a row of checkable buttons in a rounded track. */
    QFrame#Segmented {{ background: {c['alt']}; border-radius: 10px; }}
    QFrame#Segmented QPushButton {{ background: transparent; border: none; border-radius: 8px;
                                    padding: 6px 10px; color: {c['muted']}; font-weight: 600; }}
    QFrame#Segmented QPushButton:hover {{ color: {c['text']}; }}
    QFrame#Segmented QPushButton:checked {{ background: {c['surface']}; color: {c['text']};
                                            border: 1px solid {c['border']}; }}

    /* Floating bars over the canvas. */
    QFrame#Float {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 12px; }}
    QFrame#Float QToolButton, QFrame#Float QPushButton {{ background: transparent; border: none;
                                                          border-radius: 7px; padding: 5px 9px; }}
    QFrame#Float QToolButton:hover, QFrame#Float QPushButton:hover {{ background: {c['hover']}; }}
    QFrame#Float QToolButton:disabled {{ color: {c['border']}; }}
    QFrame#Float QFrame#Segmented QPushButton:checked {{ background: {c['surface']};
                                                         border: 1px solid {c['border']}; }}
    QFrame#Divider {{ background: {c['border']}; }}

    QPushButton#PillOk, QPushButton#PillWarn {{ border-radius: 15px; padding: 6px 14px; font-weight: 600; }}
    QPushButton#PillOk {{ background: {c['surface']}; color: {c['ok']}; border: 1px solid {c['ok']}; }}
    QPushButton#PillWarn {{ background: {c['surface']}; color: #C2471F; border: 1px solid {ACCENT}; }}
    QPushButton#PillOk:hover, QPushButton#PillWarn:hover {{ background: {c['hover']}; }}

    /* Collapsible sections: flat, divided by hairlines. */
    QFrame#Collapsible {{ background: transparent; border: none; border-top: 1px solid {c['border']};
                          border-radius: 0; }}
    QToolButton#SectionHeader {{ border: none; background: transparent; font-weight: 600; padding: 10px 0;
                                 text-align: left; }}
    QToolButton#SectionHeader:hover {{ color: {ACCENT}; background: transparent; }}
    QToolButton#SectionHeader:checked {{ background: transparent; color: {c['text']}; }}
    QWidget#FormHost QLabel {{ color: {c['muted']}; }}

    QFrame#Welcome {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 18px; }}
    QLabel#Step {{ background: {ACCENT}; color: white; border-radius: 13px; font-weight: 700; }}
    QWidget#Panel, QLabel#Panel {{ background: {c['panel']}; border: 1px solid {c['border']};
                                   border-radius: 10px; }}
    QLabel#Title {{ font-size: 14px; font-weight: 600; }}
    QLabel#Muted, QLabel[muted="true"] {{ color: {c['muted']}; }}
    QLabel#Section {{ color: {c['muted']}; font-size: 11px; font-weight: 700;
                      letter-spacing: 1px; padding-top: 8px; }}
    QLabel#Big {{ font-size: 22px; font-weight: 700; }}
    QGroupBox {{ border: 1px solid {c['border']}; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {c['muted']};
                        font-weight: 600; }}
    QStatusBar {{ color: {c['muted']}; }}
    """
