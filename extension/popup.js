document.addEventListener("DOMContentLoaded", () => {
  const statusEl = document.getElementById("status");
  const mainViewEl = document.getElementById("main-view");
  const settingsViewEl = document.getElementById("settings-view");
  const settingsOpenEl = document.getElementById("settings-open");
  const settingsBackEl = document.getElementById("settings-back");
  const toggleRows = Array.from(document.querySelectorAll(".toggle-row[data-setting]"));

  if (
    !statusEl ||
    !mainViewEl ||
    !settingsViewEl ||
    !settingsOpenEl ||
    !settingsBackEl ||
    !toggleRows.length
  ) {
    return;
  }

  const DEFAULTS = {
    enabled: true,
    autoFixAll: true,
    rewriteInSearchBars: true,
  };

  function showMainView() {
    mainViewEl.hidden = false;
    mainViewEl.classList.remove("view--hidden");
    settingsViewEl.hidden = true;
    settingsViewEl.classList.add("view--hidden");
  }

  function showSettingsView() {
    mainViewEl.hidden = true;
    mainViewEl.classList.add("view--hidden");
    settingsViewEl.hidden = false;
    settingsViewEl.classList.remove("view--hidden");
  }

  settingsOpenEl.addEventListener("click", showSettingsView);
  settingsBackEl.addEventListener("click", showMainView);

  function setToggleState(button, on) {
    button.classList.toggle("toggle--on", on);
    button.setAttribute("aria-checked", on ? "true" : "false");
  }

  function readToggleState(button) {
    return button.getAttribute("aria-checked") === "true";
  }

  function saveSettings(values) {
    chrome.storage.sync.set(values, () => {
      if (chrome.runtime.lastError) {
        chrome.storage.local.set(values);
      }
    });
  }

  function wireToggleRow(row) {
    const key = row.dataset.setting;
    const button = row.querySelector(".toggle");
    if (!key || !button) return;

    function setOn(on) {
      setToggleState(button, on);
    }

    function toggle() {
      const next = !readToggleState(button);
      setOn(next);
      saveSettings({ [key]: next });
    }

    row.addEventListener("click", (event) => {
      event.preventDefault();
      toggle();
    });

    button.addEventListener("keydown", (event) => {
      if (event.key === " " || event.key === "Enter") {
        event.preventDefault();
        toggle();
      }
    });

    return setOn;
  }

  const setters = new Map();
  for (const row of toggleRows) {
    const key = row.dataset.setting;
    const setOn = wireToggleRow(row);
    if (key && setOn) {
      setters.set(key, setOn);
    }
  }

  function applySettings(result) {
    for (const [key, defaultValue] of Object.entries(DEFAULTS)) {
      const setOn = setters.get(key);
      if (!setOn) continue;
      setOn(result[key] !== false);
    }
  }

  chrome.storage.sync.get(DEFAULTS, (syncResult) => {
    if (chrome.runtime.lastError) {
      chrome.storage.local.get(DEFAULTS, applySettings);
      return;
    }
    applySettings(syncResult);
  });

  fetch("http://127.0.0.1:8000/health")
    .then((response) => {
      if (!response.ok) throw new Error("Server unavailable");
      return response.json();
    })
    .then((data) => {
      const ollama = data.ollama_available ? " · Ollama ready" : " · Ollama offline";
      const grammar = data.grammar_available
        ? " · Grammar ready"
        : " · Grammar offline (restart server after ./start_server.sh)";
      statusEl.textContent = `Server connected${grammar}${ollama}`;
      statusEl.classList.add(data.grammar_available ? "ok" : "error");
    })
    .catch(() => {
      statusEl.textContent = "Server offline — run ./start_server.sh";
      statusEl.classList.add("error");
    });
});
