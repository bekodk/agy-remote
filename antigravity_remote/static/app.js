(() => {
  const urlParams = new URLSearchParams(window.location.search);
  const urlToken = urlParams.get("token");
  if (urlToken) {
    localStorage.setItem("agy_remote_token", urlToken);
    window.history.replaceState({}, document.title, "/");
  }

  let authToken = localStorage.getItem("agy_remote_token") || "";
  let activeConversationId = null;
  let ws = null;
  let renderedStepsHash = "";
  let pendingImages = []; // Çoklu görsel dizisi (base64)
  let currentDirPath = "";
  let parentDirPath = null;
  let currentEditingFilePath = "";
  let workingTimeoutId = null;

  // Sesli Sohbet (TTS & STT) durumu
  let autoTtsEnabled = localStorage.getItem("agy_auto_tts") === "1";
  let lastSpokenStepIndex = -1;
  let activeSpeechBtn = null;
  let recognition = null;
  let isRecordingMic = false;
  let speechRunId = 0;
  let speechUnlocked = false;

  function getTurkishVoice() {
    if (!("speechSynthesis" in window)) return null;
    const voices = window.speechSynthesis.getVoices() || [];
    return (
      voices.find((v) => v.lang === "tr-TR") ||
      voices.find((v) => (v.lang || "").toLowerCase().startsWith("tr")) ||
      null
    );
  }

  // DOM Elemanları
  const authScreen = document.getElementById("auth-screen");
  const pinForm = document.getElementById("pin-form");
  const pinInput = document.getElementById("pin-input");
  const authError = document.getElementById("auth-error");

  const openDrawerBtn = document.getElementById("open-drawer-btn");
  const closeDrawerBtn = document.getElementById("close-drawer-btn");
  const drawerBackdrop = document.getElementById("drawer-backdrop");
  const convDrawer = document.getElementById("conv-drawer");
  const convListEl = document.getElementById("conv-list");
  const pcWindowBadge = document.getElementById("pc-window-badge");

  const currentConvTitle = document.getElementById("current-conv-title");
  const wsDot = document.getElementById("ws-dot");
  const statusText = document.getElementById("status-text");
  const ttsToggleBtn = document.getElementById("tts-toggle-btn");
  const topLimitBadge = document.getElementById("top-limit-badge");
  const refreshBtn = document.getElementById("refresh-btn");
  const artifactsBar = document.getElementById("artifacts-bar");

  // Sekmeler
  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabPanels = {
    chat: document.getElementById("tab-chat"),
    commands: document.getElementById("tab-commands"),
    files: document.getElementById("tab-files"),
    model: document.getElementById("tab-model"),
  };
  const cmdCountBadge = document.getElementById("cmd-count-badge");
  const commandsListEl = document.getElementById("commands-list");

  // Dosya Gezgini & Düzenleyici
  const workspaceSelect = document.getElementById("workspace-select");
  const newFileBtn = document.getElementById("new-file-btn");
  const upDirBtn = document.getElementById("up-dir-btn");
  const currentPathBar = document.getElementById("current-path-bar");
  const filesListEl = document.getElementById("files-list");

  const fileModal = document.getElementById("file-modal");
  const fileModalTitle = document.getElementById("file-modal-title");
  const fileModalMeta = document.getElementById("file-modal-meta");
  const fileImageContainer = document.getElementById("file-image-container");
  const fileEditorTextarea = document.getElementById("file-editor-textarea");
  const saveFileBtn = document.getElementById("save-file-btn");
  const copyFileBtn = document.getElementById("copy-file-btn");
  const closeFileBtn = document.getElementById("close-file-btn");

  // Model & Limit Sekmesi
  const statActiveModel = document.getElementById("stat-active-model");
  const modelStatusToast = document.getElementById("model-status-toast");
  const modelsListEl = document.getElementById("models-list");
  const statContextText = document.getElementById("stat-context-text");
  const statContextBar = document.getElementById("stat-context-bar");
  const statConvTotal = document.getElementById("stat-conv-total");
  const statConvDetail = document.getElementById("stat-conv-detail");
  const statTodayTotal = document.getElementById("stat-today-total");
  const statTodayDetail = document.getElementById("stat-today-detail");

  // Sohbet & Çoklu Görsel Elemanları
  const chatContainer = document.getElementById("chat-container");
  const emptyState = document.getElementById("empty-state");
  const messagesList = document.getElementById("messages-list");
  const workingIndicator = document.getElementById("working-indicator");
  const workingText = document.getElementById("working-text");

  const imageFileInput = document.getElementById("image-file-input");
  const attachImgBtn = document.getElementById("attach-img-btn");
  const micBtn = document.getElementById("mic-btn");
  const imagePreviewBar = document.getElementById("image-preview-bar");
  const previewThumbsList = document.getElementById("preview-thumbs-list");
  const previewCountLabel = document.getElementById("preview-count-label");
  const clearImagesBtn = document.getElementById("clear-images-btn");

  const messageInput = document.getElementById("message-input");
  const sendBtn = document.getElementById("send-btn");

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatTokens(num) {
    const n = Number(num || 0);
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
    return String(n);
  }

  function formatBytes(bytes) {
    const b = Number(bytes || 0);
    if (b >= 1048576) return (b / 1048576).toFixed(1) + " MB";
    if (b >= 1024) return (b / 1024).toFixed(1) + " KB";
    return b + " B";
  }

  // Sesli Okuma (Text-to-Speech) Kurulumu
  function updateTtsButtonUI() {
    if (!ttsToggleBtn) return;
    ttsToggleBtn.textContent = autoTtsEnabled ? "🔊" : "🔇";
    ttsToggleBtn.classList.toggle("active-toggle", autoTtsEnabled);
  }
  updateTtsButtonUI();

  function cleanTextForSpeech(md) {
    return String(md || "")
      .replace(/```[\s\S]*?```/g, " kod bloğu. ")
      .replace(/\[([\s\S]*?)\]\s*\((?:file:\/\/\/|https?:\/\/)(?:[^()\r\n]|\([^()\r\n]*\))+\)/g, "$1")
      .replace(/file:\/\/\/[^\s)]+/g, "")
      .replace(/[#*`_~>-]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  // Tek bir kalıcı HTML5 Audio nesnesi (iOS Safari'de dokunuşla kilidi açılır ve tüm TTS seslerini kesintisiz çalar)
  const ttsAudio = new Audio();
  ttsAudio.playsInline = true;
  ttsAudio.preload = "auto";

  function speakTextFallbackBrowser(clean, myRun, resetBtn, onDone) {
    if (!("speechSynthesis" in window)) {
      resetBtn();
      if (onDone) onDone();
      return;
    }
    const synth = window.speechSynthesis;
    const chunks = [];
    clean.replace(/([.!?…:;])\s+/g, "$1\n").split("\n").forEach((sentence) => {
      let s = sentence.trim();
      while (s.length > 220) {
        const cut = s.lastIndexOf(" ", 220) > 80 ? s.lastIndexOf(" ", 220) : 220;
        chunks.push(s.slice(0, cut));
        s = s.slice(cut).trim();
      }
      if (s) chunks.push(s);
    });
    const voice = getTurkishVoice();
    let i = 0;
    const speakNext = () => {
      if (myRun !== speechRunId) return;
      if (i >= chunks.length) {
        resetBtn();
        if (onDone) onDone();
        return;
      }
      const utter = new SpeechSynthesisUtterance(chunks[i++]);
      utter.lang = "tr-TR";
      if (voice) utter.voice = voice;
      utter.rate = 1.05;
      utter.onend = speakNext;
      utter.onerror = speakNext;
      synth.speak(utter);
    };
    setTimeout(speakNext, 100);
  }

  function speakText(rawText, btnEl = null, onDone = null) {
    const resetBtn = () => {
      if (activeSpeechBtn) {
        activeSpeechBtn.classList.remove("speaking");
        activeSpeechBtn.textContent = "🔊 Dinle";
        activeSpeechBtn = null;
      }
    };

    const isCurrentlyPlaying =
      (!ttsAudio.paused && !ttsAudio.ended) ||
      ("speechSynthesis" in window && (window.speechSynthesis.speaking || window.speechSynthesis.pending));

    if (isCurrentlyPlaying) {
      const wasSameBtn = btnEl && activeSpeechBtn === btnEl;
      stopSpeaking();
      if (wasSameBtn) return;
    }

    const clean = cleanTextForSpeech(rawText);
    if (!clean) {
      if (onDone) onDone();
      return;
    }

    if (btnEl) {
      activeSpeechBtn = btnEl;
      btnEl.classList.add("speaking");
      btnEl.textContent = "⏹ Durdur";
    }

    const myRun = ++speechRunId;
    const ttsUrl = `/api/tts?text=${encodeURIComponent(clean.slice(0, 850))}&token=${encodeURIComponent(authToken)}`;

    ttsAudio.onended = () => {
      if (myRun !== speechRunId) return;
      resetBtn();
      if (onDone) onDone();
    };
    ttsAudio.onerror = () => {
      if (myRun !== speechRunId) return;
      speakTextFallbackBrowser(clean, myRun, resetBtn, onDone);
    };

    ttsAudio.src = ttsUrl;
    const playPromise = ttsAudio.play();
    if (playPromise && typeof playPromise.catch === "function") {
      playPromise.catch(() => {
        if (myRun !== speechRunId) return;
        speakTextFallbackBrowser(clean, myRun, resetBtn, onDone);
      });
    }
  }

  function stopSpeaking() {
    speechRunId++;
    try {
      ttsAudio.pause();
      ttsAudio.currentTime = 0;
    } catch (_) {}
    if ("speechSynthesis" in window) {
      try { window.speechSynthesis.cancel(); } catch (_) {}
    }
    if (activeSpeechBtn) {
      activeSpeechBtn.classList.remove("speaking");
      activeSpeechBtn.textContent = "🔊 Dinle";
      activeSpeechBtn = null;
    }
  }

  // iOS Safari: ses motoru ancak kullanıcı dokunuşuyla "kilidi açılınca" çalışır
  function unlockSpeech() {
    if (speechUnlocked) return;
    speechUnlocked = true;
    try {
      // Sessiz kısa WAV ile HTML5 Audio kilidini aç
      ttsAudio.src = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA";
      const p = ttsAudio.play();
      if (p && typeof p.catch === "function") p.catch(() => {});
    } catch (_) {}
    if ("speechSynthesis" in window) {
      try {
        const u = new SpeechSynthesisUtterance(" ");
        u.volume = 0;
        u.lang = "tr-TR";
        window.speechSynthesis.speak(u);
      } catch (_) {}
    }
  }
  document.addEventListener("touchend", unlockSpeech, { passive: true });
  document.addEventListener("click", unlockSpeech);
  if ("speechSynthesis" in window) {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.onvoiceschanged = () => window.speechSynthesis.getVoices();
  }

  if (ttsToggleBtn) {
    ttsToggleBtn.addEventListener("click", () => {
      autoTtsEnabled = !autoTtsEnabled;
      localStorage.setItem("agy_auto_tts", autoTtsEnabled ? "1" : "0");
      updateTtsButtonUI();
      if (autoTtsEnabled) {
        speakText("Sesli yanıt açık.");
      } else {
        stopSpeaking();
      }
    });
  }

  // Sesli Konuşarak Yazma (Speech-to-Text Mikrofon) Kurulumu
  const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (micBtn) {
    if (!SpeechRecognitionAPI) {
      micBtn.addEventListener("click", () => {
        if (!window.isSecureContext) {
          alert("Mikrofon için HTTPS gerekli. Adresi https:// ile açın (PC'deki QR kodu artık otomatik HTTPS açar).");
        } else {
          alert("Tarayıcınız ses tanımayı desteklemiyor. Klavyedeki mikrofon tuşunu kullanabilirsiniz.");
        }
      });
    } else {
      recognition = new SpeechRecognitionAPI();
      recognition.lang = "tr-TR";
      recognition.continuous = false;
      recognition.interimResults = true;

      let baseInputBeforeSpeech = "";

      recognition.onstart = () => {
        isRecordingMic = true;
        baseInputBeforeSpeech = messageInput.value ? messageInput.value.trim() + " " : "";
        micBtn.classList.add("recording");
      };

      recognition.onresult = (event) => {
        let transcript = "";
        for (let i = 0; i < event.results.length; i++) {
          transcript += event.results[i][0].transcript;
        }
        messageInput.value = baseInputBeforeSpeech + transcript;
        messageInput.style.height = "auto";
        messageInput.style.height = Math.min(messageInput.scrollHeight, 110) + "px";
      };

      recognition.onend = () => {
        isRecordingMic = false;
        micBtn.classList.remove("recording");
      };

      recognition.onerror = () => {
        isRecordingMic = false;
        micBtn.classList.remove("recording");
      };

      micBtn.addEventListener("click", () => {
        if (isRecordingMic) {
          try { recognition.stop(); } catch (_) {}
        } else {
          try { recognition.start(); } catch (_) {}
        }
      });
    }
  }

  // ================= CANLI SESLİ SOHBET (LIVE MODE) =================
  const liveOverlay = document.getElementById("live-overlay");
  const liveOrb = document.getElementById("live-orb");
  const liveStateEl = document.getElementById("live-state");
  const liveTranscriptEl = document.getElementById("live-transcript");
  const liveModeBtn = document.getElementById("live-mode-btn");
  const liveCloseBtn = document.getElementById("live-close-btn");
  const liveStopBtn = document.getElementById("live-stop-btn");
  const liveSkipBtn = document.getElementById("live-skip-btn");

  let latestConvData = null;
  const live = {
    active: false,
    state: "idle",
    rec: null,
    awaiting: false,
    baselineUserCount: 0,
    fallbackTimer: null,
    emptyRestarts: 0,
  };

  function setLiveState(state, label) {
    live.state = state;
    liveOrb.classList.remove("listening", "thinking", "speaking");
    if (state !== "idle") liveOrb.classList.add(state);
    liveStateEl.textContent = label;
  }

  function countUserSteps(data) {
    return ((data && data.steps) || []).filter((s) => s.role === "user").length;
  }

  function startLiveListening() {
    if (!live.active) return;
    if (live.rec) {
      try { live.rec.abort(); } catch (_) {}
      live.rec = null;
    }
    const rec = new SpeechRecognitionAPI();
    rec.lang = "tr-TR";
    rec.continuous = false;
    rec.interimResults = true;
    let finalText = "";
    let interimText = "";
    let errorMsg = "";

    rec.onresult = (e) => {
      finalText = "";
      interimText = "";
      for (let i = 0; i < e.results.length; i++) {
        if (e.results[i].isFinal) finalText += e.results[i][0].transcript;
        else interimText += e.results[i][0].transcript;
      }
      liveTranscriptEl.textContent = (finalText + " " + interimText).trim();
    };

    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        errorMsg = window.isSecureContext
          ? "Mikrofon izni verilmedi. Ayarlardan izin verin."
          : "Mikrofon için HTTPS gerekli.";
      }
    };

    rec.onend = () => {
      if (live.rec === rec) live.rec = null;
      if (!live.active) return;
      const text = (finalText || interimText).trim();
      if (errorMsg) {
        setLiveState("idle", errorMsg);
        return;
      }
      if (text) {
        live.emptyRestarts = 0;
        liveSend(text);
      } else if (live.emptyRestarts < 2) {
        live.emptyRestarts++;
        startLiveListening();
      } else {
        live.emptyRestarts = 0;
        setLiveState("idle", "Konuşmak için dokun");
      }
    };

    try {
      rec.start();
      live.rec = rec;
      setLiveState("listening", "Dinliyorum...");
    } catch (_) {
      setLiveState("idle", "Konuşmak için dokun");
    }
  }

  async function liveSend(text) {
    live.awaiting = true;
    live.baselineUserCount = countUserSteps(latestConvData);
    setLiveState("thinking", "Antigravity düşünüyor...");
    liveTranscriptEl.textContent = `Sen: ${text}`;
    try {
      const res = await apiFetch("/api/send", {
        method: "POST",
        body: JSON.stringify({ message: text, conversation_id: activeConversationId }),
      });
      if (!res.ok) {
        live.awaiting = false;
        setLiveState("idle", res.error || "Gönderilemedi. Tekrar dokun.");
      }
    } catch (_) {
      live.awaiting = false;
      setLiveState("idle", "Bağlantı hatası. Tekrar dokun.");
    }
  }

  function buildSpokenReply(step) {
    let text = step.content || "";
    (step.questions || []).forEach((q) => {
      if (q.answered) return;
      text += ` Soru: ${q.question}. Seçenekler: `;
      (q.options || []).forEach((o, i) => {
        text += `${i + 1}: ${String(o).replace("(Recommended)", "önerilen")}. `;
      });
    });
    return text.trim();
  }

  function liveSpeak(text) {
    setLiveState("speaking", "Konuşuyor...");
    liveTranscriptEl.textContent = cleanTextForSpeech(text).slice(0, 500);
    speakText(text, null, () => {
      if (live.active) startLiveListening();
    });
  }

  function checkLiveResponse(data) {
    if (!live.active || !live.awaiting) return;
    const steps = data.steps || [];
    if (countUserSteps(data) <= live.baselineUserCount) return; // mesajımız henüz görünmedi
    const last = steps[steps.length - 1];
    if (!last || last.role !== "assistant") return;
    const reply = buildSpokenReply(last);
    if (!reply) return;

    clearTimeout(live.fallbackTimer);
    const doSpeak = () => {
      if (!live.active || !live.awaiting) return;
      live.awaiting = false;
      liveSpeak(reply);
    };
    if (!data.is_working) doSpeak();
    else live.fallbackTimer = setTimeout(doSpeak, 9000);
  }

  function openLiveMode() {
    if (!SpeechRecognitionAPI) {
      alert(
        window.isSecureContext
          ? "Tarayıcınız ses tanımayı desteklemiyor."
          : "Canlı sohbet için HTTPS gerekli. Adresi https:// ile açın."
      );
      return;
    }
    unlockSpeech();
    stopSpeaking();
    if (isRecordingMic && recognition) {
      try { recognition.stop(); } catch (_) {}
    }
    live.active = true;
    live.awaiting = false;
    live.emptyRestarts = 0;
    liveTranscriptEl.textContent = "";
    liveOverlay.classList.remove("hidden");
    startLiveListening();
  }

  function closeLiveMode() {
    live.active = false;
    live.awaiting = false;
    clearTimeout(live.fallbackTimer);
    if (live.rec) {
      try { live.rec.abort(); } catch (_) {}
      live.rec = null;
    }
    stopSpeaking();
    setLiveState("idle", "Başlatmak için dokun");
    liveOverlay.classList.add("hidden");
  }

  liveModeBtn.addEventListener("click", openLiveMode);
  liveCloseBtn.addEventListener("click", closeLiveMode);
  liveStopBtn.addEventListener("click", closeLiveMode);
  liveSkipBtn.addEventListener("click", () => {
    stopSpeaking();
    live.awaiting = false;
    startLiveListening();
  });
  liveOrb.addEventListener("click", () => {
    unlockSpeech();
    if (live.state === "listening") {
      if (live.rec) { try { live.rec.stop(); } catch (_) {} }
    } else if (live.state === "speaking") {
      stopSpeaking();
      startLiveListening();
    } else if (live.state === "idle") {
      live.emptyRestarts = 0;
      startLiveListening();
    }
  });

  // Parantez ve boşluk içeren file:///.../Yeni klasör (9)/... linklerini kusursuz biçimlendiren Markdown ayrıştırıcı
  function renderMarkdown(md) {
    if (!md) return "";

    // 1. Kod bloklarını yer tutucuya al
    const codeBlocks = [];
    let text = String(md).replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
      const idx = codeBlocks.length;
      codeBlocks.push(`<pre><code>${escapeHtml(code.trim())}</code></pre>`);
      return `@@CODEBLOCK_${idx}@@`;
    });

    // 2. [etiket](file:///... veya https://...) linklerini (içinde boşluk veya (9) gibi parantez olsa dahi) yakala
    const linkChips = [];
    text = text.replace(
      /\[([\s\S]*?)\]\s*\(((?:file:\/\/\/|https?:\/\/)(?:[^()\r\n]|\([^()\r\n]*\))+)\)/g,
      (_, rawLabel, rawUrl) => {
        const cleanUrl = rawUrl.trim();
        let cleanLabel = rawLabel.replace(/[`\n\r]/g, "").trim();
        if (!cleanLabel) {
          cleanLabel = decodeURIComponent(cleanUrl.split("#")[0].split(/[\\/]/).pop() || "Dosya");
        }
        const idx = linkChips.length;
        if (cleanUrl.startsWith("file:///")) {
          linkChips.push(
            `<button type="button" class="file-link-chip" data-filepath="${escapeHtml(cleanUrl)}">📄 ${escapeHtml(cleanLabel)}</button>`
          );
        } else {
          linkChips.push(
            `<a href="${escapeHtml(cleanUrl)}" target="_blank" rel="noopener" class="ext-link">${escapeHtml(cleanLabel)}</a>`
          );
        }
        return `@@LINKCHIP_${idx}@@`;
      }
    );

    // 3. Açıkta kalmış çıplak file:///... adresleri varsa onları da temiz dosya butonuna çevir
    text = text.replace(
      /file:\/\/\/(?:[^\s<>")\r\n]|\([^\s<>")\r\n]*\))+/g,
      (rawUrl) => {
        const idx = linkChips.length;
        const baseName = decodeURIComponent(rawUrl.split("#")[0].split(/[\\/]/).pop() || "Dosya");
        linkChips.push(
          `<button type="button" class="file-link-chip" data-filepath="${escapeHtml(rawUrl)}">📄 ${escapeHtml(baseName)}</button>`
        );
        return `@@LINKCHIP_${idx}@@`;
      }
    );

    // 4. Kalan metin için HTML kaçışı
    text = escapeHtml(text);

    // 5. Satır içi kod `...`
    text = text.replace(/`([^`\n]+)`/g, "<code>$1</code>");

    // 6. Kalın ve İtalik
    text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    text = text.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");

    // 7. Satır bazlı yapı
    const lines = text.split("\n");
    const out = [];
    let inList = false;

    for (let i = 0; i < lines.length; i++) {
      const ln = lines[i];
      const trimmed = ln.trim();

      if (trimmed.startsWith("@@CODEBLOCK_")) {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push(trimmed);
        continue;
      }

      if (/^---+$/.test(trimmed)) {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push("<hr/>");
        continue;
      }

      if (trimmed.startsWith("### ")) {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push(`<h4>${trimmed.slice(4)}</h4>`);
        continue;
      }
      if (trimmed.startsWith("## ")) {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push(`<h3>${trimmed.slice(3)}</h3>`);
        continue;
      }
      if (trimmed.startsWith("# ")) {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push(`<h2>${trimmed.slice(2)}</h2>`);
        continue;
      }

      if (trimmed.startsWith("&gt; ")) {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push(`<blockquote>${trimmed.slice(5)}</blockquote>`);
        continue;
      }

      const listMatch = trimmed.match(/^(?:[-*•]|\d+\.)\s+(.*)$/);
      if (listMatch) {
        if (!inList) { out.push("<ul>"); inList = true; }
        out.push(`<li>${listMatch[1]}</li>`);
        continue;
      }

      if (inList && trimmed === "") {
        out.push("</ul>");
        inList = false;
        continue;
      }

      if (trimmed === "") {
        out.push("");
      } else {
        out.push(`<p>${ln}</p>`);
      }
    }
    if (inList) out.push("</ul>");

    let finalHtml = out.join("");
    finalHtml = finalHtml.replace(/@@LINKCHIP_(\d+)@@/g, (_, idx) => linkChips[Number(idx)] || "");
    finalHtml = finalHtml.replace(/@@CODEBLOCK_(\d+)@@/g, (_, idx) => codeBlocks[Number(idx)] || "");
    return finalHtml;
  }

  // Sekme Geçişleri
  function switchTab(tabName) {
    tabBtns.forEach((b) => {
      b.classList.toggle("active", b.getAttribute("data-tab") === tabName);
    });
    Object.keys(tabPanels).forEach((k) => {
      tabPanels[k].classList.toggle("hidden", k !== tabName);
      tabPanels[k].classList.toggle("active", k === tabName);
    });

    if (tabName === "files") {
      loadProjectFiles(currentDirPath);
    } else if (tabName === "model") {
      refreshUsageAndModels();
    }
  }

  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      switchTab(btn.getAttribute("data-tab"));
    });
  });

  topLimitBadge.addEventListener("click", () => {
    switchTab("model");
  });

  async function apiFetch(path, options = {}) {
    const headers = Object.assign(
      { "Content-Type": "application/json" },
      options.headers || {}
    );
    if (authToken) {
      headers["X-Auth-Token"] = authToken;
    }
    const res = await fetch(path, { ...options, headers });
    if (res.status === 401) {
      showPinScreen();
      throw new Error("Yetkisiz erişim");
    }
    return res.json();
  }

  function showPinScreen() {
    authScreen.classList.remove("hidden");
    pinInput.focus();
  }

  function hidePinScreen() {
    authScreen.classList.add("hidden");
    authError.classList.add("hidden");
  }

  pinForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const pin = pinInput.value.trim();
    try {
      const res = await fetch("/api/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pin }),
      });
      const data = await res.json();
      if (data.ok && data.token) {
        authToken = data.token;
        localStorage.setItem("agy_remote_token", authToken);
        pinInput.value = "";
        hidePinScreen();
        initApp();
      } else {
        authError.classList.remove("hidden");
      }
    } catch (err) {
      authError.textContent = "Sunucuya ulaşılamadı";
      authError.classList.remove("hidden");
    }
  });

  // Çekmece kontrolleri
  function openDrawer() {
    convDrawer.classList.add("open");
    drawerBackdrop.classList.remove("hidden");
    loadConversationsList();
  }

  function closeDrawer() {
    convDrawer.classList.remove("open");
    drawerBackdrop.classList.add("hidden");
  }

  openDrawerBtn.addEventListener("click", openDrawer);
  closeDrawerBtn.addEventListener("click", closeDrawer);
  drawerBackdrop.addEventListener("click", closeDrawer);

  // Dosya Görüntüleme & Düzenleme Modalı
  closeFileBtn.addEventListener("click", () => {
    fileModal.classList.add("hidden");
  });

  copyFileBtn.addEventListener("click", () => {
    if (navigator.clipboard && fileEditorTextarea.value) {
      navigator.clipboard.writeText(fileEditorTextarea.value);
      copyFileBtn.textContent = "Kopyalandı ✓";
      setTimeout(() => { copyFileBtn.textContent = "Kopyala"; }, 1200);
    }
  });

  saveFileBtn.addEventListener("click", async () => {
    if (!currentEditingFilePath) return;
    saveFileBtn.textContent = "Kaydediliyor...";
    try {
      const res = await apiFetch("/api/save_file", {
        method: "POST",
        body: JSON.stringify({
          path: currentEditingFilePath,
          content: fileEditorTextarea.value,
        }),
      });
      if (res.ok) {
        saveFileBtn.textContent = "Kaydedildi ✓";
        fileModalMeta.textContent = `${formatBytes(res.size)} • Kaydedildi`;
        loadProjectFiles(currentDirPath);
        setTimeout(() => { saveFileBtn.textContent = "💾 Kaydet"; }, 1400);
      } else {
        alert(res.error || "Dosya kaydedilemedi.");
        saveFileBtn.textContent = "💾 Kaydet";
      }
    } catch (e) {
      alert("Kaydetme hatası.");
      saveFileBtn.textContent = "💾 Kaydet";
    }
  });

  async function openProjectFile(filePath) {
    try {
      const res = await apiFetch(`/api/file_content?path=${encodeURIComponent(filePath)}`);
      if (!res.ok) {
        alert(res.error || "Dosya açılamadı.");
        return;
      }
      currentEditingFilePath = res.path;
      fileModalTitle.textContent = res.name;

      if (res.is_image) {
        fileModalMeta.textContent = `${formatBytes(res.size)} • Görsel`;
        saveFileBtn.classList.add("hidden");
        copyFileBtn.classList.add("hidden");
        fileEditorTextarea.classList.add("hidden");
        fileImageContainer.classList.remove("hidden");
        const imgUrl = `/api/raw_file?path=${encodeURIComponent(res.path)}&token=${encodeURIComponent(authToken)}`;
        fileImageContainer.innerHTML = `<img src="${imgUrl}" style="max-width:100%;border-radius:8px;" />`;
      } else {
        fileModalMeta.textContent = `${res.lines_count} satır • ${formatBytes(res.size)} • Düzenlenebilir`;
        saveFileBtn.classList.remove("hidden");
        copyFileBtn.classList.remove("hidden");
        fileImageContainer.classList.add("hidden");
        fileEditorTextarea.classList.remove("hidden");
        fileEditorTextarea.value = res.content || "";
      }
      fileModal.classList.remove("hidden");
    } catch (e) {
      alert("Dosya okunamadı.");
    }
  }

  // Yeni Dosya Oluşturma
  newFileBtn.addEventListener("click", () => {
    const fname = prompt("Oluşturulacak yeni dosya adı (ör. test.py, notlar.txt):");
    if (!fname || !fname.trim()) return;
    const sep = currentDirPath.includes("\\") ? "\\" : "/";
    const fullNewPath = (currentDirPath || ".") + sep + fname.trim();
    currentEditingFilePath = fullNewPath;
    fileModalTitle.textContent = fname.trim();
    fileModalMeta.textContent = "Yeni Dosya • Düzenlenebilir";
    saveFileBtn.classList.remove("hidden");
    copyFileBtn.classList.remove("hidden");
    fileImageContainer.classList.add("hidden");
    fileEditorTextarea.classList.remove("hidden");
    fileEditorTextarea.value = "";
    fileModal.classList.remove("hidden");
    fileEditorTextarea.focus();
  });

  // Sohbet içindeki dosya linklerine tıklamayı yakala
  document.addEventListener("click", (e) => {
    const chip = e.target.closest(".file-link-chip");
    if (chip) {
      const fp = chip.getAttribute("data-filepath");
      if (fp) openProjectFile(fp);
    }
  });

  // Proje Dosya Gezgini
  async function loadProjectFiles(dirPath = "") {
    try {
      const data = await apiFetch(`/api/files?path=${encodeURIComponent(dirPath || "")}`);
      if (!data.ok) return;

      currentDirPath = data.current_path;
      parentDirPath = data.parent_path;
      currentPathBar.textContent = data.current_path;

      const workspaces = data.workspaces || [];
      workspaceSelect.innerHTML = "";
      workspaces.forEach((w) => {
        const opt = document.createElement("option");
        opt.value = w;
        opt.textContent = `📁 ${w.split(/[\\/]/).pop() || w}`;
        if (currentDirPath.toLowerCase().startsWith(w.toLowerCase())) {
          opt.selected = true;
        }
        workspaceSelect.appendChild(opt);
      });

      filesListEl.innerHTML = "";
      const entries = data.entries || [];
      if (entries.length === 0) {
        filesListEl.innerHTML = `<div style="color:#737373;padding:16px;text-align:center;font-size:0.82rem;">Bu klasör boş</div>`;
        return;
      }

      entries.forEach((ent) => {
        const row = document.createElement("div");
        row.className = "file-row";
        const tag = ent.is_dir ? "DIR" : (ent.ext.replace(".", "").toUpperCase() || "FILE");
        const rightText = ent.is_dir ? "Klasörü Aç →" : `${formatBytes(ent.size)} • Düzenle`;

        row.innerHTML = `
          <div class="file-row-left">
            <span class="file-icon">${escapeHtml(tag)}</span>
            <span class="file-name">${escapeHtml(ent.name)}</span>
          </div>
          <span class="file-size">${rightText}</span>
        `;

        row.addEventListener("click", () => {
          if (ent.is_dir) {
            loadProjectFiles(ent.path);
          } else {
            openProjectFile(ent.path);
          }
        });
        filesListEl.appendChild(row);
      });
    } catch (_) {}
  }

  workspaceSelect.addEventListener("change", () => {
    loadProjectFiles(workspaceSelect.value);
  });

  upDirBtn.addEventListener("click", () => {
    if (parentDirPath) {
      loadProjectFiles(parentDirPath);
    }
  });

  // Doğrudan Model Seçimi & Limit Sekmesi
  function showModelToast(msg) {
    if (!modelStatusToast) return;
    modelStatusToast.textContent = msg;
    modelStatusToast.classList.remove("hidden");
  }

  async function refreshUsageAndModels() {
    try {
      const u = await apiFetch(
        `/api/usage?conv_id=${encodeURIComponent(activeConversationId || "")}`
      );
      if (u.ok) {
        const act = u.active || {};
        const tod = u.today || {};
        const currentModel = act.active_model || "Gemini 4 Pro (High)";
        statActiveModel.textContent = currentModel;
        statContextText.textContent = `${formatTokens(act.last_context_tokens)} / 1M (%${act.context_percent || 0})`;
        statContextBar.style.width = `${Math.min(100, act.context_percent || 0)}%`;

        statConvTotal.textContent = `${formatTokens(act.total_tokens)} token`;
        statConvDetail.textContent = `Çıktı: ${formatTokens(act.total_output_tokens)} • Cache: %${act.cache_hit_ratio || 0}`;

        statTodayTotal.textContent = `${formatTokens(tod.total_tokens)} token`;
        statTodayDetail.textContent = `${tod.conversations_count || 0} sohbet • ${tod.turns_count || 0} adım`;

        // Doğrudan Model Seçim Kartlarını Oluştur
        const models = u.available_models || [];
        modelsListEl.innerHTML = "";
        models.forEach((m, idx) => {
          const isCurrent = currentModel.toLowerCase().includes(m.name.toLowerCase());
          const item = document.createElement("div");
          item.className = "model-item" + (isCurrent ? " active" : "");
          item.innerHTML = `
            <div>
              <div class="model-item-name">${escapeHtml(m.name)}</div>
              <div class="model-item-desc">${escapeHtml(m.desc)}</div>
            </div>
            <span class="model-item-badge">${isCurrent ? "● Aktif" : "Seç"}</span>
          `;
          item.addEventListener("click", async () => {
            showModelToast(`⏳ PC'de "${m.name}" modeli seçiliyor...`);
            try {
              const res = await apiFetch("/api/model_control", {
                method: "POST",
                body: JSON.stringify({
                  action: "select_model",
                  model: m.name,
                  index: idx,
                }),
              });
              if (res.ok) {
                statActiveModel.textContent = m.name;
                statusText.textContent = m.name;
                showModelToast(`✓ "${m.name}" seçimi PC'deki Antigravity'ye iletildi.`);
                setTimeout(refreshUsageAndModels, 900);
              } else {
                showModelToast(`⚠️ Model seçilemedi. PC'de Antigravity penceresinin açık olduğundan emin olun.`);
              }
            } catch (_) {
              showModelToast(`⚠️ Sunucu bağlantı hatası.`);
            }
          });
          modelsListEl.appendChild(item);
        });
      }
    } catch (_) {}
  }

  // Çoklu Görsel Seçme, Önizleme ve Kaldırma
  function renderPendingImages() {
    if (pendingImages.length === 0) {
      imagePreviewBar.classList.add("hidden");
      previewThumbsList.innerHTML = "";
      return;
    }
    imagePreviewBar.classList.remove("hidden");
    previewCountLabel.textContent = `${pendingImages.length} görsel hazır`;
    previewThumbsList.innerHTML = "";

    pendingImages.forEach((b64, index) => {
      const wrap = document.createElement("div");
      wrap.className = "preview-thumb-item";
      wrap.innerHTML = `
        <img src="${b64}" alt="Görsel ${index + 1}" />
        <button type="button" class="remove-img-btn" data-idx="${index}">✕</button>
      `;
      wrap.querySelector(".remove-img-btn").addEventListener("click", () => {
        pendingImages.splice(index, 1);
        renderPendingImages();
      });
      previewThumbsList.appendChild(wrap);
    });
  }

  attachImgBtn.addEventListener("click", () => {
    imageFileInput.click();
  });

  clearImagesBtn.addEventListener("click", () => {
    pendingImages = [];
    renderPendingImages();
  });

  imageFileInput.addEventListener("change", (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;

    files.forEach((file) => {
      const reader = new FileReader();
      reader.onload = (ev) => {
        const img = new Image();
        img.onload = () => {
          const maxDim = 1500;
          let w = img.width;
          let h = img.height;
          if (w > maxDim || h > maxDim) {
            if (w > h) {
              h = Math.round((h * maxDim) / w);
              w = maxDim;
            } else {
              w = Math.round((w * maxDim) / h);
              h = maxDim;
            }
          }
          const canvas = document.createElement("canvas");
          canvas.width = w;
          canvas.height = h;
          const ctx = canvas.getContext("2d");
          ctx.drawImage(img, 0, 0, w, h);
          pendingImages.push(canvas.toDataURL("image/jpeg", 0.85));
          renderPendingImages();
        };
        img.src = ev.target.result;
      };
      reader.readAsDataURL(file);
    });
    imageFileInput.value = "";
  });

  async function loadStatus() {
    const st = await apiFetch("/api/status");
    if (st.window_found) {
      pcWindowBadge.textContent = `● Pencere: ${st.window_title}`;
    } else if (st.calibrated) {
      pcWindowBadge.textContent = `● Hedeflenmiş Sohbet Kutusu Aktif`;
    } else {
      pcWindowBadge.textContent = `○ Antigravity penceresi bekleniyor`;
    }
    if (!activeConversationId && st.active_conversation_id) {
      activeConversationId = st.active_conversation_id;
    }
    return st;
  }

  async function loadConversationsList() {
    const data = await apiFetch("/api/conversations");
    const convs = data.conversations || [];
    convListEl.innerHTML = "";

    if (!activeConversationId && data.active_id) {
      activeConversationId = data.active_id;
    }

    convs.forEach((c) => {
      const item = document.createElement("div");
      item.className = "conv-item" + (c.id === activeConversationId ? " active" : "");
      item.innerHTML = `
        <div class="conv-item-title">${escapeHtml(c.title)}</div>
        <div class="conv-item-sub">${escapeHtml(c.last_message || "Mesaj yok")}</div>
      `;
      item.addEventListener("click", () => {
        activeConversationId = c.id;
        renderedStepsHash = "";
        currentConvTitle.textContent = c.title;
        closeDrawer();
        loadConversationSteps(c.id, true);
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ action: "select_conversation", conversation_id: c.id }));
        }
      });
      convListEl.appendChild(item);
    });

    if (convs.length > 0 && activeConversationId) {
      const activeObj = convs.find((x) => x.id === activeConversationId) || convs[0];
      currentConvTitle.textContent = activeObj.title;
    }
  }

  async function loadConversationSteps(convId, forceScroll = false) {
    if (!convId) return;
    const data = await apiFetch(`/api/conversations/${convId}`);
    renderConversationData(data, forceScroll);
  }

  function renderToolCardHtml(tc) {
    const isCmd = tc.kind === "command";
    const prefix = isCmd ? "$ " : "▸ ";
    const label = isCmd ? (tc.command || tc.title) : tc.title;
    const tagText =
      tc.exit_code !== null && tc.exit_code !== undefined
        ? `Exit ${tc.exit_code}`
        : tc.name;

    let bodyHtml = "";
    if (tc.command) {
      bodyHtml += `<span class="cmd-line-code">$ ${escapeHtml(tc.command)}</span>`;
    }
    if (tc.file_path) {
      bodyHtml += `<div style="margin-bottom:6px;"><button type="button" class="file-link-chip" data-filepath="${escapeHtml(tc.file_path)}">📄 ${escapeHtml(tc.file_path.split(/[\\/]/).pop())} (Görüntüle / Düzenle)</button></div>`;
    }
    if (tc.output) {
      bodyHtml += escapeHtml(tc.output);
    } else {
      bodyHtml += "Çıktı yok";
    }

    return `
      <details class="cmd-card">
        <summary>
          <span class="cmd-summary-left">${prefix}${escapeHtml(label)}</span>
          <span class="cmd-tag">${escapeHtml(tagText)}</span>
        </summary>
        <div class="cmd-output-box">${bodyHtml}</div>
      </details>
    `;
  }

  // Çoktan Seçmeli Soru Kartı Oluşturucu (ask_question desteği - çoklu soruyu tek kartta birleştirir)
  function createQuestionCardElement(questionsArray) {
    const qList = Array.isArray(questionsArray) ? questionsArray : [questionsArray];
    const wrap = document.createElement("div");
    wrap.className = "question-card";
    const selectionsPerQuestion = qList.map(() => new Set());

    const firstQ = qList[0] || {};
    if (firstQ.answered && firstQ.answer_text) {
      const ansBox = document.createElement("div");
      ansBox.className = "question-answered-box";
      ansBox.textContent = `✓ Yanıtlandı: ${firstQ.answer_text.replace(/\s+/g, " ").slice(0, 140)}`;
      wrap.appendChild(ansBox);
    }

    qList.forEach((qObj, qIdx) => {
      const isMulti = Boolean(qObj.is_multi_select);
      const selectedSet = selectionsPerQuestion[qIdx];

      const sec = document.createElement("div");
      sec.style.display = "flex";
      sec.style.flexDirection = "column";
      sec.style.gap = "8px";
      if (qIdx > 0) {
        sec.style.borderTop = "1px solid #242424";
        sec.style.paddingTop = "10px";
      }

      sec.innerHTML = `
        <div class="question-header-row">
          <span class="question-badge">${qList.length > 1 ? `SORU ${qIdx + 1}` : "SORU & SEÇENEKLER"}</span>
          <span class="question-hint">${isMulti ? "Birden fazla seçebilirsiniz" : "Bir seçenek belirleyin"}</span>
        </div>
        <div class="question-title">${escapeHtml(qObj.question)}</div>
        <div class="question-options"></div>
      `;

      const optsContainer = sec.querySelector(".question-options");
      const optionsList = Array.isArray(qObj.options) ? qObj.options : [];
      optionsList.forEach((optText) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "question-opt-btn";
        const updateBtnVisual = () => {
          const isSel = selectedSet.has(optText);
          btn.classList.toggle("selected", isSel);
          const icon = isMulti ? (isSel ? "☑" : "☐") : (isSel ? "●" : "○");
          btn.innerHTML = `<span class="question-opt-check">${icon}</span><span>${escapeHtml(optText)}</span>`;
        };
        updateBtnVisual();

        btn.addEventListener("click", () => {
          if (!isMulti) {
            selectedSet.clear();
            selectedSet.add(optText);
            Array.from(optsContainer.children).forEach((c) => {
              c.classList.remove("selected");
              const chk = c.querySelector(".question-opt-check");
              if (chk) chk.textContent = "○";
            });
            updateBtnVisual();
          } else {
            if (selectedSet.has(optText)) {
              selectedSet.delete(optText);
            } else {
              selectedSet.add(optText);
            }
            updateBtnVisual();
          }
        });

        optsContainer.appendChild(btn);
      });

      wrap.appendChild(sec);
    });

    const footerDiv = document.createElement("div");
    footerDiv.style.display = "flex";
    footerDiv.style.flexDirection = "column";
    footerDiv.style.gap = "8px";
    footerDiv.innerHTML = `
      <div class="question-custom-row">
        <input type="text" class="question-custom-input" placeholder="Ek açıklama veya farklı yanıt yazın (isteğe bağlı)..." />
      </div>
      <button type="button" class="question-submit-btn">Seçimi Gönder ↵</button>
    `;
    wrap.appendChild(footerDiv);

    const customInput = footerDiv.querySelector(".question-custom-input");
    const submitBtn = footerDiv.querySelector(".question-submit-btn");

    submitBtn.addEventListener("click", async () => {
      const chosen = [];
      selectionsPerQuestion.forEach((setObj) => {
        setObj.forEach((val) => chosen.push(val));
      });
      const customVal = customInput.value.trim();
      if (chosen.length === 0 && !customVal) {
        alert("Lütfen en az bir şık seçin veya yanıt yazın.");
        return;
      }
      submitBtn.disabled = true;
      submitBtn.textContent = "PC'ye İletiliyor...";
      try {
        const res = await apiFetch("/api/answer_question", {
          method: "POST",
          body: JSON.stringify({
            selected_options: chosen,
            options: chosen,
            custom_text: customVal,
          }),
        });
        if (res.ok) {
          submitBtn.textContent = "✓ Yanıt Gönderildi";
          workingIndicator.classList.remove("hidden");
        } else {
          submitBtn.disabled = false;
          submitBtn.textContent = "Seçimi Gönder ↵";
          alert(res.error || "Yanıt gönderilemedi.");
        }
      } catch (e) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Seçimi Gönder ↵";
        alert("Bağlantı hatası.");
      }
    });

    return wrap;
  }

  function updateWorkingState(isWorking, activeModelText) {
    if (workingTimeoutId) {
      clearTimeout(workingTimeoutId);
      workingTimeoutId = null;
    }
    if (isWorking) {
      workingIndicator.classList.remove("hidden");
      wsDot.className = "status-dot working";
      statusText.textContent = "Yanıt hazırlıyor...";
      // 25 saniye boyunca yeni adım gelmezse takılı kalmasını önle
      workingTimeoutId = setTimeout(() => {
        workingIndicator.classList.add("hidden");
        wsDot.className = "status-dot online";
        statusText.textContent = activeModelText || "Canlı";
      }, 25000);
    } else {
      workingIndicator.classList.add("hidden");
      wsDot.className = "status-dot online";
      statusText.textContent = activeModelText || "Canlı";
    }
  }

  function renderConversationData(data, forceScroll = false) {
    const steps = data.steps || [];
    const commands = data.commands || [];
    const artifacts = data.artifacts || [];
    const isWorking = Boolean(data.is_working);
    const usage = data.usage || {};

    topLimitBadge.textContent = `Limit %${usage.context_percent || 0}`;
    cmdCountBadge.textContent = String(commands.length);

    // 1. Çalışıyor göstergesini her zaman anında güncelle (asla takılı kalmaz!)
    updateWorkingState(isWorking, usage.active_model || "Canlı");

    // Canlı sohbet yanıt kontrolü ve otomatik sesli okuma (hash kontrolünden ÖNCE çalışmalı)
    checkLiveResponse(data);
    latestConvData = data;
    if (autoTtsEnabled && !live.active && !isWorking && steps.length > 0) {
      const lastStep = steps[steps.length - 1];
      const speakKey = `${lastStep.step_index}:${(lastStep.content || "").length}`;
      if (lastSpokenStepIndex === -1) {
        // Sayfa ilk açıldığında eski mesajı okuma
        lastSpokenStepIndex = speakKey;
      } else if (
        lastStep.role === "assistant" &&
        lastStep.content &&
        speakKey !== lastSpokenStepIndex
      ) {
        lastSpokenStepIndex = speakKey;
        speakText(lastStep.content);
      }
    }

    // 2. Değişiklik kontrolü (Soru kartları dahil)
    const newHash = JSON.stringify(
      steps.map((s) => [
        s.step_index,
        s.content?.length || 0,
        s.tool_calls?.length || 0,
        s.questions?.length || 0,
        s.questions?.map((q) => q.answered) || [],
      ])
    );
    if (newHash === renderedStepsHash && !forceScroll) {
      return;
    }

    // Komutlar Sekmesini Güncelle
    commandsListEl.innerHTML = "";
    if (commands.length === 0) {
      commandsListEl.innerHTML = `<div style="color:#737373;padding:18px;text-align:center;font-size:0.8rem;">Henüz çalıştırılan komut yok.</div>`;
    } else {
      commands.slice().reverse().forEach((cmd) => {
        const wrap = document.createElement("div");
        wrap.innerHTML = renderToolCardHtml(cmd);
        commandsListEl.appendChild(wrap.firstElementChild);
      });
    }

    if (artifacts.length > 0) {
      artifactsBar.classList.remove("hidden");
      artifactsBar.innerHTML = "";
      artifacts.forEach((art) => {
        const pill = document.createElement("button");
        pill.className = "artifact-pill";
        pill.textContent = `📄 ${art.name}`;
        pill.addEventListener("click", () => openArtifact(data.id, art.name));
        artifactsBar.appendChild(pill);
      });
    } else {
      artifactsBar.classList.add("hidden");
    }

    const wasNearBottom =
      chatContainer.scrollHeight - chatContainer.scrollTop - chatContainer.clientHeight < 150;

    renderedStepsHash = newHash;

    if (steps.length === 0) {
      emptyState.classList.remove("hidden");
      messagesList.innerHTML = "";
      return;
    }

    emptyState.classList.add("hidden");
    messagesList.innerHTML = "";

    steps.forEach((step) => {
      const card = document.createElement("div");
      card.className = `msg-card ${step.role}`;

      const senderLabel = step.role === "user" ? "SEN" : "ANTIGRAVITY";
      const metaRow = document.createElement("div");
      metaRow.className = "msg-meta-row";
      metaRow.innerHTML = `<span class="msg-meta">${senderLabel}</span>`;

      if (step.role === "assistant" && step.content) {
        const speakBtn = document.createElement("button");
        speakBtn.type = "button";
        speakBtn.className = "speak-msg-btn";
        speakBtn.textContent = "🔊 Dinle";
        speakBtn.addEventListener("click", () => speakText(step.content, speakBtn));
        metaRow.appendChild(speakBtn);
      }
      card.appendChild(metaRow);

      // Düşünce ve çalıştırılan araçları tek bir kompakt akordeon altında topla (kalabalığı önler)
      if (step.role === "assistant") {
        const toolCount = step.tool_calls ? step.tool_calls.length : 0;
        const hasThinking = Boolean(step.thinking);
        if (hasThinking || toolCount > 0) {
          const activityDetails = document.createElement("details");
          activityDetails.className = "step-activity-group";
          const summaryParts = [];
          if (hasThinking) summaryParts.push("Düşünce");
          if (toolCount > 0) summaryParts.push(`${toolCount} işlem`);

          let innerItemsHtml = "";
          if (hasThinking) {
            innerItemsHtml += `
              <details class="thinking-box">
                <summary>
                  <span class="cmd-summary-left">Düşünce Özeti</span>
                  <span class="cmd-tag">THINK</span>
                </summary>
                <div class="thinking-content">${escapeHtml(step.thinking)}</div>
              </details>
            `;
          }
          if (toolCount > 0) {
            step.tool_calls.forEach((tc) => {
              innerItemsHtml += renderToolCardHtml(tc);
            });
          }

          activityDetails.innerHTML = `
            <summary>
              <span class="cmd-summary-left">▸ İşlem Detayları (${summaryParts.join(" • ")})</span>
              <span class="cmd-tag">DETAY</span>
            </summary>
            <div class="step-activity-body">${innerItemsHtml}</div>
          `;
          card.appendChild(activityDetails);
        }
      }

      let bubbleContent = "";
      if (step.images && step.images.length > 0) {
        const imgsHtml = step.images
          .map((imgPath) => {
            const rawUrl = `/api/raw_file?path=${encodeURIComponent(imgPath)}&token=${encodeURIComponent(authToken)}`;
            return `<img src="${rawUrl}" class="sent-img-thumb" alt="Görsel" />`;
          })
          .join("");
        bubbleContent += `<div class="sent-images-grid">${imgsHtml}</div>`;
      }

      if (step.content) {
        bubbleContent +=
          step.role === "assistant"
            ? renderMarkdown(step.content)
            : `<p>${escapeHtml(step.content).replace(/\n/g, "<br/>")}</p>`;
      }

      if (bubbleContent) {
        const bubbleEl = document.createElement("div");
        bubbleEl.className = "msg-bubble markdown-body";
        bubbleEl.innerHTML = bubbleContent;
        card.appendChild(bubbleEl);
      }

      // Çoktan Seçmeli Sorular (ask_question) varsa etkileşimli şık kartını ekle
      if (step.questions && step.questions.length > 0) {
        card.appendChild(createQuestionCardElement(step.questions));
      }

      messagesList.appendChild(card);
    });

    if (forceScroll || wasNearBottom) {
      setTimeout(() => {
        chatContainer.scrollTop = chatContainer.scrollHeight;
      }, 40);
    }
  }

  async function openArtifact(convId, filename) {
    try {
      const res = await apiFetch(`/api/artifacts/${convId}/${encodeURIComponent(filename)}`);
      if (res.ok) {
        currentEditingFilePath = "";
        fileModalTitle.textContent = res.name;
        fileModalMeta.textContent = "Artifact";
        saveFileBtn.classList.add("hidden");
        copyFileBtn.classList.remove("hidden");
        fileImageContainer.classList.add("hidden");
        fileEditorTextarea.classList.remove("hidden");
        fileEditorTextarea.value = res.content || "";
        fileModal.classList.remove("hidden");
      }
    } catch (e) {
      alert("Artifact okunamadı.");
    }
  }

  async function sendMessage() {
    if (isRecordingMic && recognition) {
      try { recognition.stop(); } catch (_) {}
    }
    const text = messageInput.value.trim();
    const imagesToSend = pendingImages.slice();

    if (!text && imagesToSend.length === 0) return;

    messageInput.value = "";
    messageInput.style.height = "auto";
    pendingImages = [];
    renderPendingImages();

    emptyState.classList.add("hidden");
    const tempCard = document.createElement("div");
    tempCard.className = "msg-card user";
    let bubbleHtml = "";
    if (imagesToSend.length > 0) {
      const thumbs = imagesToSend
        .map((src) => `<img src="${src}" class="sent-img-thumb" alt="Görsel" />`)
        .join("");
      bubbleHtml += `<div class="sent-images-grid">${thumbs}</div>`;
    }
    if (text) {
      bubbleHtml += `<p>${escapeHtml(text).replace(/\n/g, "<br/>")}</p>`;
    }
    tempCard.innerHTML = `<div class="msg-meta-row"><span class="msg-meta">SEN</span></div><div class="msg-bubble">${bubbleHtml}</div>`;
    messagesList.appendChild(tempCard);
    updateWorkingState(true);
    chatContainer.scrollTop = chatContainer.scrollHeight;

    try {
      let res;
      if (imagesToSend.length > 0) {
        res = await apiFetch("/api/send_image", {
          method: "POST",
          body: JSON.stringify({
            images: imagesToSend,
            message: text,
            conversation_id: activeConversationId,
          }),
        });
      } else {
        res = await apiFetch("/api/send", {
          method: "POST",
          body: JSON.stringify({
            message: text,
            conversation_id: activeConversationId,
          }),
        });
      }
      if (!res.ok) {
        updateWorkingState(false);
        alert(res.error || "İletilemedi.");
      }
    } catch (e) {
      updateWorkingState(false);
      alert("Bağlantı hatası: Gönderilemedi.");
    }
  }

  sendBtn.addEventListener("click", sendMessage);

  messageInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  messageInput.addEventListener("input", () => {
    messageInput.style.height = "auto";
    messageInput.style.height = Math.min(messageInput.scrollHeight, 110) + "px";
  });

  document.querySelectorAll(".action-chip").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const action = btn.getAttribute("data-action");
      await apiFetch("/api/action", {
        method: "POST",
        body: JSON.stringify({ action }),
      });
    });
  });

  document.querySelectorAll(".slash-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const slash = btn.getAttribute("data-slash");
      if (slash === "/compact") {
        messageInput.value = "/compact";
        sendMessage();
      } else {
        messageInput.value = slash + messageInput.value;
        messageInput.focus();
      }
    });
  });

  refreshBtn.addEventListener("click", async () => {
    renderedStepsHash = "";
    await loadStatus();
    await loadConversationsList();
    if (activeConversationId) {
      await loadConversationSteps(activeConversationId, true);
    }
  });

  function connectWebSocket() {
    if (ws) {
      try { ws.close(); } catch (_) {}
    }
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${proto}//${window.location.host}/ws?token=${encodeURIComponent(authToken)}`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      wsDot.className = "status-dot online";
      statusText.textContent = "Canlı";
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.event === "auth_required") {
          showPinScreen();
          return;
        }
        if (msg.event === "conversation_update") {
          if (!activeConversationId || msg.conversation_id === activeConversationId) {
            activeConversationId = msg.conversation_id;
            renderConversationData(msg.data, false);
          }
        }
      } catch (_) {}
    };

    ws.onclose = () => {
      wsDot.className = "status-dot offline";
      statusText.textContent = "Bağlanıyor...";
      setTimeout(connectWebSocket, 2500);
    };
  }

  async function initApp() {
    try {
      await loadStatus();
      await loadConversationsList();
      if (activeConversationId) {
        await loadConversationSteps(activeConversationId, true);
      }
      connectWebSocket();
    } catch (e) {}
  }

  initApp();
})();
