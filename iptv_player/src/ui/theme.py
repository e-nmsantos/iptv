"""Central premium dark theme: palette tokens + one global stylesheet.

Every widget in src/ui should read colors/spacing from `Palette` instead of
hardcoding hex values, and the app applies `build_stylesheet()` once at
startup instead of scattering `setStyleSheet()` calls per widget. Only truly
state-dependent styling (e.g. a button that turns red while recording) stays
as a small inline `setStyleSheet()` call in that widget.
"""


class Palette:
    """Streaming-app-inspired dark palette (Netflix/Plex tonal range)."""

    # Backgrounds, darkest to lightest.
    BG_BASE = "#0e0e10"
    BG_PANEL = "#161618"
    BG_ELEVATED = "#1e1e21"
    BG_CARD = "#232326"
    BG_CARD_HOVER = "#2c2c30"
    BG_INPUT = "#1c1c1f"

    BORDER = "#2c2c30"
    BORDER_STRONG = "#3a3a40"

    ACCENT = "#d6293f"          # streaming-red primary accent (softened, not neon)
    ACCENT_HOVER = "#e8455a"
    ACCENT_MUTED = "#5c1620"
    SELECTION = "#33191d"
    INFO_BLUE = "#0078d4"
    LIVE_BADGE = "#e50914"
    FAVORITE_GOLD = "#f5c518"
    SUCCESS_GREEN = "#2ecc71"
    WARNING_AMBER = "#f0b429"

    TEXT_PRIMARY = "#f5f5f7"
    TEXT_SECONDARY = "#a8a8ad"
    TEXT_MUTED = "#707076"
    TEXT_ON_ACCENT = "#ffffff"

    # Spacing scale (px).
    SPACE_XS = 4
    SPACE_SM = 8
    SPACE_MD = 12
    SPACE_LG = 16
    SPACE_XL = 24

    RADIUS_SM = 5
    RADIUS_MD = 9
    RADIUS_LG = 14
    RADIUS_CARD = 12

    CARD_GRADIENT_TOP = "rgba(0, 0, 0, 0)"
    CARD_GRADIENT_BOTTOM = "rgba(0, 0, 0, 210)"
    HERO_GRADIENT = "rgba(14, 14, 16, 235)"

    FONT_FAMILY = "'Segoe UI', 'Inter', sans-serif"


