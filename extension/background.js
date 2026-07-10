const API_BASE = "http://127.0.0.1:8000";
const MAX_TEXT_CHARS = 50000;
const MAX_PROMPT_CHARS = 2000;
const MAX_NOTES_CHARS = 5000;

importScripts("api_auth.js");

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
      const headers = await humanizerApiHeaders();
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
        const headers = await humanizerApiHeaders();
        const ai = await humanizerAiPayload();
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
        const headers = await humanizerApiHeaders();
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
        const headers = await humanizerApiHeaders();
        const ai = await humanizerAiPayload();
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
        const headers = await humanizerApiHeaders();
        const ai = await humanizerAiPayload();
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
