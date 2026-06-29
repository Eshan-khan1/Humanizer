const API_BASE = "http://127.0.0.1:8000";
importScripts("api_auth.js");

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "checkGrammar") {
    const quick = message.quick === true;
    const urls = quick
      ? [
          `${API_BASE}/grammar?quick=true`,
          `${API_BASE}/grammar/quick`,
        ]
      : [`${API_BASE}/grammar`];

    const body = JSON.stringify({ text: message.text });

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
    (async () => {
      try {
        const headers = await humanizerApiHeaders();
        const response = await fetch(`${API_BASE}/humanize`, {
          method: "POST",
          headers,
          body: JSON.stringify({ text: message.text }),
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

  if (message?.type === "updateBadge") {
    const count = Number(message.count) || 0;
    chrome.action.setBadgeText({ text: count > 0 ? String(count) : "" });
    chrome.action.setBadgeBackgroundColor({ color: count > 0 ? "#E53E3E" : "#15C39A" });
    sendResponse({ ok: true });
    return true;
  }

  if (message?.type === "rewriteText") {
    const text = String(message.text || "").trim();
    const prompt = String(message.prompt || message.tone || "").trim();
    const context = message.context && typeof message.context === "object"
      ? message.context
      : null;
    if (!text) {
      sendResponse({ ok: false, error: "No text to rewrite" });
      return true;
    }
    if (!prompt) {
      sendResponse({ ok: false, error: "No rewrite prompt" });
      return true;
    }

    (async () => {
      try {
        const headers = await humanizerApiHeaders();
        const ai = await humanizerAiPayload();
        const response = await fetch(`${API_BASE}/rewrite`, {
          method: "POST",
          headers,
          body: JSON.stringify({ text, prompt, context, ai }),
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
    const text = String(message.text || "").trim();
    const format = String(message.format || "essay").trim().toLowerCase();
    const notes = String(message.notes || "").trim();
    const context = message.context && typeof message.context === "object"
      ? message.context
      : null;
    const settings = message.settings && typeof message.settings === "object"
      ? message.settings
      : null;
    if (!text) {
      sendResponse({ ok: false, error: "No text to generate" });
      return true;
    }
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
          body: JSON.stringify({ text, format, notes, context, settings, ai }),
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
