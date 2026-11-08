import ctypes
from ctypes import wintypes
import io
import os
import platform
import time
from typing import List, Dict, Any, Optional, Tuple

from PIL import Image


IS_WINDOWS = platform.system() == "Windows"
HAS_UIA = False

if IS_WINDOWS:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    SW_RESTORE = 9
    SW_SHOW = 5
    CF_DIB = 8
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    KEYEVENTF_KEYUP = 0x0002

    VK_RETURN = 0x0D
    VK_ESCAPE = 0x1B
    VK_CONTROL = 0x11
    VK_MENU = 0x12
    VK_SHIFT = 0x10
    VK_V = 0x56
    VK_L = 0x4C
    VK_DOWN = 0x28
    VK_UP = 0x26

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL

    # Windows .NET UIAutomation yüklemesi (Model menüsü ve soru şıklarını doğrudan bulmak için)
    try:
        import clr
        wpf_dir = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\WPF"
        if os.path.isdir(wpf_dir):
            clr.AddReference(os.path.join(wpf_dir, "UIAutomationClient.dll"))
            clr.AddReference(os.path.join(wpf_dir, "UIAutomationTypes.dll"))
            from System import IntPtr
            from System.Windows.Automation import AutomationElement, TreeScope, Condition
            HAS_UIA = True
    except Exception:
        HAS_UIA = False


