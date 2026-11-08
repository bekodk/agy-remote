import asyncio
import base64
import io
import json
import mimetypes
import os
import socket
import time
from pathlib import Path
from typing import Set, Optional, Callable, Dict, Any, List
from urllib.parse import unquote

from aiohttp import web, WSMsgType
import qrcode

from .config import AppConfig
from .transcript_watcher import TranscriptManager
from .window_bridge import WindowBridge


STATIC_DIR = Path(__file__).parent / "static"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico"}
IGNORED_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv"}

AVAILABLE_MODELS = [
    {"id": "Gemini 4 Pro (High)", "name": "Gemini 4 Pro (High)", "desc": "Derin düşünme ve ileri seviye kodlama"},
    {"id": "Gemini 3.8 Flash (High)", "name": "Gemini 3.8 Flash (High)", "desc": "Hızlı ve yüksek doğruluklu ajan modu"},
    {"id": "Gemini 3.8 Flash (Medium)", "name": "Gemini 3.8 Flash (Medium)", "desc": "Dengeli hız ve bağlam performansı"},
    {"id": "Gemini 3.8 Flash (Low)", "name": "Gemini 3.8 Flash (Low)", "desc": "Anlık ve düşük gecikmeli yanıtlar"},
    {"id": "Claude Opus 5.5 (Medium)", "name": "Claude Opus 5.5 (Medium)", "desc": "Alternatif kapsamlı analiz modeli"},
]


