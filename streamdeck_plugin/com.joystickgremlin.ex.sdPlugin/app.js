/**
 * Joystick Gremlin Ex — Stream Deck plugin
 * Forwards key/dial events to GEX over localhost WebSocket (default ws://127.0.0.1:9020)
 */

const ACTION_BUTTON = "com.joystickgremlin.ex.button";
const ACTION_DIAL = "com.joystickgremlin.ex.dial";

let websocket = null;
let pluginUUID = null;
let gexSocket = null;
let gexConnected = false;
let reconnectTimer = null;
let gexConnectGeneration = 0;
let globalSettings = {
  host: "127.0.0.1",
  port: 9020
};

/** context -> { deviceId, buttonId, page, kind, title, row, column } */
const instances = {};
/** Open Property Inspector contexts awaiting connectionStatus */
const piContexts = {};
/** deviceId -> { name, type } from registration / deviceDidConnect */
const deviceInfoById = {};

/** Elgato DeviceType -> default label when the user has not renamed the deck. */
const DEVICE_TYPE_NAMES = {
  0: "Stream Deck",
  1: "Stream Deck Mini",
  2: "Stream Deck XL",
  3: "Stream Deck Mobile",
  4: "Corsair G Keys",
  5: "Stream Deck Pedal",
  7: "Stream Deck +",
  8: "Stream Deck+",
  9: "Stream Deck Neo"
};

function isWeakDeviceName(name) {
  if (!name) return true;
  const s = String(name).trim();
  if (!s) return true;
  // Our own previous fallbacks — treat as missing so type names can replace them.
  if (/^Stream Deck [0-9a-fA-F]{6,}$/.test(s)) return true;
  if (/^Stream Deck \([0-9a-fA-F]{6,}\)$/.test(s)) return true;
  return false;
}

function friendlyDeviceName(type, name, deviceId) {
  if (!isWeakDeviceName(name)) return String(name).trim();
  if (type !== undefined && type !== null && DEVICE_TYPE_NAMES[type] !== undefined) {
    return DEVICE_TYPE_NAMES[type];
  }
  try {
    const t = parseInt(type, 10);
    if (!isNaN(t) && DEVICE_TYPE_NAMES[t] !== undefined) return DEVICE_TYPE_NAMES[t];
  } catch (e) { /* ignore */ }
  if (deviceId) return "Stream Deck (" + String(deviceId).slice(0, 8) + ")";
  return "Stream Deck";
}

function rememberDevice(deviceId, name, type) {
  if (!deviceId) return null;
  const prev = deviceInfoById[deviceId] || {};
  const resolvedType = (type !== undefined && type !== null && type !== "")
    ? type
    : prev.type;
  const resolvedName = friendlyDeviceName(resolvedType, name || prev.name, deviceId);
  deviceInfoById[deviceId] = { name: resolvedName, type: resolvedType };
  return deviceInfoById[deviceId];
}

function cacheDevicesFromInfo(inInfo) {
  try {
    const info = typeof inInfo === "string" ? JSON.parse(inInfo) : inInfo;
    const devices = (info && info.devices) || [];
    devices.forEach(function (d) {
      if (!d || !d.id) return;
      rememberDevice(d.id, d.name, d.type);
    });
  } catch (e) { /* ignore */ }
}

function announceDevicesToGex() {
  Object.keys(deviceInfoById).forEach(function (deviceId) {
    const info = deviceInfoById[deviceId] || {};
    sendToGex({
      type: "device",
      action: "connected",
      deviceId: deviceId,
      name: info.name || friendlyDeviceName(info.type, null, deviceId),
      deviceType: (info.type !== undefined && info.type !== null) ? info.type : ""
    });
  });
}

