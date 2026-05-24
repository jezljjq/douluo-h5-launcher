from __future__ import annotations


APP_QSS = """
QMainWindow {
    background: #f3f7fc;
}

QScrollArea#MainScrollArea {
    background: #f3f7fc;
    border: 0;
}

QWidget {
    color: #172033;
    font-family: "Microsoft YaHei UI", "Segoe UI", Arial;
    font-size: 12px;
}

QFrame#Card {
    background: #ffffff;
    border: 1px solid #d9e4f1;
    border-radius: 8px;
}

QFrame#CardBody {
    background: transparent;
    border: 0;
}

QLabel {
    color: #334155;
}

QLabel#SectionTitle {
    color: #0867d9;
    font-size: 14px;
    font-weight: 700;
    padding-left: 2px;
    min-height: 20px;
    max-height: 20px;
}

QLabel#HelpText {
    color: #64748b;
    font-size: 11px;
    line-height: 18px;
}

QLabel#ModeStatus {
    color: #0969da;
    font-weight: 700;
    padding-top: 4px;
}

QLineEdit,
QComboBox,
QSpinBox {
    min-height: 30px;
    max-height: 30px;
    padding: 1px 7px;
    border: 1px solid #cbd9e8;
    border-radius: 6px;
    background: #ffffff;
    selection-background-color: #bfdbfe;
}

QLineEdit:hover,
QComboBox:hover,
QSpinBox:hover {
    border-color: #9eb7d4;
}

QLineEdit:focus,
QComboBox:focus,
QSpinBox:focus {
    border: 1px solid #1677ff;
}

QLineEdit:read-only {
    background: #f8fafc;
    color: #334155;
}

QComboBox::drop-down,
QSpinBox::up-button,
QSpinBox::down-button {
    border: 0;
    width: 22px;
}

QCheckBox,
QRadioButton {
    color: #1f2937;
    min-height: 26px;
    spacing: 8px;
}

QCheckBox::indicator,
QRadioButton::indicator {
    width: 16px;
    height: 16px;
}

QPushButton {
    min-height: 32px;
    max-height: 32px;
    min-width: 96px;
    padding: 3px 12px;
    border: 1px solid #b8d1f4;
    border-radius: 6px;
    background: #ffffff;
    color: #075ac9;
    font-weight: 700;
}

QPushButton:hover {
    background: #f4f8ff;
    border-color: #6aa5f5;
}

QPushButton:pressed {
    background: #e4efff;
}

QPushButton[role="primary"] {
    background: #0969da;
    border-color: #075cc0;
    color: #ffffff;
}

QPushButton[role="primary"]:hover {
    background: #075cc0;
    border-color: #064ea5;
}

QPushButton[role="primary"]:pressed {
    background: #064ea5;
}

QPushButton[role="danger"],
QPushButton#stopButton {
    background: #ef3434;
    border-color: #d52020;
    color: #ffffff;
}

QPushButton[role="danger"]:hover,
QPushButton#stopButton:hover {
    background: #d52020;
    border-color: #b91c1c;
}

QPushButton[role="danger"]:pressed,
QPushButton#stopButton:pressed {
    background: #b91c1c;
}

QTableWidget#AccountTable {
    background: #ffffff;
    alternate-background-color: #f7fbff;
    gridline-color: #e2e8f0;
    border: 1px solid #d8e0ea;
    border-radius: 6px;
    selection-background-color: #dbeafe;
    selection-color: #0f172a;
    font-size: 12px;
}

QTableWidget#AccountTable::item {
    padding: 4px 8px;
    border-bottom: 1px solid #edf2f7;
}

QTableWidget#AccountTable::item:selected {
    background: #dbeafe;
    color: #0f172a;
}

QHeaderView::section {
    background: #eaf3ff;
    color: #0f172a;
    font-weight: 700;
    min-height: 32px;
    padding: 5px 8px;
    border: 0;
    border-right: 1px solid #d8e0ea;
    border-bottom: 1px solid #d8e0ea;
}

QPlainTextEdit#LogBox {
    background: #071f3d;
    color: #e8f3ff;
    border: 1px solid #103d6f;
    border-radius: 6px;
    padding: 8px;
    font-family: Consolas, "Microsoft YaHei UI", monospace;
    font-size: 12px;
    line-height: 18px;
}

QStatusBar {
    background: #f8fbff;
    border-top: 1px solid #d8e0ea;
    color: #16407c;
    font-weight: 600;
    padding-left: 8px;
}

QStatusBar QLabel {
    padding: 0 8px;
}

QLabel#StatusReady {
    color: #24a33a;
    font-weight: 700;
}

QLabel#StatusText {
    color: #1f2937;
    font-weight: 600;
}
"""
