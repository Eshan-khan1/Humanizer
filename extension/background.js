const API_BASE = "http://127.0.0.1:8000";

function debugLog(hypothesisId, location, message, data = {}) {
  // #region agent log
  fetch("http://127.0.0.1:7614/ingest/df6edd19-693a-4116-bf9b-4599575e7a5c", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Debug-Session-Id": "2bb802",
    },
    body: JSON.stringify({
      sessionId: "2bb802",
      hypothesisId,
      location,
      message,
      data,
      timestamp: Date.now(),
    }),
  }).catch(() => {});
  // #endregion
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "checkGrammar") {
    const quick = message.quick === true;
    const urls = quick
      ? [
          `${API_BASE}/grammar?quick=true`,
          `${API_BASE}/grammar/quick`,
        ]
      : [`${API_BASE}/grammar`];
    debugLog("H2", "background.js:checkGrammar", "request start", {
      textLen: (message.text || "").length,
      quick,
    });

    const body = JSON.stringify({ text: message.text });
    const headers = { "Content-Type": "application/json" };

    (async () => {
      let lastError = null;
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
          debugLog("H2", "background.js:checkGrammar", "grammar ok", {
            matchCount: (data.matches || []).length,
            url,
          });
          sendResponse({ ok: true, data });
          return;
        } catch (error) {
          lastError = error;
        }
      }
      debugLog("H2", "background.js:checkGrammar", "grammar failed", {
        error: lastError?.message || String(lastError),
      });
      sendResponse({
        ok: false,
        error: lastError?.message || "Grammar check failed",
      });
    })();
    return true;
  }

  if (message?.type === "humanize") {
    fetch(`${API_BASE}/humanize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: message.text }),
    })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.detail || `Humanize failed (${response.status})`);
        }
        sendResponse({ ok: true, data });
      })
      .catch((error) => {
        sendResponse({ ok: false, error: error.message || String(error) });
      });
    return true;
  }

  if (message?.type === "updateBadge") {
    const count = Number(message.count) || 0;
    chrome.action.setBadgeText({ text: count > 0 ? String(count) : "" });
    chrome.action.setBadgeBackgroundColor({ color: count > 0 ? "#E53E3E" : "#15C39A" });
    sendResponse({ ok: true });
    return true;
  }

  return false;
});
