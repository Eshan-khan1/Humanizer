const DEFAULT_API_BASE = "http://127.0.0.1:8000";
const NATIVE_HOST = "com.thoth.app";
const CONNECT_ALARM = "thoth-auto-connect";
const MAX_TEXT_CHARS = 50000;
const MAX_PROMPT_CHARS = 2000;
const MAX_NOTES_CHARS = 5000;

importScripts("api_auth.js");

let API_BASE = DEFAULT_API_BASE;
let storageMigrated = false;

async function migrateLegacyStorage() {
  if (storageMigrated) return;
  storageMigrated = true;
  try {
    const legacy = await chrome.storage.local.get([
      "humanizerApiToken",
      "humanizerApiBase",
      "humanizerAppConnected",
      "humanizerAppConnectedAt",
      "thothApiToken",
      "thothApiBase",
      "thothAppConnected",
      "thothAppConnectedAt",
    ]);
    const patch = {};
    if (!legacy.thothApiToken && legacy.humanizerApiToken) {
      patch.thothApiToken = legacy.humanizerApiToken;
    }
    if (!legacy.thothApiBase && legacy.humanizerApiBase) {
      patch.thothApiBase = legacy.humanizerApiBase;
    }
    if (legacy.thothAppConnected == null && legacy.humanizerAppConnected != null) {
      patch.thothAppConnected = legacy.humanizerAppConnected;
    }
    if (legacy.thothAppConnectedAt == null && legacy.humanizerAppConnectedAt != null) {
      patch.thothAppConnectedAt = legacy.humanizerAppConnectedAt;
    }
    if (Object.keys(patch).length) {
      await chrome.storage.local.set(patch);
    }
  } catch {
    // Ignore migration errors.
  }
}

async function loadApiBase() {
  try {
    await migrateLegacyStorage();
    const stored = await chrome.storage.local.get({ thothApiBase: DEFAULT_API_BASE });
    const base = String(stored.thothApiBase || DEFAULT_API_BASE).trim().replace(/\/$/, "");
    if (base.startsWith("http://127.0.0.1")) {
      API_BASE = base;
    }
  } catch {
    API_BASE = DEFAULT_API_BASE;
  }
  return API_BASE;
}

async function applyConnectInfo(info) {
  if (!info || info.ok === false) {
    return { ok: false };
  }
  const base = String(info.base_url || "").trim().replace(/\/$/, "");
  const patch = {
    thothAppConnected: true,
    thothAppConnectedAt: Date.now(),
  };
  if (base.startsWith("http://127.0.0.1")) {
    API_BASE = base;
    patch.thothApiBase = base;
  }
  if (info.auth_required && info.token) {
    patch.thothApiToken = String(info.token);
  }
  const features = info.features && typeof info.features === "object" ? info.features : null;
  if (features) {
    patch.featureGrammar = features.feature_grammar !== false;
    patch.featureRewrite = features.feature_rewrite !== false;
    patch.featureGenerate = features.feature_generate !== false;
  }
  await chrome.storage.local.set(patch);
  return { ok: true, base: API_BASE };
}

function sendNative(message) {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendNativeMessage(NATIVE_HOST, message, (response) => {
        if (chrome.runtime.lastError) {
          resolve(null);
          return;
        }
        resolve(response || null);
      });
    } catch {
      resolve(null);
    }
  });
}

async function connectViaHttp() {
  await loadApiBase();
  const bases = Array.from(new Set([API_BASE, DEFAULT_API_BASE]));
  for (const base of bases) {
    try {
      const response = await fetch(`${base}/connect`, { method: "GET" });
      if (!response.ok) continue;
      const info = await response.json().catch(() => null);
      if (info?.ok) {
        await applyConnectInfo(info);
        try {
          await fetch(`${API_BASE}/connect/ping`, { method: "POST" });
        } catch {
          // Ignore ping failures.
        }
        return { ok: true, via: "http", base: API_BASE };
      }
    } catch {
      // Try next base.
    }
  }
  await chrome.storage.local.set({ thothAppConnected: false });
  return { ok: false };
}

async function autoConnectToApp() {
  await loadApiBase();
  const native = await sendNative({ type: "connect" });
  if (native?.ok) {
    await applyConnectInfo(native);
    try {
      await fetch(`${API_BASE}/connect/ping`, { method: "POST" });
    } catch {
      // Server may still be starting; native link is enough.
    }
    return { ok: true, via: "native", base: API_BASE };
  }
  return connectViaHttp();
}

chrome.runtime.onInstalled.addListener(() => {
  autoConnectToApp();
});

chrome.runtime.onStartup.addListener(() => {
  autoConnectToApp();
});

