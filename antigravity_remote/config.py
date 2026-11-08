import json
import random
import secrets
import socket
from pathlib import Path
from typing import Optional, Dict, Any


def get_local_ip() -> str:
    """Bilgisayarın yerel ağdaki (Wi-Fi / LAN) IPv4 adresini bulur."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
    except Exception:
        pass

    return "127.0.0.1"


def get_default_brain_dir() -> Path:
    """Antigravity konuşma kayıtlarının (brain) tutulduğu varsayılan dizini döndürür."""
    home = Path.home()
    return home / ".gemini" / "antigravity" / "brain"


class AppConfig:
    """Uygulama yapılandırmasını yönetir ve kalıcı ayarları kaydeder."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or (Path.home() / ".gemini" / "antigravity_remote_config.json")
        self.host: str = "0.0.0.0"
        self.port: int = 8765
        # HTTPS (mikrofon ve ses tanıma için telefon tarayıcılarında zorunlu)
        self.use_https: bool = True
        self.https_port: int = 8443
        self.https_active: bool = False  # Sunucu SSL ile başarıyla açıldıysa True olur
        self.pin_code: str = f"{random.randint(1000, 9999)}"
        self.require_pin: bool = True
        self.session_token: str = secrets.token_urlsafe(16)
        self.brain_dir: Path = get_default_brain_dir()
        # Pencere ve kalibrasyon ayarları
        self.target_window_keyword: str = "Antigravity"
        self.target_hwnd: Optional[int] = None
        self.chat_input_x: Optional[int] = None
        self.chat_input_y: Optional[int] = None
        self.model_btn_x: Optional[int] = None
        self.model_btn_y: Optional[int] = None
        self.auto_press_enter: bool = True
        self.load()

    def load(self) -> None:
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                self.port = int(data.get("port", self.port))
                self.use_https = bool(data.get("use_https", self.use_https))
                self.https_port = int(data.get("https_port", self.https_port))
                self.pin_code = str(data.get("pin_code", self.pin_code))
                self.require_pin = bool(data.get("require_pin", self.require_pin))
                self.target_window_keyword = str(data.get("target_window_keyword", self.target_window_keyword))
                self.chat_input_x = data.get("chat_input_x", None)
                self.chat_input_y = data.get("chat_input_y", None)
                self.model_btn_x = data.get("model_btn_x", None)
                self.model_btn_y = data.get("model_btn_y", None)
                self.auto_press_enter = bool(data.get("auto_press_enter", True))
                if data.get("brain_dir"):
                    self.brain_dir = Path(data["brain_dir"])
            except Exception:
                pass

    def save(self) -> None:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            data: Dict[str, Any] = {
                "port": self.port,
                "use_https": self.use_https,
                "https_port": self.https_port,
                "pin_code": self.pin_code,
                "require_pin": self.require_pin,
                "target_window_keyword": self.target_window_keyword,
                "chat_input_x": self.chat_input_x,
                "chat_input_y": self.chat_input_y,
                "model_btn_x": self.model_btn_x,
                "model_btn_y": self.model_btn_y,
                "auto_press_enter": self.auto_press_enter,
                "brain_dir": str(self.brain_dir),
            }
            self.config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def prepare_https(self):
        """HTTPS açıksa kendinden imzalı sertifikayı hazırlar ve SSL context döndürür (idempotent)."""
        if not self.use_https:
            self.https_active = False
            return None
        cached = getattr(self, "_ssl_context", None)
        if cached is not None:
            return cached
        try:
            from .certs import build_ssl_context
            ctx = build_ssl_context(self.local_ip)
        except Exception:
            ctx = None
        self._ssl_context = ctx
        self.https_active = ctx is not None
        return ctx

    def regenerate_pin(self) -> str:
        self.pin_code = f"{random.randint(1000, 9999)}"
        self.session_token = secrets.token_urlsafe(16)
        self.save()
        return self.pin_code

    @property
    def local_ip(self) -> str:
        return get_local_ip()

    @property
    def http_url(self) -> str:
        return f"http://{self.local_ip}:{self.port}"

    @property
    def base_url(self) -> str:
        if self.use_https and self.https_active:
            return f"https://{self.local_ip}:{self.https_port}"
        return self.http_url

    @property
    def qr_url(self) -> str:
        return f"{self.base_url}/?token={self.session_token}"
