import json
import os
import re
import time
from pathlib import Path
from typing import List, Dict, Any, Optional


USER_REQ_PATTERN = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.DOTALL)
METADATA_PATTERN = re.compile(r"<(ADDITIONAL_METADATA|USER_SETTINGS_CHANGE)>.*?</\1>", re.DOTALL)
MODEL_CHANGE_PATTERN = re.compile(r"changed setting `Model Selection` from .*? to ([^\.\n<]+)")
UPLOADED_IMG_PATTERN = re.compile(r"([A-Za-z]:[/\\][^\n\r]+?\.(?:jpg|jpeg|png|webp|gif))", re.IGNORECASE)


def clean_user_content(raw_content: str) -> str:
    """<USER_REQUEST> etiketleri arasındaki asıl kullanıcı mesajını ayıklar."""
    if not raw_content:
        return ""
    match = USER_REQ_PATTERN.search(raw_content)
    if match:
        return match.group(1).strip()
    cleaned = METADATA_PATTERN.sub("", raw_content).strip()
    return cleaned


def extract_uploaded_images(raw_content: str) -> List[str]:
    """<ADDITIONAL_METADATA> içindeki kullanıcı tarafından yüklenen görsel dosya yollarını bulur."""
    if not raw_content or "uploaded" not in raw_content:
        return []
    return [p.strip() for p in UPLOADED_IMG_PATTERN.findall(raw_content)]


def format_model_name(raw_name: str) -> str:
    """Model adını kullanıcı dostu formata dönüştürür."""
    name = (raw_name or "").strip()
    if not name or name.lower() == "none":
        return "Varsayılan Model (Auto)"
    name = re.sub(r"\bArgon\b", "Pro", name, flags=re.IGNORECASE)
    return name