function connectElgatoStreamDeckSocket(inPort, inPluginUUID, inRegisterEvent, inInfo) {
  pluginUUID = inPluginUUID;
  cacheDevicesFromInfo(inInfo);
  websocket = new WebSocket("ws://127.0.0.1:" + inPort);

  websocket.onopen = function () {
    websocket.send(JSON.stringify({
      event: inRegisterEvent,
      uuid: inPluginUUID
    }));
    getGlobalSettings();
    connectToGex();
    logToElgato("JGEx plugin registered uuid=" + pluginUUID);
  };

  websocket.onmessage = function (evt) {
    const data = JSON.parse(evt.data);
    const event = data.event;
    const payload = data.payload || {};
    const context = data.context;
    const action = data.action;
    const device = data.device;

    switch (event) {
      case "keyDown":
        handleKey(context, device, true, payload);
        break;
      case "keyUp":
        handleKey(context, device, false, payload);
        break;
      case "dialRotate":
        handleDialRotate(context, device, payload);
        break;
      case "dialDown":
        sendToGex({
          type: "dialDown",
          ...instancePayload(context, device, payload, "dial_press")
        });
        break;
      case "dialUp":
        sendToGex({
          type: "dialUp",
          ...instancePayload(context, device, payload, "dial_press")
        });
        break;
      case "willAppear":
        handleWillAppear(context, action, device, payload);
        break;
      case "willDisappear":
        handleWillDisappear(context, device, payload);
        break;
      case "didReceiveSettings":
        updateInstanceFromSettings(context, device, payload);
        pushInstanceToGex(context);
        break;
      case "titleParametersDidChange":
        // Native Stream Deck key title (what the user edits on the key art).
        if (context) {
          const prev = instances[context] || { deviceId: device, kind: "button" };
          prev.deviceId = device || prev.deviceId;
          if (payload && payload.title != null) {
            prev.elgatoTitle = String(payload.title);
            prev.elgatoTitleUpdated = Date.now();
          }
          if (payload && payload.settings) {
            prev.buttonId = resolveButtonId(payload.settings, payload);
            // Do NOT copy settings.title into titleHint here — it is often stale
            // relative to payload.title and was blocking live title sync to GEX.
          }
          if (payload && payload.coordinates) {
            prev.row = payload.coordinates.row;
            prev.column = payload.coordinates.column;
          }
          instances[context] = prev;
          pushInstanceToGex(context);
          logToElgato("JGEx titleParameters title=" + displayTitle(prev) + " buttonId=" + prev.buttonId);
        }
        break;
      case "didReceiveGlobalSettings":
        if (payload.settings) {
          globalSettings.host = payload.settings.host || "127.0.0.1";
          globalSettings.port = parseInt(payload.settings.port, 10) || 9020;
          connectToGex();
        }
        break;
      case "deviceDidConnect":
        if (device) {
          const di = payload.deviceInfo || {};
          const remembered = rememberDevice(device, di.name, di.type);
          sendToGex({
            type: "device",
            action: "connected",
            deviceId: device,
            name: remembered.name,
            deviceType: (remembered.type !== undefined && remembered.type !== null) ? remembered.type : ""
          });
        }
        break;
      case "deviceDidDisconnect":
        sendToGex({
          type: "device",
          action: "disconnected",
          deviceId: device
        });
        break;
      case "sendToPlugin":
        if (payload && payload.event === "getStatus") {
          const act = action || (instances[context] && instances[context].action) || ACTION_BUTTON;
          if (context) {
            piContexts[context] = act;
          }
          sendToPropertyInspector(context, act, {
            event: "connectionStatus",
            connected: gexConnected,
            host: globalSettings.host,
            port: globalSettings.port
          });
        } else if (payload && payload.event === "setBridge") {
          globalSettings.host = payload.host || "127.0.0.1";
          globalSettings.port = parseInt(payload.port, 10) || 9020;
          setGlobalSettings();
          connectToGex();
        } else if (payload && payload.event === "settingsChanged" && context) {
          // PI pushes live edits immediately (does not wait for didReceiveSettings).
          updateInstanceFromSettings(context, device, {
            settings: payload.settings || {},
            coordinates: payload.coordinates || (instances[context] && {
              row: instances[context].row,
              column: instances[context].column
            }) || {}
          });
          if (payload.elgatoTitle != null && payload.elgatoTitle !== "") {
            instances[context].elgatoTitle = String(payload.elgatoTitle);
            instances[context].elgatoTitleUpdated = Date.now();
          }
          pushInstanceToGex(context);
          logToElgato("JGEx PI settingsChanged buttonId=" + (instances[context] && instances[context].buttonId) +
            " title=" + displayTitle(instances[context]));
        }
        break;
      default:
        break;
    }
  };
}

