/**
 * Shared API auth + cloud AI config for Humanizer extension requests.
 * - humanizerApiToken: local server Bearer token (chrome.storage.local)
 * - aiProvider / aiApiKey: cloud LLM (chrome.storage.local, never synced)
 */
async function humanizerApiHeaders(extraHeaders = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...extraHeaders,
  };
  try {
    const stored = await chrome.storage.local.get("humanizerApiToken");
    const token = String(stored?.humanizerApiToken || "").trim();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
  } catch (_error) {
    // Ignore storage errors — server may not require auth.
  }
  return headers;
}

async function humanizerAiPayload() {
  try {
    const stored = await chrome.storage.local.get({
      aiProvider: "local",
      aiApiKey: "",
    });
    const provider = String(stored?.aiProvider || "local").trim().toLowerCase();
    const apiKey = String(stored?.aiApiKey || "").trim();
    if (provider === "local" || provider === "ollama" || !apiKey) {
      return null;
    }
    return {
      provider,
      apiKey,
    };
  } catch (_error) {
    return null;
  }
}