class WindowBridge:
    """
    PC'de açık olan Antigravity penceresini bulur, odaklanır;
    telefondan gelen metinleri, çoklu görselleri, soru şıklarını ve doğrudan model seçimlerini PC'ye iletir.
    """

    SELF_TITLE_MARKER = "Antigravity Remote"

    def __init__(self, config):
        self.config = config
        self.selected_model_override: Optional[str] = None

    def list_candidate_windows(self) -> List[Dict[str, Any]]:
        if not IS_WINDOWS:
            return []

        results: List[Dict[str, Any]] = []
        keyword = (self.config.target_window_keyword or "Antigravity").lower()

        def enum_proc(hwnd, lParam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.strip()
                    if title and self.SELF_TITLE_MARKER.lower() not in title.lower():
                        is_match = keyword in title.lower()
                        results.append({
                            "hwnd": int(hwnd),
                            "title": title,
                            "is_match": is_match,
                        })
            return True

        cb = WNDENUMPROC(enum_proc)
        user32.EnumWindows(cb, 0)
        results.sort(key=lambda w: (not w["is_match"], w["title"]))
        return results

    def find_target_window(self) -> Optional[Dict[str, Any]]:
        windows = self.list_candidate_windows()
        if not windows:
            return None

        if self.config.target_hwnd:
            for w in windows:
                if w["hwnd"] == self.config.target_hwnd:
                    return w

        for w in windows:
            if w["is_match"]:
                return w

        return None

    def set_clipboard_text(self, text: str) -> bool:
        if not IS_WINDOWS:
            return False

        for _ in range(5):
            if user32.OpenClipboard(None):
                break
            time.sleep(0.05)
        else:
            return False

        try:
            user32.EmptyClipboard()
            encoded = text.encode("utf-16-le") + b"\x00\x00"
            h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
            if not h_mem:
                return False
            ptr = kernel32.GlobalLock(h_mem)
            if not ptr:
                return False
            ctypes.memmove(ptr, encoded, len(encoded))
            kernel32.GlobalUnlock(h_mem)
            user32.SetClipboardData(CF_UNICODETEXT, h_mem)
            return True
        finally:
            user32.CloseClipboard()

    def set_clipboard_image(self, image_bytes: bytes) -> bool:
        if not IS_WINDOWS:
            return False

        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            bmp_io = io.BytesIO()
            img.save(bmp_io, format="BMP")
            dib_data = bmp_io.getvalue()[14:]
        except Exception:
            return False

        for _ in range(5):
            if user32.OpenClipboard(None):
                break
            time.sleep(0.05)
        else:
            return False

        try:
            user32.EmptyClipboard()
            h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib_data))
            if not h_mem:
                return False
            ptr = kernel32.GlobalLock(h_mem)
            if not ptr:
                return False
            ctypes.memmove(ptr, dib_data, len(dib_data))
            kernel32.GlobalUnlock(h_mem)
            user32.SetClipboardData(CF_DIB, h_mem)
            return True
        finally:
            user32.CloseClipboard()

    def focus_window(self, hwnd: int) -> bool:
        if not IS_WINDOWS:
            return False
        try:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)
                time.sleep(0.15)
            else:
                user32.ShowWindow(hwnd, SW_SHOW)

            user32.keybd_event(VK_MENU, 0, 0, 0)
            user32.SetForegroundWindow(hwnd)
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.12)
            return True
        except Exception:
            return False

    def click_at(self, x: int, y: int) -> None:
        if not IS_WINDOWS:
            return
        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.03)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.1)

    def get_cursor_pos(self) -> Tuple[int, int]:
        if not IS_WINDOWS:
            return (0, 0)
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return (int(pt.x), int(pt.y))

    def _paste_shortcut(self) -> None:
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_V, 0, 0, 0)
        time.sleep(0.04)
        user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

    def _press_key(self, vk: int) -> None:
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.03)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

    def _uia_find_element_coords(self, hwnd: int, keywords: List[str]) -> Optional[Tuple[int, int]]:
        """
        Windows UIAutomation kullanarak Antigravity penceresi içindeki bir butonun
        veya menü öğesinin ekran koordinatlarını (x, y) ismine göre bulur.
        """
        if not HAS_UIA or not hwnd:
            return None
        try:
            root = AutomationElement.FromHandle(IntPtr(hwnd))
            if not root:
                return None
            all_elements = root.FindAll(TreeScope.Descendants, Condition.TrueCondition)
            if not all_elements:
                return None

            lower_kws = [k.lower() for k in keywords if k]
            for i in range(all_elements.Count):
                try:
                    el = all_elements[i]
                    name = (el.Current.Name or "").strip()
                    if not name:
                        continue
                    name_low = name.lower()
                    if any(kw in name_low for kw in lower_kws):
                        rect = el.Current.BoundingRectangle
                        if rect.Width > 4 and rect.Height > 4 and rect.Width < 700 and rect.Height < 120:
                            cx = int(rect.X + rect.Width / 2)
                            cy = int(rect.Y + rect.Height / 2)
                            if cx > 0 and cy > 0:
                                return (cx, cy)
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def find_chat_input_coords(self, hwnd: int) -> Optional[Tuple[int, int]]:
        """Sohbet giriş kutusunun koordinatlarını otomatik bulur veya kayıtlı koordinatları döndürür."""
        if self.config.chat_input_x is not None and self.config.chat_input_y is not None:
            return (self.config.chat_input_x, self.config.chat_input_y)

        # 1. UIAutomation ile 'Message input' veya 'Ask anything' ara
        if HAS_UIA and hwnd:
            try:
                root = AutomationElement.FromHandle(IntPtr(hwnd))
                if root:
                    els = root.FindAll(TreeScope.Descendants, Condition.TrueCondition)
                    for i in range(els.Count):
                        el = els[i]
                        name = (el.Current.Name or "").strip().lower()
                        ct = el.Current.ControlType.ProgrammaticName
                        if (ct == "ControlType.ComboBox" and ("input" in name or "message" in name)) or "ask anything" in name:
                            r = el.Current.BoundingRectangle
                            if r.Width > 50 and r.Height > 15:
                                cx = int(r.X + min(200, r.Width / 2))
                                cy = int(r.Y + r.Height / 2)
                                self.config.chat_input_x = cx
                                self.config.chat_input_y = cy
                                self.config.save()
                                return (cx, cy)
            except Exception:
                pass

        # 2. Fallback: Pencere geometrisinin alt orta kısmını hedefle (standart Antigravity alt sohbet kutusu)
        if hwnd:
            rect = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                if w > 300 and h > 300:
                    cx = int(rect.left + w / 2)
                    cy = int(rect.bottom - 70)
                    return (cx, cy)

        return None

    def find_model_button_coords(self, hwnd: int) -> Optional[Tuple[int, int]]:
        """Model seçici butonunun koordinatlarını otomatik bulur veya kayıtlı koordinatları döndürür."""
        if self.config.model_btn_x is not None and self.config.model_btn_y is not None:
            return (self.config.model_btn_x, self.config.model_btn_y)

        if HAS_UIA and hwnd:
            try:
                root = AutomationElement.FromHandle(IntPtr(hwnd))
                if root:
                    els = root.FindAll(TreeScope.Descendants, Condition.TrueCondition)
                    for i in range(els.Count):
                        el = els[i]
                        name = (el.Current.Name or "").strip().lower()
                        ct = el.Current.ControlType.ProgrammaticName
                        if ct == "ControlType.Button" and (name.startswith("select model") or "model selection" in name):
                            r = el.Current.BoundingRectangle
                            if r.Width > 20 and r.Height > 15:
                                cx = int(r.X + r.Width / 2)
                                cy = int(r.Y + r.Height / 2)
                                self.config.model_btn_x = cx
                                self.config.model_btn_y = cy
                                self.config.save()
                                return (cx, cy)
            except Exception:
                pass

        # Fallback: Sohbet kutusunun hemen altı
        chat_coords = self.find_chat_input_coords(hwnd)
        if chat_coords:
            return (chat_coords[0] - 20, chat_coords[1] + 46)

        return None

    def _focus_target_and_input(self) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        target = self.find_target_window()
        if not target and (self.config.chat_input_x is None or self.config.chat_input_y is None):
            return (
                False,
                None,
                (
                    f"PC'de açık bir '{self.config.target_window_keyword}' penceresi bulunamadı. "
                    "Lütfen PC uygulamasından sohbet kutusunu hedefleyin."
                ),
            )
        hwnd = target["hwnd"] if target else 0
        if hwnd:
            self.focus_window(hwnd)

        coords = self.find_chat_input_coords(hwnd)
        if coords:
            self.click_at(coords[0], coords[1])
            time.sleep(0.09)
        return True, target, None

    def send_message_to_antigravity(self, message: str, press_enter: Optional[bool] = None) -> Dict[str, Any]:
        message = (message or "").strip()
        if not message:
            return {"ok": False, "error": "Boş mesaj gönderilemez."}

        ok, target, err = self._focus_target_and_input()
        if not ok:
            return {"ok": False, "error": err}

        if not self.set_clipboard_text(message):
            return {"ok": False, "error": "Mesaj PC panosuna kopyalanamadı."}

        self._paste_shortcut()
        time.sleep(0.12)

        should_enter = self.config.auto_press_enter if press_enter is None else press_enter
        if should_enter:
            self._press_key(VK_RETURN)

        return {
            "ok": True,
            "window_title": target["title"] if target else "Kalibre Edilmiş Konum",
            "calibrated": self.config.chat_input_x is not None,
        }

    def send_images_to_antigravity(
        self,
        images_bytes_list: List[bytes],
        caption: str = "",
        press_enter: Optional[bool] = None,
    ) -> Dict[str, Any]:
        if not images_bytes_list:
            return {"ok": False, "error": "Görsel listesi boş."}

        ok, target, err = self._focus_target_and_input()
        if not ok:
            return {"ok": False, "error": err}

        for idx, img_bytes in enumerate(images_bytes_list):
            if not self.set_clipboard_image(img_bytes):
                return {"ok": False, "error": f"{idx + 1}. görsel PC panosuna kopyalanamadı."}
            self._paste_shortcut()
            time.sleep(0.45)

        caption = (caption or "").strip()
        if caption:
            if self.set_clipboard_text(caption):
                self._paste_shortcut()
                time.sleep(0.15)

        should_enter = self.config.auto_press_enter if press_enter is None else press_enter
        if should_enter:
            self._press_key(VK_RETURN)

        return {
            "ok": True,
            "count": len(images_bytes_list),
            "window_title": target["title"] if target else "Kalibre Edilmiş Konum",
        }

    def select_model_direct(self, model_name: str, model_index: int = 0) -> Dict[str, Any]:
        """
        Telefondan bir model seçildiğinde PC'deki Antigravity model menüsünü açar ve
        UIAutomation (veya kalibre edilmiş menü koordinatı) ile doğrudan o modele tıklar.
        """
        self.selected_model_override = model_name
        target = self.find_target_window()
        hwnd = target["hwnd"] if target else 0
        if hwnd:
            self.focus_window(hwnd)

        # 1. Model Seçici Butonunun yerini bul ve tıkla
        m_coords = self.find_model_button_coords(hwnd)
        if not m_coords:
            return {
                "ok": False,
                "error": "Model seçici butonu bulunamadı. Lütfen PC'deki Antigravity penceresinin açık olduğundan emin olun.",
            }
        mx, my = m_coords

        # Model menüsünü açmak için butona tıkla
        self.click_at(mx, my)
        time.sleep(0.38)

        # 2. Açılan menüde seçilen modeli UIAutomation ile ismine göre bulup tıkla
        search_terms = [model_name]
        if "Pro" in model_name:
            search_terms.append(model_name.replace("Pro", "Argon"))
        uia_item = self._uia_find_element_coords(hwnd, search_terms)
        if uia_item:
            self.click_at(uia_item[0], uia_item[1])
            return {"ok": True, "selected_model": model_name, "method": "uia"}

        # 3. UIAutomation menüyü göremediyse: Açılan menüde kalibre edilen butonun üstündeki ilgili satıra tıkla
        # Antigravity model menüsü butonun hemen üstünde açılır ve her satır ~36px yüksekliğindedir
        total_models = 5
        offset_from_bottom = (total_models - model_index) * 36
        item_y = max(20, my - offset_from_bottom)
        self.click_at(mx, item_y)
        time.sleep(0.1)

        return {"ok": True, "selected_model": model_name, "method": "offset_click"}

    def answer_question_on_pc(self, selected_options: List[str], custom_text: str = "") -> Dict[str, Any]:
        """
        Antigravity çoktan seçmeli bir soru (ask_question) sorduğunda telefondan seçilen
        şıkları PC'de işaretler veya yanıt olarak gönderir.
        """
        target = self.find_target_window()
        hwnd = target["hwnd"] if target else 0
        if hwnd:
            self.focus_window(hwnd)

        clicked_any = False
        if hwnd and selected_options:
            for opt in selected_options:
                clean_opt = opt.replace("(Recommended)", "").strip()
                coords = self._uia_find_element_coords(hwnd, [clean_opt[:35]])
                if coords:
                    self.click_at(coords[0], coords[1])
                    clicked_any = True
                    time.sleep(0.15)

            if clicked_any:
                # Submit / Proceed / Gönder butonunu ara
                submit_coords = self._uia_find_element_coords(hwnd, ["Submit", "Proceed", "Send", "Continue", "Confirm"])
                if submit_coords:
                    self.click_at(submit_coords[0], submit_coords[1])
                else:
                    self._press_key(VK_RETURN)
                return {"ok": True, "method": "uia_option_click"}

        # Fallback: Seçilen şıkları doğrudan mesaj/yanıt olarak gönder
        combined = ", ".join(selected_options)
        if custom_text:
            combined = f"{combined} - {custom_text}" if combined else custom_text
        return self.send_message_to_antigravity(combined, press_enter=True)

    def send_quick_action(self, action: str) -> Dict[str, Any]:
        target = self.find_target_window()
        if target:
            self.focus_window(target["hwnd"])
        elif self.config.chat_input_x is not None and self.config.chat_input_y is not None:
            self.click_at(self.config.chat_input_x, self.config.chat_input_y)
        else:
            return {"ok": False, "error": "Açık Antigravity penceresi bulunamadı."}

        if action == "enter":
            self._press_key(VK_RETURN)
        elif action == "alt_enter":
            user32.keybd_event(VK_MENU, 0, 0, 0)
            user32.keybd_event(VK_RETURN, 0, 0, 0)
            time.sleep(0.03)
            user32.keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        elif action == "escape":
            self._press_key(VK_ESCAPE)
        elif action == "focus_chat":
            if self.config.chat_input_x is not None and self.config.chat_input_y is not None:
                self.click_at(self.config.chat_input_x, self.config.chat_input_y)
            else:
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(VK_L, 0, 0, 0)
                time.sleep(0.03)
                user32.keybd_event(VK_L, 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
        else:
            return {"ok": False, "error": f"Bilinmeyen aksiyon: {action}"}

        return {"ok": True, "action": action}