function getGlobalSettings() {
  if (!websocket) return;
  websocket.send(JSON.stringify({
    event: "getGlobalSettings",
    context: pluginUUID
  }));
}

function setGlobalSettings() {
  if (!websocket) return;
  websocket.send(JSON.stringify({
    event: "setGlobalSettings",
    context: pluginUUID,
    payload: globalSettings
  }));
}

function sendToPropertyInspector(context, action, payload) {
  if (!websocket) return;
  websocket.send(JSON.stringify({
    event: "sendToPropertyInspector",
    context: context,
    action: action,
    payload: payload
  }));
}

function connectToGex() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  // Bump generation so a superseded socket's onclose does not schedule another reconnect.
  const myGen = ++gexConnectGeneration;
  if (gexSocket) {
    try {
      gexSocket.onopen = null;
      gexSocket.onclose = null;
      gexSocket.onerror = null;
      gexSocket.onmessage = null;
      gexSocket.close();
    } catch (e) { /* ignore */ }
    gexSocket = null;
  }

  const url = "ws://" + globalSettings.host + ":" + globalSettings.port;
  try {
    gexSocket = new WebSocket(url);
  } catch (e) {
    gexConnected = false;
    broadcastStatus();
    scheduleReconnect();
    return;
  }

  gexSocket.onopen = function () {
    if (myGen !== gexConnectGeneration) return;
    gexConnected = true;
    broadcastStatus();
    sendToGex({ type: "hello", client: "streamdeck-plugin", version: 1 });
    // Devices first (friendly Elgato / type names), then key instances.
    syncAllInstancesToGex();
  };

  gexSocket.onclose = function () {
    if (myGen !== gexConnectGeneration) return;
    gexConnected = false;
    gexSocket = null;
    broadcastStatus();
    scheduleReconnect();
  };

  gexSocket.onerror = function () {
    if (myGen !== gexConnectGeneration) return;
    gexConnected = false;
    broadcastStatus();
  };

  gexSocket.onmessage = function (evt) {
    if (myGen !== gexConnectGeneration) return;
    let data;
    try {
      data = JSON.parse(evt.data);
    } catch (e) {
      return;
    }
    handleGexMessage(data);
  };
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(function () {
    reconnectTimer = null;
    connectToGex();
  }, 2000);
}

function sendToGex(payload) {
  if (!gexSocket || gexSocket.readyState !== WebSocket.OPEN) return;
  try {
    gexSocket.send(JSON.stringify(payload));
  } catch (e) {
    /* ignore */
  }
}

/** Visible in Stream Deck logs (logMessage). */
function logToElgato(message) {
  try {
    if (!websocket || websocket.readyState !== WebSocket.OPEN) return;
    websocket.send(JSON.stringify({
      event: "logMessage",
      payload: { message: String(message) }
    }));
  } catch (e) { /* ignore */ }
}

/** deviceId -> current virtual page (0-based) */
const devicePage = {};

