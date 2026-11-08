import asyncio
import io
import sys
import threading
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap, QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QCheckBox,
    QTextEdit,
    QFrame,
)
import qrcode

from .config import AppConfig
from .server import RemoteServer


class LogBridge(QObject):
    log_signal = pyqtSignal(str)


class ServerThread(threading.Thread):
    """aiohttp sunucusunu PyQt6 arayüzünü dondurmadan arka planda çalıştırır."""

    def __init__(self, config: AppConfig, log_callback):
        super().__init__(daemon=True)
        self.config = config
        self.config.prepare_https()
        self.log_callback = log_callback
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.server: Optional[RemoteServer] = None

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.server = RemoteServer(self.config, on_log=self.log_callback)
        self.loop.run_until_complete(self.server.start())
        try:
            self.loop.run_forever()
        finally:
            self.loop.run_until_complete(self.server.stop())
            self.loop.close()


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.log_bridge = LogBridge()
        self.log_bridge.log_signal.connect(self.append_log)

        self.server_thread = ServerThread(self.config, self.log_bridge.log_signal.emit)
        self.server_thread.start()

        self.calibration_countdown = 0
        self.calibration_mode = "chat"  # "chat" veya "model"
        self.calibration_timer = QTimer(self)
        self.calibration_timer.timeout.connect(self._on_calibration_tick)

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start(2000)

        self.init_ui()
        self.refresh_qr()
        self.refresh_windows()

    def init_ui(self) -> None:
        self.setWindowTitle("Antigravity Remote — Kontrol Merkezi")
        self.setMinimumSize(860, 560)
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #000000;
                color: #ffffff;
                font-family: 'Segoe UI', sans-serif;
            }
            QFrame.Card {
                background-color: #0a0a0a;
                border: 1px solid #262626;
                border-radius: 12px;
            }
            QPushButton {
                background-color: #ffffff;
                color: #000000;
                border: 1px solid #ffffff;
                border-radius: 7px;
                padding: 8px 13px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #e5e5e5;
            }
            QPushButton.Secondary {
                background-color: #121212;
                color: #ffffff;
                border: 1px solid #333333;
            }
            QPushButton.Secondary:hover {
                background-color: #1f1f1f;
            }
            QComboBox {
                background-color: #121212;
                border: 1px solid #333333;
                border-radius: 7px;
                padding: 7px 10px;
                color: #ffffff;
            }
            QTextEdit {
                background-color: #050505;
                border: 1px solid #262626;
                border-radius: 7px;
                color: #d4d4d4;
                font-family: Consolas, monospace;
                font-size: 12px;
                padding: 8px;
            }
            QCheckBox {
                color: #d4d4d4;
                font-size: 12px;
            }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(18)

        # SOL PANEL: Siyah-Beyaz QR Kod ve IP Bağlantı Bilgileri
        left_card = QFrame()
        left_card.setProperty("class", "Card")
        left_card.setFixedWidth(310)
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(12)

        title_lbl = QLabel("TELEFONDAN BAĞLAN")
        title_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(title_lbl)

        sub_lbl = QLabel("Aynı Wi-Fi ağındaki telefonunuzdan\nQR kodu okutun veya IP adresine girin:")
        sub_lbl.setStyleSheet("color: #737373; font-size: 12px;")
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(sub_lbl)

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setFixedSize(210, 210)
        self.qr_label.setStyleSheet("background: #ffffff; border-radius: 10px; padding: 8px;")
        qr_wrap = QHBoxLayout()
        qr_wrap.addStretch()
        qr_wrap.addWidget(self.qr_label)
        qr_wrap.addStretch()
        left_layout.addLayout(qr_wrap)

        ip_title = QLabel("BAĞLANTI ADRESİ (IP)")
        ip_title.setStyleSheet("color: #737373; font-size: 11px; font-weight: bold;")
        ip_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(ip_title)

        self.ip_label = QLabel(self.config.base_url)
        self.ip_label.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        self.ip_label.setStyleSheet(
            "color: #ffffff; background: #141414; border: 1px solid #262626; padding: 8px; border-radius: 7px;"
        )
        self.ip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ip_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        left_layout.addWidget(self.ip_label)

        copy_btn = QPushButton("Adresi Kopyala")
        copy_btn.setProperty("class", "Secondary")
        copy_btn.clicked.connect(self.copy_url)
        left_layout.addWidget(copy_btn)

        pin_row = QHBoxLayout()
        self.pin_label = QLabel(f"PIN: {self.config.pin_code}")
        self.pin_label.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        self.pin_label.setStyleSheet("color: #ffffff;")
        pin_row.addWidget(self.pin_label)

        regen_btn = QPushButton("Yeni PIN")
        regen_btn.setProperty("class", "Secondary")
        regen_btn.clicked.connect(self.regenerate_pin)
        pin_row.addWidget(regen_btn)
        left_layout.addLayout(pin_row)

        self.pin_checkbox = QCheckBox("PIN Koruması Aktif")
        self.pin_checkbox.setChecked(self.config.require_pin)
        self.pin_checkbox.stateChanged.connect(self.toggle_pin)
        left_layout.addWidget(self.pin_checkbox)

        left_layout.addStretch()
        main_layout.addWidget(left_card)

        # SAĞ PANEL: Pencere Köprüsü, Model/Mesaj Hedefleme ve Loglar
        right_card = QFrame()
        right_card.setProperty("class", "Card")
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(20, 20, 20, 20)
        right_layout.setSpacing(12)

        r_title = QLabel("ANTIGRAVITY PENCERE & MODEL KÖPRÜSÜ")
        r_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        right_layout.addWidget(r_title)

        win_row = QHBoxLayout()
        self.window_combo = QComboBox()
        self.window_combo.currentIndexChanged.connect(self.on_window_selected)
        win_row.addWidget(self.window_combo, 1)

        refresh_win_btn = QPushButton("Pencereleri Yenile")
        refresh_win_btn.setProperty("class", "Secondary")
        refresh_win_btn.clicked.connect(self.refresh_windows)
        win_row.addWidget(refresh_win_btn)
        right_layout.addLayout(win_row)

        # 1. Mesaj Kutusu Hedefleme Satırı
        calib_row = QHBoxLayout()
        self.calib_label = QLabel()
        calib_row.addWidget(self.calib_label, 1)

        self.calib_btn = QPushButton("Mesaj Kutusunu Hedefle (3 sn)")
        self.calib_btn.clicked.connect(lambda: self.start_calibration("chat"))
        calib_row.addWidget(self.calib_btn)
        right_layout.addLayout(calib_row)

        # 2. Model Seçici Hedefleme Satırı
        model_calib_row = QHBoxLayout()
        self.model_calib_label = QLabel()
        model_calib_row.addWidget(self.model_calib_label, 1)

        self.model_calib_btn = QPushButton("Model Seçiciyi Hedefle (3 sn)")
        self.model_calib_btn.setProperty("class", "Secondary")
        self.model_calib_btn.clicked.connect(lambda: self.start_calibration("model"))
        model_calib_row.addWidget(self.model_calib_btn)

        clear_calib_btn = QPushButton("Konumları Sıfırla")
        clear_calib_btn.setProperty("class", "Secondary")
        clear_calib_btn.clicked.connect(self.clear_calibration)
        model_calib_row.addWidget(clear_calib_btn)
        right_layout.addLayout(model_calib_row)

        self.update_calib_labels()

        self.enter_checkbox = QCheckBox("Telefondan mesaj/görsel gönderildiğinde otomatik Enter tuşuna bas")
        self.enter_checkbox.setChecked(self.config.auto_press_enter)
        self.enter_checkbox.stateChanged.connect(self.toggle_auto_enter)
        right_layout.addWidget(self.enter_checkbox)

        self.clients_label = QLabel("● Sunucu Aktif • Bağlı Telefon: 0")
        self.clients_label.setStyleSheet("color: #ffffff; font-weight: 600; font-size: 12px;")
        right_layout.addWidget(self.clients_label)

        log_title = QLabel("CANLI GÜNLÜK")
        log_title.setStyleSheet("color: #737373; font-size: 11px; font-weight: bold;")
        right_layout.addWidget(log_title)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        right_layout.addWidget(self.log_box, 1)

        main_layout.addWidget(right_card, 1)

    def refresh_qr(self) -> None:
        url = self.config.qr_url if self.config.require_pin else self.config.base_url
        qr = qrcode.QRCode(version=1, box_size=6, border=1)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#000000", back_color="#ffffff")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        pixmap = QPixmap()
        pixmap.loadFromData(buf.getvalue())
        self.qr_label.setPixmap(
            pixmap.scaled(194, 194, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )

    def copy_url(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(self.config.base_url)
            self.append_log(f"Adres kopyalandı: {self.config.base_url}")

    def regenerate_pin(self) -> None:
        new_pin = self.config.regenerate_pin()
        self.pin_label.setText(f"PIN: {new_pin}")
        self.refresh_qr()
        self.append_log(f"Yeni PIN oluşturuldu: {new_pin}")

    def toggle_pin(self) -> None:
        self.config.require_pin = self.pin_checkbox.isChecked()
        self.config.save()
        self.refresh_qr()

    def toggle_auto_enter(self) -> None:
        self.config.auto_press_enter = self.enter_checkbox.isChecked()
        self.config.save()

    def refresh_windows(self) -> None:
        if not self.server_thread.server:
            return
        windows = self.server_thread.server.bridge.list_candidate_windows()
        self.window_combo.blockSignals(True)
        self.window_combo.clear()
        self.window_combo.addItem("Otomatik Algıla (Antigravity)", None)
        for w in windows:
            prefix = "● " if w["is_match"] else "○ "
            self.window_combo.addItem(f"{prefix}{w['title'][:65]}", w["hwnd"])
        self.window_combo.blockSignals(False)

    def on_window_selected(self, idx: int) -> None:
        hwnd = self.window_combo.itemData(idx)
        self.config.target_hwnd = hwnd

    def update_calib_labels(self) -> None:
        if self.config.chat_input_x is not None and self.config.chat_input_y is not None:
            self.calib_label.setText(
                f"● Mesaj Kutusu: ({self.config.chat_input_x}, {self.config.chat_input_y})"
            )
            self.calib_label.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 600;")
        else:
            self.calib_label.setText("○ Mesaj Kutusu: Otomatik Pencere Odağı")
            self.calib_label.setStyleSheet("color: #737373; font-size: 12px;")

        if self.config.model_btn_x is not None and self.config.model_btn_y is not None:
            self.model_calib_label.setText(
                f"● Model Seçici: ({self.config.model_btn_x}, {self.config.model_btn_y})"
            )
            self.model_calib_label.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 600;")
        else:
            self.model_calib_label.setText("○ Model Seçici: Hedeflenmedi")
            self.model_calib_label.setStyleSheet("color: #737373; font-size: 12px;")

    def start_calibration(self, mode: str) -> None:
        self.calibration_mode = mode
        self.calibration_countdown = 3
        self.calib_btn.setEnabled(False)
        self.model_calib_btn.setEnabled(False)
        if mode == "chat":
            self.calib_btn.setText("Fareyi Mesaj Kutusuna Götürün (3)...")
        else:
            self.model_calib_btn.setText("Fareyi Model Seçiciye Götürün (3)...")
        self.calibration_timer.start(1000)

    def _on_calibration_tick(self) -> None:
        self.calibration_countdown -= 1
        if self.calibration_countdown > 0:
            if self.calibration_mode == "chat":
                self.calib_btn.setText(f"Fareyi Mesaj Kutusuna Götürün ({self.calibration_countdown})...")
            else:
                self.model_calib_btn.setText(f"Fareyi Model Seçiciye Götürün ({self.calibration_countdown})...")
        else:
            self.calibration_timer.stop()
            if self.server_thread.server:
                x, y = self.server_thread.server.bridge.get_cursor_pos()
                if self.calibration_mode == "chat":
                    self.config.chat_input_x = x
                    self.config.chat_input_y = y
                    self.append_log(f"Mesaj kutusu konumu kaydedildi: ({x}, {y})")
                else:
                    self.config.model_btn_x = x
                    self.config.model_btn_y = y
                    self.append_log(f"Model seçici konumu kaydedildi: ({x}, {y})")
                self.config.save()
                self.update_calib_labels()
            self.calib_btn.setText("Mesaj Kutusunu Hedefle (3 sn)")
            self.model_calib_btn.setText("Model Seçiciyi Hedefle (3 sn)")
            self.calib_btn.setEnabled(True)
            self.model_calib_btn.setEnabled(True)

    def clear_calibration(self) -> None:
        self.config.chat_input_x = None
        self.config.chat_input_y = None
        self.config.model_btn_x = None
        self.config.model_btn_y = None
        self.config.save()
        self.update_calib_labels()
        self.append_log("Tüm hedef koordinatları sıfırlandı.")

    def refresh_status(self) -> None:
        if self.server_thread.server:
            count = len(self.server_thread.server.ws_clients)
            self.clients_label.setText(f"● Sunucu Aktif ({self.config.base_url}) • Bağlı Telefon: {count}")

    def append_log(self, text: str) -> None:
        self.log_box.append(text)


def run_gui(config: Optional[AppConfig] = None) -> None:
    cfg = config or AppConfig()
    app = QApplication(sys.argv)
    win = MainWindow(cfg)
    win.show()
    sys.exit(app.exec())
