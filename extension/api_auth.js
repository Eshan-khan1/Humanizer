/**
 * Shared API auth + cloud AI config for Humanizer extension requests.
 * - humanizerApiToken: local server Bearer token (chrome.storage.local)
 * - aiProvider / aiApiKey / aiBaseUrl / aiModel: cloud LLM (never synced)
 */

const MAX_API_TOKEN_CHARS = 512;
const MAX_AI_API_KEY_CHARS = 512;
const MAX_AI_BASE_URL_CHARS = 512;
const ALLOWED_AI_PROVIDERS = new Set([
  "local",
  "ollama",
  "api",
  "groq",
  "openai",
]);

function normalizeStoredAiProvider(provider) {
  const value = String(provider || "local").trim().toLowerCase();
  if (value === "groq" || value === "openai") {
    return "api";
  }
  if (value === "ollama") {
    return "local";
  }
  return ALLOWED_AI_PROVIDERS.has(value) ? value : "local";
}

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
      aiBaseUrl: "",
      aiModel: "",
      aiConnected: false,
    });
    const provider = normalizeStoredAiProvider(stored?.aiProvider);
    const apiKey = String(stored?.aiApiKey || "").trim();
    const baseUrl = String(stored?.aiBaseUrl || "").trim();
    const model = String(stored?.aiModel || "").trim();
    if (provider === "local" || !apiKey) {
      return null;
    }
    if (apiKey.includes("\0") || apiKey.length > MAX_AI_API_KEY_CHARS) {
      return null;
    }
    if (baseUrl.includes("\0") || baseUrl.length > MAX_AI_BASE_URL_CHARS) {
      return null;
    }
    const payload = {
      provider: "api",
      apiKey,
    };
    if (baseUrl) {
      payload.baseUrl = baseUrl;
    }
    if (model) {
      payload.model = model;
    }
    return payload;
  } catch (_error) {
    return null;
  }
}