@web.middleware
async def no_cache_middleware(request: web.Request, handler):
    response = await handler(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


class RemoteServer:
    """
    Telefondan gelen HTTP ve WebSocket bağlantılarını yöneten;
    konuşmaları, çoktan seçmeli soruları (ask_question), çalıştırılan komutları,
    proje dosyası görüntüleme/düzenlemeyi, çoklu görsel gönderimini,
    doğrudan model seçimini ve token limitlerini sunan sunucu.
    """

    def __init__(self, config: AppConfig, on_log: Optional[Callable[[str], None]] = None):
        self.config = config
        self.project_root = Path.cwd()
        self.transcript_mgr = TranscriptManager(config.brain_dir, default_workspace=self.project_root)
        self.bridge = WindowBridge(config)
        self.on_log = on_log
        self.ws_clients: Set[web.WebSocketResponse] = set()
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self._watch_task: Optional[asyncio.Task] = None
        self._running = False
        self.active_conversation_id: Optional[str] = None

    def log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        if self.on_log:
            try:
                self.on_log(formatted)
            except Exception:
                pass

    def _is_authorized(self, request: web.Request) -> bool:
        if not self.config.require_pin:
            return True
        token = request.headers.get("X-Auth-Token") or request.query.get("token")
        pin = request.headers.get("X-Auth-Pin") or request.query.get("pin")
        if token and token == self.config.session_token:
            return True
        if pin and pin == self.config.pin_code:
            return True
        return False

    def create_app(self) -> web.Application:
        app = web.Application(
            client_max_size=50 * 1024 * 1024,
            middlewares=[no_cache_middleware],
        )
        app.router.add_get("/", self.handle_index)
        app.router.add_get("/manifest.json", self.handle_manifest)
        app.router.add_get("/api/qr.png", self.handle_qr)
        app.router.add_post("/api/auth", self.handle_auth)
        app.router.add_get("/api/status", self.handle_status)
        app.router.add_get("/api/usage", self.handle_usage)
        app.router.add_get("/api/files", self.handle_files)
        app.router.add_get("/api/file_content", self.handle_file_content)
        app.router.add_post("/api/save_file", self.handle_save_file)
        app.router.add_get("/api/raw_file", self.handle_raw_file)
        app.router.add_get("/api/conversations", self.handle_conversations)
        app.router.add_get("/api/conversations/{conv_id}", self.handle_conversation_detail)
        app.router.add_get("/api/artifacts/{conv_id}/{filename}", self.handle_artifact)
        app.router.add_post("/api/send", self.handle_send)
        app.router.add_post("/api/send_image", self.handle_send_image)
        app.router.add_post("/api/answer_question", self.handle_answer_question)
        app.router.add_get("/api/tts", self.handle_tts)
        app.router.add_post("/api/tts", self.handle_tts)
        app.router.add_post("/api/model_control", self.handle_model_control)
        app.router.add_post("/api/action", self.handle_action)
        app.router.add_get("/ws", self.handle_ws)
        if STATIC_DIR.exists():
            app.router.add_static("/static", STATIC_DIR, show_index=False)
        return app

    async def handle_index(self, request: web.Request) -> web.Response:
        index_file = STATIC_DIR / "index.html"
        if not index_file.exists():
            return web.Response(text="index.html bulunamadı.", status=404)
        html_text = index_file.read_text(encoding="utf-8", errors="replace")
        return web.Response(text=html_text, content_type="text/html")

    async def handle_manifest(self, request: web.Request) -> web.Response:
        manifest_file = STATIC_DIR / "manifest.json"
        if not manifest_file.exists():
            return web.json_response({})
        return web.FileResponse(manifest_file)

    async def handle_qr(self, request: web.Request) -> web.Response:
        qr_url = self.config.qr_url if self.config.require_pin else self.config.base_url
        qr = qrcode.QRCode(version=1, box_size=8, border=2)
        qr.add_data(qr_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#000000", back_color="#ffffff")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return web.Response(body=buf.getvalue(), content_type="image/png")

    async def handle_auth(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            data = {}

        pin = str(data.get("pin", "")).strip()
        token = str(data.get("token", "")).strip()
        client_ip = request.remote or "Bilinmeyen IP"

        if not self.config.require_pin:
            return web.json_response({
                "ok": True,
                "token": self.config.session_token,
                "require_pin": False,
            })

        if token == self.config.session_token or pin == self.config.pin_code:
            self.log(f"Telefon doğrulandı ({client_ip})")
            return web.json_response({
                "ok": True,
                "token": self.config.session_token,
            })

        self.log(f"Hatalı PIN denemesi ({client_ip})")
        return web.json_response({"ok": False, "error": "Hatalı PIN kodu!"}, status=401)

    async def handle_status(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response({"ok": False, "auth_required": True}, status=401)

        target_win = self.bridge.find_target_window()
        convs = self.transcript_mgr.list_conversations(limit=5)
        latest_conv_id = convs[0]["id"] if convs else None
        if not self.active_conversation_id and latest_conv_id:
            self.active_conversation_id = latest_conv_id

        return web.json_response({
            "ok": True,
            "hostname": socket.gethostname(),
            "local_ip": self.config.local_ip,
            "port": self.config.port,
            "window_found": target_win is not None,
            "window_title": target_win["title"] if target_win else None,
            "calibrated": self.config.chat_input_x is not None and self.config.chat_input_y is not None,
            "model_calibrated": self.config.model_btn_x is not None and self.config.model_btn_y is not None,
            "active_conversation_id": self.active_conversation_id or latest_conv_id,
            "connected_clients": len(self.ws_clients),
            "project_root": str(self.project_root),
        })

    async def handle_usage(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response({"ok": False, "auth_required": True}, status=401)

        conv_id = request.query.get("conv_id") or self.active_conversation_id
        summary = self.transcript_mgr.get_global_usage_summary(conv_id)
        if self.bridge.selected_model_override:
            summary["active"]["active_model"] = self.bridge.selected_model_override
        summary["available_models"] = AVAILABLE_MODELS
        return web.json_response({"ok": True, **summary})

    async def handle_files(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response({"ok": False, "auth_required": True}, status=401)

        req_path = (request.query.get("path") or "").strip()
        if req_path.startswith("file:///"):
            req_path = unquote(req_path[8:]).replace("/", "\\")

        workspaces: List[str] = [str(self.project_root.resolve())]
        if self.active_conversation_id:
            conv_detail = self.transcript_mgr.get_conversation_steps(self.active_conversation_id)
            for w in conv_detail.get("workspaces", []):
                if os.path.isdir(w) and w.lower() not in {x.lower() for x in workspaces}:
                    workspaces.append(str(Path(w).resolve()))

        target_dir = Path(req_path) if req_path else Path(workspaces[0])
        if target_dir.is_file():
            target_dir = target_dir.parent

        if not target_dir.exists() or not target_dir.is_dir():
            target_dir = self.project_root

        entries: List[Dict[str, Any]] = []
        try:
            for item in target_dir.iterdir():
                if item.name in IGNORED_DIRS:
                    continue
                is_dir = item.is_dir()
                try:
                    st = item.stat()
                    size = st.st_size if not is_dir else 0
                    mtime = st.st_mtime
                except Exception:
                    size = 0
                    mtime = 0
                entries.append({
                    "name": item.name,
                    "path": str(item.resolve()),
                    "is_dir": is_dir,
                    "size": size,
                    "ext": item.suffix.lower() if not is_dir else "",
                    "mtime": mtime,
                })
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

        entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        parent_dir = str(target_dir.parent.resolve()) if target_dir.parent != target_dir else None

        return web.json_response({
            "ok": True,
            "current_path": str(target_dir.resolve()),
            "folder_name": target_dir.name or str(target_dir),
            "parent_path": parent_dir,
            "workspaces": workspaces,
            "entries": entries,
        })

    async def handle_file_content(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response({"ok": False, "auth_required": True}, status=401)

        req_path = (request.query.get("path") or "").strip()
        if req_path.startswith("file:///"):
            req_path = unquote(req_path[8:]).replace("/", "\\")
        if "#" in req_path:
            req_path = req_path.split("#", 1)[0]

        if not req_path:
            return web.json_response({"ok": False, "error": "Dosya yolu belirtilmedi."}, status=400)

        target = Path(req_path)
        if not target.exists() or not target.is_file():
            return web.json_response({"ok": False, "error": f"Dosya bulunamadı: {req_path}"}, status=404)

        ext = target.suffix.lower()
        size = target.stat().st_size

        if ext in IMAGE_EXTENSIONS:
            return web.json_response({
                "ok": True,
                "name": target.name,
                "path": str(target.resolve()),
                "size": size,
                "is_image": True,
                "ext": ext,
            })

        try:
            with target.open("r", encoding="utf-8", errors="replace") as f:
                content = f.read(512 * 1024)
            lines_count = content.count("\n") + 1
            return web.json_response({
                "ok": True,
                "name": target.name,
                "path": str(target.resolve()),
                "size": size,
                "is_image": False,
                "ext": ext,
                "lines_count": lines_count,
                "content": content,
            })
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_save_file(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response({"ok": False, "auth_required": True}, status=401)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Geçersiz JSON."}, status=400)

        req_path = str(body.get("path", "")).strip()
        content = str(body.get("content", ""))
        client_ip = request.remote or "Telefon"

        if not req_path:
            return web.json_response({"ok": False, "error": "Dosya yolu boş olamaz."}, status=400)

        try:
            target = Path(req_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            self.log(f"Dosya telefondan kaydedildi ({client_ip}): {target.name}")
            return web.json_response({
                "ok": True,
                "name": target.name,
                "path": str(target.resolve()),
                "size": target.stat().st_size,
            })
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_raw_file(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.Response(status=401, text="Unauthorized")

        req_path = (request.query.get("path") or "").strip()
        if not req_path:
            return web.Response(status=400, text="Missing path")
        target = Path(req_path)
        if not target.exists() or not target.is_file():
            return web.Response(status=404, text="Not found")
        mime, _ = mimetypes.guess_type(str(target))
        return web.FileResponse(target, headers={"Content-Type": mime or "application/octet-stream"})

    async def handle_conversations(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response({"ok": False, "auth_required": True}, status=401)

        convs = self.transcript_mgr.list_conversations(limit=30)
        if convs and not self.active_conversation_id:
            self.active_conversation_id = convs[0]["id"]
        return web.json_response({
            "ok": True,
            "conversations": convs,
            "active_id": self.active_conversation_id,
        })

    async def handle_conversation_detail(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response({"ok": False, "auth_required": True}, status=401)

        conv_id = request.match_info["conv_id"]
        since_step = int(request.query.get("since", "-1"))
        self.active_conversation_id = conv_id
        data = self.transcript_mgr.get_conversation_steps(conv_id, since_step=since_step)
        if self.bridge.selected_model_override:
            data["usage"]["active_model"] = self.bridge.selected_model_override
        return web.json_response({"ok": True, **data})

    async def handle_artifact(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response({"ok": False, "auth_required": True}, status=401)

        conv_id = request.match_info["conv_id"]
        filename = request.match_info["filename"]
        content = self.transcript_mgr.read_artifact(conv_id, filename)
        if content is None:
            return web.json_response({"ok": False, "error": "Artifact bulunamadı."}, status=404)
        return web.json_response({"ok": True, "name": filename, "content": content})

    async def handle_send(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response({"ok": False, "auth_required": True}, status=401)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Geçersiz JSON."}, status=400)

        message = str(body.get("message", "")).strip()
        press_enter = body.get("press_enter", None)
        client_ip = request.remote or "Telefon"

        if not message:
            return web.json_response({"ok": False, "error": "Mesaj boş olamaz."}, status=400)

        self.log(f"Telefondan mesaj ({client_ip}): {message[:60]}")
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, self.bridge.send_message_to_antigravity, message, press_enter
        )

        if result.get("ok"):
            await self.broadcast({
                "event": "message_sent",
                "message": message,
                "window_title": result.get("window_title"),
            })
        else:
            self.log(f"Gönderim hatası: {result.get('error')}")

        return web.json_response(result)

    async def handle_send_image(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response({"ok": False, "auth_required": True}, status=401)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Geçersiz veri."}, status=400)

        raw_list = body.get("images") or []
        single_b64 = str(body.get("image_data", "")).strip()
        if single_b64 and not raw_list:
            raw_list = [single_b64]

        caption = str(body.get("message", "")).strip()
        client_ip = request.remote or "Telefon"

        if not raw_list:
            return web.json_response({"ok": False, "error": "Görsel verisi bulunamadı."}, status=400)

        decoded_images: List[bytes] = []
        for item_b64 in raw_list:
            s = str(item_b64).strip()
            if "," in s:
                s = s.split(",", 1)[1]
            try:
                decoded_images.append(base64.b64decode(s))
            except Exception:
                continue

        if not decoded_images:
            return web.json_response({"ok": False, "error": "Görseller çözümlenemedi."}, status=400)

        self.log(f"Telefondan {len(decoded_images)} görsel gönderildi ({client_ip})")
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, self.bridge.send_images_to_antigravity, decoded_images, caption, None
        )
        return web.json_response(result)

    async def handle_answer_question(self, request: web.Request) -> web.Response:
        """Telefondaki çoktan seçmeli soru (ask_question) kartından seçilen şıkları PC'ye iletir."""
        if not self._is_authorized(request):
            return web.json_response({"ok": False, "auth_required": True}, status=401)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Geçersiz JSON."}, status=400)

        options = body.get("selected_options") or body.get("options") or []
        if isinstance(options, str):
            options = [options]
        options = [str(o).strip() for o in options if str(o).strip()]
        custom_text = str(body.get("custom_text", "")).strip()
        if not options and not custom_text:
            return web.json_response({"ok": False, "error": "Lütfen bir şık seçin veya yanıt yazın."}, status=400)
        client_ip = request.remote or "Telefon"

        self.log(f"Telefondan soru yanıtlandı ({client_ip}): {options} {custom_text}")
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, self.bridge.answer_question_on_pc, options, custom_text
        )
        return web.json_response(result)

    @staticmethod
    def _synthesize_turkish_mp3(text: str) -> bytes:
        import urllib.parse
        import urllib.request

        clean = " ".join(text.split())[:900]
        if not clean:
            return b""

        # 180 karakterlik kelime sınırlarında parçalara böl
        words = clean.split(" ")
        chunks = []
        cur = ""
        for w in words:
            if len(cur) + len(w) + 1 <= 180:
                cur = f"{cur} {w}".strip()
            else:
                if cur:
                    chunks.append(cur)
                cur = w[:180]
        if cur:
            chunks.append(cur)

        audio_parts = []
        for ch in chunks:
            q = urllib.parse.quote(ch)
            url = f"https://translate.googleapis.com/translate_tts?ie=UTF-8&client=tw-ob&tl=tr&q={q}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                audio_parts.append(resp.read())
        return b"".join(audio_parts)

    async def handle_tts(self, request: web.Request) -> web.Response:
        """Metni Türkçe MP3 ses dosyasına dönüştürür (iOS Safari'de kesintisiz ses çalması için)."""
        if not self._is_authorized(request):
            return web.json_response({"ok": False, "auth_required": True}, status=401)

        text = request.query.get("text", "").strip()
        if not text and request.method == "POST":
            try:
                body = await request.json()
                text = str(body.get("text", "")).strip()
            except Exception:
                pass

        if not text:
            return web.Response(status=400, text="Boş metin")

        loop = asyncio.get_running_loop()
        try:
            mp3_bytes = await loop.run_in_executor(None, self._synthesize_turkish_mp3, text)
            if not mp3_bytes:
                return web.Response(status=400, text="Ses üretilemedi")
            return web.Response(
                body=mp3_bytes,
                content_type="audio/mpeg",
                headers={"Accept-Ranges": "bytes"},
            )
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_model_control(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response({"ok": False, "auth_required": True}, status=401)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Geçersiz istek."}, status=400)

        action = str(body.get("action", "select_model")).strip()
        client_ip = request.remote or "Telefon"
        loop = asyncio.get_running_loop()

        if action == "select_model":
            model_name = str(body.get("model", "")).strip()
            model_idx = int(body.get("index", 0))
            self.log(f"Telefondan model seçildi ({client_ip}): {model_name}")
            result = await loop.run_in_executor(
                None, self.bridge.select_model_direct, model_name, model_idx
            )
            return web.json_response(result)

        return web.json_response({"ok": False, "error": "Bilinmeyen model aksiyonu."}, status=400)

    async def handle_action(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response({"ok": False, "auth_required": True}, status=401)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Geçersiz istek."}, status=400)

        action = str(body.get("action", "")).strip()
        client_ip = request.remote or "Telefon"
        self.log(f"Uzaktan aksiyon ({client_ip}): {action}")

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self.bridge.send_quick_action, action)
        return web.json_response(result)

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20.0)
        await ws.prepare(request)

        if not self._is_authorized(request):
            await ws.send_json({"event": "auth_required"})
            await ws.close()
            return ws

        client_ip = request.remote or "Telefon"
        self.ws_clients.add(ws)
        self.log(f"Canlı bağlantı kuruldu ({client_ip}) - Aktif cihaz: {len(self.ws_clients)}")

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        payload = json.loads(msg.data)
                        if payload.get("action") == "select_conversation":
                            self.active_conversation_id = payload.get("conversation_id")
                    except Exception:
                        pass
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            self.ws_clients.discard(ws)
            self.log(f"Bağlantı ayrıldı ({client_ip}) - Aktif cihaz: {len(self.ws_clients)}")

        return ws

    async def broadcast(self, data: Dict[str, Any]) -> None:
        if not self.ws_clients:
            return
        dead = []
        for ws in list(self.ws_clients):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.ws_clients.discard(ws)

    async def _watch_loop(self) -> None:
        last_state: Dict[str, Any] = {}

        while self._running:
            try:
                convs = self.transcript_mgr.list_conversations(limit=5)
                if convs:
                    newest_id = convs[0]["id"]
                    if not self.active_conversation_id:
                        self.active_conversation_id = newest_id

                    check_ids = {newest_id}
                    if self.active_conversation_id:
                        check_ids.add(self.active_conversation_id)

                    for cid in check_ids:
                        t_path = self.config.brain_dir / cid / ".system_generated" / "logs" / "transcript.jsonl"
                        if not t_path.exists():
                            continue
                        stat = t_path.stat()
                        is_recent = (time.time() - stat.st_mtime) < 25
                        sig = (stat.st_mtime, stat.st_size, is_recent)
                        if last_state.get(cid) != sig:
                            last_state[cid] = sig
                            detail = self.transcript_mgr.get_conversation_steps(cid)
                            if self.bridge.selected_model_override:
                                detail["usage"]["active_model"] = self.bridge.selected_model_override
                            await self.broadcast({
                                "event": "conversation_update",
                                "conversation_id": cid,
                                "data": detail,
                            })
            except Exception:
                pass

            await asyncio.sleep(0.5)

    async def start(self) -> None:
        app = self.create_app()
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()

        ssl_ctx = self.config.prepare_https()
        self._redirect_runner = None
        if ssl_ctx is not None:
            # Ana uygulama HTTPS üzerinde (mikrofon / ses tanıma için gerekli)
            self.site = web.TCPSite(self.runner, self.config.host, self.config.https_port, ssl_context=ssl_ctx)
            await self.site.start()

            # Eski http://IP:8765 adresine girenleri otomatik HTTPS'e yönlendir
            https_port = self.config.https_port

            async def _redirect(request: web.Request) -> web.Response:
                host = (request.host or "").split(":")[0] or self.config.local_ip
                raise web.HTTPFound(f"https://{host}:{https_port}{request.path_qs}")

            redirect_app = web.Application()
            redirect_app.router.add_route("*", "/{tail:.*}", _redirect)
            self._redirect_runner = web.AppRunner(redirect_app, access_log=None)
            await self._redirect_runner.setup()
            await web.TCPSite(self._redirect_runner, self.config.host, self.config.port).start()
        else:
            self.site = web.TCPSite(self.runner, self.config.host, self.config.port)
            await self.site.start()

        self._running = True
        self._watch_task = asyncio.create_task(self._watch_loop())
        self.log(f"Sunucu başlatıldı: {self.config.base_url} (PIN: {self.config.pin_code})")
        if ssl_ctx is not None:
            self.log("HTTPS aktif. Telefonda 'Bağlantı gizli değil' uyarısı çıkarsa: Ayrıntıları Göster → Bu web sitesini ziyaret et.")

    async def stop(self) -> None:
        self._running = False
        if self._watch_task:
            self._watch_task.cancel()
        for ws in list(self.ws_clients):
            await ws.close()
        if getattr(self, "_redirect_runner", None):
            await self._redirect_runner.cleanup()
        if self.runner:
            await self.runner.cleanup()
        self.log("Sunucu durduruldu.")
