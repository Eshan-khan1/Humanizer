/**
 * Shared API auth + cloud AI config for Humanizer extension requests.
 * - humanizerApiToken: local server Bearer token (chrome.storage.local)
 * - aiProvider / aiApiKey: cloud LLM (chrome.storage.local, never synced)
 */

const MAX_API_TOKEN_CHARS = 512;
const MAX_AI_API_KEY_CHARS = 512;
const ALLOWED_AI_PROVIDERS = new Set(["local", "ollama", "groq", "openai"]);

async function humanizerApiHeaders(extraHeaders = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...extraHeaders,
  };
  try {
    const stored = await chrome.storage.local.get("humanizerApiToken");
    const token = String(stored?.humanizerApiToken || "").trim();
    if (token) {
      if (token.includes("\0") || token.length > MAX_API_TOKEN_CHARS) {
        throw new Error("Stored API token is invalid");
      }
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
    if (!ALLOWED_AI_PROVIDERS.has(provider) || provider === "local" || provider === "ollama" || !apiKey) {
      return null;
    }
    if (apiKey.includes("\0") || apiKey.length > MAX_AI_API_KEY_CHARS) {
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
