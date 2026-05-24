from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .qt_styles import APP_QSS
from .version import APP_VERSION


class PySideLauncherWindow(QMainWindow):
    """Stage 1 PySide6 shell UI.

    This preview intentionally does not call login, OCR, Dm, Playwright, or
    window-management business logic. It only establishes the target UI shape.
    """

    def __init__(self) -> None:
        super().__init__()
        app = QApplication.instance()
        if app is not None and not app.styleSheet():
            app.setStyleSheet(APP_QSS)

        self.setWindowTitle(f"上号器 — PySide6 预览 v{APP_VERSION}")
        self.resize(1600, 980)
        self.setMinimumSize(1400, 860)

        scroll_area = QScrollArea(self)
        scroll_area.setObjectName("MainScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(10)

        config_mode_row = QHBoxLayout()
        config_mode_row.setSpacing(10)
        config_mode_row.addWidget(self._create_config_card(), stretch=65)
        config_mode_row.addWidget(self._create_mode_card(), stretch=35)

        content_layout.addWidget(self._create_window_manager_card())
        content_layout.addLayout(config_mode_row)
        content_layout.addWidget(self._create_run_card())
        content_layout.addWidget(self._create_account_card())
        content_layout.addWidget(self._create_log_card())

        scroll_area.setWidget(content)
        self.setCentralWidget(scroll_area)
        self._setup_status_bar()

    def _create_window_manager_card(self) -> QFrame:
        card, layout = self._card("窗口管理区", QGridLayout)
        card.setMinimumHeight(188)
        card.setMaximumHeight(190)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.setVerticalSpacing(10)
        layout.setContentsMargins(10, 6, 10, 10)
        layout.setColumnStretch(0, 1)

        self.game_path_edit = QLineEdit(r"D:\Games\Douluo\Client\斗罗大陆H5.exe")
        self.launch_count_spin = self._spin_box(1, 99, 31, width=70)
        self.launch_interval_spin = self._spin_box(0, 60000, 100, width=80)
        self.auto_click_start_check = QCheckBox("自动点击启动按钮")
        self.auto_rename_check = QCheckBox("排列后自动编号标题")
        self.auto_rename_check.setChecked(True)
        self.title_template_edit = QLineEdit("斗罗大陆H5-{index}号")
        self.title_template_edit.setFixedWidth(260)
        self.title_template_edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        row1, row1_layout = self._row()
        row1_layout.addWidget(self._label("游戏路径", 74))
        row1_layout.addWidget(self.game_path_edit, 1)
        row1_layout.addWidget(self._secondary_button("选择", 100))
        layout.addWidget(row1, 0, 0)

        row2, row2_layout = self._row()
        row2_layout.addWidget(self._field("打开数量", self.launch_count_spin, 74))
        row2_layout.addWidget(self._field("启动间隔(ms)", self.launch_interval_spin, 100))
        row2_layout.addSpacing(4)
        row2_layout.addWidget(self.auto_click_start_check)
        row2_layout.addSpacing(12)
        row2_layout.addWidget(self.auto_rename_check)
        row2_layout.addSpacing(12)
        row2_layout.addWidget(self._label("标题模板", 74))
        row2_layout.addWidget(self.title_template_edit)
        row2_layout.addWidget(self._secondary_button("重命名", 100))
        row2_layout.addStretch(1)
        layout.addWidget(row2, 1, 0)

        self.tile_mode_combo = QComboBox()
        self.tile_mode_combo.addItems(["固定参数排列", "行数列数排列"])
        self.tile_mode_combo.setFixedWidth(135)
        self.tile_mode_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.window_width_spin = self._spin_box(1, 9999, 320, width=75)
        self.window_height_spin = self._spin_box(1, 9999, 540, width=75)
        self.per_row_spin = self._spin_box(1, 99, 8, width=70)
        self.start_x_spin = self._spin_box(-9999, 9999, 250, width=75)
        self.start_y_spin = self._spin_box(-9999, 9999, 0, width=75)
        self.gap_x_spin = self._spin_box(0, 9999, 320, width=75)
        self.gap_y_spin = self._spin_box(0, 9999, 525, width=75)

        row3, row3_layout = self._row()
        row3_layout.addWidget(self._field("排列方式", self.tile_mode_combo, 74))
        row3_layout.addWidget(self._field("窗口宽度", self.window_width_spin, 74))
        row3_layout.addWidget(self._field("窗口高度", self.window_height_spin, 74))
        row3_layout.addWidget(self._field("每行数量", self.per_row_spin, 74))
        row3_layout.addWidget(self._field("起点X", self.start_x_spin, 58))
        row3_layout.addWidget(self._field("起点Y", self.start_y_spin, 58))
        row3_layout.addWidget(self._field("横向间距", self.gap_x_spin, 74))
        row3_layout.addWidget(self._field("纵向间距", self.gap_y_spin, 74))
        row3_layout.addStretch(1)
        layout.addWidget(row3, 2, 0)

        row4, row4_layout = self._row()
        row4_layout.addWidget(self._primary_button("批量启动窗口", 115))
        row4_layout.addWidget(self._secondary_button("识别窗口", 105))
        row4_layout.addWidget(self._secondary_button("排列窗口", 105))
        row4_layout.addWidget(self._danger_button("关闭窗口", 115))
        row4_layout.addStretch(1)
        layout.addWidget(row4, 3, 0)
        for row in range(4):
            layout.setRowMinimumHeight(row, 36)
        return card

    def _create_config_card(self) -> QFrame:
        card, layout = self._card("配置区", QGridLayout)
        card.setMinimumHeight(145)
        card.setMaximumHeight(150)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(6)
        layout.setContentsMargins(10, 6, 10, 10)
        layout.setColumnStretch(1, 1)

        self.bookmark_path_edit = QLineEdit(r"D:\Tools\Favorites")
        self.bookmark_root_edit = QLineEdit("账号")
        self.bookmark_root_edit.setFixedWidth(260)
        self.bookmark_root_edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.settings_path_edit = QLineEdit("automation_settings.json")
        self.csv_path_edit = QLineEdit(r"D:\Tools\accounts.csv")

        layout.addWidget(self._label("收藏夹路径", 90), 0, 0)
        layout.addWidget(self.bookmark_path_edit, 0, 1)
        layout.addWidget(self._secondary_button("选择", 100), 0, 2)
        layout.addWidget(self._label("根目录名", 90), 1, 0)
        layout.addWidget(self.bookmark_root_edit, 1, 1)
        layout.addWidget(self._secondary_button("选择", 100), 1, 2)
        layout.addWidget(self._label("自动化设置", 90), 2, 0)
        layout.addWidget(self.settings_path_edit, 2, 1)
        layout.addWidget(self._secondary_button("选择", 100), 2, 2)
        layout.addWidget(self._label("CSV 文件路径", 90), 3, 0)
        layout.addWidget(self.csv_path_edit, 3, 1)
        layout.addWidget(self._secondary_button("选择", 100), 3, 2)
        return card

    def _create_mode_card(self) -> QFrame:
        card, layout = self._card("上号方式区", QVBoxLayout)
        card.setMinimumHeight(145)
        card.setMaximumHeight(150)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.setContentsMargins(10, 6, 10, 10)
        layout.setSpacing(4)

        self.method_one_radio = QRadioButton("方式一：通行证上号")
        self.method_two_radio = QRadioButton("方式二：账号密码 + 通行证上号")
        self.method_one_radio.setChecked(True)
        layout.addWidget(self.method_one_radio)
        layout.addWidget(self._help_label("使用通行证链接完成登录（推荐）"))
        layout.addSpacing(4)
        layout.addWidget(self.method_two_radio)
        layout.addWidget(self._help_label("先使用账号密码登录，再使用通行证进入"))
        mode_status = self._help_label("源码模式开发中")
        mode_status.setObjectName("ModeStatus")
        layout.addWidget(mode_status)
        layout.addStretch(1)
        return card

    def _create_run_card(self) -> QFrame:
        card, layout = self._card("运行控制区", QGridLayout)
        card.setMinimumHeight(96)
        card.setMaximumHeight(105)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(6)
        layout.setContentsMargins(10, 6, 10, 10)
        layout.setColumnStretch(10, 1)

        self.level_combo = QComboBox()
        self.level_combo.addItems(["第一层", "第二层", "第三层", "第四层", "单层账号"])
        self.level_combo.setFixedWidth(130)
        self.level_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.account_combo = QComboBox()
        self.account_combo.addItems(["第一层-1 → 窗口1"])
        self.account_combo.setFixedWidth(230)
        self.account_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.mode_value = QLineEdit("前台串行")
        self.mode_value.setReadOnly(True)
        self.mode_value.setFixedWidth(130)
        self.mode_value.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.concurrency_value = QLineEdit("1")
        self.concurrency_value.setReadOnly(True)
        self.concurrency_value.setFixedWidth(70)
        self.concurrency_value.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.retry_spin = self._spin_box(1, 9, 3, width=70)

        layout.addWidget(self._label("层级", 50), 0, 0)
        layout.addWidget(self.level_combo, 0, 1)
        layout.addWidget(self._label("单个账号", 70), 0, 2)
        layout.addWidget(self.account_combo, 0, 3)
        layout.addWidget(self._label("模式", 50), 0, 4)
        layout.addWidget(self.mode_value, 0, 5)
        layout.addWidget(self._label("并发", 50), 0, 6)
        layout.addWidget(self.concurrency_value, 0, 7)
        layout.addWidget(self._label("重试次数", 70), 0, 8)
        layout.addWidget(self.retry_spin, 0, 9)

        layout.addWidget(self._primary_button("单账号运行", 115), 1, 0, 1, 2)
        layout.addWidget(self._primary_button("当前层串行", 115), 1, 2, 1, 2)
        layout.addWidget(self._primary_button("全部串行", 115), 1, 4, 1, 2)
        stop_button = self._danger_button("停止任务", 115)
        stop_button.setObjectName("stopButton")
        layout.addWidget(stop_button, 1, 6, 1, 2)
        layout.setRowMinimumHeight(0, 36)
        layout.setRowMinimumHeight(1, 36)
        return card

    def _create_account_card(self) -> QFrame:
        card, layout = self._card("账号列表区", QVBoxLayout)
        card.setMinimumHeight(230)
        card.setMaximumHeight(240)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.setContentsMargins(10, 6, 10, 10)

        self.account_table = QTableWidget(0, 8)
        self.account_table.setObjectName("AccountTable")
        self.account_table.setMinimumHeight(210)
        self.account_table.setHorizontalHeaderLabels(["序号", "层级", "收藏编号", "窗口号", "用户名", "通行证", "链接", "状态"])
        self.account_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.account_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.account_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.account_table.verticalHeader().setVisible(False)
        self.account_table.verticalHeader().setDefaultSectionSize(28)
        self.account_table.horizontalHeader().setDefaultSectionSize(90)
        self.account_table.horizontalHeader().setMinimumSectionSize(40)
        self.account_table.horizontalHeader().setFixedHeight(32)
        self.account_table.setAlternatingRowColors(True)
        self._fill_sample_accounts()
        layout.addWidget(self.account_table)
        return card

    def _create_log_card(self) -> QFrame:
        card, layout = self._card("日志区", QVBoxLayout)
        card.setMinimumHeight(150)
        card.setMaximumHeight(160)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.setContentsMargins(10, 6, 10, 10)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(QLabel("前端简洁日志"))
        header.addStretch(1)
        header.addWidget(self._secondary_button("打开日志目录", 130))
        layout.addLayout(header)

        self.log_text = QPlainTextEdit()
        self.log_text.setObjectName("LogBox")
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(92)
        self.log_text.setPlainText(
            "[10:35:21] [信息] PySide6 阶段1空壳界面已启动。\n"
            "[10:35:22] [信息] 当前不接上号流程，不调用业务逻辑。\n"
            "[10:35:23] [信息] 使用 QFrame 卡片、QGridLayout 与 QSS 还原目标结构。\n"
            "[10:35:24] [警告] 排列窗口参数已修改，请重新排列生效。"
        )
        layout.addWidget(self.log_text)
        return card

    def _setup_status_bar(self) -> None:
        status = QStatusBar(self)
        status.setFixedHeight(28)
        ready_label = QLabel("● 就绪")
        ready_label.setObjectName("StatusReady")
        mode_label = QLabel("当前模式：方式一")
        mode_label.setObjectName("StatusText")
        concurrency_label = QLabel("并发=1")
        concurrency_label.setObjectName("StatusText")
        status.addWidget(ready_label)
        status.addWidget(QLabel(" | "))
        status.addWidget(mode_label)
        status.addWidget(QLabel(" | "))
        status.addWidget(concurrency_label)
        status.addPermanentWidget(QLabel("任务完成时将在此显示状态"))
        self.setStatusBar(status)

    def _fill_sample_accounts(self) -> None:
        rows = [
            ("1", "第一层", "1", "1", "user_0001", "通行证_0001", "https://example.com/passport?token=PLs8D7K9mNwZrYx1", "运行中"),
            ("2", "第一层", "2", "2", "user_0002", "通行证_0002", "https://example.com/passport?token=QwE2R4T9bJkLmP2", "成功"),
            ("3", "第一层", "3", "3", "user_0003", "通行证_0003", "https://example.com/passport?token=RTy6G3P8uLmNeW4", "已登录跳过"),
            ("4", "第一层", "4", "4", "user_0004", "通行证_0004", "https://example.com/passport?token=GFh9Y6V2dJsQfR7", "未开始"),
            ("5", "第一层", "5", "5", "user_0005", "通行证_0005", "https://example.com/passport?token=ZgH3dP9LmNwQ12", "失败"),
            ("6", "第一层", "6", "6", "user_0006", "通行证_0006", "https://example.com/passport?token=YtR4Vb6KpLmNsD8", "未开始"),
        ]
        self.account_table.setColumnCount(8)
        self.account_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for col_index, value in enumerate(row):
                item = QTableWidgetItem(value)
                if col_index in (0, 2, 3, 5, 7):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col_index == 7:
                    status_text = value
                    color = {
                        "成功": "#52c41a",
                        "运行中": "#1890ff",
                        "未开始": "#8c8c8c",
                        "失败": "#ff4d4f",
                        "已登录跳过": "#fa8c16",
                    }.get(status_text, "#8c8c8c")
                    item.setText(f"●  {status_text}")
                    item.setForeground(QBrush(QColor(color)))
                self.account_table.setItem(row_index, col_index, item)
        self.account_table.setColumnWidth(0, 46)
        self.account_table.setColumnWidth(1, 90)
        self.account_table.setColumnWidth(2, 90)
        self.account_table.setColumnWidth(3, 70)
        self.account_table.setColumnWidth(4, 110)
        self.account_table.setColumnWidth(5, 120)
        self.account_table.setColumnWidth(7, 130)
        self.account_table.horizontalHeader().setStretchLastSection(False)
        self.account_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.account_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.account_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.account_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.account_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.account_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.account_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.account_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)

    def _card(self, title: str, layout_class: type[QGridLayout] | type[QVBoxLayout]) -> tuple[QFrame, QGridLayout | QVBoxLayout]:
        card = QFrame()
        card.setObjectName("Card")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        title_label.setContentsMargins(10, 7, 10, 0)
        outer.addWidget(title_label)

        body = QFrame()
        body.setObjectName("CardBody")
        body_layout = layout_class(body)
        body_layout.setContentsMargins(10, 6, 10, 10)
        if isinstance(body_layout, QGridLayout):
            body_layout.setHorizontalSpacing(10)
            body_layout.setVerticalSpacing(10)
        else:
            body_layout.setSpacing(8)
        outer.addWidget(body, 1)
        return card, body_layout

    @staticmethod
    def _row(spacing: int = 10) -> tuple[QWidget, QHBoxLayout]:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(spacing)
        return row, row_layout

    def _field(self, text: str, widget: QWidget, label_width: int = 72) -> QWidget:
        field, layout = self._row(6)
        layout.addWidget(self._label(text, label_width))
        layout.addWidget(widget)
        return field

    @staticmethod
    def _help_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("HelpText")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _label(text: str, width: int | None = 72) -> QLabel:
        label = QLabel(text)
        if width is not None:
            label.setFixedWidth(width)
        return label

    @staticmethod
    def _primary_button(text: str, width: int | None = None) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("role", "primary")
        button.setMinimumHeight(32)
        button.setMaximumHeight(32)
        if width is not None:
            button.setFixedWidth(width)
        else:
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return button

    @staticmethod
    def _secondary_button(text: str, width: int | None = None) -> QPushButton:
        button = QPushButton(text)
        button.setMinimumHeight(32)
        button.setMaximumHeight(32)
        if width is not None:
            button.setFixedWidth(width)
        else:
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return button

    @staticmethod
    def _danger_button(text: str, width: int | None = None) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("role", "danger")
        button.setMinimumHeight(32)
        button.setMaximumHeight(32)
        if width is not None:
            button.setFixedWidth(width)
        else:
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return button

    @staticmethod
    def _spin_box(minimum: int, maximum: int, value: int, width: int = 90) -> QSpinBox:
        spin_box = QSpinBox()
        spin_box.setRange(minimum, maximum)
        spin_box.setValue(value)
        spin_box.setMinimumHeight(30)
        spin_box.setMaximumHeight(30)
        spin_box.setFixedWidth(width)
        spin_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return spin_box


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    smoke_test = "--smoke-test" in args
    app = QApplication(args)
    app.setStyleSheet(APP_QSS)
    window = PySideLauncherWindow()
    window.show()
    if smoke_test:
        QTimer.singleShot(500, app.quit)
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
