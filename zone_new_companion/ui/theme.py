"""Visual identity: one palette, one stylesheet, used everywhere."""

from __future__ import annotations

import sys

# Graphite surfaces + a single warm accent. Status colours are kept apart
# from the accent so "selected" never looks like "OK" or "error".
BG = "#0E1014"
SURFACE = "#15181E"
SURFACE_2 = "#1C2028"
SURFACE_3 = "#252A34"
BORDER = "#2A303B"
TEXT = "#ECEEF2"
TEXT_MUTED = "#8B93A3"
TEXT_FAINT = "#5C6475"
ACCENT = "#FF6A3D"
ACCENT_HOVER = "#FF845F"
ACCENT_SOFT = "rgba(255, 106, 61, 0.14)"
OK = "#3DD68C"
WARN = "#F5B84A"
ERROR = "#FF5C6C"
INFO = "#6CA8FF"

FONT_FAMILY = "Segoe UI" if sys.platform == "win32" else ("SF Pro Text" if sys.platform == "darwin" else "Inter")

STYLESHEET = f"""
* {{
    font-family: "{FONT_FAMILY}", "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: 10pt;
    color: {TEXT};
    outline: 0;
}}
QMainWindow, QWidget#Root {{ background: {BG}; }}
QWidget#Page {{ background: {BG}; }}
QToolTip {{
    background: {SURFACE_3}; color: {TEXT}; border: 1px solid {BORDER};
    padding: 6px 8px; border-radius: 6px;
}}

/* ---------- navigation rail ---------- */
QWidget#NavRail {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QLabel#Brand {{ font-size: 15pt; font-weight: 800; color: {TEXT}; letter-spacing: 0.5px; }}
QLabel#BrandAccent {{ font-size: 15pt; font-weight: 800; color: {ACCENT}; }}
QLabel#BrandSub {{ color: {TEXT_FAINT}; font-size: 8pt; letter-spacing: 2px; }}
QPushButton#NavButton {{
    text-align: left; padding: 10px 14px; border: none; border-radius: 10px;
    background: transparent; color: {TEXT_MUTED}; font-size: 10.5pt; font-weight: 600;
}}
QPushButton#NavButton:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
QPushButton#NavButton:checked {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QPushButton#NavButton:disabled {{ color: {TEXT_FAINT}; }}

/* ---------- typography ---------- */
QLabel#PageTitle {{ font-size: 20pt; font-weight: 800; }}
QLabel#PageSubtitle {{ color: {TEXT_MUTED}; font-size: 10pt; }}
QLabel#SectionTitle {{ font-size: 11.5pt; font-weight: 700; }}
QLabel#Muted {{ color: {TEXT_MUTED}; }}
QLabel#Faint {{ color: {TEXT_FAINT}; font-size: 9pt; }}
QLabel#FieldLabel {{ color: {TEXT_MUTED}; font-size: 9pt; font-weight: 600; }}
QLabel#Error {{ color: {ERROR}; }}
QLabel#Success {{ color: {OK}; }}

/* ---------- cards ---------- */
QFrame#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#Tile {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#TileLabel {{ color: {TEXT_MUTED}; font-size: 8.5pt; font-weight: 600; }}
QLabel#TileValue {{ font-size: 12pt; font-weight: 700; }}
QFrame#Divider {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QComboBox {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 9px;
    padding: 9px 12px; selection-background-color: {ACCENT}; selection-color: white;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit#BigInput {{ font-size: 11pt; padding: 13px 14px; }}
QLineEdit#Search {{ padding: 8px 12px; border-radius: 18px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT}; padding: 4px;
}}

/* ---------- buttons ---------- */
QPushButton {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 9px;
    padding: 8px 14px; font-weight: 600;
}}
QPushButton:hover {{ background: {SURFACE_3}; }}
QPushButton:pressed {{ background: {SURFACE}; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; background: {SURFACE}; }}
QPushButton#Primary {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: white; padding: 10px 20px; }}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#Primary:disabled {{ background: {SURFACE_3}; border-color: {SURFACE_3}; color: {TEXT_FAINT}; }}
QPushButton#Ghost {{ background: transparent; border: none; color: {TEXT_MUTED}; padding: 6px 10px; }}
QPushButton#Ghost:hover {{ color: {TEXT}; background: {SURFACE_2}; }}
QPushButton#Segment {{
    background: transparent; border: none; border-radius: 8px; padding: 7px 14px; color: {TEXT_MUTED};
}}
QPushButton#Segment:checked {{ background: {SURFACE_3}; color: {TEXT}; }}
QPushButton#Segment:hover:!checked {{ color: {TEXT}; }}
QFrame#SegmentBar {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px; }}
QPushButton#IconToggle {{ padding: 6px 10px; border-radius: 8px; background: transparent; border: 1px solid transparent; color: {TEXT_MUTED}; }}
QPushButton#IconToggle:checked {{ background: {SURFACE_3}; border-color: {BORDER}; color: {TEXT}; }}

/* ---------- lists ---------- */
QListView, QListWidget, QPlainTextEdit, QTableView {{
    background: transparent; border: none;
}}
QListWidget#CategoryList::item {{
    padding: 9px 12px; border-radius: 8px; margin: 1px 4px; color: {TEXT_MUTED};
}}
QListWidget#CategoryList::item:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
QListWidget#CategoryList::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT}; font-weight: 600; }}
QListWidget#HistoryList::item {{ padding: 0; margin: 2px 0; border-radius: 8px; }}
QListWidget#HistoryList::item:hover {{ background: {SURFACE_2}; }}
QListWidget#HistoryList::item:selected {{ background: {SURFACE_3}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {SURFACE_3}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #343B48; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {SURFACE_3}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; border: none; width: 0; height: 0;
}}

QProgressBar {{ background: {SURFACE_2}; border: none; border-radius: 2px; max-height: 3px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}

QCheckBox {{ spacing: 8px; color: {TEXT_MUTED}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {BORDER}; background: {SURFACE_2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QMenu {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 7px 16px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SURFACE_3}; }}
QMessageBox {{ background: {SURFACE}; }}
"""


def status_color(status: str) -> str | None:
    """Colour for a verification status string."""
    upper = status.upper()
    if upper.startswith(("OK", "✓")):
        return OK
    if upper.startswith(("OFF", "✗")):
        return ERROR
    if upper.startswith(("UNSTABLE", "⚠")):
        return WARN
    return None


def avatar_color(text: str) -> str:
    """Stable pleasant colour for channels without logo."""
    palette = ["#FF6A3D", "#6CA8FF", "#3DD68C", "#B38CFF", "#F5B84A", "#FF5C9A", "#3CC8D6", "#9AD14B"]
    return palette[sum(ord(ch) for ch in text) % len(palette)]
