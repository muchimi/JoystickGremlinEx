let websocket = null;
let uuid = null;
let actionInfo = {};
let statusPollTimer = null;
let saveTimer = null;

function connectElgatoStreamDeckSocket(inPort, inUUID, inRegisterEvent, inInfo, inActionInfo) {
  uuid = inUUID;
  try {
    actionInfo = JSON.parse(inActionInfo);
  } catch (e) {
    actionInfo = {};
  }

  websocket = new WebSocket("ws://127.0.0.1:" + inPort);
  websocket.onopen = function () {
    websocket.send(JSON.stringify({ event: inRegisterEvent, uuid: uuid }));
    requestStatus();
    loadSettings();
    startStatusPoll();
    // Push current values to the plugin/GEX only — do NOT setSettings here.
    notifyPluginSettings();
  };
  websocket.onclose = function () {
    stopStatusPoll();
  };
  websocket.onmessage = function (evt) {
    const data = JSON.parse(evt.data);
    if (data.event === "sendToPropertyInspector" && data.payload) {
      if (data.payload.event === "connectionStatus") {
        setStatus(data.payload.connected, data.payload.host, data.payload.port);
      }
    } else if (data.event === "didReceiveSettings") {
      applySettings(data.payload.settings || {});
    }
  };

  ["buttonId", "page", "title"].forEach(function (id) {
    const el = document.getElementById(id);
    el.addEventListener("change", function () { saveSettings(true); });
    el.addEventListener("input", function () { saveSettings(false); });
  });
  document.getElementById("applyBridge").addEventListener("click", applyBridge);
}

function loadSettings() {
  const settings = (actionInfo.payload && actionInfo.payload.settings) || {};
  applySettings(settings);
  if (!settings.buttonId) {
    const coords = (actionInfo.payload && actionInfo.payload.coordinates) || {};
    if (coords.row != null && coords.column != null) {
      document.getElementById("buttonId").placeholder = String(coords.row) + ":" + String(coords.column);
    }
  }
}

function applySettings(settings) {
  if (settings.buttonId != null) {
    document.getElementById("buttonId").value = settings.buttonId;
  }
  if (settings.page != null && settings.page !== "") {
    document.getElementById("page").value = String(normalizePage(settings.page));
  } else if (!document.getElementById("page").value) {
    document.getElementById("page").value = "1";
  }
  if (settings.title != null) {
    document.getElementById("title").value = settings.title;
  }
}

function normalizePage(value) {
  const n = parseInt(value, 10);
  if (isNaN(n) || n < 1) return 1;
  if (n > 99) return 99;
  return n;
}

function currentSettings() {
  const coords = (actionInfo.payload && actionInfo.payload.coordinates) || {};
  let buttonId = (document.getElementById("buttonId").value || "").trim();
  if (!buttonId && coords.row != null && coords.column != null) {
    buttonId = String(coords.row) + ":" + String(coords.column);
  }
  return {
    buttonId: buttonId || "0",
    page: normalizePage(document.getElementById("page").value),
    title: document.getElementById("title").value || ""
  };
}

function notifyPluginSettings() {
  if (!websocket || websocket.readyState !== WebSocket.OPEN) return;
  const settings = currentSettings();
  const coords = (actionInfo.payload && actionInfo.payload.coordinates) || {};
  websocket.send(JSON.stringify({
    event: "sendToPlugin",
    context: uuid,
    action: actionUUID(),
    payload: {
      event: "settingsChanged",
      settings: settings,
      coordinates: coords,
      elgatoTitle: (actionInfo.payload && actionInfo.payload.title) || ""
    }
  }));
}

function saveSettings(immediate) {
  if (!websocket || websocket.readyState !== WebSocket.OPEN) return;
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  const run = function () {
    const settings = currentSettings();
    websocket.send(JSON.stringify({
      event: "setSettings",
      context: uuid,
      payload: settings
    }));
    notifyPluginSettings();
  };
  if (immediate) {
    run();
  } else {
    saveTimer = setTimeout(run, 250);
  }
}

function actionUUID() {
  return actionInfo.action || "com.joystickgremlin.ex.button";
}

function requestStatus() {
  if (!websocket || websocket.readyState !== WebSocket.OPEN) return;
  websocket.send(JSON.stringify({
    event: "sendToPlugin",
    context: uuid,
    action: actionUUID(),
    payload: { event: "getStatus" }
  }));
}

function startStatusPoll() {
  stopStatusPoll();
  statusPollTimer = setInterval(requestStatus, 2000);
}

function stopStatusPoll() {
  if (statusPollTimer) {
    clearInterval(statusPollTimer);
    statusPollTimer = null;
  }
}

function applyBridge() {
  if (!websocket) return;
  const host = document.getElementById("host").value || "127.0.0.1";
  const port = parseInt(document.getElementById("port").value, 10) || 9020;
  document.getElementById("status").textContent = "Connecting…";
  document.getElementById("status").className = "sdpi-item-value";
  websocket.send(JSON.stringify({
    event: "sendToPlugin",
    context: uuid,
    action: actionUUID(),
    payload: { event: "setBridge", host: host, port: port }
  }));
  setTimeout(requestStatus, 500);
  setTimeout(requestStatus, 1500);
}

function setStatus(connected, host, port) {
  const el = document.getElementById("status");
  if (connected) {
    el.textContent = "Connected to JG Ex";
    el.className = "sdpi-item-value ok";
  } else {
    el.textContent = "JG Ex not running / bridge offline";
    el.className = "sdpi-item-value err";
  }
  if (host) document.getElementById("host").value = host;
  if (port) document.getElementById("port").value = port;
}