function applyVirtualPage(deviceId, page) {
  const pageNum = parseInt(page, 10);
  const pageIndex = isNaN(pageNum) ? 0 : Math.max(0, pageNum);
  if (deviceId) {
    devicePage[deviceId] = pageIndex;
  }
  const label = "P" + (pageIndex + 1);
  let updated = 0;
  Object.keys(instances).forEach(function (ctx) {
    const inst = instances[ctx];
    if (!inst) return;
    if (deviceId && inst.deviceId && inst.deviceId !== deviceId) return;
    const base = inst.buttonId || "";
    const title = label + "\n" + base;
    if (!websocket || websocket.readyState !== WebSocket.OPEN) return;
    websocket.send(JSON.stringify({
      event: "setTitle",
      context: ctx,
      payload: { title: title, target: 0 }
    }));
    if (updated === 0) {
      websocket.send(JSON.stringify({ event: "showOk", context: ctx }));
    }
    updated += 1;
  });
  logToElgato("JGEx virtual page=" + (pageIndex + 1) + " device=" + (deviceId || "?") + " keys=" + updated);
  return updated;
}

function broadcastStatus() {
  const payload = {
    event: "connectionStatus",
    connected: gexConnected,
    host: globalSettings.host,
    port: globalSettings.port
  };
  const seen = {};
  Object.keys(instances).forEach(function (ctx) {
    const inst = instances[ctx];
    seen[ctx] = true;
    sendToPropertyInspector(ctx, inst.action || ACTION_BUTTON, payload);
  });
  Object.keys(piContexts).forEach(function (ctx) {
    if (seen[ctx]) return;
    sendToPropertyInspector(ctx, piContexts[ctx] || ACTION_BUTTON, payload);
  });
}

function normalizeButtonId(buttonId) {
  if (buttonId == null) return "";
  let id = String(buttonId).trim();
  // Legacy coordinate form 0_0 -> 0:0
  if (id.indexOf("_") >= 0 && id.indexOf(":") < 0) {
    const parts = id.split("_");
    if (parts.length === 2 && /^\d+$/.test(parts[0]) && /^\d+$/.test(parts[1])) {
      id = parts[0] + ":" + parts[1];
    }
  }
  return id;
}

function resolveButtonId(settings, payload) {
  if (settings && settings.buttonId) return normalizeButtonId(settings.buttonId);
  const coords = (payload && payload.coordinates) || {};
  if (coords.row != null && coords.column != null) {
    // Match seeded profile IDs (row:col).
    return String(coords.row) + ":" + String(coords.column);
  }
  return "0";
}

/** 1-based Elgato profile page from action settings (default 1). */
function resolvePage(settings, prev) {
  const raw = (settings && settings.page != null && settings.page !== "")
    ? settings.page
    : (prev && prev.page != null ? prev.page : 1);
  const n = parseInt(raw, 10);
  if (isNaN(n) || n < 1) return 1;
  if (n > 99) return 99;
  return n;
}

/** Title shown in GEX: whichever source was updated most recently. */
function displayTitle(inst) {
  if (!inst) return "";
  const hint = inst.titleHint != null ? String(inst.titleHint) : "";
  const native = inst.elgatoTitle != null ? String(inst.elgatoTitle) : "";
  const hintTs = inst.hintUpdated || 0;
  const nativeTs = inst.elgatoTitleUpdated || 0;
  if (hint && native) {
    return (hintTs >= nativeTs) ? hint : native;
  }
  if (native) return native;
  if (hint) return hint;
  if (inst.title) return String(inst.title);
  return "";
}

function pushInstanceToGex(context) {
  const inst = instances[context];
  if (!inst || !inst.deviceId) return;
  const info = deviceInfoById[inst.deviceId] || {};
  const title = displayTitle(inst);
  sendToGex({
    type: "willAppear",
    deviceId: inst.deviceId,
    deviceName: info.name || friendlyDeviceName(info.type, null, inst.deviceId),
    deviceType: (info.type !== undefined && info.type !== null) ? info.type : "",
    buttonId: inst.buttonId,
    page: resolvePage({ page: inst.page }, inst),
    kind: inst.kind || "button",
    title: title,
    context: context,
    row: inst.row,
    column: inst.column
  });
  logToElgato(
    "JGEx push title=" + title +
    " page=" + resolvePage({ page: inst.page }, inst) +
    " buttonId=" + inst.buttonId +
    " ctx=" + String(context).slice(0, 8)
  );
}

