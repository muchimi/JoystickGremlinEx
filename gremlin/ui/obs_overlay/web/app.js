(() => {
  "use strict";

  const FIT_MODES = ["contain", "cover", "stretch"];
  const FRAME_MS = 33;
  const HOLD_MS = 1000;
  const HOLD_MOVE_PX = 12;
  const isMobile =
    window.matchMedia("(pointer: coarse)").matches ||
    /iPhone|iPad|iPod|Android/i.test(navigator.userAgent || "");

  const frameEl = document.getElementById("frame");
  const hitEl = document.getElementById("hit");
  const offlineEl = document.getElementById("offline");
  const statusEl = document.getElementById("status");
  const btnFs = document.getElementById("btn-fs");
  const btnFit = document.getElementById("btn-fit");

  let session = null;
  let ws = null;
  let fitMode = "contain";
  let canvasW = 1280;
  let canvasH = 720;
  let objectUrl = null;
  let reconnectTimer = null;
  let hideToolbarTimer = null;
  let holdTimer = null;
  let holdToken = 0;
  let holdStart = null;
  let pollTimer = null;
  let lastSeq = "";
  let live = false;
  let offline = false;
  let missStreak = 0;
  const MISS_BEFORE_OFFLINE = 6;

  function setStatus(text, cls) {
    statusEl.textContent = text;
    statusEl.className = "badge" + (cls ? " " + cls : "");
  }

  function clearFrame() {
    frameEl.onload = null;
    frameEl.removeAttribute("src");
    frameEl.style.opacity = "0";
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl);
      objectUrl = null;
    }
  }

  function showOffline() {
    if (offline) {
      setStatus("JG Ex Offline", "bad");
      return;
    }
    offline = true;
    live = false;
    missStreak = 0;
    clearFrame();
    stopPolling();
    if (ws) {
      try {
        ws.onclose = null;
        ws.close();
      } catch (_) {}
      ws = null;
    }
    if (offlineEl) offlineEl.hidden = false;
    setStatus("JG Ex Offline", "bad");
    scheduleReconnect();
  }

  function hideOffline() {
    if (!offline) return;
    offline = false;
    if (offlineEl) offlineEl.hidden = true;
  }

  function applyFit() {
    frameEl.style.objectFit = fitMode === "stretch" ? "fill" : fitMode;
    btnFit.textContent = "Fit: " + fitMode;
    layoutHit();
  }

  function cycleFit() {
    const i = FIT_MODES.indexOf(fitMode);
    fitMode = FIT_MODES[(i + 1) % FIT_MODES.length];
    applyFit();
  }

  function layoutHit() {
    const stage = document.getElementById("stage");
    const sw = stage.clientWidth;
    const sh = stage.clientHeight;
    let dw = sw;
    let dh = sh;
    let ox = 0;
    let oy = 0;
    if (fitMode === "contain") {
      const scale = Math.min(sw / canvasW, sh / canvasH);
      dw = canvasW * scale;
      dh = canvasH * scale;
      ox = (sw - dw) / 2;
      oy = (sh - dh) / 2;
    } else if (fitMode === "cover") {
      const scale = Math.max(sw / canvasW, sh / canvasH);
      dw = canvasW * scale;
      dh = canvasH * scale;
      ox = (sw - dw) / 2;
      oy = (sh - dh) / 2;
    }
    hitEl.style.left = ox + "px";
    hitEl.style.top = oy + "px";
    hitEl.style.width = dw + "px";
    hitEl.style.height = dh + "px";
    hitEl.width = Math.max(1, Math.round(dw));
    hitEl.height = Math.max(1, Math.round(dh));
  }

  function eventToCanvas(ev) {
    const rect = hitEl.getBoundingClientRect();
    const x = ((ev.clientX - rect.left) / Math.max(1, rect.width)) * canvasW;
    const y = ((ev.clientY - rect.top) / Math.max(1, rect.height)) * canvasH;
    return {
      x: Math.max(0, Math.min(canvasW, x)),
      y: Math.max(0, Math.min(canvasH, y)),
    };
  }

  function sendInput(event, ev) {
    const pt = eventToCanvas(ev);
    const pointerId = ev.pointerId != null ? String(ev.pointerId) : "0";
    const payload = {
      type: "input",
      event,
      x: pt.x,
      y: pt.y,
      buttons: ev.buttons || 0,
      pointerId,
      t_client: performance.now(),
    };
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
      return pt;
    }
    fetch("/api/input", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => {});
    return pt;
  }

  function clearHoldTimer() {
    if (holdTimer) {
      clearTimeout(holdTimer);
      holdTimer = null;
    }
    holdStart = null;
    holdToken += 1;
  }

  async function probeEmpty(x, y) {
    try {
      const res = await fetch(
        "/api/hit?x=" + encodeURIComponent(x) + "&y=" + encodeURIComponent(y),
        { cache: "no-store" }
      );
      if (!res.ok) return true;
      const data = await res.json();
      return !!data.empty;
    } catch (_) {
      return true;
    }
  }

  function showToolbar() {
    document.body.classList.remove("toolbar-hidden");
    clearTimeout(hideToolbarTimer);
    hideToolbarTimer = setTimeout(() => {
      if (isMobile || isFsActive()) {
        document.body.classList.add("toolbar-hidden");
      }
    }, 4000);
  }

  function hideToolbar() {
    clearTimeout(hideToolbarTimer);
    hideToolbarTimer = null;
    document.body.classList.add("toolbar-hidden");
  }

  function bindHit() {
    const onDown = (ev) => {
      const pt = sendInput("down", ev);
      hitEl.setPointerCapture(ev.pointerId);
      ev.preventDefault();

      if (!isMobile) {
        showToolbar();
        return;
      }

      // Mobile: hide chrome on any touch; only re-show after 1s on empty space.
      hideToolbar();
      clearHoldTimer();
      const token = holdToken;
      holdStart = { x: ev.clientX, y: ev.clientY, cx: pt.x, cy: pt.y };
      holdTimer = setTimeout(async () => {
        holdTimer = null;
        if (token !== holdToken || !holdStart) return;
        const empty = await probeEmpty(holdStart.cx, holdStart.cy);
        if (token !== holdToken) return;
        if (empty) showToolbar();
      }, HOLD_MS);
    };
    const onMove = (ev) => {
      if (ev.buttons || (ev.pointerType === "touch" && hitEl.hasPointerCapture(ev.pointerId))) {
        sendInput("move", ev);
        ev.preventDefault();
        if (holdStart) {
          const dx = ev.clientX - holdStart.x;
          const dy = ev.clientY - holdStart.y;
          if (dx * dx + dy * dy > HOLD_MOVE_PX * HOLD_MOVE_PX) {
            clearHoldTimer();
          }
        }
      }
    };
    const onUp = (ev) => {
      sendInput("up", ev);
      clearHoldTimer();
      try {
        hitEl.releasePointerCapture(ev.pointerId);
      } catch (_) {}
      ev.preventDefault();
    };
    hitEl.addEventListener("pointerdown", onDown);
    hitEl.addEventListener("pointermove", onMove);
    hitEl.addEventListener("pointerup", onUp);
    hitEl.addEventListener("pointercancel", onUp);
  }

  function isFsActive() {
    return !!(
      document.fullscreenElement ||
      document.webkitFullscreenElement ||
      document.body.classList.contains("immersive")
    );
  }

  function isIPhoneOrIPod() {
    return /iPhone|iPod/i.test(navigator.userAgent || "");
  }

  function isIPad() {
    const ua = navigator.userAgent || "";
    if (/iPad/i.test(ua)) return true;
    // iPadOS desktop-class Safari reports as MacIntel with touch.
    return navigator.platform === "MacIntel" && (navigator.maxTouchPoints || 0) > 1;
  }

  function isStandaloneWebApp() {
    return (
      window.navigator.standalone === true ||
      window.matchMedia("(display-mode: standalone)").matches ||
      window.matchMedia("(display-mode: fullscreen)").matches
    );
  }

  function nativeFullscreenSupported() {
    const el = document.documentElement;
    return typeof (el.requestFullscreen || el.webkitRequestFullscreen) === "function";
  }

  function syncVisualViewport() {
    const vv = window.visualViewport;
    if (!vv) {
      document.documentElement.style.setProperty("--vv-top", "0px");
      document.documentElement.style.setProperty("--vv-left", "0px");
      document.documentElement.style.setProperty("--vv-width", "100%");
      document.documentElement.style.setProperty("--vv-height", "100%");
      return;
    }
    document.documentElement.style.setProperty("--vv-top", vv.offsetTop + "px");
    document.documentElement.style.setProperty("--vv-left", vv.offsetLeft + "px");
    document.documentElement.style.setProperty("--vv-width", vv.width + "px");
    document.documentElement.style.setProperty("--vv-height", vv.height + "px");
  }

  function enterImmersive() {
    syncVisualViewport();
    document.body.classList.add("immersive");
    // Nudge Safari's chrome to collapse when possible (best-effort on iPhone).
    try {
      window.scrollTo(0, 1);
      setTimeout(() => window.scrollTo(0, 0), 50);
    } catch (_) {}
    updateFsLabel();
    layoutHit();
  }

  function exitImmersive() {
    document.body.classList.remove("immersive");
    if (isMobile) hideToolbar();
    updateFsLabel();
    layoutHit();
  }

  async function requestNativeFullscreen(root) {
    const req = root.requestFullscreen || root.webkitRequestFullscreen;
    if (!req) return false;
    try {
      // navigationUI: "hide" asks the browser to drop system/browser chrome when supported.
      if (root.requestFullscreen) {
        await root.requestFullscreen({ navigationUI: "hide" });
      } else {
        await req.call(root);
      }
      return true;
    } catch (_) {
      try {
        await req.call(root);
        return true;
      } catch (_) {
        return false;
      }
    }
  }

  async function toggleFullscreen() {
    // iPhone/iPod only: element Fullscreen API is unavailable — CSS immersive fallback.
    // iPad supports native Fullscreen and that is what can hide the system status bar.
    if (!nativeFullscreenSupported() || isIPhoneOrIPod()) {
      if (document.body.classList.contains("immersive")) {
        exitImmersive();
      } else {
        enterImmersive();
      }
      return;
    }
    const root = document.documentElement;
    try {
      if (document.fullscreenElement || document.webkitFullscreenElement) {
        const exit = document.exitFullscreen || document.webkitExitFullscreen;
        if (exit) await exit.call(document);
      } else {
        const ok = await requestNativeFullscreen(root);
        if (!ok) enterImmersive();
      }
    } catch (_) {
      if (document.body.classList.contains("immersive")) exitImmersive();
      else enterImmersive();
    }
    updateFsLabel();
    layoutHit();
  }

  function updateFsLabel() {
    btnFs.textContent = isFsActive() ? "Exit fullscreen" : "Fullscreen";
  }

  function showFrameBlob(blob) {
    if (!blob || blob.size < 32) return;
    hideOffline();
    const url = URL.createObjectURL(blob);
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = url;
    frameEl.onload = () => {
      frameEl.style.opacity = "1";
    };
    frameEl.src = url;
    missStreak = 0;
    if (!live) {
      live = true;
      const via = ws && ws.readyState === WebSocket.OPEN ? "WS+HTTP" : "HTTP";
      setStatus("Live (" + via + ")", "ok");
    }
  }

  function noteFrameMiss() {
    missStreak += 1;
    if (live || missStreak >= MISS_BEFORE_OFFLINE) {
      showOffline();
    } else if (!live) {
      setStatus("Waiting for frames…", "warn");
    }
  }

  async function pollFrameOnce() {
    try {
      const res = await fetch("/frame.jpg?t=" + Date.now(), { cache: "no-store" });
      if (!res.ok) {
        noteFrameMiss();
        return;
      }
      const seq = res.headers.get("X-Gex-Frame-Seq") || "";
      if (seq && seq === lastSeq) {
        missStreak = 0;
        return;
      }
      lastSeq = seq;
      const blob = await res.blob();
      showFrameBlob(blob);
    } catch (_) {
      noteFrameMiss();
    }
  }

  function startPolling() {
    stopPolling();
    const tick = async () => {
      await pollFrameOnce();
      pollTimer = setTimeout(tick, FRAME_MS);
    };
    tick();
  }

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function connectWs(wsPort) {
    if (!wsPort) {
      setStatus("Live path: HTTP", "warn");
      return;
    }
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.hostname}:${wsPort}/`;
    try {
      ws = new WebSocket(url);
    } catch (_) {
      return;
    }
    ws.binaryType = "arraybuffer";
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "hello" }));
      ws.send(JSON.stringify({ type: "ready" }));
      if (live) setStatus("Live (WS+HTTP)", "ok");
    };
    ws.onclose = () => {
      ws = null;
      if (live && !offline) setStatus("Live (HTTP)", "warn");
    };
    ws.onerror = () => {};
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        let msg;
        try {
          msg = JSON.parse(ev.data);
        } catch (_) {
          return;
        }
        if (msg.type === "frame") {
          if (msg.w) canvasW = msg.w;
          if (msg.h) canvasH = msg.h;
          return;
        }
        if (msg.type === "hello" || msg.type === "ready") {
          if (msg.canvas_w) canvasW = msg.canvas_w;
          if (msg.canvas_h) canvasH = msg.canvas_h;
          if (msg.fit) {
            fitMode = msg.fit;
            applyFit();
          }
          layoutHit();
        }
        return;
      }
      showFrameBlob(new Blob([ev.data], { type: "image/jpeg" }));
    };
  }

  function scheduleReconnect() {
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(boot, 1500);
  }

  async function boot() {
    live = false;
    lastSeq = "";
    missStreak = 0;
    clearFrame();
    if (!offline) setStatus("Connecting…", "warn");
    else setStatus("JG Ex Offline", "bad");
    try {
      const res = await fetch("/api/session", { cache: "no-store" });
      if (!res.ok) throw new Error("session " + res.status);
      session = await res.json();
      canvasW = session.canvas_w || canvasW;
      canvasH = session.canvas_h || canvasH;
      fitMode = session.fit || "contain";
      applyFit();
      layoutHit();
      // Keep the offline screen up until the first real frame arrives.
      startPolling();
      connectWs(session.ws_port || 0);
      if (offline) setStatus("Reconnecting…", "warn");
      else setStatus("Waiting for frames…", "warn");
    } catch (err) {
      if (offline) {
        setStatus("JG Ex Offline", "bad");
        scheduleReconnect();
      } else {
        showOffline();
      }
    }
  }

  btnFs.addEventListener("click", (ev) => {
    ev.preventDefault();
    toggleFullscreen();
  });
  btnFit.addEventListener("click", cycleFit);
  const onFsChange = () => {
    updateFsLabel();
    syncVisualViewport();
    layoutHit();
    if (isFsActive() && isMobile) hideToolbar();
  };
  document.addEventListener("fullscreenchange", onFsChange);
  document.addEventListener("webkitfullscreenchange", onFsChange);
  window.addEventListener("resize", () => {
    syncVisualViewport();
    layoutHit();
  });
  window.addEventListener("orientationchange", () => {
    setTimeout(() => {
      syncVisualViewport();
      layoutHit();
    }, 150);
  });
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", () => {
      syncVisualViewport();
      layoutHit();
    });
    window.visualViewport.addEventListener("scroll", syncVisualViewport);
  }

  bindHit();
  syncVisualViewport();
  if (isMobile) hideToolbar();
  applyFit();
  // iPad in Safari: native Fullscreen is the only way to clear the system status bar.
  // Home Screen mode still keeps status glyphs (Apple limitation) — prefer Fullscreen button.
  if (isIPad() && !isStandaloneWebApp() && isMobile) {
    btnFs.title = "Fullscreen (hides iPad status bar)";
  }
  boot();
})();
