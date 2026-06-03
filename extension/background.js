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

chrome.action.onClicked.addListener((tab) => {
  if (!tab?.id) return;
  chrome.tabs.sendMessage(tab.id, { type: "toggleSidePanel" }, () => {
    void chrome.runtime.lastError;
  });
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "checkGrammar") {
    debugLog("H2", "background.js:checkGrammar", "request start", {
      textLen: (message.text || "").length,
    });
    fetch(`${API_BASE}/grammar`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: message.text }),
    })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          debugLog("H2", "background.js:checkGrammar", "grammar http error", {
            status: response.status,
            detail: data.detail || null,
          });
          throw new Error(data.detail || `Grammar check failed (${response.status})`);
        }
        debugLog("H2", "background.js:checkGrammar", "grammar ok", {
          matchCount: (data.matches || []).length,
        });
        sendResponse({ ok: true, data });
      })
      .catch((error) => {
        debugLog("H2", "background.js:checkGrammar", "grammar failed", {
          error: error.message || String(error),
        });
        sendResponse({ ok: false, error: error.message || String(error) });
      });
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

  if (message?.type === "toggleSidePanel") {
    sendResponse({ ok: true });
    return true;
  }

  if (message?.type === "updateBadge") {
    const count = Number(message.count) || 0;
    chrome.action.setBadgeText({ text: count > 0 ? String(count) : "" });
    chrome.action.setBadgeBackgroundColor({ color: count > 0 ? "#ec407a" : "#43a047" });
    sendResponse({ ok: true });
    return true;
  }

  return false;
});
