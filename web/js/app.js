/**
 * Humanize — frontend (PyWebView)
 * Calls Python via window.pywebview.api
 */

const INTENSITY_LABELS = ["Mild", "Moderate", "Aggressive"];
const INTENSITY_VALUES = ["mild", "moderate", "aggressive"];

const $ = (id) => document.getElementById(id);

const inputText = $("input-text");
const outputText = $("output-text");
const wordCount = $("word-count");
const statusEl = $("status");
const intensitySlider = $("intensity-slider");
const intensityValue = $("intensity-value");
const pasteOverlay = $("paste-overlay");
const emptyOverlay = $("empty-overlay");
const btnHumanize = $("btn-humanize");
const btnClear = $("btn-clear");
const btnPaste = $("btn-paste");
const btnCopy = $("btn-copy");

let wordLimit = 1200;
let apiReady = false;

function setStatus(text, className = "") {
  statusEl.textContent = text;
  statusEl.className = "status" + (className ? ` ${className}` : "");
}

function updateWordCount() {
  const words = inputText.value.trim() ? inputText.value.trim().split(/\s+/).length : 0;
  wordCount.textContent = `${words}/${wordLimit} words`;
  wordCount.classList.toggle("over-limit", words > wordLimit * 0.95);
  pasteOverlay.classList.toggle("hidden", inputText.value.trim().length > 0);
}

function updateEmptyOverlay() {
  const hasOutput = outputText.value.trim().length > 0;
  emptyOverlay.classList.toggle("hidden", hasOutput);
}

function getIntensity() {
  const idx = parseInt(intensitySlider.value, 10);
  return INTENSITY_VALUES[Math.max(0, Math.min(2, idx))];
}

function updateIntensityLabel() {
  const idx = parseInt(intensitySlider.value, 10);
  intensityValue.textContent = INTENSITY_LABELS[idx] || "Moderate";
}

async function callApi(method, ...args) {
  if (!apiReady || !window.pywebview?.api?.[method]) {
    throw new Error("App API not ready. Restart the application.");
  }
  return window.pywebview.api[method](...args);
}

async function onHumanize() {
  const text = inputText.value.trim();
  if (!text) {
    setStatus("Enter text in the Input Text area.", "error");
    return;
  }

  btnHumanize.disabled = true;
  setStatus("Humanizing…", "busy");

  try {
    const response = await callApi("humanize_text", text, getIntensity());

    if (!response.ok) {
      setStatus(response.error || "Something went wrong.", "error");
      return;
    }

    outputText.value = response.result;
    updateEmptyOverlay();

    const improved = response.score_after < response.score_before;
    setStatus(
      `AI score: ${response.score_before} → ${response.score_after} · Changes: ${response.changes.toLocaleString()}`,
      improved ? "improved" : ""
    );
  } catch (err) {
    setStatus(String(err.message || err), "error");
  } finally {
    btnHumanize.disabled = false;
  }
}

async function onPaste() {
  try {
    const clip = await navigator.clipboard.readText();
    if (!clip) return;
    inputText.value = clip;
    updateWordCount();
    inputText.focus();
  } catch {
    setStatus("Could not read clipboard.", "error");
  }
}

function onClear() {
  inputText.value = "";
  updateWordCount();
  inputText.focus();
}

async function onCopy() {
  const text = outputText.value.trim();
  if (!text) {
    setStatus("Nothing to copy yet.", "error");
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    const prev = statusEl.textContent;
    setStatus(prev + " · Copied!", "improved");
  } catch {
    setStatus("Could not copy to clipboard.", "error");
  }
}

function enforceWordLimit() {
  const words = inputText.value.trim().split(/\s+/).filter(Boolean);
  if (words.length > wordLimit) {
    inputText.value = words.slice(0, wordLimit).join(" ");
  }
  updateWordCount();
}

function bindEvents() {
  btnHumanize.addEventListener("click", onHumanize);
  btnClear.addEventListener("click", onClear);
  btnPaste.addEventListener("click", onPaste);
  btnCopy.addEventListener("click", onCopy);
  inputText.addEventListener("input", () => {
    enforceWordLimit();
  });
  intensitySlider.addEventListener("input", updateIntensityLabel);
}

async function initApp() {
  bindEvents();
  updateWordCount();
  updateEmptyOverlay();
  updateIntensityLabel();

  try {
    const config = await callApi("get_config");
    if (config?.word_limit) {
      wordLimit = config.word_limit;
      updateWordCount();
    }
  } catch {
    /* use defaults */
  }
}

function waitForApi() {
  if (window.pywebview?.api) {
    apiReady = true;
    initApp();
    return;
  }
  window.addEventListener("pywebviewready", () => {
    apiReady = true;
    initApp();
  });
}

waitForApi();