function requestSettings(context) {
  if (!websocket || websocket.readyState !== WebSocket.OPEN || !context) return;
  try {
    websocket.send(JSON.stringify({ event: "getSettings", context: context }));
  } catch (e) { /* ignore */ }
}

function syncAllInstancesToGex() {
  announceDevicesToGex();
  const keys = Object.keys(instances);
  logToElgato("JGEx syncInputs count=" + keys.length);
  // Refresh from Elgato first — do NOT push stale cached titles (that was
  // overwriting newer GEX labels like test3 with older test).
  keys.forEach(function (ctx) { requestSettings(ctx); });
  // After settings round-trip, push everything (includes elgatoTitle).
  setTimeout(function () {
    keys.forEach(function (ctx) { pushInstanceToGex(ctx); });
    sendToGex({ type: "command_ack", command: "syncInputs", ok: true, count: keys.length, phase: "pushed" });
  }, 350);
}

function updateInstanceFromSettings(context, device, payload) {
  const settings = payload.settings || {};
  const coords = payload.coordinates || {};
  const prev = instances[context] || {};
  const hasHint = Object.prototype.hasOwnProperty.call(settings, "title");
  const next = {
    deviceId: device || prev.deviceId,
    buttonId: resolveButtonId(settings, payload),
    page: resolvePage(settings, prev),
    kind: prev.kind || "button",
    titleHint: hasHint ? String(settings.title || "") : (prev.titleHint || ""),
    titleHintExplicit: hasHint ? true : !!prev.titleHintExplicit,
    hintUpdated: hasHint ? Date.now() : (prev.hintUpdated || 0),
    elgatoTitle: prev.elgatoTitle || "",
    elgatoTitleUpdated: prev.elgatoTitleUpdated || 0,
    title: hasHint ? String(settings.title || "") : (prev.title || ""),
    row: (coords.row != null) ? coords.row : prev.row,
    column: (coords.column != null) ? coords.column : prev.column,
    action: prev.action
  };
  instances[context] = next;
}

function handleWillAppear(context, action, device, payload) {
  const settings = payload.settings || {};
  const coords = payload.coordinates || {};
  const kind = (action === ACTION_DIAL) ? "dial" : "button";
  const prev = instances[context] || {};
  instances[context] = {
    deviceId: device,
    buttonId: resolveButtonId(settings, payload),
    page: resolvePage(settings, prev),
    kind: kind,
    // Seeded profile titles land here but are NOT an explicit PI override.
    titleHint: (settings.title != null && settings.title !== "") ? String(settings.title) : (prev.titleHint || ""),
    titleHintExplicit: !!prev.titleHintExplicit,
    elgatoTitle: prev.elgatoTitle || "",
    title: (settings.title != null && settings.title !== "") ? String(settings.title) : (prev.title || ""),
    row: coords.row,
    column: coords.column,
    action: action
  };
  const remembered = rememberDevice(
    device,
    (deviceInfoById[device] && deviceInfoById[device].name) || null,
    (deviceInfoById[device] && deviceInfoById[device].type)
  ) || { name: friendlyDeviceName(null, null, device), type: "" };
  sendToGex({
    type: "device",
    action: "connected",
    deviceId: device,
    name: remembered.name,
    deviceType: (remembered.type !== undefined && remembered.type !== null) ? remembered.type : ""
  });
  pushInstanceToGex(context);
  sendToPropertyInspector(context, action, {
    event: "connectionStatus",
    connected: gexConnected,
    host: globalSettings.host,
    port: globalSettings.port
  });
}