def build_stylesheet() -> str:
    """Return the single global QSS applied to the whole application."""
    p = Palette
    return f"""
    * {{
        font-family: {p.FONT_FAMILY};
    }}

    QWidget {{
        background: {p.BG_BASE};
        color: {p.TEXT_PRIMARY};
        font-size: 13px;
    }}

    QMainWindow, QDialog {{
        background: {p.BG_BASE};
    }}

    QToolTip {{
        background: {p.BG_ELEVATED};
        color: {p.TEXT_PRIMARY};
        border: 1px solid {p.BORDER_STRONG};
        border-radius: {p.RADIUS_SM}px;
        padding: 4px 8px;
    }}

    QLabel {{
        background: transparent;
        color: {p.TEXT_PRIMARY};
    }}

    QPushButton {{
        background: {p.BG_ELEVATED};
        color: {p.TEXT_PRIMARY};
        border: 1px solid {p.BORDER_STRONG};
        border-radius: {p.RADIUS_MD}px;
        padding: 6px 14px;
    }}
    QPushButton:hover {{
        background: {p.BG_CARD_HOVER};
        border-color: {p.BORDER_STRONG};
    }}
    QPushButton:pressed {{
        background: {p.ACCENT_MUTED};
    }}
    QPushButton:disabled {{
        color: {p.TEXT_MUTED};
        border-color: {p.BORDER};
    }}
    QPushButton:checked {{
        background: {p.ACCENT};
        border-color: {p.ACCENT};
        color: {p.TEXT_ON_ACCENT};
    }}

    QPushButton#primaryButton {{
        background: {p.ACCENT};
        border-color: {p.ACCENT};
        color: {p.TEXT_ON_ACCENT};
        font-weight: 600;
    }}
    QPushButton#primaryButton:hover {{
        background: {p.ACCENT_HOVER};
    }}

    QLineEdit, QSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
        background: {p.BG_INPUT};
        color: {p.TEXT_PRIMARY};
        border: 1px solid {p.BORDER_STRONG};
        border-radius: {p.RADIUS_MD}px;
        padding: 6px 10px;
        selection-background-color: {p.SELECTION};
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border-color: {p.ACCENT};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background: {p.BG_ELEVATED};
        color: {p.TEXT_PRIMARY};
        border: 1px solid {p.BORDER_STRONG};
        selection-background-color: {p.SELECTION};
        outline: none;
    }}

    QListWidget, QListView, QTreeWidget, QTreeView, QTableWidget, QTableView {{
        background: {p.BG_PANEL};
        color: {p.TEXT_PRIMARY};
        border: 1px solid {p.BORDER};
        border-radius: {p.RADIUS_MD}px;
        outline: none;
    }}
    QListWidget::item, QTreeWidget::item {{
        padding: 5px 6px;
        border-radius: {p.RADIUS_SM}px;
    }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background: {p.SELECTION};
        color: {p.TEXT_PRIMARY};
    }}
    QListWidget::item:hover, QTreeWidget::item:hover {{
        background: {p.BG_CARD_HOVER};
    }}
    QHeaderView::section {{
        background: {p.BG_ELEVATED};
        color: {p.TEXT_SECONDARY};
        border: none;
        border-bottom: 1px solid {p.BORDER};
        padding: 6px;
    }}

    QTabWidget::pane {{
        border: 1px solid {p.BORDER};
        border-radius: {p.RADIUS_MD}px;
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {p.TEXT_SECONDARY};
        padding: 8px 16px;
        margin-right: 2px;
        border-top-left-radius: {p.RADIUS_SM}px;
        border-top-right-radius: {p.RADIUS_SM}px;
    }}
    QTabBar::tab:selected {{
        background: {p.BG_ELEVATED};
        color: {p.TEXT_PRIMARY};
        border-bottom: 2px solid {p.ACCENT};
    }}
    QTabBar::tab:hover:!selected {{
        color: {p.TEXT_PRIMARY};
    }}

    QMenu {{
        background: {p.BG_ELEVATED};
        color: {p.TEXT_PRIMARY};
        border: 1px solid {p.BORDER_STRONG};
        border-radius: {p.RADIUS_MD}px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 12px;
        border-radius: {p.RADIUS_SM}px;
    }}
    QMenu::item:selected {{
        background: {p.SELECTION};
    }}
    QMenu::separator {{
        height: 1px;
        background: {p.BORDER};
        margin: 4px 6px;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {p.BORDER_STRONG};
        border-radius: 5px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {p.TEXT_MUTED};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
    }}
    QScrollBar::handle:horizontal {{
        background: {p.BORDER_STRONG};
        border-radius: 5px;
        min-width: 24px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    QSlider::groove:horizontal {{
        height: 4px;
        background: {p.BORDER_STRONG};
        border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: {p.ACCENT};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        width: 13px;
        height: 13px;
        background: {p.TEXT_PRIMARY};
        border-radius: 6px;
        margin: -5px 0;
    }}

    QCheckBox {{
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {p.BORDER_STRONG};
        border-radius: {p.RADIUS_SM}px;
        background: {p.BG_INPUT};
    }}
    QCheckBox::indicator:checked {{
        background: {p.ACCENT};
        border-color: {p.ACCENT};
    }}

    QStatusBar {{
        background: {p.BG_PANEL};
        color: {p.TEXT_SECONDARY};
        border-top: 1px solid {p.BORDER};
    }}

    QSplitter::handle {{
        background: {p.BORDER};
    }}
    QSplitter::handle:hover {{
        background: {p.ACCENT_MUTED};
    }}

    QMenuBar {{
        background: {p.BG_PANEL};
        color: {p.TEXT_PRIMARY};
        border-bottom: 1px solid {p.BORDER};
    }}
    QMenuBar::item:selected {{
        background: {p.SELECTION};
    }}

    QGroupBox {{
        border: 1px solid {p.BORDER};
        border-radius: {p.RADIUS_MD}px;
        margin-top: 10px;
        padding-top: 12px;
        font-weight: 600;
        color: {p.TEXT_SECONDARY};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
    }}
    """