chrome.alarms.create(CONNECT_ALARM, { periodInMinutes: 5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === CONNECT_ALARM) {
    autoConnectToApp();
  }
});

autoConnectToApp();

function validateTextPayload(text, fieldName, maxChars) {
  const value = String(text || "").trim();
  if (!value) {
    return { ok: false, error: `No ${fieldName} provided` };
  }
  if (value.includes("\0")) {
    return { ok: false, error: `${fieldName} contains invalid characters` };
  }
  if (value.length > maxChars) {
    return { ok: false, error: `${fieldName} exceeds maximum length (${maxChars})` };
  }
  return { ok: true, value };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "autoConnect") {
    autoConnectToApp().then((result) => sendResponse(result));
    return true;
  }

  if (message?.type === "restartServer") {
    (async () => {
      await loadApiBase();

      // Prefer HTTP restart — works even when native messaging is stale.
      try {
        const response = await fetch(`${API_BASE}/connect/restart`, {
          method: "POST",
        });
        const data = await response.json().catch(() => ({}));
        if (response.ok && data?.ok) {
          // Detached restart sleeps ~0.6s before kill — wait past that, then
          // require a real outage before treating /health as the new process.
          await new Promise((r) => setTimeout(r, 900));
          let sawDown = false;
          let online = false;
          const deadline = Date.now() + 45000;
          while (Date.now() < deadline) {
            await new Promise((r) => setTimeout(r, 400));
            try {
              const health = await fetch(`${API_BASE}/health`, {
                method: "GET",
                cache: "no-store",
              });
              if (health.ok) {
                if (sawDown) {
                  online = true;
                  break;
                }
              } else {
                sawDown = true;
              }
            } catch {
              sawDown = true;
            }
          }
          if (!online && sawDown) {
            try {
              const health = await fetch(`${API_BASE}/health`, {
                method: "GET",
                cache: "no-store",
              });
              online = health.ok;
            } catch {
              online = false;
            }
          }
          if (online) {
            await autoConnectToApp();
          }
          sendResponse({
            ok: online,
            accepted: true,
            detail: online ? "Server online" : "Restart started, still booting",
            via: "http",
          });
          return;
        }
      } catch {
        // Fall through to native messaging.
      }

      const native = await sendNative({ type: "restart" });
      // Connect payloads also have ok:true — require action/server_ok.
      const isRestart =
        native &&
        (native.action === "restart" || typeof native.server_ok === "boolean") &&
        !native.base_url;
      if (isRestart && native.ok) {
        await autoConnectToApp();
        sendResponse({
          ok: true,
          detail: native.detail || "Server online",
          via: "native",
        });
        return;
      }
      sendResponse({
        ok: false,
        error:
          (isRestart && native?.detail) ||
          native?.detail ||
          "Could not restart. Open Thoth.app and try again.",
      });
    })();
    return true;
  }

  if (message?.type === "getConnectionStatus") {
    (async () => {
      await loadApiBase();
      const stored = await chrome.storage.local.get({
        thothAppConnected: false,
        thothAppConnectedAt: 0,
        thothApiBase: DEFAULT_API_BASE,
      });
      sendResponse({
        ok: true,
        connected: Boolean(stored.thothAppConnected),
        connectedAt: stored.thothAppConnectedAt || 0,
        base: stored.thothApiBase || API_BASE,
      });
    })();
    return true;
  }
  if (message?.type === "checkGrammar") {
    const textCheck = validateTextPayload(message.text, "text", MAX_TEXT_CHARS);
    if (!textCheck.ok) {
      sendResponse({ ok: false, error: textCheck.error });
      return true;
    }

    const quick = message.quick === true;
    const urls = quick
      ? [
          `${API_BASE}/grammar?quick=true`,
          `${API_BASE}/grammar/quick`,
        ]
      : [`${API_BASE}/grammar`];

    const body = JSON.stringify({ text: textCheck.value });

    (async () => {
      let lastError = null;
      const headers = await thothApiHeaders();
      for (const url of urls) {
        try {
          const response = await fetch(url, { method: "POST", headers, body });
          const data = await response.json().catch(() => ({}));
          if (!response.ok) {
            lastError = new Error(
              data.detail || `Grammar check failed (${response.status})`
            );
            continue;
          }
          sendResponse({ ok: true, data });
          return;
        } catch (error) {
          lastError = error;
        }
      }
      sendResponse({
        ok: false,
        error: lastError?.message || "Grammar check failed",
      });
    })();
    return true;
  }

  if (message?.type === "humanize") {
    const textCheck = validateTextPayload(message.text, "text", MAX_TEXT_CHARS);
    if (!textCheck.ok) {
      sendResponse({ ok: false, error: textCheck.error });
      return true;
    }

    (async () => {
      try {
        const headers = await thothApiHeaders();
        const ai = await thothAiPayload();
        const response = await fetch(`${API_BASE}/humanize`, {
          method: "POST",
          headers,
          body: JSON.stringify({
            text: textCheck.value,
            ai,
          }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.detail || `Humanize failed (${response.status})`);
        }
        sendResponse({ ok: true, data });
      } catch (error) {
        sendResponse({ ok: false, error: error.message || String(error) });
      }
    })();
    return true;
  }

  if (message?.type === "testAiConnection") {
    (async () => {
      try {
        const headers = await thothApiHeaders();
        const provider = String(message.provider || "api").trim().toLowerCase();
        const apiKey = String(message.apiKey || "").trim();
        const baseUrl = String(message.baseUrl || "").trim();
        const model = String(message.model || "").trim();
        if (!apiKey) {
          sendResponse({ ok: false, error: "Enter an API key first" });
          return;
        }
        const ai = { provider: provider === "local" ? "api" : provider, apiKey };
        if (baseUrl) ai.baseUrl = baseUrl;
        if (model) ai.model = model;
        const response = await fetch(`${API_BASE}/ai/test`, {
          method: "POST",
          headers,
          body: JSON.stringify({ ai }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.detail || `Connection test failed (${response.status})`);
        }
        if (!data.ok) {
          sendResponse({
            ok: false,
            error: data.detail || "API key was rejected",
            data,
          });
          return;
        }
        sendResponse({ ok: true, data });
      } catch (error) {
        sendResponse({ ok: false, error: error.message || String(error) });
      }
    })();
    return true;
  }

  if (message?.type === "updateBadge") {
    const count = Number(message.count) || 0;
    chrome.action.setBadgeText({ text: count > 0 ? String(count) : "" });
    chrome.action.setBadgeBackgroundColor({ color: count > 0 ? "#E53E3E" : "#15C39A" });
    sendResponse({ ok: true });
    return true;
  }

  if (message?.type === "rewriteText") {
    const textCheck = validateTextPayload(message.text, "text", MAX_TEXT_CHARS);
    if (!textCheck.ok) {
      sendResponse({ ok: false, error: textCheck.error });
      return true;
    }

    const promptCheck = validateTextPayload(
      message.prompt || message.tone,
      "prompt",
      MAX_PROMPT_CHARS
    );
    if (!promptCheck.ok) {
      sendResponse({ ok: false, error: promptCheck.error });
      return true;
    }

    const context = message.context && typeof message.context === "object"
      ? message.context
      : null;

    (async () => {
      try {
        const headers = await thothApiHeaders();
        const ai = await thothAiPayload();
        const response = await fetch(`${API_BASE}/rewrite`, {
          method: "POST",
          headers,
          body: JSON.stringify({
            text: textCheck.value,
            prompt: promptCheck.value,
            context,
            ai,
          }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.detail || `Rewrite failed (${response.status})`);
        }
        sendResponse({ ok: true, rewritten: data.rewritten || "" });
      } catch (error) {
        sendResponse({ ok: false, error: error.message || String(error) });
      }
    })();
    return true;
  }

  if (message?.type === "generateText") {
    const textCheck = validateTextPayload(message.text, "text", MAX_TEXT_CHARS);
    if (!textCheck.ok) {
      sendResponse({ ok: false, error: textCheck.error });
      return true;
    }

    const format = String(message.format || "essay").trim().toLowerCase();
    const notesRaw = String(message.notes || "").trim();
    if (notesRaw.includes("\0")) {
      sendResponse({ ok: false, error: "notes contains invalid characters" });
      return true;
    }
    if (notesRaw.length > MAX_NOTES_CHARS) {
      sendResponse({ ok: false, error: `notes exceeds maximum length (${MAX_NOTES_CHARS})` });
      return true;
    }

    const context = message.context && typeof message.context === "object"
      ? message.context
      : null;
    const settings = message.settings && typeof message.settings === "object"
      ? message.settings
      : null;
    if (format !== "email" && format !== "essay") {
      sendResponse({ ok: false, error: "format must be email or essay" });
      return true;
    }

    (async () => {
      try {
        const headers = await thothApiHeaders();
        const ai = await thothAiPayload();
        const response = await fetch(`${API_BASE}/generate`, {
          method: "POST",
          headers,
          body: JSON.stringify({
            text: textCheck.value,
            format,
            notes: notesRaw,
            context,
            settings,
            ai,
          }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.detail || `Generate failed (${response.status})`);
        }
        sendResponse({ ok: true, generated: data.generated || "" });
      } catch (error) {
        sendResponse({ ok: false, error: error.message || String(error) });
      }
    })();
    return true;
  }

  return false;
});