function handleWillDisappear(context, device, payload) {
  const inst = instances[context];
  if (inst) {
    sendToGex({
      type: "willDisappear",
      deviceId: device,
      buttonId: inst.buttonId,
      page: resolvePage({ page: inst.page }, inst),
      kind: inst.kind,
      context: context
    });
  }
  delete instances[context];
}

function instancePayload(context, device, payload, kind) {
  const settings = (payload && payload.settings) || {};
  const coords = (payload && payload.coordinates) || {};
  const inst = instances[context] || {};
  return {
    deviceId: device,
    buttonId: inst.buttonId || resolveButtonId(settings, payload || {}),
    page: resolvePage(settings, inst),
    kind: kind || inst.kind || "button",
    title: displayTitle(inst) || settings.title || "",
    context: context,
    row: coords.row != null ? coords.row : inst.row,
    column: coords.column != null ? coords.column : inst.column
  };
}

function handleKey(context, device, isPressed, payload) {
  sendToGex({
    type: isPressed ? "keyDown" : "keyUp",
    ...instancePayload(context, device, payload, "button")
  });
}

function handleDialRotate(context, device, payload) {
  const ticks = payload.ticks || 0;
  sendToGex({
    type: "dialRotate",
    ticks: ticks,
    ...instancePayload(context, device, payload, "dial")
  });
}

function findContextByButton(deviceId, buttonId) {
  const keys = Object.keys(instances);
  for (let i = 0; i < keys.length; i++) {
    const ctx = keys[i];
    const inst = instances[ctx];
    if (inst.deviceId === deviceId && String(inst.buttonId) === String(buttonId)) {
      return ctx;
    }
  }
  return null;
}

function resolveDeviceId(preferred) {
  let device = preferred || "";
  if (!device) {
    const keys = Object.keys(instances);
    if (keys.length) {
      device = instances[keys[0]].deviceId || "";
    }
  }
  if (!device) {
    const known = Object.keys(deviceInfoById);
    if (known.length) {
      device = known[0];
    }
  }
  return device;
}

/**
 * Elgato switchToProfile — profile must be declared in manifest Profiles.
 * page is 0-based. Close the Stream Deck configuration window or switches are ignored.
 */
function sendSwitchToProfile(deviceId, profile, page) {
  const device = resolveDeviceId(deviceId);
  const payload = {};
  if (profile) {
    payload.profile = profile;
  }
  if (page !== undefined && page !== null && page !== "") {
    const pageNum = parseInt(page, 10);
    if (!isNaN(pageNum)) {
      payload.page = pageNum;
    }
  }
  const msg = {
    event: "switchToProfile",
    context: pluginUUID,
    device: device,
    payload: payload
  };
  logToElgato("JGEx switchToProfile " + JSON.stringify(msg));
  try {
    const fs = (typeof require === "function") ? require("fs") : null;
    const os = (typeof require === "function") ? require("os") : null;
    if (fs && os) {
      fs.appendFileSync(
        os.tmpdir() + "/jgex-streamdeck-plugin.log",
        new Date().toISOString() + " " + JSON.stringify(msg) + "\n"
      );
    }
  } catch (e) { /* ignore */ }
  if (!websocket || websocket.readyState !== WebSocket.OPEN) {
    logToElgato("JGEx switchToProfile aborted: Elgato websocket not open");
    return false;
  }
  if (!device) {
    logToElgato("JGEx switchToProfile aborted: no device id");
    return false;
  }
  if (!pluginUUID) {
    logToElgato("JGEx switchToProfile aborted: no pluginUUID");
    return false;
  }
  websocket.send(JSON.stringify(msg));
  return true;
}

