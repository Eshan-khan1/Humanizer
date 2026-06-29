document.addEventListener("DOMContentLoaded", () => {
  const statusEl = document.getElementById("status");
  const mainViewEl = document.getElementById("main-view");
  const settingsViewEl = document.getElementById("settings-view");
  const generateViewEl = document.getElementById("generate-view");
  const aiViewEl = document.getElementById("ai-view");
  const settingsOpenEl = document.getElementById("settings-open");
  const settingsBackEl = document.getElementById("settings-back");
  const generateOpenEl = document.getElementById("generate-open");
  const generateBackEl = document.getElementById("generate-back");
  const aiOpenEl = document.getElementById("ai-open");
  const aiBackEl = document.getElementById("ai-back");
  const toggleRows = Array.from(document.querySelectorAll(".toggle-row[data-setting]"));
  const profileFieldsEl = document.getElementById("generate-profile-fields");
  const profileAddEl = document.getElementById("generate-profile-add");
  const profileEmptyEl = document.getElementById("generate-profile-empty");
  const permanentNoteEl = document.getElementById("generate-permanent-note");
  const lengthOptionsEl = document.getElementById("generate-length-options");
  const tonePresetsEl = document.getElementById("generate-tone-presets");
  const complexityOptionsEl = document.getElementById("generate-complexity-options");
  const apiTokenEl = document.getElementById("humanizer-api-token");
  const aiProviderOptionsEl = document.getElementById("ai-provider-options");
  const aiKeySectionEl = document.getElementById("ai-key-section");
  const aiKeyHintEl = document.getElementById("ai-key-hint");
  const aiApiKeyEl = document.getElementById("ai-api-key");
  const aiNavSubtitleEl = document.getElementById("ai-nav-subtitle");

  const AI_PROVIDER_OPTIONS = [
    {
      id: "local",
      label: "Local Ollama",
      description: "Uses your machine. Default — no API key needed.",
    },
    {
      id: "groq",
      label: "Groq cloud",
      description: "Fast cloud models. Requires a free Groq API key.",
    },
    {
      id: "openai",
      label: "OpenAI",
      description: "GPT models. Requires an OpenAI API key.",
    },
  ];

  const AI_KEY_HINTS = {
    groq: "Groq keys usually start with gsk_. Create one at console.groq.com/keys.",
    openai: "OpenAI keys usually start with sk-. Create one at platform.openai.com/api-keys.",
  };

  if (
    !statusEl ||
    !mainViewEl ||
    !settingsViewEl ||
    !generateViewEl ||
    !aiViewEl ||
    !settingsOpenEl ||
    !settingsBackEl ||
    !generateOpenEl ||
    !generateBackEl ||
    !aiOpenEl ||
    !aiBackEl ||
    !aiProviderOptionsEl ||
    !aiKeySectionEl ||
    !aiApiKeyEl ||
    !toggleRows.length ||
    !profileFieldsEl ||
    !profileAddEl ||
    !profileEmptyEl ||
    !permanentNoteEl ||
    !lengthOptionsEl ||
    !tonePresetsEl ||
    !complexityOptionsEl
  ) {
    return;
  }

  const EMPTY_PROFILE = {
    fullName: "",
    signOff: "",
    jobTitle: "",
    companyName: "",
    schoolName: "",
    email: "",
    phone: "",
    permanentNote: "",
  };

  const DEFAULTS = {
    enabled: true,
    autoFixAll: true,
    rewriteInSearchBars: true,
    generateProfile: { ...EMPTY_PROFILE },
    generateProfileFields: [],
    generateLength: "medium",
    generateTonePreset: "friendly",
    generateComplexity: "standard",
    generateIncludeSubject: true,
  };

  let generateConfig = {
    tonePresets: [],
    lengths: [],
    complexityLevels: [],
    profileFields: [],
    defaultSettings: {
      tonePreset: "friendly",
      length: "medium",
      complexity: "standard",
      includeSubject: true,
      profile: { ...EMPTY_PROFILE },
    },
  };

  let profileInputs = new Map();
  let enabledProfileFields = [];
  let profileValues = { ...EMPTY_PROFILE };
  let profileSaveTimer = null;

  function getProfileFieldDefs() {
    if (generateConfig.profileFields.length) {
      return generateConfig.profileFields;
    }
    return [
      { id: "fullName", label: "Full name", placeholder: "Alex Johnson" },
      { id: "signOff", label: "Preferred sign-off", placeholder: "Best regards" },
      { id: "jobTitle", label: "Job title", placeholder: "Product Manager" },
      { id: "companyName", label: "Company name", placeholder: "Acme Inc." },
      { id: "schoolName", label: "School name", placeholder: "Lincoln High School" },
      { id: "email", label: "Email address", placeholder: "alex@example.com" },
      { id: "phone", label: "Phone number", placeholder: "(555) 123-4567" },
    ];
  }

  function getProfileFieldDef(fieldId) {
    return getProfileFieldDefs().find((field) => field.id === fieldId);
  }

  function inferEnabledProfileFields(profile) {
    return getProfileFieldDefs()
      .filter((field) => String(profile?.[field.id] || "").trim())
      .map((field) => field.id);
  }

  function updateProfileAddDropdown() {
    const available = getProfileFieldDefs().filter(
      (field) => !enabledProfileFields.includes(field.id)
    );
    profileAddEl.replaceChildren();
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = available.length
      ? "Choose what to add…"
      : "All profile fields added";
    profileAddEl.appendChild(placeholder);
    for (const field of available) {
      const option = document.createElement("option");
      option.value = field.id;
      option.textContent = field.label;
      profileAddEl.appendChild(option);
    }
    profileAddEl.disabled = available.length === 0;
  }

  function updateProfileEmptyState() {
    profileEmptyEl.hidden = enabledProfileFields.length > 0;
  }

  function renderProfileFields() {
    profileFieldsEl.replaceChildren();
    profileInputs = new Map();

    for (const fieldId of enabledProfileFields) {
      const field = getProfileFieldDef(fieldId);
      if (!field) continue;

      const card = document.createElement("div");
      card.className = "profile-field-card";
      card.dataset.fieldId = field.id;

      const label = document.createElement("label");
      label.className = "field-row profile-field-card-body";
      label.setAttribute("for", `generate-profile-${field.id}`);

      const fieldLabel = document.createElement("span");
      fieldLabel.className = "field-label";
      fieldLabel.textContent = field.label;

      const input = document.createElement("input");
      input.id = `generate-profile-${field.id}`;
      input.type = field.id === "email" ? "email" : "text";
      input.className = "settings-input";
      input.placeholder = field.placeholder || "";
      input.value = profileValues[field.id] || "";
      input.autocomplete = "off";
      input.addEventListener("input", () => {
        profileValues[field.id] = input.value;
        scheduleProfileSave();
      });

      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "profile-field-remove";
      removeButton.setAttribute("aria-label", `Remove ${field.label}`);
      removeButton.textContent = "×";
      removeButton.addEventListener("click", () => {
        removeProfileField(field.id);
      });

      label.appendChild(fieldLabel);
      label.appendChild(input);
      card.appendChild(label);
      card.appendChild(removeButton);
      profileFieldsEl.appendChild(card);
      profileInputs.set(field.id, input);
    }

    updateProfileAddDropdown();
    updateProfileEmptyState();
  }

  function addProfileField(fieldId) {
    if (!fieldId || enabledProfileFields.includes(fieldId)) return;
    enabledProfileFields.push(fieldId);
    renderProfileFields();
    const input = profileInputs.get(fieldId);
    input?.focus();
    saveProfileState();
  }

  function removeProfileField(fieldId) {
    enabledProfileFields = enabledProfileFields.filter((id) => id !== fieldId);
    profileValues[fieldId] = "";
    renderProfileFields();
    saveProfileState();
  }

  function saveProfileState() {
    saveSettings({
      generateProfile: readProfileFromForm(),
      generateProfileFields: [...enabledProfileFields],
    });
  }

  profileAddEl.addEventListener("change", () => {
    const fieldId = profileAddEl.value;
    profileAddEl.value = "";
    if (fieldId) {
      addProfileField(fieldId);
    }
  });

  function hideView(viewEl) {
    viewEl.hidden = true;
    viewEl.classList.add("view--hidden");
  }

  function showView(viewEl) {
    viewEl.hidden = false;
    viewEl.classList.remove("view--hidden");
  }

  function showMainView() {
    showView(mainViewEl);
    hideView(settingsViewEl);
    hideView(generateViewEl);
    hideView(aiViewEl);
  }

  function showSettingsView() {
    hideView(mainViewEl);
    showView(settingsViewEl);
    hideView(generateViewEl);
    hideView(aiViewEl);
  }

  function showGenerateView() {
    hideView(mainViewEl);
    hideView(settingsViewEl);
    hideView(aiViewEl);
    showView(generateViewEl);
  }

  function showAiView() {
    hideView(mainViewEl);
    hideView(settingsViewEl);
    hideView(generateViewEl);
    showView(aiViewEl);
  }

  settingsOpenEl.addEventListener("click", showSettingsView);
  settingsBackEl.addEventListener("click", showMainView);
  generateOpenEl.addEventListener("click", showGenerateView);
  generateBackEl.addEventListener("click", showSettingsView);
  aiOpenEl.addEventListener("click", showAiView);
  aiBackEl.addEventListener("click", showSettingsView);

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

  function createOptionCard(groupName, option, selectedValue) {
    const card = document.createElement("label");
    card.className = "option-card";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = groupName;
    input.value = option.id;
    input.checked = option.id === selectedValue;
    const title = document.createElement("span");
    title.className = "option-card-title";
    title.textContent = option.label;
    const description = document.createElement("span");
    description.className = "option-card-description";
    description.textContent = option.description || "";
    card.appendChild(input);
    card.appendChild(title);
    if (option.description) {
      card.appendChild(description);
    }
    return card;
  }

  function buildProfileFields() {
    updateProfileAddDropdown();
    renderProfileFields();
  }

  function buildOptionGroups() {
    const lengths = generateConfig.lengths.length
      ? generateConfig.lengths
      : [
          { id: "short", label: "Short", description: "Quick and concise." },
          { id: "medium", label: "Medium", description: "Standard length." },
          { id: "long", label: "Long", description: "Fully expanded." },
        ];
    const tonePresets = generateConfig.tonePresets.length
      ? generateConfig.tonePresets
      : [
          { id: "formal", label: "Formal", description: "Professional and respectful." },
          { id: "friendly", label: "Friendly", description: "Warm and approachable." },
          { id: "casual", label: "Casual", description: "Relaxed everyday language." },
        ];
    const complexityLevels = generateConfig.complexityLevels.length
      ? generateConfig.complexityLevels
      : [
          { id: "simple", label: "Simple", description: "Easy, clear words." },
          { id: "standard", label: "Standard", description: "Balanced vocabulary." },
          { id: "advanced", label: "Advanced", description: "Sophisticated vocabulary." },
        ];

    lengthOptionsEl.replaceChildren();
    for (const option of lengths) {
      lengthOptionsEl.appendChild(
        createOptionCard("generate-length", option, DEFAULTS.generateLength)
      );
    }

    tonePresetsEl.replaceChildren();
    for (const option of tonePresets) {
      tonePresetsEl.appendChild(
        createOptionCard("generate-tone-preset", option, DEFAULTS.generateTonePreset)
      );
    }

    complexityOptionsEl.replaceChildren();
    for (const option of complexityLevels) {
      complexityOptionsEl.appendChild(
        createOptionCard("generate-complexity", option, DEFAULTS.generateComplexity)
      );
    }
  }

  function readProfileFromForm() {
    const profile = { ...EMPTY_PROFILE, ...profileValues };
    for (const [key, input] of profileInputs.entries()) {
      profile[key] = input.value.trim();
      profileValues[key] = profile[key];
    }
    profile.permanentNote = permanentNoteEl.value.trim();
    profileValues.permanentNote = profile.permanentNote;
    return profile;
  }

  function scheduleProfileSave() {
    clearTimeout(profileSaveTimer);
    profileSaveTimer = setTimeout(saveProfileState, 250);
  }

  permanentNoteEl.addEventListener("input", scheduleProfileSave);

  function getToneForPreset(presetId) {
    const preset = generateConfig.tonePresets.find((item) => item.id === presetId);
    return preset?.tone || "warm and friendly";
  }

  function wireGenerateControls() {
    lengthOptionsEl.addEventListener("change", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement) || !target.checked) return;
      saveSettings({ generateLength: target.value });
    });

    tonePresetsEl.addEventListener("change", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement) || !target.checked) return;
      saveSettings({
        generateTonePreset: target.value,
        generateTone: getToneForPreset(target.value),
      });
    });

    complexityOptionsEl.addEventListener("change", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement) || !target.checked) return;
      saveSettings({
        generateComplexity: target.value,
        generateWording: target.value,
      });
    });
  }

  function applyProfile(profile, enabledFields) {
    const values = { ...EMPTY_PROFILE, ...(profile || {}) };
    profileValues = values;
    const permanentNote =
      values.permanentNote || values.permanentNotes || "";
    permanentNoteEl.value = permanentNote;
    profileValues.permanentNote = permanentNote;

    if (Array.isArray(enabledFields) && enabledFields.length) {
      enabledProfileFields = enabledFields.filter((fieldId) =>
        getProfileFieldDefs().some((field) => field.id === fieldId)
      );
    } else {
      enabledProfileFields = inferEnabledProfileFields(values);
    }
    renderProfileFields();
  }

  function applyGenerateOptions(result) {
    const length = result.generateLength || DEFAULTS.generateLength;
    const tonePreset = result.generateTonePreset || DEFAULTS.generateTonePreset;
    const complexity =
      result.generateComplexity ||
      result.generateWording ||
      DEFAULTS.generateComplexity;

    for (const input of lengthOptionsEl.querySelectorAll('input[type="radio"]')) {
      input.checked = input.value === length;
    }
    for (const input of tonePresetsEl.querySelectorAll('input[type="radio"]')) {
      input.checked = input.value === tonePreset;
    }
    for (const input of complexityOptionsEl.querySelectorAll('input[type="radio"]')) {
      input.checked = input.value === complexity;
    }
  }

  function applySettings(result) {
    for (const [key] of Object.entries(DEFAULTS)) {
      if (
        key === "generateProfile" ||
        key === "generateProfileFields" ||
        key === "generateLength" ||
        key === "generateTonePreset" ||
        key === "generateComplexity"
      ) {
        continue;
      }
      const setOn = setters.get(key);
      if (!setOn) continue;
      setOn(result[key] !== false);
    }
    applyProfile(result.generateProfile, result.generateProfileFields);
    applyGenerateOptions(result);
  }

  async function loadGenerateConfig() {
    try {
      const response = await fetch(chrome.runtime.getURL("generate_tones.json"));
      if (response.ok) {
        const data = await response.json();
        if (Array.isArray(data.tonePresets) && data.tonePresets.length) {
          generateConfig.tonePresets = data.tonePresets;
        }
        if (Array.isArray(data.lengths) && data.lengths.length) {
          generateConfig.lengths = data.lengths;
        }
        const complexityLevels = data.complexityLevels || data.wordingLevels;
        if (Array.isArray(complexityLevels) && complexityLevels.length) {
          generateConfig.complexityLevels = complexityLevels;
        }
        if (Array.isArray(data.profileFields) && data.profileFields.length) {
          generateConfig.profileFields = data.profileFields;
        }
        if (data.defaultSettings && typeof data.defaultSettings === "object") {
          generateConfig.defaultSettings = {
            ...generateConfig.defaultSettings,
            ...data.defaultSettings,
          };
          DEFAULTS.generateLength =
            generateConfig.defaultSettings.length || DEFAULTS.generateLength;
          DEFAULTS.generateTonePreset =
            generateConfig.defaultSettings.tonePreset || DEFAULTS.generateTonePreset;
          DEFAULTS.generateComplexity =
            generateConfig.defaultSettings.complexity ||
            generateConfig.defaultSettings.wording ||
            DEFAULTS.generateComplexity;
          DEFAULTS.generateProfile = {
            ...EMPTY_PROFILE,
            ...(generateConfig.defaultSettings.profile || {}),
          };
        }
      }
    } catch {
      // Keep built-in fallbacks.
    }

    buildProfileFields();
    buildOptionGroups();
    wireGenerateControls();

    chrome.storage.sync.get(DEFAULTS, (syncResult) => {
      if (chrome.runtime.lastError) {
        chrome.storage.local.get(DEFAULTS, applySettings);
        return;
      }
      applySettings(syncResult);
    });
  }

  loadGenerateConfig();

  function getAiProviderLabel(providerId) {
    return AI_PROVIDER_OPTIONS.find((item) => item.id === providerId)?.label || "Local Ollama";
  }

  function updateAiNavSubtitle(providerId, hasKey) {
    if (!aiNavSubtitleEl) return;
    if (providerId === "local" || !providerId) {
      aiNavSubtitleEl.textContent = "Local Ollama · no cloud key";
      return;
    }
    const label = getAiProviderLabel(providerId);
    aiNavSubtitleEl.textContent = hasKey
      ? `${label} · key saved`
      : `${label} · add API key`;
  }

  function updateAiKeySection(providerId) {
    const useCloud = providerId !== "local";
    aiKeySectionEl.classList.toggle("ai-key-section--hidden", !useCloud);
    if (aiKeyHintEl) {
      aiKeyHintEl.textContent = AI_KEY_HINTS[providerId] || "";
    }
    aiApiKeyEl.disabled = !useCloud;
    aiApiKeyEl.placeholder = useCloud
      ? `Paste your ${getAiProviderLabel(providerId)} key`
      : "Select a cloud provider above";
  }

  function buildAiProviderOptions(selectedProvider) {
    aiProviderOptionsEl.replaceChildren();
    for (const option of AI_PROVIDER_OPTIONS) {
      aiProviderOptionsEl.appendChild(
        createOptionCard("aiProvider", option, selectedProvider)
      );
    }
  }

  function applyAiSettings(providerId, apiKey) {
    const provider = providerId || "local";
    buildAiProviderOptions(provider);
    if (aiApiKeyEl) {
      aiApiKeyEl.value = apiKey || "";
    }
    updateAiKeySection(provider);
    updateAiNavSubtitle(provider, Boolean(String(apiKey || "").trim()));
  }

  function wireAiControls() {
    aiProviderOptionsEl.addEventListener("change", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement) || !target.checked) return;
      const provider = target.value;
      chrome.storage.local.set({ aiProvider: provider }, () => {
        updateAiKeySection(provider);
        updateAiNavSubtitle(provider, Boolean(aiApiKeyEl.value.trim()));
      });
    });
  }

  if (apiTokenEl) {
    chrome.storage.local.get({ humanizerApiToken: "" }, (result) => {
      apiTokenEl.value = String(result.humanizerApiToken || "");
    });
    apiTokenEl.addEventListener("change", () => {
      chrome.storage.local.set({
        humanizerApiToken: apiTokenEl.value.trim(),
      });
    });
  }

  chrome.storage.local.get({ aiProvider: "local", aiApiKey: "" }, (result) => {
    applyAiSettings(String(result.aiProvider || "local"), String(result.aiApiKey || ""));
  });

  if (aiApiKeyEl) {
    aiApiKeyEl.addEventListener("change", () => {
      const apiKey = aiApiKeyEl.value.trim();
      chrome.storage.local.set({ aiApiKey: apiKey }, () => {
        chrome.storage.local.get({ aiProvider: "local" }, (stored) => {
          updateAiNavSubtitle(String(stored.aiProvider || "local"), Boolean(apiKey));
        });
      });
    });
  }

  wireAiControls();

  (async () => {
    const headers = {};
    try {
      const stored = await chrome.storage.local.get({ humanizerApiToken: "" });
      const token = String(stored.humanizerApiToken || "").trim();
      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }
    } catch {
      // Ignore storage errors.
    }

    fetch("http://127.0.0.1:8000/health", { headers })
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
  })();
});