def clean_arg_str(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        try:
            return json.loads(s)
        except Exception:
            return s[1:-1]
    return s


def parse_ask_questions(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    """ask_question aracının argümanlarındaki soru ve şıkları ayrıştırır."""
    raw_q = args.get("questions")
    if not raw_q:
        return []
    if isinstance(raw_q, list):
        return raw_q
    if isinstance(raw_q, str):
        s = clean_arg_str(raw_q)
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return []


class TranscriptManager:
    """Antigravity brain dizinindeki konuşmaları, soruları (ask_question), komut çıktılarını ve token limitlerini okur."""

    def __init__(self, brain_dir: Path, default_workspace: Optional[Path] = None):
        self.brain_dir = brain_dir
        self.default_workspace = default_workspace or Path.cwd()

    def list_conversations(self, limit: int = 30) -> List[Dict[str, Any]]:
        if not self.brain_dir.exists():
            return []

        conversations: List[Dict[str, Any]] = []
        for folder in self.brain_dir.iterdir():
            if not folder.is_dir() or folder.name.startswith("."):
                continue
            transcript_path = folder / ".system_generated" / "logs" / "transcript.jsonl"
            if not transcript_path.exists():
                continue

            try:
                stat = transcript_path.stat()
                mtime = stat.st_mtime
                preview_info = self._get_conversation_preview(folder, transcript_path, mtime)
                conversations.append({
                    "id": folder.name,
                    "title": preview_info["title"],
                    "last_message": preview_info["last_message"],
                    "step_count": preview_info["step_count"],
                    "updated_at": mtime,
                    "status": preview_info["status"],
                    "active_model": preview_info["active_model"],
                })
            except Exception:
                continue

        conversations.sort(key=lambda c: c["updated_at"], reverse=True)
        return conversations[:limit]

    def _get_conversation_preview(self, folder: Path, transcript_path: Path, mtime: float) -> Dict[str, Any]:
        title = f"Sohbet ({folder.name[:8]})"
        last_message = ""
        step_count = 0
        status = "IDLE"
        active_model = "Varsayılan Model"

        try:
            with transcript_path.open("r", encoding="utf-8", errors="replace") as f:
                lines = [line.strip() for line in f if line.strip()]
                step_count = len(lines)
                for line in lines:
                    try:
                        obj = json.loads(line)
                        raw_c = obj.get("content", "") or ""
                        m_match = MODEL_CHANGE_PATTERN.search(raw_c)
                        if m_match:
                            active_model = format_model_name(m_match.group(1))

                        if obj.get("type") == "USER_INPUT" and title.startswith("Sohbet ("):
                            text = clean_user_content(raw_c)
                            if text:
                                first_line = text.splitlines()[0][:65]
                                title = first_line + ("..." if len(text) > 65 else "")
                        if obj.get("type") in ("USER_INPUT", "PLANNER_RESPONSE"):
                            content = raw_c
                            if obj.get("type") == "USER_INPUT":
                                content = clean_user_content(content)
                            if content:
                                last_message = content.strip()[:100]
                    except Exception:
                        continue

                # Sadece son 25 saniye içinde güncellenmişse WORKING kabul et
                if lines and (time.time() - mtime < 25):
                    last_obj = json.loads(lines[-1])
                    t_calls = last_obj.get("tool_calls") or []
                    is_ask = any(isinstance(tc, dict) and tc.get("name") == "ask_question" for tc in t_calls)
                    if not is_ask and (
                        last_obj.get("type") in ("USER_INPUT", "GENERIC")
                        or (last_obj.get("type") == "PLANNER_RESPONSE" and t_calls and not last_obj.get("content"))
                    ):
                        status = "WORKING"
        except Exception:
            pass

        return {
            "title": title,
            "last_message": last_message,
            "step_count": step_count,
            "status": status,
            "active_model": active_model,
        }

    def get_conversation_steps(self, conversation_id: str, since_step: int = -1) -> Dict[str, Any]:
        folder = self.brain_dir / conversation_id
        compact_path = folder / ".system_generated" / "logs" / "transcript.jsonl"
        full_path = folder / ".system_generated" / "logs" / "transcript_full.jsonl"

        if not compact_path.exists():
            return {
                "id": conversation_id,
                "steps": [],
                "commands": [],
                "workspaces": [str(self.default_workspace)],
                "artifacts": [],
                "is_working": False,
                "usage": self._empty_usage(),
            }

        try:
            file_mtime = compact_path.stat().st_mtime
        except Exception:
            file_mtime = 0.0

        compact_lines: List[str] = []
        try:
            with compact_path.open("r", encoding="utf-8", errors="replace") as f:
                compact_lines = [line.strip() for line in f if line.strip()]
        except Exception:
            pass

        full_lines: Optional[List[str]] = None

        def get_step_obj(idx: int, raw_line: str) -> Dict[str, Any]:
            nonlocal full_lines
            obj = json.loads(raw_line)
            if obj.get("truncated_fields") and full_path.exists():
                if full_lines is None:
                    try:
                        with full_path.open("r", encoding="utf-8", errors="replace") as ff:
                            full_lines = [fl.strip() for fl in ff if fl.strip()]
                    except Exception:
                        full_lines = []
                if idx < len(full_lines):
                    try:
                        obj = json.loads(full_lines[idx])
                    except Exception:
                        pass
            return obj

        all_objs: List[Dict[str, Any]] = []
        for idx, line in enumerate(compact_lines):
            try:
                all_objs.append(get_step_obj(idx, line))
            except Exception:
                continue

        parsed_steps: List[Dict[str, Any]] = []
        commands_history: List[Dict[str, Any]] = []
        detected_workspaces: List[str] = [str(self.default_workspace)]
        is_working = False

        active_model = "Varsayılan Model"
        total_input = 0
        total_cache = 0
        total_output = 0
        last_context_size = 0
        model_turns = 0

        num_objs = len(all_objs)
        for i, obj in enumerate(all_objs):
            step_index = int(obj.get("step_index", i))
            raw_content_meta = obj.get("content", "") or ""
            m_match = MODEL_CHANGE_PATTERN.search(raw_content_meta)
            if m_match:
                active_model = format_model_name(m_match.group(1))

            step_type = obj.get("type", "")
            created_at = obj.get("created_at", "")
            status = obj.get("status", "DONE")

            if step_type == "PLANNER_RESPONSE":
                inp = int(obj.get("input_tokens", 0) or 0)
                cache = int(obj.get("cache_read_tokens", 0) or 0)
                out = int(obj.get("output_tokens", 0) or 0)
                total_input += inp
                total_cache += cache
                total_output += out
                if inp + cache > 0:
                    last_context_size = inp + cache
                model_turns += 1

            if step_index <= since_step:
                continue

            if step_type == "USER_INPUT":
                clean_text = clean_user_content(raw_content_meta)
                uploaded_imgs = extract_uploaded_images(raw_content_meta)
                if clean_text or uploaded_imgs:
                    parsed_steps.append({
                        "step_index": step_index,
                        "role": "user",
                        "type": "USER_INPUT",
                        "content": clean_text,
                        "images": uploaded_imgs,
                        "created_at": created_at,
                        "status": status,
                    })

            elif step_type == "PLANNER_RESPONSE":
                content = obj.get("content", "") or ""
                thinking = (obj.get("thinking", "") or "").strip()
                raw_tools = obj.get("tool_calls", []) or []

                generic_outputs: List[str] = []
                j = i + 1
                while j < num_objs and all_objs[j].get("type") == "GENERIC":
                    generic_outputs.append(all_objs[j].get("content", "") or "")
                    j += 1

                tools_detailed: List[Dict[str, Any]] = []
                step_questions: List[Dict[str, Any]] = []
                question_answered = len(generic_outputs) > 0
                question_answer_text = generic_outputs[0] if generic_outputs else ""

                for t_idx, tc in enumerate(raw_tools):
                    if not isinstance(tc, dict):
                        continue
                    t_name = tc.get("name", "tool")
                    t_args = tc.get("args", {}) or {}
                    t_out = generic_outputs[t_idx] if t_idx < len(generic_outputs) else ""

                    if t_name == "ask_question":
                        qs = parse_ask_questions(t_args)
                        for q_item in qs:
                            step_questions.append({
                                "question": q_item.get("question", "Seçim yapın:"),
                                "options": q_item.get("options", []),
                                "is_multi_select": bool(q_item.get("is_multi_select", False)),
                                "answered": question_answered,
                                "answer_text": question_answer_text,
                            })
                        continue

                    detail = self._build_tool_detail(t_name, t_args, t_out, step_index, created_at)
                    tools_detailed.append(detail)

                    file_path_str = detail.get("file_path", "")
                    if file_path_str and ".gemini" not in file_path_str:
                        self._register_workspace_candidate(file_path_str, detected_workspaces)

                    if t_name in ("run_command", "write_file", "edit_file"):
                        commands_history.append(detail)

                if content or thinking or tools_detailed or step_questions:
                    if (
                        parsed_steps
                        and parsed_steps[-1]["role"] == "assistant"
                        and not parsed_steps[-1].get("content")
                        and not parsed_steps[-1].get("questions")
                    ):
                        prev = parsed_steps[-1]
                        if thinking:
                            prev["thinking"] = thinking  # Sadece en güncel düşünceyi tut, şişmeyi önle
                        prev["tool_calls"].extend(tools_detailed)
                        if content:
                            prev["content"] = content
                        if step_questions:
                            prev["questions"] = step_questions
                        prev["step_index"] = step_index
                    else:
                        parsed_steps.append({
                            "step_index": step_index,
                            "role": "assistant",
                            "type": "PLANNER_RESPONSE",
                            "content": content,
                            "thinking": thinking,
                            "tool_calls": tools_detailed,
                            "questions": step_questions,
                            "created_at": created_at,
                            "status": status,
                        })

        # Çalışıyor durumunu kontrol et (ask_question bekliyorsa veya 25 sn'den eskiyse False)
        if all_objs and (time.time() - file_mtime < 25):
            last_raw = all_objs[-1]
            last_type = last_raw.get("type", "")
            last_tools = last_raw.get("tool_calls") or []
            is_last_ask = any(isinstance(tc, dict) and tc.get("name") == "ask_question" for tc in last_tools)
            if not is_last_ask:
                if last_type in ("USER_INPUT", "GENERIC") or (
                    last_type == "PLANNER_RESPONSE" and last_tools and not last_raw.get("content")
                ):
                    is_working = True

        context_limit = 1_000_000
        context_percent = round(min(100.0, (last_context_size / context_limit) * 100), 2)
        all_prompt_tokens = total_input + total_cache
        cache_hit_ratio = round((total_cache / all_prompt_tokens) * 100, 1) if all_prompt_tokens > 0 else 0.0

        usage = {
            "active_model": active_model,
            "last_context_tokens": last_context_size,
            "context_limit": context_limit,
            "context_percent": context_percent,
            "total_input_tokens": total_input,
            "total_cache_tokens": total_cache,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_cache + total_output,
            "cache_hit_ratio": cache_hit_ratio,
            "model_turns": model_turns,
        }

        artifacts = self.list_artifacts(conversation_id)
        return {
            "id": conversation_id,
            "steps": parsed_steps,
            "commands": commands_history,
            "workspaces": detected_workspaces,
            "total_raw_steps": len(all_objs),
            "artifacts": artifacts,
            "is_working": is_working,
            "usage": usage,
        }

    def _register_workspace_candidate(self, file_path_str: str, workspaces: List[str]) -> None:
        try:
            p = Path(file_path_str).resolve()
            parent = p.parent if p.suffix else p
            parts = parent.parts
            candidate = str(parent)
            if "Desktop" in parts:
                idx = parts.index("Desktop")
                if idx + 1 < len(parts):
                    candidate = str(Path(*parts[: idx + 2]).resolve())
            lower_existing = {w.lower() for w in workspaces}
            if os.path.isdir(candidate) and candidate.lower() not in lower_existing:
                workspaces.append(candidate)
        except Exception:
            pass

    def _build_tool_detail(
        self,
        name: str,
        args: Dict[str, Any],
        raw_output: str,
        step_index: int,
        created_at: str,
    ) -> Dict[str, Any]:
        cmd_line = clean_arg_str(args.get("CommandLine", ""))
        file_path = clean_arg_str(args.get("Path", ""))
        tool_summary = clean_arg_str(args.get("toolSummary", ""))

        clean_out = raw_output or ""
        exit_code = None
        m_exit = re.search(r"Command exited with code (\d+)", clean_out)
        if m_exit:
            exit_code = int(m_exit.group(1))
        if "Command output:" in clean_out:
            clean_out = clean_out.split("Command output:", 1)[1].strip()
        else:
            lines = [
                ln for ln in clean_out.splitlines()
                if not ln.startswith("Created At:") and not ln.startswith("Completed At:")
            ]
            clean_out = "\n".join(lines).strip()

        if name == "run_command":
            title = tool_summary or cmd_line[:60] or "Terminal Komutu"
            kind = "command"
        elif name == "write_file":
            fname = Path(file_path).name if file_path else "dosya"
            title = f"Dosya Oluşturuldu: {fname}"
            kind = "file_write"
        elif name == "edit_file":
            fname = Path(file_path).name if file_path else "dosya"
            title = f"Dosya Düzenlendi: {fname}"
            kind = "file_edit"
        elif name == "read_file":
            fname = Path(file_path).name if file_path else "dosya"
            title = f"Dosya Okundu: {fname}"
            kind = "file_read"
        else:
            title = tool_summary or name
            kind = "other"

        return {
            "step_index": step_index,
            "name": name,
            "kind": kind,
            "title": title,
            "summary": title,
            "command": cmd_line,
            "file_path": file_path,
            "exit_code": exit_code,
            "output": clean_out[:4000],
            "created_at": created_at,
        }

    def get_global_usage_summary(self, active_conv_id: Optional[str] = None) -> Dict[str, Any]:
        now = time.time()
        day_ago = now - 86400

        today_conversations = 0
        today_input = 0
        today_cache = 0
        today_output = 0
        today_turns = 0
        detected_models: List[str] = []

        if self.brain_dir.exists():
            for folder in self.brain_dir.iterdir():
                if not folder.is_dir() or folder.name.startswith("."):
                    continue
                t_path = folder / ".system_generated" / "logs" / "transcript.jsonl"
                if not t_path.exists():
                    continue
                try:
                    stat = t_path.stat()
                    if stat.st_mtime < day_ago:
                        continue
                    today_conversations += 1
                    with t_path.open("r", encoding="utf-8", errors="replace") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            obj = json.loads(line)
                            raw_c = obj.get("content", "") or ""
                            m_match = MODEL_CHANGE_PATTERN.search(raw_c)
                            if m_match:
                                m_name = format_model_name(m_match.group(1))
                                if m_name not in detected_models:
                                    detected_models.append(m_name)
                            if obj.get("type") == "PLANNER_RESPONSE":
                                today_input += int(obj.get("input_tokens", 0) or 0)
                                today_cache += int(obj.get("cache_read_tokens", 0) or 0)
                                today_output += int(obj.get("output_tokens", 0) or 0)
                                today_turns += 1
                except Exception:
                    continue

        active_usage = self._empty_usage()
        if active_conv_id:
            conv_data = self.get_conversation_steps(active_conv_id)
            active_usage = conv_data.get("usage", active_usage)

        return {
            "active": active_usage,
            "today": {
                "conversations_count": today_conversations,
                "turns_count": today_turns,
                "input_tokens": today_input,
                "cache_tokens": today_cache,
                "output_tokens": today_output,
                "total_tokens": today_input + today_cache + today_output,
            },
            "detected_models": detected_models,
        }

    def _empty_usage(self) -> Dict[str, Any]:
        return {
            "active_model": "Varsayılan Model",
            "last_context_tokens": 0,
            "context_limit": 1_000_000,
            "context_percent": 0.0,
            "total_input_tokens": 0,
            "total_cache_tokens": 0,
            "total_output_tokens": 0,
            "total_tokens": 0,
            "cache_hit_ratio": 0.0,
            "model_turns": 0,
        }

    def list_artifacts(self, conversation_id: str) -> List[Dict[str, Any]]:
        folder = self.brain_dir / conversation_id
        if not folder.exists():
            return []
        result = []
        for item in folder.iterdir():
            if item.is_file() and item.suffix.lower() in (".md", ".html") and not item.name.startswith("."):
                try:
                    stat = item.stat()
                    result.append({
                        "name": item.name,
                        "size": stat.st_size,
                        "updated_at": stat.st_mtime,
                    })
                except Exception:
                    continue
        result.sort(key=lambda x: x["updated_at"], reverse=True)
        return result

    def read_artifact(self, conversation_id: str, filename: str) -> Optional[str]:
        safe_name = Path(filename).name
        target = self.brain_dir / conversation_id / safe_name
        if not target.exists() or not target.is_file():
            return None
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None