function handleGexMessage(data) {
  if (!data) return;
  if (data.type === "hello" || data.type === "hello_ack" || data.type === "status" || data.type === "pong") {
    return;
  }
  if (data.type !== "command") return;

  const command = data.command;
  const deviceId = data.deviceId;
  const buttonId = data.buttonId;
  let context = data.context;
  if (!context && deviceId && buttonId != null) {
    context = findContextByButton(deviceId, buttonId);
  }

  logToElgato("JGEx GEX command=" + command + " raw=" + JSON.stringify(data));
  if (command !== "changePage" && command !== "switchToProfile" && command !== "syncInputs" && command !== "refresh") {
    sendToGex({ type: "command_ack", command: command, ok: true });
  }

  switch (command) {
    case "syncInputs":
    case "refresh":
      // GEX Refresh — getSettings first, then push (see syncAllInstancesToGex).
      syncAllInstancesToGex();
      break;
    case "setTitle":
      if (!context) return;
      websocket.send(JSON.stringify({
        event: "setTitle",
        context: context,
        payload: { title: data.title || "", target: 0 }
      }));
      // Keep our cache / GEX list in sync with what we just set.
      if (instances[context]) {
        instances[context].elgatoTitle = data.title || "";
        instances[context].elgatoTitleUpdated = Date.now();
        pushInstanceToGex(context);
      }
      break;
    case "setImage":
      if (!context) return;
      websocket.send(JSON.stringify({
        event: "setImage",
        context: context,
        payload: { image: data.image || "", target: 0 }
      }));
      break;
    case "setState":
      if (!context) return;
      websocket.send(JSON.stringify({
        event: "setState",
        context: context,
        payload: { state: data.state || 0 }
      }));
      break;
    case "showOk":
      if (!context) return;
      websocket.send(JSON.stringify({ event: "showOk", context: context }));
      break;
    case "showAlert":
      if (!context) return;
      websocket.send(JSON.stringify({ event: "showAlert", context: context }));
      break;
    case "changePage":
    case "switchToProfile": {
      // One profile (e.g. profiles/jgex-xl); page is the 0-based page index.
      const device = resolveDeviceId(deviceId);
      const n = applyVirtualPage(device, data.page);
      const profile = data.profile || "profiles/jgex-xl";
      sendSwitchToProfile(device, profile, data.page);
      sendToGex({ type: "command_ack", command: command, ok: true, keys: n, page: data.page });
      break;
    }
    default:
      logToElgato("JGEx unknown command=" + command);
      break;
  }
}

// Elgato Node host looks for this export / global.
if (typeof globalThis !== "undefined") {
  globalThis.connectElgatoStreamDeckSocket = connectElgatoStreamDeckSocket;
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = { connectElgatoStreamDeckSocket };
}

/**
 * Stream Deck's Node.js host launches: node app.js -port N -pluginUUID ... -registerEvent ... -info ...
 * (HTML plugins get connectElgatoStreamDeckSocket injected; Node plugins must self-start from argv.)
 */
function bootstrapFromArgv() {
  if (typeof process === "undefined" || !process.argv || process.argv.length < 3) {
    return;
  }
  const args = process.argv.slice(2);
  let port = null;
  let uuid = null;
  let registerEvent = null;
  let info = "{}";

  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === "-port" && args[i + 1]) {
      port = args[++i];
    } else if (a === "-pluginUUID" && args[i + 1]) {
      uuid = args[++i];
    } else if (a === "-registerEvent" && args[i + 1]) {
      registerEvent = args[++i];
    } else if (a === "-info" && args[i + 1]) {
      info = args[++i];
    }
  }

  // Positional fallback used by some hosts: port uuid registerEvent info
  if (!port && args.length >= 3 && args[0] && args[0].charAt(0) !== "-") {
    port = args[0];
    uuid = args[1];
    registerEvent = args[2];
    if (args[3]) info = args[3];
  }

  if (port && uuid && registerEvent) {
    connectElgatoStreamDeckSocket(String(port), String(uuid), String(registerEvent), info);
  }
}

bootstrapFromArgv();

