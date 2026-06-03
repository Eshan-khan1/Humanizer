document.addEventListener("DOMContentLoaded", () => {
  const statusEl = document.getElementById("status");
  const toggleEl = document.getElementById("enabled-toggle");
  if (!statusEl || !toggleEl) return;

  chrome.storage.sync.get({ enabled: true }, (result) => {
    toggleEl.checked = result.enabled !== false;
  });

  toggleEl.addEventListener("change", () => {
    chrome.storage.sync.set({ enabled: toggleEl.checked });
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
