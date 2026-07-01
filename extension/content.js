(() => {
  const CHECK_IDLE_MS = 2000;
  const MIN_TEXT_LENGTH = 2;
  const MAX_AUTO_FIX_PASSES = 12;

  const IGNORED_INPUT_TYPES = new Set([
    "password",
    "checkbox",
    "radio",
    "file",
    "hidden",
    "submit",
    "button",
    "reset",
    "range",
    "color",
    "date",
    "datetime-local",
    "month",
    "time",
    "week",
    "number",
  ]);

  let activeField = null;
  let activeMirror = null;
  let checkDebounceTimer = null;
  let fullCheckDelayTimer = null;
  let pendingFullCheckText = "";
  let suggestionPopup = null;
  let suggestionPopupAnchor = null;
  let ignoreNextFocusOut = false;
  let currentMatches = [];
  let fieldMutationObserver = null;
  let bodyMutationObserver = null;
  let scanDebounceTimer = null;
  let floatingPositionHandler = null;
  let enabled = true;
  let autoFixAll = true;
  let rewriteInSearchBars = true;
  let autoFixInProgress = false;
  let autoFixPass = 0;
  let lastAutoFixFingerprint = "";
  let checkerStarted = false;
  let overlaySetupInProgress = false;
  let suppressGrammarEvents = false;
  /** Ranges the user accepted — never re-suggest until that slice is edited. */
  let acceptedFixes = [];
  let lastCheckedText = "";
  let lastQuickRequestId = 0;
  let lastFullRequestId = 0;
  let scrollParentListeners = [];
  let fieldClickHandler = null;
  let suppressPopupUntil = 0;
  let popupEscapeHandler = null;

  const REWRITE_ICON_DATA_URI =
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAACiUlEQVR4nJ2WyWsVQRDGf/NmTOISl7gkoARvggcRDB78EwT15iWCiuBC1IPiguJBwehFEYkgntzwvxA8iF48iYKKiIgBcRcjauLLSCVfSWXSY4wF/bqnu6u+rq+rqh/AJuAjUE6jNdWfYVxyICMhBXAVeALcABrAaGoj40bM8Fpgi/SOSueIegOdJDa5nX+XjdIxg7s1Pqu1RsoD2zBHY2u/agwXWpurfj5wGZgBXARuAQ+rLBTiblRKmWhISaa1hvTu63Dfpd8tgCzcR2kbo/jlpWRE/R3gCrBAhtoF2qzc1RhlDuCILRqXiago1Q8Cu8L8QuC9QKwNi76f5p1fyg+d6B0wVNO+AV+k+ApYJKqWBDCj6jTwCXgNbHYPChk4IC9SHmRAq075Afiqe/Og+KxwPQacAHqA6+56nzbZabqATvVdoXUkAE1WCuSubL0FZgKXnFb72SEup8rgHnnbErJ3mQBs/RzwWB7a9z6nqFXlYpUU66LoaQjnXEb2a3wQOC9PtwF7LE9imBq3S3XCSEEZAF4EAOv7gUPAYRm/ION7lYTFdClaHQ7UrzkzjIyXMu6B8+eEPulZmofSkcfNOn2v9J4Dz4CbdcaL4H4bcFz3USYoGlZkvBHvt4ENwEsBmu6AatNIFaApgK3ArL8AXAMWA2uAR8ADhbbp30uVewdoU6JYwZpKekVbt7wYkGftMj4pCmOiVYtfSoyCdcA8fXfKxnp9TwBIGayWiA5ghcb+XA6qLuUqbLXiD45HT5F4YPqAkxU9K47LlbFeMJNl3h+coUrhIoxP6XKjh1bozLiJleo6NsYm7XJ3qkClHn2jxE4cxfbN1l5PPgvXpCf/87el2sxLB54gvwGERdVSs4UgNQAAAABJRU5ErkJggg==";

  function rewriteIconUrl() {
    return REWRITE_ICON_DATA_URI;
  }

  const GENERATE_ICON_DATA_URI =
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAABuklEQVR4nK2VuUpDQRSGv2waEYKIja2mUhFUtFGEpPUNBMFG7MTKJOQBtNAH8AHEQmsLRRARcUMQm4BFsBFxIyoirlcG/gtjyHaTe2A4y8x8M2fuPTNQXgKWnQO2ZYekk4ADTMtvkl4F7oEW4wSrwKPAABAHeoFua4ECcA7cyTeLdQGDQAcwCsTK7d5d+FATv9WMvV5mzpL6f4Ef2c9hKsuWwCPAB3AG7FlH4ijbT+AY2AX6gTbgBLisBHePKSTQjdUXKpOxkQON7zROpQwc9RudAR4FDiubPqAHyAOnQETHswLsA09V+CUlLJ3Swm5bLpGJZ3Cz7Iygr9ptXv6w+iON7DwjWEF1YGRRf81U0diG4AnFkqoDR3XiZhDyA56Qb+ILitUM9gLPKOZ+o1lgTbdA0C942Jp7pL64X/Co9AxwZa4HVfY1sNMovNWamwbegHfgSzpXDzxrxUy1TlqMmO4rM27IvnO87jwowAUwUfQeZHVVuEdXMzxdNL7aI/XPT9XxtwSsZkuwODbnPg4e4J7kRW2szmOpKu5jYipxXJn4snMkmwLe6v81tvkmvsCNtAMbAj8A837C/wCTFpjkGBVsJwAAAABJRU5ErkJggg==";

  function generateIconUrl() {
    return GENERATE_ICON_DATA_URI;
  }

  /** Rewrite selection UI */
  let savedRewriteRange = null;
  let savedRewriteField = null;
  let savedInputSelection = null;
  let rewriteAnchorRect = null;
  let rewriteCircleEl = null;
  let rewriteBoxEl = null;
  let rewriteMenuEl = null;
  let generatePanelEl = null;
  let rewriteInputOpen = false;
  let rewriteMenuOpen = false;
  let generateStep = null;
  let generateFormat = null;
  let generateSettings = {
    tone: "warm and friendly",
    tonePreset: "friendly",
    length: "medium",
    complexity: "standard",
    includeSubject: true,
    profile: {
      fullName: "",
      signOff: "",
      jobTitle: "",
      companyName: "",
      schoolName: "",
      email: "",
      phone: "",
      permanentNote: "",
    },
  };
  let generateLengthOptions = [
    { id: "short", label: "Short" },
    { id: "medium", label: "Medium" },
    { id: "long", label: "Long" },
  ];
  let generateTonePresets = [
    { id: "formal", label: "Formal" },
    { id: "friendly", label: "Friendly" },
    { id: "casual", label: "Casual" },
  ];
  let generateComplexityOptions = [
    { id: "simple", label: "Simple" },
    { id: "standard", label: "Standard" },
    { id: "advanced", label: "Advanced" },
  ];
  let rewriteSubmitting = false;
  let rewriteWateryEl = null;
  let rewriteOriginalText = "";
  let rewriteUseBlocks = false;
  let rewriteBlockTag = "DIV";
  let rewriteDomSnapshot = null;
  let rewriteRangeSnapshot = null;

  const BLOCK_TAGS = new Set([
    "DIV",
    "P",
    "LI",
    "H1",
    "H2",
    "H3",
    "H4",
    "H5",
    "H6",
    "BLOCKQUOTE",
    "PRE",
    "TD",
  ]);

  const PUNCTUATION_ONLY_RE =
    /^[\s"'‘’“”`´.,!?;:—–\-…()\[\]{}\\/|@#$%^&*+=<>~]+$/;

  const attachedFields = new WeakSet();
  const SCAN_DEBOUNCE_MS = 150;
  const RESCAN_INTERVAL_MS = 2500;
  /** Max characters between errors to merge into one multi-word fix chunk. */
  const MERGE_NEARBY_GAP = 2;
  let rescanIntervalId = null;
  const REWRITE_API = "http://127.0.0.1:8000/rewrite";
  const GENERATE_API = "http://127.0.0.1:8000/generate";

  const isValid = () => {
    try {
      return !!chrome.runtime?.id;
    } catch {
      return false;
    }
  };

  init();

  function init() {
    document.querySelectorAll(".humanizer-side-panel").forEach((el) => el.remove());

    waitForBody(() => startGrammarChecker());

    loadEnabledSetting();
    loadGenerateConfig();

    if (chrome.storage?.onChanged) {
      chrome.storage.onChanged.addListener((changes, area) => {
        if (area !== "sync" && area !== "local") return;
        applyStoredSettings(changes);
      });
    }

    document.addEventListener("focusin", onDocumentFocusIn, true);
    document.addEventListener("input", onDocumentInput, true);

    document.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onWindowChange);
    document.addEventListener("mouseup", onDocumentMouseUp, true);
    document.addEventListener("pointerdown", onRewriteOutsidePointerDown, true);
    document.addEventListener("selectionchange", onDocumentSelectionChange);
    document.addEventListener("keydown", onRewriteDocumentKeydown, true);
  }

  function startGrammarChecker() {
    if (!isValid() || !enabled || checkerStarted) return;
    checkerStarted = true;

    scanForEditableFields();

    if (!bodyMutationObserver && document.body) {
      bodyMutationObserver = new MutationObserver(() => {
        clearTimeout(scanDebounceTimer);
        scanDebounceTimer = setTimeout(scanForEditableFields, SCAN_DEBOUNCE_MS);
      });
      bodyMutationObserver.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["contenteditable", "role", "aria-hidden", "hidden", "disabled"],
      });
    }

    if (!rescanIntervalId) {
      rescanIntervalId = setInterval(() => {
        if (enabled) scanForEditableFields();
      }, RESCAN_INTERVAL_MS);
    }
  }

  function applyStoredSettings(changes) {
    if (changes.enabled) {
      enabled = changes.enabled.newValue !== false;
      if (!enabled) {
        stopAutoFixLoop();
        deactivateField();
        hideRewriteUI();
      } else {
        startGrammarChecker();
        scanForEditableFields();
      }
    }
    if (changes.autoFixAll) {
      autoFixAll = changes.autoFixAll.newValue !== false;
      if (!autoFixAll) stopAutoFixLoop();
    }
    if (changes.rewriteInSearchBars) {
      rewriteInSearchBars = changes.rewriteInSearchBars.newValue !== false;
      if (
        !rewriteInSearchBars &&
        savedRewriteField &&
        isSearchBarField(savedRewriteField)
      ) {
        hideRewriteUI();
        clearRewriteSelectionState();
      }
    }
    if (
      changes.generateTone ||
      changes.generateTonePreset ||
      changes.generateLength ||
      changes.generateComplexity ||
      changes.generateWording ||
      changes.generateIncludeSubject ||
      changes.generateProfile
    ) {
      applyGenerateSettingsFromStorage({
        generateTone: changes.generateTone?.newValue,
        generateTonePreset: changes.generateTonePreset?.newValue,
        generateLength: changes.generateLength?.newValue,
        generateComplexity: changes.generateComplexity?.newValue,
        generateWording: changes.generateWording?.newValue,
        generateIncludeSubject: changes.generateIncludeSubject?.newValue,
        generateProfile: changes.generateProfile?.newValue,
      });
      syncGeneratePanelSummary();
    }
  }

  const TONE_PRESET_VOICE = {
    formal: "formal",
    friendly: "warm and friendly",
    casual: "relaxed and casual",
  };

  function applyGenerateSettingsFromStorage(result) {
    if (result.generateTone) {
      generateSettings.tone = String(result.generateTone);
    }
    if (result.generateTonePreset) {
      generateSettings.tonePreset = String(result.generateTonePreset);
      if (!result.generateTone) {
        generateSettings.tone =
          TONE_PRESET_VOICE[generateSettings.tonePreset] || generateSettings.tone;
      }
    }
    if (result.generateLength) {
      generateSettings.length = String(result.generateLength);
    }
    if (result.generateComplexity || result.generateWording) {
      generateSettings.complexity = String(
        result.generateComplexity || result.generateWording
      );
    }
    if (result.generateIncludeSubject !== undefined) {
      generateSettings.includeSubject = result.generateIncludeSubject !== false;
    }
    if (result.generateProfile && typeof result.generateProfile === "object") {
      generateSettings.profile = {
        ...generateSettings.profile,
        ...result.generateProfile,
      };
    }
  }

  function loadGenerateConfig() {
    if (!isValid() || !chrome.runtime?.getURL) return;
    fetch(chrome.runtime.getURL("generate_tones.json"))
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (!data) return;
        if (Array.isArray(data.tonePresets) && data.tonePresets.length) {
          generateTonePresets = data.tonePresets.map((preset) => ({
            id: preset.id,
            label: preset.label,
            tone: preset.tone,
          }));
        }
        if (Array.isArray(data.lengths) && data.lengths.length) {
          generateLengthOptions = data.lengths;
        }
        const complexityLevels = data.complexityLevels || data.wordingLevels;
        if (Array.isArray(complexityLevels) && complexityLevels.length) {
          generateComplexityOptions = complexityLevels;
        }
        if (data.defaultSettings && typeof data.defaultSettings === "object") {
          applyGenerateSettingsFromStorage({
            generateTone: data.defaultSettings.tone,
            generateTonePreset: data.defaultSettings.tonePreset,
            generateLength: data.defaultSettings.length,
            generateComplexity:
              data.defaultSettings.complexity || data.defaultSettings.wording,
            generateIncludeSubject: data.defaultSettings.includeSubject,
            generateProfile: data.defaultSettings.profile,
          });
        }
        syncGeneratePanelSummary();
      })
      .catch(() => {});
  }

  function getGenerateLengthLabel(lengthId) {
    const match = generateLengthOptions.find((item) => item.id === lengthId);
    return match?.label || "Medium";
  }

  function getGenerateComplexityLabel(complexityId) {
    const match = generateComplexityOptions.find((item) => item.id === complexityId);
    return match?.label || "Standard";
  }

  function syncGeneratePanelSummary() {
    const summary = generatePanelEl?.querySelector(
      ".humanizer-generate-settings-summary"
    );
    if (summary) {
      summary.textContent = formatGenerateSettingsSummary();
    }
  }

  function getGenerateToneLabel(tonePresetId) {
    const match = generateTonePresets.find((item) => item.id === tonePresetId);
    return match?.label || "Friendly";
  }

  function formatGenerateSettingsSummary() {
    return `${getGenerateToneLabel(generateSettings.tonePreset)} · ${getGenerateLengthLabel(generateSettings.length)} · ${getGenerateComplexityLabel(generateSettings.complexity)}`;
  }

  function readStoredGenerateSettings() {
    const profile = { ...generateSettings.profile };
    if (profile.permanentNotes && !profile.permanentNote) {
      profile.permanentNote = profile.permanentNotes;
    }
    return {
      tonePreset: generateSettings.tonePreset,
      tone: generateSettings.tone,
      length: generateSettings.length,
      complexity: generateSettings.complexity,
      wording: generateSettings.complexity,
      includeSubject: generateSettings.includeSubject !== false,
      profile,
    };
  }

  function loadEnabledSetting() {
    if (!isValid() || !chrome.storage?.sync) return;
    const defaults = {
      enabled: true,
      autoFixAll: true,
      rewriteInSearchBars: true,
      generateProfile: { ...generateSettings.profile },
      generateLength: "medium",
      generateTonePreset: "friendly",
      generateTone: "warm and friendly",
      generateComplexity: "standard",
      generateIncludeSubject: true,
    };
    const applyLoadedSettings = (result) => {
      enabled = result.enabled !== false;
      autoFixAll = result.autoFixAll !== false;
      rewriteInSearchBars = result.rewriteInSearchBars !== false;
      applyGenerateSettingsFromStorage({
        generateTone: result.generateTone || defaults.generateTone,
        generateTonePreset: result.generateTonePreset || defaults.generateTonePreset,
        generateLength: result.generateLength || defaults.generateLength,
        generateComplexity:
          result.generateComplexity ||
          result.generateWording ||
          defaults.generateComplexity,
        generateIncludeSubject:
          result.generateIncludeSubject !== false,
        generateProfile: result.generateProfile || defaults.generateProfile,
      });
      syncGeneratePanelSummary();
      if (!enabled) {
        deactivateField();
        return;
      }
      waitForBody(() => {
        startGrammarChecker();
        scanForEditableFields();
      });
    };

    chrome.storage.sync.get(defaults, (syncResult) => {
      if (chrome.runtime.lastError && chrome.storage?.local) {
        chrome.storage.local.get(defaults, applyLoadedSettings);
        return;
      }
      applyLoadedSettings(syncResult);
    });
  }

  function stopAutoFixLoop() {
    autoFixInProgress = false;
    autoFixPass = 0;
    lastAutoFixFingerprint = "";
  }

  function matchFingerprint(matches, text) {
    return matches
      .map((m) => {
        const word = getMatchWord(m, text);
        const suggestion = getMatchSuggestions(m)[0] || "";
        return `${m.offset}:${m.length}:${word}:${suggestion}`;
      })
      .sort()
      .join("\n");
  }

  function shouldApplyMatch(match, text) {
    const suggestions = getMatchSuggestions(match);
    if (!suggestions.length) return false;
    const replacement = suggestions[0];
    const current = text.slice(match.offset, match.offset + match.length);
    return current !== replacement;
  }

  function getFixableMatches(matches, text) {
    return filterMatches(matches, text).filter((m) => shouldApplyMatch(m, text));
  }

  function chunkWordCount(text) {
    return text.trim().split(/\s+/).filter(Boolean).length;
  }

  function buildChunkFromGroup(group, text) {
    const start = group[0].offset ?? 0;
    const end =
      (group[group.length - 1].offset ?? 0) +
      (group[group.length - 1].length ?? 0);
    const chunk = text.slice(start, end);
    let result = chunk;

    for (const m of [...group].sort((a, b) => (b.offset ?? 0) - (a.offset ?? 0))) {
      const rel = (m.offset ?? 0) - start;
      const repl = getMatchSuggestions(m)[0] ?? "";
      result = result.slice(0, rel) + repl + result.slice(rel + (m.length ?? 0));
    }

    if (result === chunk) return null;

    return {
      ...group[0],
      offset: start,
      length: end - start,
      word: chunk,
      suggestions: [result],
      replacements: [result],
      mergedCount: group.length,
    };
  }

  /** Merge nearby single-word hits into multi-word fix chunks. */
  function mergeNearbyFixableChunks(matches, text, maxGap = MERGE_NEARBY_GAP) {
    if (!matches.length) return [];

    const sorted = [...matches].sort((a, b) => (a.offset ?? 0) - (b.offset ?? 0));
    const groups = [[sorted[0]]];

    for (let i = 1; i < sorted.length; i++) {
      const prev = groups[groups.length - 1][groups[groups.length - 1].length - 1];
      const prevEnd = (prev.offset ?? 0) + (prev.length ?? 0);
      const gap = (sorted[i].offset ?? 0) - prevEnd;
      if (gap <= maxGap) {
        groups[groups.length - 1].push(sorted[i]);
      } else {
        groups.push([sorted[i]]);
      }
    }

    const chunks = groups
      .map((group) => buildChunkFromGroup(group, text))
      .filter(Boolean);

    const multiWord = chunks.filter(
      (c) =>
        (c.mergedCount ?? 1) >= 2 ||
        chunkWordCount(c.word || text.slice(c.offset, c.offset + c.length)) >= 2
    );

    return multiWord.length ? multiWord : chunks;
  }

  function selectNextFixChunk(chunks) {
    return [...chunks].sort((a, b) => (a.offset ?? 0) - (b.offset ?? 0))[0];
  }

  function applyAllSuggestionsInField(field, matches) {
    const { raw, trimmed, trimStart } = getGrammarTextContext(field);
    const onRaw = mapMatchesToRawOffsets(
      remapMatchesToFieldText(matches, trimmed),
      trimStart
    );
    const remapped = remapMatchesToFieldText(onRaw, raw)
      .filter((m) => shouldApplyMatch(m, raw))
      .sort((a, b) => b.offset - a.offset);

    if (!remapped.length) return 0;

    cancelScheduledCheck();
    lastQuickRequestId += 1;
    lastFullRequestId += 1;
    suppressGrammarEvents = true;

    let applied = 0;
    let leftBound = Infinity;

    try {
      for (const match of remapped) {
        if (match.offset + match.length > leftBound) continue;

        const offset = match.offset;
        const length = match.length;
        const replacement = getMatchSuggestions(match)[0];
        const wrongText = getMatchWord(match, raw);

        if (isContentEditableField(field)) {
          replaceTextInContentEditable(field, offset, length, replacement, wrongText);
        } else {
          const text = getFieldText(field);
          setFieldText(
            field,
            text.slice(0, offset) + replacement + text.slice(offset + length)
          );
        }

        recordAcceptedFix(offset, length, replacement);
        optimisticUpdateAfterFix(field, match, replacement);
        leftBound = offset;
        applied += 1;
      }
    } finally {
      suppressGrammarEvents = false;
    }

    if (applied > 0) {
      field.focus();
    }

    return applied;
  }

  /** Immediately refresh underlines after a local fix, before the next server scan. */
  function optimisticUpdateAfterFix(field, match, replacement) {
    const offset = match.offset ?? 0;
    const length = match.length ?? 0;
    const end = offset + length;
    const delta = replacement.length - length;

    currentMatches = filterMatchesForDisplay(
      currentMatches
        .filter((m) => {
          const mStart = m.offset ?? 0;
          const mEnd = mStart + (m.length ?? 0);
          return !rangesOverlap(mStart, mEnd, offset, end);
        })
        .map((m) => {
          if ((m.offset ?? 0) > offset) {
            return { ...m, offset: (m.offset ?? 0) + delta };
          }
          return m;
        })
    );

    syncGrammarDisplay(field, currentMatches);
    updateBadge(currentMatches.length);
  }

  function rescanAfterFix(field, { resetPass = false } = {}) {
    lastCheckedText = "";
    if (autoFixAll) {
      if (resetPass) {
        autoFixPass = 0;
        lastAutoFixFingerprint = "";
      }
      autoFixInProgress = true;
    }
    runFullCheckImmediately(field);
  }

  function runFullCheckImmediately(field) {
    if (!isValid() || !enabled || suppressGrammarEvents) return;
    if (!(field instanceof HTMLElement) || field !== activeField) return;

    cancelScheduledCheck();

    const { trimmed, trimStart } = getGrammarTextContext(field);
    if (trimmed.length < MIN_TEXT_LENGTH) {
      stopAutoFixLoop();
      currentMatches = [];
      syncGrammarDisplay(field, []);
      updateBadge(0);
      return;
    }

    checkGrammar(field, trimmed, trimStart, { quick: false });
  }

  function continueAutoFixAfterFullCheck(field, matches, trimmed, corrected) {
    if (!autoFixAll || !enabled) {
      stopAutoFixLoop();
      return;
    }

    const filtered = filterMatches(matches, trimmed);
    const fixable = getFixableMatches(matches, trimmed);
    const chunks = mergeNearbyFixableChunks(fixable, trimmed);

    if (!filtered.length) {
      stopAutoFixLoop();
      syncGrammarDisplay(field, []);
      updateBadge(0);
      return;
    }

    if (!chunks.length) {
      stopAutoFixLoop();
      currentMatches = filterMatchesForDisplay(filtered);
      syncGrammarDisplay(field, currentMatches);
      updateBadge(currentMatches.length);
      return;
    }

    if (autoFixPass >= MAX_AUTO_FIX_PASSES) {
      stopAutoFixLoop();
      return;
    }

    const nextFix = selectNextFixChunk(chunks);
    const fingerprint = matchFingerprint([nextFix], trimmed);
    if (fingerprint === lastAutoFixFingerprint) {
      stopAutoFixLoop();
      return;
    }

    const beforeText = trimmed;
    autoFixInProgress = true;
    hideSuggestionPopup();

    const applied = applyAllSuggestionsInField(field, [nextFix]);
    const { trimmed: afterText } = getGrammarTextContext(field);

    autoFixPass += 1;
    lastAutoFixFingerprint = fingerprint;

    if (applied === 0 || afterText === beforeText) {
      stopAutoFixLoop();
      return;
    }

    rescanAfterFix(field);
  }

  function waitForBody(callback) {
    if (document.body) {
      callback();
      return;
    }

    const observer = new MutationObserver(() => {
      if (!document.body) return;
      observer.disconnect();
      callback();
    });
    observer.observe(document.documentElement, { childList: true });
  }

  function isConnectedElement(el) {
    return el instanceof Element && el.isConnected;
  }

  function usesNativeHighlights() {
    return typeof CSS !== "undefined" && !!CSS.highlights;
  }

  /** CSS ::highlight works on contenteditable; inputs/textareas need the mirror overlay. */
  function canUseNativeHighlights(field) {
    return (
      usesNativeHighlights() &&
      field instanceof HTMLElement &&
      isContentEditableField(field)
    );
  }

  function ensureActiveSession() {
    if (!activeField) return false;
    if (!canUseNativeHighlights(activeField) && !activeMirror) return false;
    if (!isConnectedElement(activeField)) {
      deactivateField();
      return false;
    }
    return true;
  }

  function scanForEditableFields() {
    if (!isValid() || !enabled) return;
    for (const field of findEditableFields()) {
      attachGrammarChecker(field);
    }
  }

  function queryAllDeep(selector) {
    const results = new Set();

    function walk(root) {
      if (!(root instanceof Document || root instanceof DocumentFragment || root instanceof Element)) {
        return;
      }
      try {
        root.querySelectorAll(selector).forEach((node) => {
          if (node instanceof HTMLElement) results.add(node);
        });
      } catch {
        /* invalid selector in some contexts */
      }
      const children =
        root instanceof Document
          ? [root.documentElement]
          : root instanceof DocumentFragment
            ? [...root.children]
            : root instanceof Element
              ? [...root.children]
              : [];
      for (const child of children) {
        if (!(child instanceof Element)) continue;
        walk(child);
        if (child.shadowRoot) walk(child.shadowRoot);
      }
    }

    walk(document);
    return [...results];
  }

  function findEditableFields() {
    const fields = new Set();

    for (const node of queryAllDeep("textarea")) {
      if (isVisibleField(node)) fields.add(node);
    }

    for (const node of queryAllDeep("input")) {
      if (node instanceof HTMLInputElement && isTextInput(node) && isVisibleField(node)) {
        fields.add(node);
      }
    }

    const editableSelector = [
      '[contenteditable="true"]',
      '[contenteditable=""]',
      '[contenteditable="plaintext-only"]',
      '[contenteditable]:not([contenteditable="false"])',
      ".ProseMirror",
      ".ql-editor",
      ".tox-edit-area",
      ".ace_text-input",
      '[data-lexical-editor="true"]',
    ].join(", ");

    for (const node of queryAllDeep(editableSelector)) {
      if (!isEditableElement(node) || !isVisibleField(node)) continue;
      if (isNestedTextbox(node)) continue;
      fields.add(normalizeEditableField(node));
    }

    for (const node of queryAllDeep(
      '[role="textbox"], [role="searchbox"], [role="combobox"], [role="search"]'
    )) {
      if (!isEditableElement(node) || !isVisibleField(node)) continue;
      if (isNestedTextbox(node)) continue;
      fields.add(normalizeEditableField(node));
    }

    return [...fields];
  }

  function isNestedTextbox(el) {
    const parent = el.parentElement?.closest(
      '[contenteditable="true"], [contenteditable=""], [contenteditable="plaintext-only"], [role="textbox"], [role="searchbox"]'
    );
    return parent && parent !== el;
  }

  function normalizeEditableField(field) {
    if (!(field instanceof HTMLElement)) return field;
    if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) {
      return field;
    }
    const root = field.closest(
      '[contenteditable="true"], [contenteditable=""], [contenteditable="plaintext-only"], [role="textbox"], [role="searchbox"], .ProseMirror, .ql-editor'
    );
    return root instanceof HTMLElement ? root : field;
  }

  function isEditableElement(el) {
    if (!(el instanceof HTMLElement)) return false;
    if (el.classList?.contains("grammar-overlay-floating")) return false;
    if (el.closest?.(".grammar-overlay-floating, .grm-suggestion-popup")) return false;
    if (el === document.body || el === document.documentElement) return false;

    if (el.getAttribute("aria-readonly") === "true" || el.getAttribute("aria-disabled") === "true") {
      return false;
    }

    if (el instanceof HTMLTextAreaElement) {
      return !el.disabled && !el.readOnly;
    }
    if (el instanceof HTMLInputElement) {
      return isTextInput(el) && !el.disabled && !el.readOnly;
    }

    if (el.isContentEditable) return true;

    const role = (el.getAttribute("role") || "").toLowerCase();
    if (role === "textbox" || role === "searchbox" || role === "combobox" || role === "search") {
      return (
        el.isContentEditable ||
        el.querySelector?.(
          "[contenteditable='true'], [contenteditable=''], .ProseMirror, .ql-editor"
        ) != null ||
        el instanceof HTMLInputElement ||
        el instanceof HTMLTextAreaElement
      );
    }

    return false;
  }

  function resolveEditableField(node) {
    if (!(node instanceof Node)) return null;

    let el = node instanceof Element ? node : node.parentElement;
    while (el) {
      if (attachedFields.has(el) && el instanceof HTMLElement) {
        return el;
      }
      if (el instanceof HTMLTextAreaElement && isVisibleField(el)) {
        return el;
      }
      if (el instanceof HTMLInputElement && isTextInput(el) && isVisibleField(el)) {
        return el;
      }
      if (isEditableElement(el) && isVisibleField(el)) {
        return normalizeEditableField(el);
      }
      el = el.parentElement;
    }

    const root = node.getRootNode?.();
    if (root instanceof ShadowRoot && root.host instanceof HTMLElement) {
      return resolveEditableField(root.host);
    }
    return null;
  }

  function onDocumentFocusIn(event) {
    if (!isValid() || !enabled) return;
    const field = resolveEditableField(event.target);
    if (!field) return;
    if (!attachedFields.has(field)) {
      attachGrammarChecker(field);
    }
    activateField(field);
  }

  function onDocumentInput(event) {
    if (!isValid() || !enabled || suppressGrammarEvents) return;
    const field = resolveEditableField(event.target);
    if (!field) return;
    if (!attachedFields.has(field)) {
      attachGrammarChecker(field);
    }
    handleFieldTyping(field, { fromUser: event.isTrusted !== false });
  }

  function isVisibleField(el) {
    if (!el.isConnected) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    if (Number(style.opacity) === 0) return false;

    if (el.isContentEditable) return true;

    const role = (el.getAttribute("role") || "").toLowerCase();
    if (role === "textbox" || role === "searchbox" || role === "search") return true;

    const rect = el.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) return true;

    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
      return !el.disabled && !el.readOnly;
    }

    return false;
  }

  function isTextInput(input) {
    const type = (input.getAttribute("type") || "text").toLowerCase();
    return !IGNORED_INPUT_TYPES.has(type);
  }

  function isContentEditableField(field) {
    return isEditableElement(field) && field.tagName !== "INPUT" && field.tagName !== "TEXTAREA";
  }

  function attachGrammarChecker(field) {
    field = normalizeEditableField(field);
    if (attachedFields.has(field)) return;
    attachedFields.add(field);

    field.addEventListener("focusin", onFieldFocusIn);
    field.addEventListener("focusout", onFieldFocusOut);
    field.addEventListener("input", onFieldInput);
    field.addEventListener("compositionend", onFieldCompositionEnd);

    const active = document.activeElement;
    if (
      field === active ||
      (active instanceof Node && field.contains(active))
    ) {
      activateField(field);
    }
  }

  function onFieldFocusIn(event) {
    onDocumentFocusIn(event);
  }

  function onFieldFocusOut(event) {
    const field = event.currentTarget;
    if (!(field instanceof HTMLElement) || field !== activeField) return;

    setTimeout(() => {
      if (!isValid()) return;
      if (ignoreNextFocusOut || overlaySetupInProgress) return;
      const focused = document.activeElement;
      if (focused && field.contains(focused)) return;
      if (suggestionPopup?.contains(focused)) return;
      deactivateField();
    }, 150);
  }

  function onFieldInput(event) {
    if (!isValid() || !enabled || suppressGrammarEvents) return;
    const field = event.currentTarget;
    if (!(field instanceof HTMLElement)) return;
    handleFieldTyping(field, { fromUser: event.isTrusted !== false });
  }

  function onFieldCompositionEnd(event) {
    onFieldInput(event);
  }

  function handleFieldTyping(field, { fromUser = true } = {}) {
    if (!isValid() || !enabled) return;
    if (!(field instanceof HTMLElement)) return;

    if (field !== activeField) {
      activateField(field);
      return;
    }

    if (fromUser) {
      reconcileAcceptedFixes(field);
      const { trimmed } = getGrammarTextContext(field);
      if (trimmed.length >= MIN_TEXT_LENGTH && trimmed === lastCheckedText) {
        return;
      }
      markTextDirty(field);
      return;
    }

    syncGrammarDisplay(field, currentMatches);
  }

  function activateField(field) {
    if (!isValid() || !enabled) return;
    field = normalizeEditableField(field);
    if (!isConnectedElement(field)) return;

    if (activeField === field && (activeMirror || canUseNativeHighlights(field))) {
      scheduleCheck(field);
      return;
    }

    deactivateField();
    overlaySetupInProgress = true;
    activeField = field;
    setupFloatingOverlay(field);
    overlaySetupInProgress = false;
    scheduleCheck(field);
  }

  function deactivateField() {
    stopAutoFixLoop();
    hideSuggestionPopup();
    acceptedFixes = [];
    detachFieldMutationObserver();
    cancelScheduledCheck();
    detachScrollListeners();
    clearGrammarHighlights();
    detachFieldClickHandler();

    if (floatingPositionHandler) {
      window.removeEventListener("scroll", floatingPositionHandler, true);
      window.removeEventListener("resize", floatingPositionHandler);
      floatingPositionHandler = null;
    }

    detachOverlay();
    activeField = null;
    currentMatches = [];
    lastCheckedText = "";
    clearActiveHighlight();
    updateBadge(0);
  }

  function setupFloatingOverlay(field) {
    ensureHighlightStyles();

    if (canUseNativeHighlights(field)) {
      activeMirror = null;
      attachFieldClickHandler(field);
    } else {
      const mirror = document.createElement("div");
      mirror.className = "grammar-overlay grammar-overlay-floating";
      mirror.setAttribute("aria-hidden", "true");
      document.body.appendChild(mirror);
      activeMirror = mirror;
      copyFieldStyles(field, mirror);
      mirror.addEventListener("mousedown", onMirrorMouseDown, true);
      mirror.addEventListener("click", onMirrorClick, true);
    }

    attachScrollListeners(field);
    syncGrammarDisplay(field, currentMatches);

    attachFieldMutationObserver(field);

    floatingPositionHandler = () => positionOverlay();
    window.addEventListener("scroll", floatingPositionHandler, true);
    window.addEventListener("resize", floatingPositionHandler);
  }

  function detachOverlay() {
    if (!activeMirror) return;

    activeMirror.removeEventListener("mousedown", onMirrorMouseDown, true);
    activeMirror.removeEventListener("click", onMirrorClick, true);
    activeMirror.remove();

    activeMirror = null;
  }

  function attachFieldMutationObserver(field) {
    detachFieldMutationObserver();

    fieldMutationObserver = new MutationObserver(() => {
      if (!isValid() || suppressGrammarEvents || overlaySetupInProgress) return;
      if (field !== activeField) return;
      if (!ensureActiveSession()) return;

      syncGrammarDisplay(field, currentMatches);
      positionOverlay();

      const { trimmed } = getGrammarTextContext(field);
      if (trimmed === lastCheckedText) return;
      markTextDirty(field);
    });

    if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) {
      return;
    }

    fieldMutationObserver.observe(field, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  }

  function detachFieldMutationObserver() {
    fieldMutationObserver?.disconnect();
    fieldMutationObserver = null;
  }

  function onScroll(event) {
    repositionRewriteUi();
    if (suggestionPopup && suggestionPopupAnchor) {
      positionSuggestionPopup(suggestionPopup, suggestionPopupAnchor);
    }
    if (!ensureActiveSession()) return;
    if (event.target === activeField || activeField.contains(event.target)) {
      positionOverlay();
    }
  }

  function onWindowChange() {
    repositionRewriteUi();
    if (suggestionPopup && suggestionPopupAnchor) {
      positionSuggestionPopup(suggestionPopup, suggestionPopupAnchor);
    }
    positionOverlay();
  }

  function positionOverlay() {
    if (!activeField || canUseNativeHighlights(activeField)) return;
    positionFloatingOverlay();
  }

  function positionFloatingOverlay() {
    if (!ensureActiveSession()) return;

    try {
      const rect = activeField.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) return;

      const styles = window.getComputedStyle(activeField);

      activeMirror.style.top = `${rect.top}px`;
      activeMirror.style.left = `${rect.left}px`;
      activeMirror.style.width = `${rect.width}px`;
      activeMirror.style.height = `${rect.height}px`;
      activeMirror.style.paddingTop = styles.paddingTop;
      activeMirror.style.paddingRight = styles.paddingRight;
      activeMirror.style.paddingBottom = styles.paddingBottom;
      activeMirror.style.paddingLeft = styles.paddingLeft;
      activeMirror.style.borderTopWidth = styles.borderTopWidth;
      activeMirror.style.borderRightWidth = styles.borderRightWidth;
      activeMirror.style.borderBottomWidth = styles.borderBottomWidth;
      activeMirror.style.borderLeftWidth = styles.borderLeftWidth;
      activeMirror.style.overflow = "auto";

      if (typeof activeField.scrollTop === "number") {
        activeMirror.scrollTop = activeField.scrollTop;
      }
      if (typeof activeField.scrollLeft === "number") {
        activeMirror.scrollLeft = activeField.scrollLeft;
      }
    } catch {
      deactivateField();
    }
  }

  function copyFieldStyles(field, mirror) {
    if (!isConnectedElement(field)) return;

    try {
      const styles = window.getComputedStyle(field);
      const props = [
        "fontFamily",
        "fontSize",
        "fontWeight",
        "fontStyle",
        "lineHeight",
        "letterSpacing",
        "textTransform",
        "textIndent",
        "paddingTop",
        "paddingRight",
        "paddingBottom",
        "paddingLeft",
        "borderTopWidth",
        "borderRightWidth",
        "borderBottomWidth",
        "borderLeftWidth",
        "boxSizing",
        "wordSpacing",
        "tabSize",
      ];

      props.forEach((prop) => {
        mirror.style[prop] = styles[prop];
      });

      mirror.style.whiteSpace = field.tagName === "INPUT" ? "pre" : "pre-wrap";
    } catch {
      deactivateField();
    }
  }

  function getFieldText(field) {
    if (!isConnectedElement(field)) return "";
    if (field.tagName === "INPUT" || field.tagName === "TEXTAREA") {
      return field.value;
    }
    return extractContentEditableText(field) || field.innerText || field.textContent || "";
  }

  /** Plain text aligned with findTextRange / CSS Highlight offsets (Gmail-safe). */
  function extractContentEditableText(field) {
    let text = "";

    function visit(node) {
      if (node.nodeType === Node.TEXT_NODE) {
        text += node.textContent || "";
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;

      const el = node;
      if (el.tagName === "BR") {
        text += "\n";
        return;
      }

      const isBlock = BLOCK_TAGS.has(el.tagName);
      if (isBlock && text && !text.endsWith("\n")) {
        text += "\n";
      }

      for (const child of el.childNodes) {
        visit(child);
      }
    }

    for (const child of field.childNodes) {
      visit(child);
    }

    return text.replace(/\u200b/g, "");
  }

  /** Plain text for a DOM range, preserving block/line breaks like extractContentEditableText. */
  function extractRangePlainText(range) {
    if (!range) return "";
    const container = document.createElement("div");
    container.appendChild(range.cloneContents());
    return extractContentEditableText(container);
  }

  function rangeContainsBlockElements(range) {
    const container = document.createElement("div");
    container.appendChild(range.cloneContents());
    for (const tag of BLOCK_TAGS) {
      if (container.querySelector(tag)) return true;
    }
    return false;
  }

  function inferRewriteBlockTag(range, wrapEl) {
    if (wrapEl instanceof HTMLElement) {
      for (const child of wrapEl.children) {
        if (BLOCK_TAGS.has(child.tagName)) return child.tagName;
      }
      const parent = wrapEl.parentElement;
      if (parent) {
        for (const sib of parent.children) {
          if (sib !== wrapEl && BLOCK_TAGS.has(sib.tagName)) return sib.tagName;
        }
      }
    }

    let node = range?.commonAncestorContainer;
    if (node?.nodeType === Node.TEXT_NODE) node = node.parentElement;
    const block = node?.closest?.("div, p, li, h1, h2, h3, h4, h5, h6, blockquote, pre, td");
    return block?.tagName || "DIV";
  }

  function shouldUseBlockLayout(range, plainText) {
    if (plainText.includes("\n")) return true;
    return rangeContainsBlockElements(range);
  }

  function captureRewriteDomSnapshot(root) {
    if (!(root instanceof HTMLElement)) return [];
    return Array.from(root.childNodes).map((node) => node.cloneNode(true));
  }

  function cloneElementShell(template) {
    if (!(template instanceof Element)) return null;
    const el = document.createElement(template.tagName);
    for (const attr of template.attributes) {
      el.setAttribute(attr.name, attr.value);
    }
    return el;
  }

  function getInlineFormatShell(element) {
    if (!(element instanceof Element)) return null;
    if (
      element.getAttribute("style") ||
      (element.tagName === "FONT" &&
        (element.getAttribute("color") ||
          element.getAttribute("face") ||
          element.getAttribute("size")))
    ) {
      return element;
    }
    for (const child of element.children) {
      if (
        child.tagName === "SPAN" ||
        child.tagName === "FONT" ||
        child.tagName === "B" ||
        child.tagName === "I" ||
        child.tagName === "U" ||
        child.tagName === "A"
      ) {
        const nested = getInlineFormatShell(child);
        if (nested) return nested;
        if (child.getAttribute("style") || child.className) return child;
      }
    }
    return null;
  }

  function replaceTextPreservingMarkup(root, newText) {
    const textNodes = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) textNodes.push(walker.currentNode);
    if (!textNodes.length) {
      if (root instanceof Element) root.textContent = newText;
      return;
    }
    textNodes[0].textContent = newText;
    for (let i = 1; i < textNodes.length; i++) {
      textNodes[i].textContent = "";
    }
  }

  function splitNormalizedLines(text) {
    const lines = [];
    let previousBlank = false;
    for (const line of normalizeEmailSpacing(text).split("\n")) {
      const isBlank = line.trim() === "";
      if (isBlank) {
        if (!previousBlank) lines.push("");
        previousBlank = true;
      } else {
        lines.push(line);
        previousBlank = false;
      }
    }
    return lines;
  }

  function createBlockFromTemplate(template, line) {
    const block =
      template instanceof Element
        ? cloneElementShell(template) || document.createElement(template.tagName)
        : document.createElement(rewriteBlockTag || "DIV");

    if (line === "") {
      const blankTemplate =
        template instanceof Element &&
        (template.querySelector("br") || template.textContent.trim() === "");
      if (blankTemplate && template.firstChild) {
        block.appendChild(template.firstChild.cloneNode(true));
      } else {
        block.appendChild(document.createElement("br"));
      }
      return block;
    }

    if (template instanceof Element) {
      const inlineShell = getInlineFormatShell(template);
      if (inlineShell) {
        const styled = inlineShell.cloneNode(false);
        styled.textContent = line;
        block.appendChild(styled);
        return block;
      }

      const cloned = template.cloneNode(true);
      replaceTextPreservingMarkup(cloned, line);
      while (cloned.firstChild) {
        block.appendChild(cloned.firstChild);
      }
      return block;
    }

    block.textContent = line;
    return block;
  }

  function buildFragmentFromBlockTemplates(blockTemplates, text) {
    const frag = document.createDocumentFragment();
    const lines = splitNormalizedLines(text);
    if (!lines.length) return frag;

    for (let i = 0; i < lines.length; i++) {
      const template = blockTemplates[Math.min(i, blockTemplates.length - 1)];
      frag.appendChild(createBlockFromTemplate(template, lines[i]));
    }
    return frag;
  }

  function findStyledShellInSnapshot(snapshot) {
    for (const node of snapshot) {
      if (node.nodeType !== Node.ELEMENT_NODE) continue;
      const shell = getInlineFormatShell(node);
      if (shell) return shell;
      if (node.tagName === "SPAN" || node.tagName === "FONT") return node;
    }
    return null;
  }

  function buildFragmentPreservingFormat(snapshot, text) {
    const frag = document.createDocumentFragment();
    const normalized = normalizeEmailSpacing(text);
    if (!snapshot?.length) {
      frag.appendChild(document.createTextNode(normalized));
      return frag;
    }

    const blockTemplates = snapshot.filter(
      (node) => node.nodeType === Node.ELEMENT_NODE && BLOCK_TAGS.has(node.tagName)
    );

    if (blockTemplates.length > 0) {
      return buildFragmentFromBlockTemplates(blockTemplates, normalized);
    }

    if (!normalized.includes("\n")) {
      const styledShell = findStyledShellInSnapshot(snapshot);
      if (styledShell) {
        const wrapper = styledShell.cloneNode(false);
        wrapper.textContent = normalized;
        frag.appendChild(wrapper);
        return frag;
      }

      if (
        snapshot.length === 1 &&
        snapshot[0].nodeType === Node.ELEMENT_NODE
      ) {
        const cloned = snapshot[0].cloneNode(true);
        replaceTextPreservingMarkup(cloned, normalized);
        frag.appendChild(cloned);
        return frag;
      }
    }

    if (rewriteUseBlocks) {
      return plainTextToBlockFragment(normalized, rewriteBlockTag);
    }

    frag.appendChild(document.createTextNode(normalized));
    return frag;
  }

  function replaceElementPreservingFormat(el, text, snapshot) {
    if (!(el instanceof HTMLElement) || !el.parentNode) return false;
    const parent = el.parentNode;
    el.replaceWith(buildFragmentPreservingFormat(snapshot, text));
    parent.normalize?.();
    return true;
  }

  function insertTextAtRangePreservingFormat(range, text, snapshot) {
    if (!range) return false;
    range.deleteContents();
    range.insertNode(buildFragmentPreservingFormat(snapshot, text));
    return true;
  }

  function plainTextToBlockFragment(text, blockTag) {
    const frag = document.createDocumentFragment();
    const tag = blockTag || "DIV";
    const normalized = normalizeEmailSpacing(text);
    let previousBlank = false;
    for (const line of normalized.split("\n")) {
      const isBlank = line.trim() === "";
      if (isBlank) {
        if (previousBlank) continue;
        previousBlank = true;
        const block = document.createElement(tag);
        block.appendChild(document.createElement("br"));
        frag.appendChild(block);
        continue;
      }
      previousBlank = false;
      const block = document.createElement(tag);
      block.textContent = line;
      frag.appendChild(block);
    }
    return frag;
  }

  function replaceElementWithPlainText(el, text, { useBlocks = false, blockTag = "DIV" } = {}) {
    if (!(el instanceof HTMLElement) || !el.parentNode) return false;
    const parent = el.parentNode;

    if (!useBlocks) {
      el.replaceWith(document.createTextNode(text));
      parent.normalize?.();
      return true;
    }

    el.replaceWith(plainTextToBlockFragment(text, blockTag));
    parent.normalize?.();
    return true;
  }

  function insertPlainTextAtRange(range, text, { useBlocks = false, blockTag = "DIV" } = {}) {
    if (!range) return false;
    range.deleteContents();
    if (!useBlocks) {
      range.insertNode(document.createTextNode(text));
      return true;
    }
    range.insertNode(plainTextToBlockFragment(text, blockTag));
    return true;
  }

  function normalizeEmailSpacing(text) {
    let normalized = String(text || "")
      .replace(/\r\n/g, "\n")
      .replace(/\r/g, "\n")
      .replace(/\u200b/g, "");

    normalized = normalized.replace(/\n{3,}/g, "\n\n");

    const lines = normalized.split("\n");
    const collapsed = [];
    let previousBlank = false;
    for (const line of lines) {
      const isBlank = line.trim() === "";
      if (isBlank) {
        if (!previousBlank) {
          collapsed.push("");
        }
        previousBlank = true;
      } else {
        collapsed.push(line);
        previousBlank = false;
      }
    }

    return collapsed.join("\n");
  }

  function normalizeRewrittenText(text) {
    return normalizeEmailSpacing(
      String(text || "")
        .replace(/\r\n/g, "\n")
        .replace(/\r/g, "\n")
        .replace(/\\n/g, "\n")
        .trim()
    );
  }

  /** Replace the entire highlighted range with one rewritten block — no word-level diffing. */
  function insertRewrittenTextAtRange(range, text) {
    if (!range) return false;

    const normalized = normalizeRewrittenText(text);
    range.deleteContents();

    const snapshot = rewriteRangeSnapshot;
    const useBlocks =
      rewriteUseBlocks || (normalized.includes("\n") && shouldUseBlockLayout(range, normalized));

    if (useBlocks) {
      range.insertNode(plainTextToBlockFragment(normalized, rewriteBlockTag || "DIV"));
      return true;
    }

    if (snapshot?.length && !normalized.includes("\n")) {
      const styledShell = findStyledShellInSnapshot(snapshot);
      if (styledShell) {
        const wrapper = styledShell.cloneNode(false);
        wrapper.textContent = normalized;
        range.insertNode(wrapper);
        return true;
      }
    }

    range.insertNode(document.createTextNode(normalized));
    return true;
  }

  /** Swap the full highlighted selection for the model response as one unit. */
  function replaceHighlightedSelectionWithRewrite(rewritten, ctx) {
    const text = normalizeRewrittenText(rewritten);
    const { range, field, inputSelection } = ctx;

    if (
      inputSelection &&
      (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement)
    ) {
      const { start, end } = inputSelection;
      commitInputOrTextareaReplacement(field, start, end, text);
      return field;
    }

    if (rewriteWateryEl) {
      resolveWateryEffect(rewriteWateryEl, text);
      return (
        field ||
        activeField ||
        rewriteWateryEl.closest?.("[contenteditable]") ||
        null
      );
    }

    if (range) {
      const liveSelection = window.getSelection();
      if (liveSelection) {
        liveSelection.removeAllRanges();
        liveSelection.addRange(range);
      }
      insertRewrittenTextAtRange(range, text);
      const anchor =
        range.commonAncestorContainer instanceof Element
          ? range.commonAncestorContainer
          : range.commonAncestorContainer?.parentElement;
      return field || activeField || (anchor ? normalizeEditableField(anchor) : null);
    }

    return field || null;
  }

  function findPhraseInText(text, phrase, hintOffset = 0) {
    if (!phrase || !text) return null;

    const searchFrom = Math.max(0, hintOffset - 80);
    let idx = text.indexOf(phrase, searchFrom);
    if (idx !== -1) {
      return { offset: idx, length: phrase.length };
    }

    idx = text.toLowerCase().indexOf(phrase.toLowerCase(), searchFrom);
    if (idx !== -1) {
      return { offset: idx, length: phrase.length };
    }

    const compact = phrase.replace(/\s+/g, " ").trim();
    if (compact.length >= 2) {
      const escaped = compact.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/ /g, "\\s+");
      const re = new RegExp(escaped, "i");
      const slice = text.slice(searchFrom);
      const match = slice.match(re);
      if (match && match.index != null) {
        return { offset: searchFrom + match.index, length: match[0].length };
      }
    }

    return null;
  }

  function remapMatchesToFieldText(matches, text) {
    return matches
      .map((match) => {
        const word = getMatchWord(match, text);
        if (!word) return null;

        let offset = match.offset ?? 0;
        let length = match.length ?? word.length;

        if (text.slice(offset, offset + length) === word) {
          return { ...match, offset, length, word };
        }

        const found = findPhraseInText(text, word, offset);
        if (!found) return null;

        return {
          ...match,
          offset: found.offset,
          length: found.length,
          word: text.slice(found.offset, found.offset + found.length),
        };
      })
      .filter(Boolean);
  }

  function ensureHighlightStyles() {
    const id = "humanizer-highlight-styles";
    if (document.getElementById(id)) return;
    const style = document.createElement("style");
    style.id = id;
    style.textContent = `
      ::highlight(humanizer-grammar) {
        text-decoration: underline solid #ff4d8d;
        text-decoration-thickness: 2px;
        text-underline-offset: 2px;
        background-color: transparent;
      }
      ::highlight(humanizer-grammar-active) {
        text-decoration: underline solid #ff4d8d;
        text-decoration-thickness: 2px;
        text-underline-offset: 2px;
        background-color: transparent;
      }
    `;
    (document.head || document.documentElement).appendChild(style);
  }

  function clearGrammarHighlights() {
    if (!usesNativeHighlights()) return;
    try {
      CSS.highlights.delete("humanizer-grammar");
      CSS.highlights.delete("humanizer-grammar-active");
    } catch {
      /* ignore */
    }
  }

  function matchToDomRange(field, match, text) {
    const word = getMatchWord(match, text);
    const start = match.offset ?? 0;
    const end = start + (match.length ?? 0);

    let range = findTextRange(field, start, end);
    if (range && word && range.toString() !== word) {
      range = null;
    }
    if (!range && word) {
      range = findTextRangeBySearch(field, word, start);
    }
    if (!range && word) {
      const found = findPhraseInText(text, word, start);
      if (found) {
        range = findTextRange(field, found.offset, found.offset + found.length);
      }
    }
    return range;
  }

  function syncGrammarHighlights(field, matches) {
    if (!canUseNativeHighlights(field)) return false;

    clearGrammarHighlights();
    const text = getFieldText(field);
    const ranges = [];

    for (const match of matches) {
      const range = matchToDomRange(field, match, text);
      if (range) {
        ranges.push(range);
      }
    }

    if (ranges.length) {
      try {
        CSS.highlights.set("humanizer-grammar", new Highlight(...ranges));
      } catch {
        for (const range of ranges) {
          try {
            const existing = CSS.highlights.get("humanizer-grammar");
            if (existing) {
              existing.add(range);
            } else {
              CSS.highlights.set("humanizer-grammar", new Highlight(range));
            }
          } catch {
            /* skip invalid range */
          }
        }
      }
    }
    return true;
  }

  function attachScrollListeners(field) {
    detachScrollListeners();
    const handler = () => positionOverlay();
    const parents = getScrollParents(field);
    parents.push(window);
    for (const parent of parents) {
      parent.addEventListener("scroll", handler, { passive: true });
      scrollParentListeners.push({ parent, handler });
    }
  }

  function detachScrollListeners() {
    for (const { parent, handler } of scrollParentListeners) {
      parent.removeEventListener("scroll", handler);
    }
    scrollParentListeners = [];
  }

  function getScrollParents(el) {
    const parents = [];
    let node = el.parentElement;
    while (node && node !== document.documentElement) {
      const style = window.getComputedStyle(node);
      const overflow = `${style.overflow} ${style.overflowY} ${style.overflowX}`;
      if (/(auto|scroll|overlay)/.test(overflow)) {
        parents.push(node);
      }
      node = node.parentElement;
    }
    return parents;
  }

  function attachFieldClickHandler(field) {
    detachFieldClickHandler();
    fieldClickHandler = (event) => onFieldGrammarClick(event, field);
    field.addEventListener("click", fieldClickHandler, true);
  }

  function detachFieldClickHandler() {
    if (activeField && fieldClickHandler) {
      activeField.removeEventListener("click", fieldClickHandler, true);
    }
    fieldClickHandler = null;
  }

  function isPointInRange(range, x, y) {
    for (const rect of range.getClientRects()) {
      if (
        x >= rect.left - 2 &&
        x <= rect.right + 2 &&
        y >= rect.top - 2 &&
        y <= rect.bottom + 2
      ) {
        return true;
      }
    }
    return false;
  }

  function onFieldGrammarClick(event, field) {
    if (!ensureActiveSession() || field !== activeField) return;
    if (Date.now() < suppressPopupUntil) return;
    if (suggestionPopup?.contains(event.target)) return;
    if (!currentMatches.length) return;

    const text = getFieldText(field);
    let hitMatch = null;
    let hitRange = null;

    for (const match of currentMatches) {
      const range = matchToDomRange(field, match, text);
      if (!range || !isPointInRange(range, event.clientX, event.clientY)) continue;
      hitMatch = match;
      hitRange = range;
      break;
    }

    if (!hitMatch) return;

    event.preventDefault();
    event.stopPropagation();

    const anchor = hitRange
      ? { getBoundingClientRect: () => hitRange.getBoundingClientRect() }
      : field;

    showSuggestionPopup(anchor, hitMatch, field);
  }

  function syncGrammarDisplay(field, matches) {
    if (canUseNativeHighlights(field)) {
      syncGrammarHighlights(field, matches);
      positionOverlay();
      return;
    }
    syncMirrorText(field, matches);
  }

  /** Server checks trimmed text; map match offsets back onto raw field text. */
  function getGrammarTextContext(field) {
    const raw = getFieldText(field);
    const trimmed = raw.trim();
    if (!trimmed) {
      return { raw, trimmed, trimStart: 0 };
    }
    const trimStart = raw.indexOf(trimmed);
    return {
      raw,
      trimmed,
      trimStart: trimStart >= 0 ? trimStart : 0,
    };
  }

  function mapMatchesToRawOffsets(matches, trimStart) {
    if (!trimStart) return matches;
    return matches.map((match) => ({
      ...match,
      offset: (match.offset ?? 0) + trimStart,
    }));
  }

  function setFieldText(field, text) {
    if (!isConnectedElement(field)) return;
    if (field.tagName === "INPUT" || field.tagName === "TEXTAREA") {
      field.value = text;
    } else {
      field.textContent = text;
    }
    field.dispatchEvent(new Event("input", { bubbles: true }));
  }

  // Commit a value into input/textarea so framework-controlled fields (React, etc.)
  // pick up the change. Adapted from github/text-expander-element onCommit, plus the
  // native prototype setter pattern required when React overrides element.value.
  function setNativeInputOrTextareaValue(field, value) {
    const prototype =
      field instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype;
    const { set: prototypeSetter } =
      Object.getOwnPropertyDescriptor(prototype, "value") || {};
    const { set: fieldSetter } =
      Object.getOwnPropertyDescriptor(field, "value") || {};

    if (prototypeSetter && fieldSetter !== prototypeSetter) {
      prototypeSetter.call(field, value);
    } else if (fieldSetter) {
      fieldSetter.call(field, value);
    } else {
      field.value = value;
    }
  }

  function notifyInputOrTextareaValueChange(field, previousValue) {
    const tracker = field._valueTracker;
    if (tracker) {
      tracker.setValue(previousValue);
    }

    field.dispatchEvent(new Event("input", { bubbles: true, cancelable: true }));
    try {
      field.dispatchEvent(
        new InputEvent("input", {
          bubbles: true,
          cancelable: true,
          inputType: "insertReplacementText",
        })
      );
    } catch {
      /* InputEvent unsupported in some contexts */
    }
  }

  function commitInputOrTextareaValue(field, newValue, selectionStart, selectionEnd) {
    if (
      !(field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) ||
      !isConnectedElement(field)
    ) {
      return;
    }

    const previousValue = field.value;
    setNativeInputOrTextareaValue(field, newValue);
    notifyInputOrTextareaValueChange(field, previousValue);

    const maxLen = newValue.length;
    const start = Math.max(0, Math.min(selectionStart ?? maxLen, maxLen));
    const end = Math.max(start, Math.min(selectionEnd ?? start, maxLen));
    field.setSelectionRange(start, end);
    field.focus({ preventScroll: true });
  }

  function commitInputOrTextareaReplacement(field, start, end, replacement) {
    const beginning = field.value.substring(0, start);
    const remaining = field.value.substring(end);
    const newValue = beginning + replacement + remaining;
    const cursor = beginning.length + replacement.length;
    commitInputOrTextareaValue(field, newValue, cursor, cursor);
  }

  function dispatchFieldInput(field) {
    field.dispatchEvent(new Event("input", { bubbles: true, cancelable: true }));
    try {
      field.dispatchEvent(
        new InputEvent("input", {
          bubbles: true,
          cancelable: true,
          inputType: "insertReplacementText",
        })
      );
    } catch {
      /* InputEvent unsupported in some contexts */
    }
  }

  function findTextRangeBySearch(root, searchText, hintOffset) {
    if (!searchText || !isConnectedElement(root)) return null;

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let charIndex = 0;
    let best = null;
    let bestDistance = Infinity;

    while (walker.nextNode()) {
      const node = walker.currentNode;
      const text = node.textContent || "";
      let index = text.indexOf(searchText);

      while (index !== -1) {
        const start = charIndex + index;
        const end = start + searchText.length;
        const distance = Math.abs(start - hintOffset);

        if (distance < bestDistance) {
          bestDistance = distance;
          const range = document.createRange();
          range.setStart(node, index);
          range.setEnd(node, index + searchText.length);
          best = range;
        }

        index = text.indexOf(searchText, index + 1);
      }

      charIndex += text.length;
    }

    return best;
  }

  function replaceTextInContentEditable(field, offset, length, replacement, wrongText) {
    const expectedWrong =
      wrongText || getFieldText(field).slice(offset, offset + length);

    let range = findTextRange(field, offset, offset + length);

    if (range && expectedWrong && range.toString() !== expectedWrong) {
      range = null;
    }

    if (!range && expectedWrong) {
      range = findTextRangeBySearch(field, expectedWrong, offset);
    }

    if (!range) {
      const text = getFieldText(field);
      setFieldText(
        field,
        text.slice(0, offset) + replacement + text.slice(offset + length)
      );
      dispatchFieldInput(field);
      return;
    }

    range.deleteContents();
    const textNode = document.createTextNode(replacement);
    range.insertNode(textNode);

    const selection = window.getSelection();
    if (selection) {
      const after = document.createRange();
      after.setStartAfter(textNode);
      after.collapse(true);
      selection.removeAllRanges();
      selection.addRange(after);
    }

    dispatchFieldInput(field);
  }

  function findTextRange(root, start, end) {
    if (!isConnectedElement(root)) return null;

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let charIndex = 0;
    let startNode = null;
    let startOffset = 0;
    let endNode = null;
    let endOffset = 0;

    while (walker.nextNode()) {
      const node = walker.currentNode;
      const nodeLength = node.textContent?.length || 0;

      if (!startNode && charIndex + nodeLength >= start) {
        startNode = node;
        startOffset = start - charIndex;
      }

      if (!endNode && charIndex + nodeLength >= end) {
        endNode = node;
        endOffset = end - charIndex;
        break;
      }

      charIndex += nodeLength;
    }

    if (!startNode || !endNode) return null;

    const range = document.createRange();
    try {
      range.setStart(startNode, Math.max(0, startOffset));
      range.setEnd(endNode, Math.max(0, endOffset));
      return range;
    } catch {
      return null;
    }
  }

  function getMatchSuggestions(match) {
    return match.suggestions || match.replacements || [];
  }

  function getMatchType(match) {
    if (match.type === "spelling" || match.type === "grammar") {
      return match.type;
    }
    if (match.match_type === "spelling" || match.match_type === "grammar") {
      return match.match_type;
    }

    const category = String(match.category || "").toLowerCase();
    const ruleId = String(match.rule_id || "").toLowerCase();

    if (
      category.includes("typo") ||
      category.includes("misspell") ||
      category.includes("spelling") ||
      ruleId.includes("morfologik") ||
      ruleId.includes("speller") ||
      ruleId.includes("hunspell")
    ) {
      return "spelling";
    }

    return "grammar";
  }

  function getMatchWord(match, text) {
    if (match.word) return match.word;
    return text.slice(match.offset, match.offset + match.length);
  }

  function isFalsePositiveMatch(match, text) {
    const ruleId = String(match.rule_id || "");
    if (ruleId === "OLLAMA_GRAMMAR") return false;

    const word = getMatchWord(match, text).trim();
    if (!word) return true;

    const suggestions = getMatchSuggestions(match);
    if (!suggestions.length) return true;

    const offset = match.offset ?? 0;
    const length = match.length ?? 0;
    if (text.slice(offset, offset + length) === suggestions[0]) return true;

    if (PUNCTUATION_ONLY_RE.test(word) && word.length <= 2) return true;

    return false;
  }

  function rangesOverlap(startA, endA, startB, endB) {
    return startA < endB && startB < endA;
  }

  function matchOverlapsAcceptedFix(match) {
    const start = match.offset ?? 0;
    const end = start + (match.length ?? 0);
    return acceptedFixes.some((fix) =>
      rangesOverlap(start, end, fix.start, fix.end)
    );
  }

  function filterMatches(matches, text) {
    return matches.filter(
      (m) => !isFalsePositiveMatch(m, text) && !matchOverlapsAcceptedFix(m)
    );
  }

  function recordAcceptedFix(offset, removedLength, replacement) {
    const removedEnd = offset + removedLength;
    const delta = replacement.length - removedLength;

    acceptedFixes = acceptedFixes
      .filter((fix) => !rangesOverlap(fix.start, fix.end, offset, removedEnd))
      .map((fix) => {
        if (fix.start >= removedEnd) {
          return {
            ...fix,
            start: fix.start + delta,
            end: fix.end + delta,
          };
        }
        return fix;
      });

    acceptedFixes.push({
      start: offset,
      end: offset + replacement.length,
      text: replacement,
    });
  }

  /** Drop or re-anchor fixes the user edited; keep fixes whose text is still intact. */
  function reconcileAcceptedFixes(field) {
    if (!isConnectedElement(field)) {
      acceptedFixes = [];
      return;
    }

    const raw = getFieldText(field);
    acceptedFixes = acceptedFixes.flatMap((fix) => {
      if (fix.end > raw.length) return [];

      if (raw.slice(fix.start, fix.end) === fix.text) {
        return [fix];
      }

      const windowStart = Math.max(0, fix.start - 80);
      const idx = raw.indexOf(fix.text, windowStart);
      if (idx === -1) return [];

      return [{ start: idx, end: idx + fix.text.length, text: fix.text }];
    });
  }

  function filterMatchesForDisplay(matches) {
    return matches.filter((m) => !matchOverlapsAcceptedFix(m));
  }

  function cancelScheduledCheck() {
    clearTimeout(checkDebounceTimer);
    checkDebounceTimer = null;
    clearTimeout(fullCheckDelayTimer);
    fullCheckDelayTimer = null;
    pendingFullCheckText = "";
  }

  /** User edited text — allow a new check after idle period. */
  function markTextDirty(field) {
    if (autoFixInProgress) stopAutoFixLoop();
    reconcileAcceptedFixes(field);
    lastCheckedText = "";
    syncGrammarDisplay(field, currentMatches);
    scheduleCheck(field);
  }

  function scheduleCheck(field) {
    if (!isValid() || !enabled || suppressGrammarEvents) return;
    if (!(field instanceof HTMLElement) || field !== activeField) return;

    const { trimmed } = getGrammarTextContext(field);
    if (trimmed.length >= MIN_TEXT_LENGTH && trimmed === lastCheckedText) {
      return;
    }

    cancelScheduledCheck();
    checkDebounceTimer = setTimeout(() => {
      checkDebounceTimer = null;
      runCheckOnce(field);
    }, CHECK_IDLE_MS);
  }

  function runCheckOnce(field) {
    if (!isValid() || !enabled) return;
    if (!ensureActiveSession() || field !== activeField) return;
    if (suppressGrammarEvents) return;

    const { trimmed, trimStart } = getGrammarTextContext(field);
    if (trimmed.length < MIN_TEXT_LENGTH) {
      lastCheckedText = "";
      currentMatches = [];
      syncGrammarDisplay(field, []);
      updateBadge(0);
      return;
    }

    if (trimmed === lastCheckedText) return;

    pendingFullCheckText = trimmed;
    checkGrammar(field, trimmed, trimStart, { quick: true });

    clearTimeout(fullCheckDelayTimer);
    fullCheckDelayTimer = setTimeout(() => {
      fullCheckDelayTimer = null;
      if (!isValid() || !enabled || field !== activeField) return;
      const { trimmed: currentTrimmed, trimStart: currentTrimStart } =
        getGrammarTextContext(field);
      if (currentTrimmed !== pendingFullCheckText) return;
      if (currentTrimmed === lastCheckedText) return;
      checkGrammar(field, currentTrimmed, currentTrimStart, { quick: false });
    }, 500);
  }

  function applyGrammarMatches(field, matches, trimmed, trimStart) {
    const { raw } = getGrammarTextContext(field);
    const filtered = filterMatches(matches, trimmed);
    const onRaw = mapMatchesToRawOffsets(
      remapMatchesToFieldText(filtered, trimmed),
      trimStart
    );
    currentMatches = remapMatchesToFieldText(onRaw, raw);
    suppressGrammarEvents = true;
    try {
      syncGrammarDisplay(field, currentMatches);
    } finally {
      suppressGrammarEvents = false;
    }
    updateBadge(currentMatches.length);
  }

  function checkGrammar(field, trimmed, trimStart, { quick = false } = {}) {
    const requestId = quick ? ++lastQuickRequestId : ++lastFullRequestId;

    chrome.runtime.sendMessage(
      { type: "checkGrammar", text: trimmed, quick },
      (response) => {
        if (!isValid()) return;
        const expectedId = quick ? lastQuickRequestId : lastFullRequestId;
        if (requestId !== expectedId || field !== activeField) return;
        if (!ensureActiveSession()) return;

        const { trimmed: currentTrimmed } = getGrammarTextContext(field);
        if (currentTrimmed !== trimmed) return;

        if (chrome.runtime.lastError || !response?.ok) {
          if (!quick && !currentMatches.length) {
            syncGrammarDisplay(field, []);
            updateBadge(0);
          }
          return;
        }

        if (quick && trimmed === lastCheckedText) {
          return;
        }

        if (quick && autoFixInProgress) {
          return;
        }

        applyGrammarMatches(
          field,
          response.data.matches || [],
          trimmed,
          trimStart
        );

        if (!quick) {
          lastCheckedText = trimmed;
          if (!filteredMatchesCount(response.data.matches || [], trimmed)) {
            stopAutoFixLoop();
          }
          continueAutoFixAfterFullCheck(
            field,
            response.data.matches || [],
            trimmed,
            response.data.corrected || ""
          );
        }
      }
    );
  }

  function filteredMatchesCount(matches, text) {
    return filterMatches(matches, text).length;
  }

  function syncMirrorText(field, matches) {
    if (!ensureActiveSession()) return;

    try {
      const text = getFieldText(field);
      activeMirror.innerHTML = buildMirrorHtml(text, matches);
      positionOverlay();
    } catch {
      deactivateField();
    }
  }

  function buildMirrorHtml(text, matches) {
    const sorted = [...matches].sort((a, b) => a.offset - b.offset);
    let html = "";
    let cursor = 0;

    for (const match of sorted) {
      const start = match.offset;
      const end = match.offset + match.length;
      if (start >= text.length) continue;
      if (end <= cursor) continue;

      if (start > cursor) {
        html += escapeHtml(text.slice(cursor, start));
      }

      const spanStart = Math.max(start, cursor);
      const snippet = text.slice(spanStart, Math.min(end, text.length));
      if (!snippet) continue;
      const matchType = getMatchType(match);
      const suggestions = JSON.stringify(getMatchSuggestions(match)).replace(/'/g, "&#39;");
      const message = escapeHtml(match.message || "Suggestion").replace(/'/g, "&#39;");

      html += `<span class="grammar-error grm-highlight grm-highlight--${matchType}" data-offset="${start}" data-length="${match.length}" data-match-type="${matchType}" data-replacements='${suggestions}' data-message='${message}' title="Click for suggestion">${escapeHtml(snippet)}</span>`;
      cursor = Math.max(cursor, end);
    }

    html += escapeHtml(text.slice(cursor));
    if (text.endsWith("\n")) {
      html += "\n";
    }
    return html || "&nbsp;";
  }

  function onMirrorMouseDown(event) {
    const errorEl = event.target.closest(".grammar-error");
    if (!errorEl || !ensureActiveSession()) return;

    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();

    ignoreNextFocusOut = true;
    setTimeout(() => {
      ignoreNextFocusOut = false;
    }, 300);
  }

  function onMirrorClick(event) {
    const errorEl = event.target.closest(".grammar-error");
    if (!errorEl) return;

    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();

    if (!ensureActiveSession()) return;

    const offset = Number(errorEl.dataset.offset);
    const length = Number(errorEl.dataset.length);
    let replacements = [];

    try {
      replacements = JSON.parse(errorEl.dataset.replacements || "[]");
    } catch {
      replacements = [];
    }

    const matchType = errorEl.dataset.matchType || "grammar";
    const fieldText = getFieldText(activeField);
    const match = currentMatches.find(
      (item) => item.offset === offset && item.length === length
    ) || {
      offset,
      length,
      word: errorEl.textContent || fieldText.slice(offset, offset + length),
      suggestions: replacements,
      replacements,
      message: errorEl.dataset.message || "Suggestion",
      type: matchType,
      match_type: matchType,
    };

    showSuggestionPopup(errorEl, match, activeField);
  }

  function buildSuggestionPreview(field, match, replacement) {
    const text = getFieldText(field);
    const start = match.offset;
    const end = start + match.length;
    const wrong = getMatchWord(match, text);
    const before = text.slice(Math.max(0, start - 28), start);
    const after = text.slice(end, Math.min(text.length, end + 28));
    const prefix = start > 28 ? "…" : "";
    const suffix = end + 28 < text.length ? "…" : "";
    return { prefix, before, wrong, replacement, after, suffix };
  }

  function correctnessIconSvg() {
    return `<svg class="grm-card__icon grm-icon--correctness" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true"><circle cx="10" cy="10" r="4" fill="#FF4D8D"/></svg>`;
  }

  function bindCloseControl(element, onClose) {
    element.addEventListener(
      "mousedown",
      (event) => {
        event.stopPropagation();
      },
      true
    );
    element.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        suppressPopupUntil = Date.now() + 400;
        onClose();
      },
      true
    );
  }

  function shouldKeepEditorFocus(event) {
    return !event.target.closest("button, a, input, label, select, textarea");
  }

  function showSuggestionPopup(anchor, match, field) {
    hideSuggestionPopup();
    setActiveHighlight(match.offset);

    const popup = document.createElement("div");
    popup.className = "grm-card grammar-inline-card";
    popup.setAttribute("role", "dialog");
    popup.setAttribute("aria-label", "Writing suggestion");

    const suggestions = getMatchSuggestions(match);
    const primary = suggestions[0];

    const header = document.createElement("div");
    header.className = "grm-card__header";
    header.innerHTML = correctnessIconSvg();

    const headerClose = document.createElement("button");
    headerClose.type = "button";
    headerClose.className = "grm-card__close";
    headerClose.setAttribute("aria-label", "Dismiss suggestion");
    headerClose.textContent = "×";
    bindCloseControl(headerClose, hideSuggestionPopup);
    header.appendChild(headerClose);
    popup.appendChild(header);

    if (primary) {
      const preview = buildSuggestionPreview(field, match, primary);
      const previewEl = document.createElement("p");
      previewEl.className = "grm-card__preview";
      previewEl.innerHTML = `
        <span class="grm-context">${escapeHtml(preview.prefix)}${escapeHtml(preview.before)}</span>
        <span class="grm-error">${escapeHtml(preview.wrong)}</span>
        <span class="grm-replacement">${escapeHtml(preview.replacement)}</span>
        <span class="grm-context">${escapeHtml(preview.after)}${escapeHtml(preview.suffix)}</span>
      `;
      popup.appendChild(previewEl);

      const actions = document.createElement("div");
      actions.className = "grm-card__actions";

      const acceptBtn = document.createElement("button");
      acceptBtn.type = "button";
      acceptBtn.className = "grm-btn--accept";
      acceptBtn.textContent = "Accept";
      acceptBtn.addEventListener(
        "mousedown",
        (event) => {
          event.stopPropagation();
        },
        true
      );
      acceptBtn.addEventListener(
        "click",
        (event) => {
          event.preventDefault();
          event.stopPropagation();
          event.stopImmediatePropagation();
          suppressPopupUntil = Date.now() + 400;
          if (!isValid()) return;
          const anchorEl = suggestionPopupAnchor;
          hideSuggestionPopup();
          applySuggestionReplacement(field, anchorEl, match, primary);
        },
        true
      );

      const dismissBtn = document.createElement("button");
      dismissBtn.type = "button";
      dismissBtn.className = "grm-btn--dismiss";
      dismissBtn.textContent = "Dismiss";
      bindCloseControl(dismissBtn, hideSuggestionPopup);

      actions.appendChild(acceptBtn);
      actions.appendChild(dismissBtn);
      popup.appendChild(actions);
    } else {
      const empty = document.createElement("p");
      empty.className = "grm-card__empty";
      empty.textContent = "No suggestion found";
      popup.appendChild(empty);

      const actions = document.createElement("div");
      actions.className = "grm-card__actions";
      const dismissBtn = document.createElement("button");
      dismissBtn.type = "button";
      dismissBtn.className = "grm-btn--dismiss";
      dismissBtn.textContent = "Dismiss";
      bindCloseControl(dismissBtn, hideSuggestionPopup);
      actions.appendChild(dismissBtn);
      popup.appendChild(actions);
    }

    popup.addEventListener("mousedown", (event) => {
      if (!shouldKeepEditorFocus(event)) return;
      event.preventDefault();
    });

    popupEscapeHandler = (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      suppressPopupUntil = Date.now() + 400;
      hideSuggestionPopup();
    };
    document.addEventListener("keydown", popupEscapeHandler, true);

    document.body.appendChild(popup);
    suggestionPopup = popup;
    suggestionPopupAnchor = anchor;
    positionSuggestionPopup(popup, anchor);
  }

  function positionSuggestionPopup(popup, anchor) {
    const rect = anchor.getBoundingClientRect();
    const popupRect = popup.getBoundingClientRect();
    const gap = 8;

    let left = rect.left;
    let top = rect.bottom + gap;

    if (top + popupRect.height > window.innerHeight - 8) {
      top = rect.top - popupRect.height - gap;
    }
    if (left + popupRect.width > window.innerWidth - 8) {
      left = window.innerWidth - popupRect.width - 8;
    }
    if (left < 8) {
      left = 8;
    }
    if (top < 8) {
      top = 8;
    }

    popup.style.top = `${top}px`;
    popup.style.left = `${left}px`;
  }

  function hideSuggestionPopup() {
    if (popupEscapeHandler) {
      document.removeEventListener("keydown", popupEscapeHandler, true);
      popupEscapeHandler = null;
    }
    suggestionPopup?.remove();
    suggestionPopup = null;
    suggestionPopupAnchor = null;
    clearActiveHighlight();
  }

  function setActiveHighlight(offset) {
    if (activeField && canUseNativeHighlights(activeField)) {
      try {
        CSS.highlights.delete("humanizer-grammar-active");
      } catch {
        /* ignore */
      }
      if (offset == null || !activeField) return;
      const text = getFieldText(activeField);
      const match = currentMatches.find((m) => m.offset === offset);
      if (!match) return;
      const range = matchToDomRange(activeField, match, text);
      if (range) {
        CSS.highlights.set("humanizer-grammar-active", new Highlight(range));
      }
      return;
    }

    if (!activeMirror) return;
    activeMirror.querySelectorAll(".grammar-error-active, .grm-highlight--active").forEach((el) => {
      el.classList.remove("grammar-error-active", "grm-highlight--active");
    });
    if (offset == null) return;
    const span = activeMirror.querySelector(
      `.grammar-error[data-offset="${offset}"]`
    );
    span?.classList.add("grammar-error-active", "grm-highlight--active");
  }

  function clearActiveHighlight() {
    if (activeField && canUseNativeHighlights(activeField)) {
      try {
        CSS.highlights.delete("humanizer-grammar-active");
      } catch {
        /* ignore */
      }
      return;
    }
    activeMirror?.querySelectorAll(".grammar-error-active, .grm-highlight--active").forEach((el) => {
      el.classList.remove("grammar-error-active", "grm-highlight--active");
    });
  }

  function applySuggestionReplacement(field, mirrorSpan, match, replacement) {
    if (!isConnectedElement(field)) return;

    const offset = match.offset;
    const length = match.length;
    const wrongText =
      match.word ||
      getFieldText(field).slice(offset, offset + length);

    cancelScheduledCheck();
    lastQuickRequestId += 1;
    lastFullRequestId += 1;
    suppressGrammarEvents = true;
    try {
      if (isContentEditableField(field)) {
        replaceTextInContentEditable(field, offset, length, replacement, wrongText);
      } else {
        const text = getFieldText(field);
        setFieldText(
          field,
          text.slice(0, offset) + replacement + text.slice(offset + length)
        );
      }
    } finally {
      suppressGrammarEvents = false;
    }

    field.focus();

    recordAcceptedFix(offset, length, replacement);

    optimisticUpdateAfterFix(field, match, replacement);

    rescanAfterFix(field, { resetPass: true });
  }

  function applyReplacement(field, offset, length, replacement) {
    applySuggestionReplacement(
      field,
      null,
      { offset, length, replacements: [replacement] },
      replacement
    );
  }

  function updateBadge(count) {
    if (!isValid()) return;
    chrome.runtime.sendMessage({ type: "updateBadge", count });
  }

  function selectionInEditableField(selection) {
    const anchor = selection?.anchorNode;
    if (anchor) {
      const field = resolveEditableField(anchor);
      if (field) return field;
    }

    const active = document.activeElement;
    if (
      active instanceof HTMLInputElement ||
      active instanceof HTMLTextAreaElement
    ) {
      if (!active.disabled && !active.readOnly) return active;
    }
    return null;
  }

  function selectionInContentEditable(selection) {
    return selectionInEditableField(selection);
  }

  function clearRewriteSelectionState() {
    savedRewriteRange = null;
    savedRewriteField = null;
    savedInputSelection = null;
    rewriteAnchorRect = null;
  }

  function getInputSelectionAnchorRect(field, start, end) {
    const rect = field.getBoundingClientRect();
    if (!(field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement)) {
      return new DOMRect(rect.right - 1, rect.bottom - 1, 1, 1);
    }

    const style = window.getComputedStyle(field);
    const textBefore = field.value.slice(0, end);
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.font = `${style.fontStyle} ${style.fontVariant} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      const textWidth = ctx.measureText(textBefore).width;
      const padLeft = Number.parseFloat(style.paddingLeft) || 0;
      const padTop = Number.parseFloat(style.paddingTop) || 0;
      const lineHeight =
        Number.parseFloat(style.lineHeight) ||
        Number.parseFloat(style.fontSize) ||
        16;
      const innerWidth = Math.max(0, rect.width - padLeft - (Number.parseFloat(style.paddingRight) || 0));
      const x = rect.left + padLeft + Math.min(textWidth, Math.max(0, innerWidth - 4));
      const y = rect.top + padTop + lineHeight;
      return new DOMRect(x, y, 1, 1);
    }

    return new DOMRect(rect.right - 1, rect.bottom - 1, 1, 1);
  }

  function getRewriteSelectionFromPage() {
    const active = document.activeElement;
    if (
      active instanceof HTMLInputElement ||
      active instanceof HTMLTextAreaElement
    ) {
      if (!active.disabled && !active.readOnly && isTextInput(active)) {
        const start = active.selectionStart ?? 0;
        const end = active.selectionEnd ?? 0;
        if (start !== end) {
          const text = active.value.slice(start, end);
          if (text.length > 10) {
            return {
              field: active,
              text,
              inputSelection: { start, end },
              range: null,
            };
          }
        }
      }
    }

    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
      return null;
    }

    const text = selection.toString();
    if (text.length <= 10) return null;

    const field = selectionInEditableField(selection);
    if (!field) return null;

    if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) {
      const start = field.selectionStart ?? 0;
      const end = field.selectionEnd ?? 0;
      if (start === end) return null;
      return {
        field,
        text: field.value.slice(start, end),
        inputSelection: { start, end },
        range: null,
      };
    }

    return {
      field,
      text,
      inputSelection: null,
      range: selection.getRangeAt(0).cloneRange(),
    };
  }

  function setRewriteSelection(rewriteSel) {
    savedRewriteField = rewriteSel.field;
    if (!attachedFields.has(rewriteSel.field)) {
      attachGrammarChecker(rewriteSel.field);
    }

    if (rewriteSel.range) {
      savedRewriteRange = rewriteSel.range;
      savedInputSelection = null;
      rewriteAnchorRect = getRangeEndRect(rewriteSel.range);
      applyRewriteHighlight(rewriteSel.range);
      return;
    }

    savedRewriteRange = null;
    savedInputSelection = rewriteSel.inputSelection;
    rewriteAnchorRect = getInputSelectionAnchorRect(
      rewriteSel.field,
      rewriteSel.inputSelection.start,
      rewriteSel.inputSelection.end
    );
    clearRewriteHighlight();
  }

  function rewriteSelectionMatches(a, b) {
    if (!a || !b) return false;
    if (a.field !== b.field) return false;
    if (a.text !== b.text) return false;
    if (a.range && b.range) return true;
    if (a.inputSelection && b.inputSelection) {
      return (
        a.inputSelection.start === b.inputSelection.start &&
        a.inputSelection.end === b.inputSelection.end
      );
    }
    return false;
  }

  function getRewritePositionRange() {
    return savedRewriteRange;
  }

  function inferPageContext() {
    const host = location.hostname.replace(/^www\./, "");
    let app = host;
    let documentType = "web_form";

    if (host.includes("mail.google")) {
      app = "gmail";
      documentType = "email";
    } else if (host.includes("docs.google")) {
      app = "google_docs";
      documentType = "document";
    } else if (host.includes("google.") && /\/search|\/webhp/.test(location.pathname)) {
      app = "google_search";
      documentType = "search";
    } else if (host.includes("slack.com")) {
      app = "slack";
      documentType = "chat_message";
    } else if (host.includes("linkedin.com")) {
      app = "linkedin";
      documentType = "social_post";
    } else if (host.includes("notion.")) {
      app = "notion";
      documentType = "document";
    }

    return {
      app,
      documentType,
      title: document.title || "",
      host,
    };
  }

  function isSearchBarField(field) {
    if (!(field instanceof HTMLElement)) return false;

    const el = normalizeEditableField(field);
    const role = (el.getAttribute("role") || "").toLowerCase();
    if (role === "searchbox" || role === "search") return true;

    if (el instanceof HTMLInputElement && (el.type || "").toLowerCase() === "search") {
      return true;
    }

    const searchContainer = el.closest(
      '[role="search"], form[role="search"], form[action*="search" i]'
    );
    if (searchContainer?.contains(el)) return true;

    const aria = (el.getAttribute("aria-label") || "").toLowerCase();
    const placeholder = (el.getAttribute("placeholder") || "").toLowerCase();
    if (/\bsearch\b/.test(aria) || /\bsearch\b/.test(placeholder)) return true;

    const name = (el.getAttribute("name") || "").toLowerCase();
    if (
      (name === "q" || name === "query" || name === "search") &&
      el.closest("form")
    ) {
      return true;
    }

    if (
      inferPageContext().app === "google_search" &&
      (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)
    ) {
      return true;
    }

    return false;
  }

  function rewriteAllowedForField(field) {
    if (rewriteInSearchBars) return true;
    return !isSearchBarField(field);
  }

  function inferFieldRole(field) {
    if (!(field instanceof HTMLElement)) {
      return { role: "unknown", label: "" };
    }

    const aria = (field.getAttribute("aria-label") || "").trim();
    const name = (field.getAttribute("name") || "").toLowerCase();
    const placeholder = (field.getAttribute("placeholder") || "").trim();
    const lowerAria = aria.toLowerCase();

    if (
      lowerAria.includes("subject") ||
      name === "subjectbox" ||
      field.closest('[aria-label*="Subject" i], [name="subjectbox"]')
    ) {
      return { role: "email_subject", label: aria || placeholder || "Subject" };
    }

    if (
      lowerAria.includes("message body") ||
      name === "messagebody" ||
      field.closest('[aria-label*="Message Body" i], [name="messagebody"]')
    ) {
      return { role: "email_body", label: aria || placeholder || "Message body" };
    }

    if (field instanceof HTMLInputElement) {
      return {
        role: "single_line_input",
        label: aria || placeholder || field.type || "input",
      };
    }

    if (field instanceof HTMLTextAreaElement) {
      return {
        role: "multi_line_textarea",
        label: aria || placeholder || "textarea",
      };
    }

    if (lowerAria.includes("to") && lowerAria.length <= 4) {
      return { role: "email_recipient", label: aria };
    }

    return {
      role: "rich_text",
      label: aria || placeholder || "",
    };
  }

  function getTextNodeOffsetHint(field, container, pointOffset) {
    let offset = 0;
    const walker = document.createTreeWalker(field, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const len = (node.textContent || "").replace(/\u200b/g, "").length;
      if (node === container) {
        return offset + pointOffset;
      }
      offset += len;
    }
    return offset;
  }

  function getRangeOffsetsInFieldText(field, range) {
    if (!field || !range) return null;

    const selected = extractRangePlainText(range);
    const fieldText = getFieldText(field);
    if (!selected || !fieldText) return null;

    const hint = getTextNodeOffsetHint(
      field,
      range.startContainer,
      range.startOffset
    );
    let idx = fieldText.indexOf(selected, Math.max(0, hint - 60));
    if (idx === -1) {
      idx = fieldText.indexOf(selected);
    }
    if (idx === -1) return null;

    return { start: idx, end: idx + selected.length };
  }

  function detectSelectionLayout(field, range) {
    let node = range.commonAncestorContainer;
    if (node.nodeType === Node.TEXT_NODE) {
      node = node.parentElement;
    }

    const block =
      node instanceof Element
        ? node.closest(
            "li, p, div, h1, h2, h3, h4, h5, h6, blockquote, pre, td, tr"
          )
        : null;
    const blockTag = block?.tagName?.toLowerCase() || "inline";
    const listRoot = block?.closest("ul, ol");
    const inList = Boolean(listRoot);
    const listType = listRoot?.tagName?.toLowerCase() || null;
    let listIndex = null;
    if (inList && block) {
      const items = Array.from(listRoot.querySelectorAll(":scope > li"));
      listIndex = items.indexOf(block.closest("li") || block) + 1;
      if (listIndex <= 0) listIndex = null;
    }

    const blocks = field
      ? Array.from(
          field.querySelectorAll("p, div:not(:empty), li, h1, h2, h3, h4, h5, h6")
        ).filter((el) => (el.textContent || "").trim())
      : [];
    let paragraphIndex = null;
    let paragraphCount = blocks.length || null;
    if (block && blocks.length) {
      const idx = blocks.findIndex((el) => el === block || el.contains(block));
      if (idx >= 0) paragraphIndex = idx + 1;
    }

    const fieldText = field ? getFieldText(field) : "";
    const fieldLineCount = fieldText ? fieldText.split("\n").length : null;

    return {
      blockType: blockTag,
      inList,
      listType,
      listIndex,
      paragraphIndex,
      paragraphCount,
      fieldLineCount,
    };
  }

  function analyzeSelectionShape(text, fieldText, start, end) {
    const trimmed = text.trim();
    const wordCount = trimmed ? trimmed.split(/\s+/).length : 0;
    const paragraphLineCount = text.split("\n").length;
    const spansParagraphs = paragraphLineCount > 1 || text.includes("\n");
    const before = fieldText.slice(Math.max(0, start - 1), start);
    const after = fieldText.slice(end, end + 1);
    const startsMidSentence =
      Boolean(before) && !/[.!?\n]\s*$/.test(fieldText.slice(Math.max(0, start - 80), start));
    const endsMidSentence =
      Boolean(after) && !/^\s*[.!?]/.test(fieldText.slice(end, end + 80));
    const isCompleteSentence =
      /[.!?]["')\]]*\s*$/.test(trimmed) && /^[A-Z0-9"(']/.test(trimmed);

    return {
      wordCount,
      paragraphLineCount,
      spansParagraphs,
      startsMidSentence,
      endsMidSentence,
      isCompleteSentence,
    };
  }

  function gatherRewriteContext(range, field) {
    const normalizedField =
      field instanceof HTMLElement ? normalizeEditableField(field) : null;
    const rawSelectedText = extractRangePlainText(range);
    const normalizedInput = rawSelectedText
      .replace(/\r\n/g, "\n")
      .replace(/\r/g, "\n")
      .replace(/\u200b/g, "");
    const selectedText = normalizeEmailSpacing(normalizedInput);
    const excessVerticalSpacing = selectedText !== normalizedInput;
    const fieldText = normalizedField ? getFieldText(normalizedField) : "";
    const offsets = normalizedField
      ? getRangeOffsetsInFieldText(normalizedField, range)
      : null;

    let before = "";
    let after = "";
    let selectionMeta = analyzeSelectionShape(selectedText, fieldText, 0, selectedText.length);

    if (offsets && fieldText) {
      const { start, end } = offsets;
      before = fieldText.slice(Math.max(0, start - 280), start).trimStart();
      after = fieldText.slice(end, Math.min(fieldText.length, end + 280)).trimEnd();
      selectionMeta = analyzeSelectionShape(selectedText, fieldText, start, end);
    } else if (fieldText && selectedText) {
      const idx = fieldText.indexOf(selectedText);
      if (idx >= 0) {
        before = fieldText.slice(Math.max(0, idx - 280), idx).trimStart();
        after = fieldText
          .slice(idx + selectedText.length, idx + selectedText.length + 280)
          .trimEnd();
        selectionMeta = analyzeSelectionShape(
          selectedText,
          fieldText,
          idx,
          idx + selectedText.length
        );
      }
    }

    return {
      page: inferPageContext(),
      field: normalizedField ? inferFieldRole(normalizedField) : { role: "unknown", label: "" },
      layout: normalizedField
        ? detectSelectionLayout(normalizedField, range)
        : { blockType: "unknown" },
      selection: {
        text: selectedText,
        excessVerticalSpacing,
        ...selectionMeta,
      },
      surrounding: {
        before,
        after,
      },
    };
  }

  function gatherRewriteContextForInput(field, { start, end }) {
    const fieldText = field.value || "";
    const rawSelectedText = fieldText.slice(start, end);
    const normalizedInput = rawSelectedText
      .replace(/\r\n/g, "\n")
      .replace(/\r/g, "\n")
      .replace(/\u200b/g, "");
    const selectedText = normalizeEmailSpacing(normalizedInput);
    const excessVerticalSpacing = selectedText !== normalizedInput;

    return {
      page: inferPageContext(),
      field: inferFieldRole(field),
      layout: { blockType: field.tagName.toLowerCase() },
      selection: {
        text: selectedText,
        excessVerticalSpacing,
        ...analyzeSelectionShape(selectedText, fieldText, start, end),
      },
      surrounding: {
        before: fieldText.slice(Math.max(0, start - 280), start).trimStart(),
        after: fieldText.slice(end, Math.min(fieldText.length, end + 280)).trimEnd(),
      },
    };
  }

  function clearRewriteHighlight() {
    if (!usesNativeHighlights()) return;
    try {
      CSS.highlights.delete("humanizer-rewrite-selection");
    } catch {
      /* ignore */
    }
  }

  function applyRewriteHighlight(range) {
    if (!usesNativeHighlights()) return;
    try {
      CSS.highlights.set("humanizer-rewrite-selection", new Highlight(range));
    } catch {
      /* ignore */
    }
  }

  function ensureHumanizerRippleFilter() {
    if (document.getElementById("humanizer-ripple-filter")) return;

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("width", "0");
    svg.setAttribute("height", "0");
    svg.style.position = "absolute";
    svg.style.overflow = "hidden";
    svg.innerHTML =
      '<filter id="humanizer-ripple-filter" x="-20%" y="-20%" width="140%" height="140%">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.015 0.05" numOctaves="2" seed="6" result="humanizer-noise">' +
      '<animate attributeName="baseFrequency" dur="4s" values="0.015 0.05;0.025 0.06;0.015 0.05" repeatCount="indefinite" />' +
      "</feTurbulence>" +
      '<feDisplacementMap in="SourceGraphic" in2="humanizer-noise" scale="7" xChannelSelector="R" yChannelSelector="G" />' +
      "</filter>";
    document.body.appendChild(svg);
  }

  function wrapRangeForWateryEffect(range) {
    const span = document.createElement("span");
    span.className = "humanizer-watery-wrap";
    try {
      range.surroundContents(span);
    } catch {
      const contents = range.extractContents();
      span.appendChild(contents);
      range.insertNode(span);
    }
    rewriteDomSnapshot = captureRewriteDomSnapshot(span);
    return span;
  }

  function startWateryEffect(el) {
    if (!(el instanceof HTMLElement)) return;
    ensureHumanizerRippleFilter();
    el.classList.remove("humanizer-watery-settle");
    el.classList.add("humanizer-watery");
  }

  function restoreRewriteDomSnapshot(wrapEl) {
    if (!(wrapEl instanceof HTMLElement) || !wrapEl.parentNode) return false;
    if (!rewriteDomSnapshot?.length) return false;
    const parent = wrapEl.parentNode;
    const frag = document.createDocumentFragment();
    for (const node of rewriteDomSnapshot) {
      frag.appendChild(node.cloneNode(true));
    }
    wrapEl.replaceWith(frag);
    parent.normalize?.();
    return true;
  }

  function cancelWateryEffect(el, originalText) {
    if (!(el instanceof HTMLElement) || !el.isConnected) return;
    el.classList.remove("humanizer-watery", "humanizer-watery-settle");
    if (restoreRewriteDomSnapshot(el)) return;
    replaceElementWithPlainText(el, originalText, {
      useBlocks: rewriteUseBlocks,
      blockTag: rewriteBlockTag,
    });
  }

  function resolveWateryEffect(el, newText) {
    if (!(el instanceof HTMLElement) || !el.isConnected) {
      return false;
    }

    el.classList.remove("humanizer-watery");
    el.classList.add("humanizer-watery-settle");

    const normalized = normalizeRewrittenText(newText);
    setTimeout(() => {
      if (!(el instanceof HTMLElement) || !el.isConnected) return;
      el.classList.remove("humanizer-watery-settle");

      const parent = el.parentNode;
      const useBlocks = rewriteUseBlocks || normalized.includes("\n");

      if (useBlocks) {
        el.replaceWith(plainTextToBlockFragment(normalized, rewriteBlockTag || "DIV"));
      } else {
        const styledShell = findStyledShellInSnapshot(rewriteDomSnapshot || []);
        if (styledShell) {
          const wrapper = styledShell.cloneNode(false);
          wrapper.textContent = normalized;
          el.replaceWith(wrapper);
        } else {
          el.replaceWith(document.createTextNode(normalized));
        }
      }
      parent?.normalize?.();
    }, 350);

    return true;
  }

  function clearRewriteWateryState() {
    rewriteWateryEl = null;
    rewriteOriginalText = "";
    rewriteUseBlocks = false;
    rewriteBlockTag = "DIV";
    rewriteDomSnapshot = null;
    rewriteRangeSnapshot = null;
  }

  function isRewriteSourceFieldTarget(target) {
    if (!savedRewriteField || !(target instanceof Node)) return false;
    const field = normalizeEditableField(savedRewriteField);
    return field instanceof HTMLElement && field.contains(target);
  }

  function wireCancelButton(button) {
    button.addEventListener("mousedown", (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!rewriteSubmitting) {
        cancelRewrite();
      }
    });
    return button;
  }

  function createCancelButton(className, label = "Cancel") {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `humanizer-action-cancel ${className}`.trim();
    button.setAttribute("aria-label", label);
    button.textContent = "×";
    return wireCancelButton(button);
  }

  function onRewriteOutsidePointerDown(event) {
    if (!isValid() || !enabled || rewriteSubmitting) return;
    if (!rewriteUiVisible()) return;
    if (eventHitsRewriteUi(event.target)) return;
    if (!rewriteUiBlockingSelection() && isRewriteSourceFieldTarget(event.target)) {
      return;
    }
    cancelRewrite();
  }

  function rewriteUiVisible() {
    return !!(rewriteCircleEl || rewriteBoxEl || rewriteMenuEl || generatePanelEl);
  }

  function rewriteUiBlockingSelection() {
    return rewriteSubmitting || rewriteInputOpen || rewriteMenuOpen || Boolean(generateStep);
  }

  function eventHitsRewriteUi(target) {
    if (!(target instanceof Element)) return false;
    return !!target.closest(
      ".humanizer-rewrite-btn, .humanizer-rewrite-box, .humanizer-rewrite-menu, .humanizer-generate-panel, .humanizer-action-cancel"
    );
  }

  function getActiveRewritePanel() {
    if (
      rewriteBoxEl &&
      !rewriteBoxEl.classList.contains("humanizer-rewrite-box--hidden")
    ) {
      return rewriteBoxEl;
    }
    if (
      generatePanelEl &&
      !generatePanelEl.classList.contains("humanizer-generate-panel--hidden")
    ) {
      return generatePanelEl;
    }
    if (
      rewriteMenuEl &&
      !rewriteMenuEl.classList.contains("humanizer-rewrite-menu--hidden")
    ) {
      return rewriteMenuEl;
    }
    return rewriteCircleEl;
  }

  function hideRewriteSubpanels() {
    rewriteMenuOpen = false;
    generateStep = null;
    generateFormat = null;
    rewriteInputOpen = false;

    if (rewriteMenuEl) {
      rewriteMenuEl.classList.add("humanizer-rewrite-menu--hidden");
      rewriteMenuEl.classList.remove(
        "humanizer-rewrite-menu--visible",
        "humanizer-rewrite-menu--hiding"
      );
    }
    if (generatePanelEl) {
      generatePanelEl.classList.add("humanizer-generate-panel--hidden");
      generatePanelEl.classList.remove(
        "humanizer-generate-panel--visible",
        "humanizer-generate-panel--hiding",
        "humanizer-generate-panel--error"
      );
      const formatStep = generatePanelEl.querySelector(".humanizer-generate-formats");
      const notesStep = generatePanelEl.querySelector(".humanizer-generate-notes");
      formatStep?.classList.remove("humanizer-generate-formats--hidden");
      notesStep?.classList.add("humanizer-generate-notes--hidden");
      const notesInput = generatePanelEl.querySelector("textarea");
      if (notesInput) notesInput.value = "";
    }
    if (rewriteBoxEl) {
      rewriteBoxEl.classList.add("humanizer-rewrite-box--hidden");
      rewriteBoxEl.classList.remove(
        "humanizer-rewrite-box--visible",
        "humanizer-rewrite-box--hiding",
        "humanizer-rewrite-box--error"
      );
      const rewriteInput = rewriteBoxEl.querySelector("input");
      if (rewriteInput) rewriteInput.value = "";
    }
  }

  function getRangeEndRect(range) {
    const rects = range.getClientRects();
    if (rects.length > 0) {
      return rects[rects.length - 1];
    }
    return range.getBoundingClientRect();
  }

  function positionAtSelectionCorner(el, range) {
    if (!el) return;
    const endRect = range ? getRangeEndRect(range) : rewriteAnchorRect;
    if (!endRect) return;
    const width = el.offsetWidth || 32;
    const height = el.offsetHeight || 32;
    const gap = 8;

    // Bottom-right of selection end, with a small gap from the text.
    let left = endRect.right + gap;
    let top = endRect.bottom + gap;

    if (left + width > window.innerWidth - 8) {
      left = endRect.right - width - gap;
    }
    if (top + height > window.innerHeight - 8) {
      top = endRect.top - height - gap;
    }

    left = Math.min(Math.max(8, left), Math.max(8, window.innerWidth - width - 8));
    top = Math.min(Math.max(8, top), Math.max(8, window.innerHeight - height - 8));
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
  }

  function repositionRewriteUi() {
    if ((!savedRewriteRange && !rewriteAnchorRect) || rewriteSubmitting) return;
    if (savedRewriteRange) {
      applyRewriteHighlight(savedRewriteRange);
    }
    const anchor = getRewritePositionRange();
    const panel = getActiveRewritePanel();
    if (panel) {
      positionAtSelectionCorner(panel, anchor);
    }
  }

  function setRewriteLoading(loading) {
    rewriteSubmitting = loading;
    const input = rewriteBoxEl?.querySelector("input");
    const sendButton = rewriteBoxEl?.querySelector(".humanizer-rewrite-send");
    const cancelButton = rewriteBoxEl?.querySelector(".humanizer-rewrite-cancel");
    const notesInput = generatePanelEl?.querySelector("textarea");
    const generateSend = generatePanelEl?.querySelector(".humanizer-generate-send");
    const generateCancel = generatePanelEl?.querySelector(".humanizer-generate-cancel");
    if (input) input.disabled = loading;
    if (sendButton) sendButton.disabled = loading;
    if (cancelButton) cancelButton.disabled = loading;
    if (notesInput) notesInput.disabled = loading;
    if (generateSend) generateSend.disabled = loading;
    if (generateCancel) generateCancel.disabled = loading;
    const notesCancel = generatePanelEl?.querySelector(".humanizer-generate-notes-cancel");
    if (notesCancel) notesCancel.disabled = loading;

    if (!rewriteCircleEl || !rewriteBoxEl) return;

    if (loading) {
      rewriteBoxEl.classList.add("humanizer-rewrite-box--hidden");
      rewriteCircleEl.classList.remove("humanizer-rewrite-btn--hidden");
      rewriteCircleEl.classList.add("humanizer-rewrite-btn--loading");
      if (savedRewriteRange || rewriteAnchorRect) {
        positionAtSelectionCorner(rewriteCircleEl, getRewritePositionRange());
      }
      return;
    }

    rewriteCircleEl.classList.remove("humanizer-rewrite-btn--loading");
  }

  function cancelRewrite() {
    if (rewriteWateryEl) {
      cancelWateryEffect(rewriteWateryEl, rewriteOriginalText);
      clearRewriteWateryState();
    }
    if (rewriteSubmitting) {
      rewriteSubmitting = false;
    }
    hideRewriteUI();
  }

  function removeRewriteUi() {
    rewriteCircleEl?.remove();
    rewriteBoxEl?.remove();
    rewriteMenuEl?.remove();
    generatePanelEl?.remove();
    rewriteCircleEl = null;
    rewriteBoxEl = null;
    rewriteMenuEl = null;
    generatePanelEl = null;
    rewriteInputOpen = false;
    rewriteMenuOpen = false;
    generateStep = null;
    generateFormat = null;
    rewriteSubmitting = false;
  }

  function hideRewriteUI({ animate = true } = {}) {
    if (!rewriteUiVisible()) {
      clearRewriteHighlight();
      clearRewriteSelectionState();
      rewriteSubmitting = false;
      rewriteInputOpen = false;
      rewriteMenuOpen = false;
      generateStep = null;
      generateFormat = null;
      return;
    }

    const finish = () => {
      removeRewriteUi();
      clearRewriteHighlight();
      clearRewriteSelectionState();
      clearRewriteWateryState();
    };

    if (!animate) {
      finish();
      return;
    }

    const fading = getActiveRewritePanel();
    if (!fading) {
      finish();
      return;
    }

    fading.classList.remove(
      "humanizer-rewrite-box--visible",
      "humanizer-rewrite-btn--visible",
      "humanizer-rewrite-menu--visible",
      "humanizer-generate-panel--visible"
    );
    const hidingClass =
      fading === rewriteBoxEl
        ? "humanizer-rewrite-box--hiding"
        : fading === rewriteMenuEl
          ? "humanizer-rewrite-menu--hiding"
          : fading === generatePanelEl
            ? "humanizer-generate-panel--hiding"
            : "humanizer-rewrite-btn--hiding";
    fading.classList.add(hidingClass);
    const onDone = () => finish();
    fading.addEventListener("transitionend", onDone, { once: true });
    setTimeout(onDone, 180);
  }

  function ensureRewriteCircle() {
    if (rewriteCircleEl) return rewriteCircleEl;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "humanizer-rewrite-btn humanizer-rewrite-btn--hidden";
    btn.setAttribute("aria-label", "Writing tools");
    btn.innerHTML =
      '<span class="humanizer-rewrite-btn-icon" aria-hidden="true">↗</span>' +
      '<span class="humanizer-rewrite-btn-spinner" aria-hidden="true"></span>';

    btn.addEventListener("mousedown", (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
    btn.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!rewriteSubmitting && !rewriteUiBlockingSelection()) {
        openRewriteActionMenu();
      }
    });

    document.body.appendChild(btn);
    rewriteCircleEl = btn;
    return btn;
  }

  function ensureRewriteBox() {
    if (rewriteBoxEl) return rewriteBoxEl;

    const box = document.createElement("div");
    box.className = "humanizer-rewrite-box humanizer-rewrite-box--hidden";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-label", "Rewrite tone");

    const input = document.createElement("input");
    input.type = "text";
    input.placeholder = "Tone… e.g. friendly, formal, simple";
    input.setAttribute("aria-label", "Rewrite tone");

    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        cancelRewrite();
        return;
      }
      if (event.key === "Enter" && !rewriteSubmitting) {
        event.preventDefault();
        submitRewrite(input);
      }
    });

    const sendButton = document.createElement("button");
    sendButton.type = "button";
    sendButton.className = "humanizer-rewrite-send";
    sendButton.setAttribute("aria-label", "Submit rewrite");
    sendButton.textContent = "→";

    const cancelButton = createCancelButton(
      "humanizer-rewrite-cancel",
      "Cancel rewrite"
    );

    sendButton.addEventListener("mousedown", (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
    sendButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!rewriteSubmitting) {
        submitRewrite(input);
      }
    });

    box.appendChild(input);
    box.appendChild(cancelButton);
    box.appendChild(sendButton);
    box.addEventListener("mousedown", (event) => {
      event.stopPropagation();
    });

    document.body.appendChild(box);
    rewriteBoxEl = box;
    return box;
  }

  function ensureRewriteMenu() {
    if (rewriteMenuEl) return rewriteMenuEl;

    const menu = document.createElement("div");
    menu.className = "humanizer-rewrite-menu humanizer-rewrite-menu--hidden";
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-label", "Writing actions");

    const rewriteBtn = document.createElement("button");
    rewriteBtn.type = "button";
    rewriteBtn.className =
      "humanizer-rewrite-menu-item humanizer-rewrite-menu-item--icon-only";
    rewriteBtn.setAttribute("role", "menuitem");
    rewriteBtn.setAttribute("aria-label", "Rewrite");
    rewriteBtn.innerHTML =
      '<img class="humanizer-rewrite-menu-item-icon" src="' +
      rewriteIconUrl() +
      '" alt="" width="18" height="18" draggable="false">' +
      '<span class="humanizer-rewrite-menu-item-label">Rewrite</span>';
    rewriteBtn.addEventListener("mousedown", (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
    rewriteBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openRewriteInput();
    });

    const generateBtn = document.createElement("button");
    generateBtn.type = "button";
    generateBtn.className =
      "humanizer-rewrite-menu-item humanizer-rewrite-menu-item--icon-only";
    generateBtn.setAttribute("role", "menuitem");
    generateBtn.setAttribute("aria-label", "Generate");
    generateBtn.innerHTML =
      '<img class="humanizer-rewrite-menu-item-icon" src="' +
      generateIconUrl() +
      '" alt="" width="18" height="18" draggable="false">' +
      '<span class="humanizer-rewrite-menu-item-label">Generate</span>';
    generateBtn.addEventListener("mousedown", (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
    generateBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openGenerateFormatStep();
    });

    menu.appendChild(rewriteBtn);
    menu.appendChild(generateBtn);
    menu.addEventListener("mousedown", (event) => {
      event.stopPropagation();
    });

    document.body.appendChild(menu);
    rewriteMenuEl = menu;
    return menu;
  }

  function ensureGeneratePanel() {
    if (generatePanelEl) return generatePanelEl;

    const panel = document.createElement("div");
    panel.className = "humanizer-generate-panel humanizer-generate-panel--hidden";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Generate writing");

    const formatStep = document.createElement("div");
    formatStep.className = "humanizer-generate-formats";

    const formatLabel = document.createElement("p");
    formatLabel.className = "humanizer-generate-label";
    formatLabel.textContent = "Generate as";

    const formatActions = document.createElement("div");
    formatActions.className = "humanizer-generate-format-actions";

    for (const [format, label] of [
      ["email", "Email"],
      ["essay", "Essay"],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "humanizer-generate-format-btn";
      button.dataset.format = format;
      button.textContent = label;
      button.addEventListener("mousedown", (event) => {
        event.preventDefault();
        event.stopPropagation();
      });
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        openGenerateNotesStep(format);
      });
      formatActions.appendChild(button);
    }

    formatStep.appendChild(formatLabel);
    formatStep.appendChild(formatActions);

    const panelCancel = createCancelButton(
      "humanizer-generate-cancel",
      "Cancel generate"
    );

    const notesStep = document.createElement("div");
    notesStep.className = "humanizer-generate-notes humanizer-generate-notes--hidden";

    const settingsSummary = document.createElement("p");
    settingsSummary.className = "humanizer-generate-settings-summary";
    settingsSummary.textContent = formatGenerateSettingsSummary();
    settingsSummary.title = "Change in extension settings";

    const notesBody = document.createElement("div");
    notesBody.className = "humanizer-generate-notes-row";

    const notesInput = document.createElement("textarea");
    notesInput.rows = 2;
    notesInput.placeholder = "Anything to specify? (optional)";
    notesInput.setAttribute("aria-label", "Generation notes");

    notesInput.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        cancelRewrite();
        return;
      }
      if (event.key === "Enter" && !event.shiftKey && !rewriteSubmitting) {
        event.preventDefault();
        submitGenerate(notesInput);
      }
    });

    const sendButton = document.createElement("button");
    sendButton.type = "button";
    sendButton.className = "humanizer-generate-send";
    sendButton.setAttribute("aria-label", "Generate text");
    sendButton.textContent = "→";

    const notesCancel = createCancelButton(
      "humanizer-generate-notes-cancel",
      "Cancel generate"
    );

    sendButton.addEventListener("mousedown", (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
    sendButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!rewriteSubmitting) {
        submitGenerate(notesInput);
      }
    });

    notesBody.appendChild(notesInput);
    notesBody.appendChild(notesCancel);
    notesBody.appendChild(sendButton);

    notesStep.appendChild(settingsSummary);
    notesStep.appendChild(notesBody);

    panel.appendChild(panelCancel);
    panel.appendChild(formatStep);
    panel.appendChild(notesStep);
    panel.addEventListener("mousedown", (event) => {
      event.stopPropagation();
    });

    document.body.appendChild(panel);
    generatePanelEl = panel;
    return panel;
  }

  function openRewriteActionMenu() {
    if (!savedRewriteField && !savedRewriteRange) return;
    hideRewriteSubpanels();
    rewriteMenuOpen = true;
    const circle = ensureRewriteCircle();
    const menu = ensureRewriteMenu();
    circle.classList.add("humanizer-rewrite-btn--hidden");
    circle.classList.remove("humanizer-rewrite-btn--visible");
    menu.classList.remove("humanizer-rewrite-menu--hidden", "humanizer-rewrite-menu--hiding");
    const anchor = getRewritePositionRange();
    positionAtSelectionCorner(menu, anchor);
    menu.classList.add("humanizer-rewrite-menu--visible");
    requestAnimationFrame(() => {
      positionAtSelectionCorner(menu, anchor);
    });
  }

  function openGenerateFormatStep() {
    if (!savedRewriteField && !savedRewriteRange) return;
    rewriteMenuOpen = false;
    generateStep = "format";
    generateFormat = null;
    const menu = ensureRewriteMenu();
    const panel = ensureGeneratePanel();
    menu.classList.add("humanizer-rewrite-menu--hidden");
    menu.classList.remove("humanizer-rewrite-menu--visible");
    panel.classList.remove(
      "humanizer-generate-panel--hidden",
      "humanizer-generate-panel--hiding",
      "humanizer-generate-panel--error"
    );
    panel.querySelector(".humanizer-generate-formats")?.classList.remove(
      "humanizer-generate-formats--hidden"
    );
    panel.querySelector(".humanizer-generate-notes")?.classList.add(
      "humanizer-generate-notes--hidden"
    );
    syncGeneratePanelSummary();
    const anchor = getRewritePositionRange();
    positionAtSelectionCorner(panel, anchor);
    panel.classList.add("humanizer-generate-panel--visible");
  }

  function openGenerateNotesStep(format) {
    generateStep = "notes";
    generateFormat = format;
    const panel = ensureGeneratePanel();
    panel.querySelector(".humanizer-generate-formats")?.classList.add(
      "humanizer-generate-formats--hidden"
    );
    const notesStep = panel.querySelector(".humanizer-generate-notes");
    notesStep?.classList.remove("humanizer-generate-notes--hidden");
    syncGeneratePanelSummary();
    const notesInput = panel.querySelector("textarea");
    const anchor = getRewritePositionRange();
    positionAtSelectionCorner(panel, anchor);
    panel.classList.add("humanizer-generate-panel--visible");
    notesInput?.focus();
    requestAnimationFrame(() => {
      positionAtSelectionCorner(panel, anchor);
    });
  }

  function showRewriteCircle(range) {
    hideRewriteSubpanels();
    const circle = ensureRewriteCircle();
    const box = ensureRewriteBox();
    box.classList.add("humanizer-rewrite-box--hidden");
    box.classList.remove(
      "humanizer-rewrite-box--visible",
      "humanizer-rewrite-box--hiding",
      "humanizer-rewrite-box--error"
    );
    const input = box.querySelector("input");
    if (input && document.activeElement !== input) {
      input.value = "";
    }
    circle.classList.remove(
      "humanizer-rewrite-btn--hidden",
      "humanizer-rewrite-btn--hiding",
      "humanizer-rewrite-btn--loading"
    );
    const anchor = range || getRewritePositionRange();
    positionAtSelectionCorner(circle, anchor);
    requestAnimationFrame(() => {
      positionAtSelectionCorner(circle, anchor);
      circle.classList.add("humanizer-rewrite-btn--visible");
    });
  }

  function openRewriteInput() {
    if (!savedRewriteField && !savedRewriteRange) return;
    rewriteMenuOpen = false;
    generateStep = null;
    generateFormat = null;
    rewriteInputOpen = true;
    const circle = ensureRewriteCircle();
    const box = ensureRewriteBox();
    const menu = ensureRewriteMenu();
    const panel = ensureGeneratePanel();
    circle.classList.add("humanizer-rewrite-btn--hidden");
    circle.classList.remove("humanizer-rewrite-btn--visible");
    menu.classList.add("humanizer-rewrite-menu--hidden");
    menu.classList.remove("humanizer-rewrite-menu--visible");
    panel.classList.add("humanizer-generate-panel--hidden");
    panel.classList.remove("humanizer-generate-panel--visible");
    box.classList.remove("humanizer-rewrite-box--hidden", "humanizer-rewrite-box--hiding");
    const anchor = getRewritePositionRange();
    positionAtSelectionCorner(box, anchor);
    box.classList.add("humanizer-rewrite-box--visible");
    box.querySelector("input")?.focus();
    requestAnimationFrame(() => {
      positionAtSelectionCorner(box, anchor);
    });
  }

  async function callGenerateApi(text, format, notes, context, settings) {
    const headers = await humanizerApiHeaders();
    const ai = await humanizerAiPayload();
    const response = await fetch(GENERATE_API, {
      method: "POST",
      headers,
      body: JSON.stringify({
        text,
        format,
        notes: notes || "",
        context,
        settings,
        ai,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || `Generate failed (${response.status})`);
    }
    return normalizeRewrittenText(data.generated || "");
  }

  function collectTransformationPayload() {
    if (!savedRewriteRange && !savedInputSelection) {
      return null;
    }

    const field = savedRewriteField;
    let rawText;
    let text;
    let rewriteContext;
    let range = null;
    let inputSelection = null;

    if (savedRewriteRange) {
      rawText = extractRangePlainText(savedRewriteRange);
      text = normalizeEmailSpacing(rawText);
      if (!text.trim()) {
        return null;
      }

      range = savedRewriteRange.cloneRange();
      rewriteUseBlocks = shouldUseBlockLayout(range, text);
      rewriteBlockTag = inferRewriteBlockTag(range, null);
      rewriteContext = gatherRewriteContext(range, field);
      clearRewriteHighlight();

      const selection = window.getSelection();
      if (selection) {
        selection.removeAllRanges();
        selection.addRange(range);
      }

      rewriteOriginalText = rawText;
      rewriteRangeSnapshot = Array.from(
        savedRewriteRange.cloneContents().childNodes
      ).map((node) => node.cloneNode(true));
      rewriteWateryEl = null;
      try {
        rewriteWateryEl = wrapRangeForWateryEffect(range);
        rewriteBlockTag = inferRewriteBlockTag(range, rewriteWateryEl);
        startWateryEffect(rewriteWateryEl);
      } catch {
        rewriteWateryEl = null;
      }
    } else {
      rawText = field.value.slice(
        savedInputSelection.start,
        savedInputSelection.end
      );
      text = normalizeEmailSpacing(rawText);
      if (!text.trim()) {
        return null;
      }

      inputSelection = { ...savedInputSelection };
      rewriteContext = gatherRewriteContextForInput(field, savedInputSelection);
      rewriteOriginalText = rawText;
      rewriteWateryEl = null;
      rewriteRangeSnapshot = null;
      rewriteUseBlocks = false;
    }

    return {
      text,
      rewriteContext,
      resultCtx: { range, field, inputSelection },
    };
  }

  function handleTransformationFailure(reopenFn) {
    setRewriteLoading(false);
    if (!isValid()) return;
    if (rewriteWateryEl) {
      cancelWateryEffect(rewriteWateryEl, rewriteOriginalText);
      clearRewriteWateryState();
    }
    reopenFn();
    generatePanelEl?.classList.add("humanizer-generate-panel--error");
    rewriteBoxEl?.classList.add("humanizer-rewrite-box--error");
    setTimeout(() => {
      generatePanelEl?.classList.remove("humanizer-generate-panel--error");
      rewriteBoxEl?.classList.remove("humanizer-rewrite-box--error");
    }, 1200);
  }
  async function callRewriteApi(text, prompt, context) {
    const headers = await humanizerApiHeaders();
    const ai = await humanizerAiPayload();
    const response = await fetch(REWRITE_API, {
      method: "POST",
      headers,
      body: JSON.stringify({ text, prompt, context, ai }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || `Rewrite failed (${response.status})`);
    }
    return normalizeRewrittenText(data.rewritten || "");
  }

  function finishRewriteField(targetField, { skipInputDispatch = false } = {}) {
    if (!(targetField instanceof HTMLElement)) return;
    const normalized = normalizeEditableField(targetField);
    suppressGrammarEvents = true;
    try {
      if (!skipInputDispatch) {
        dispatchFieldInput(normalized);
      }
    } finally {
      suppressGrammarEvents = false;
    }
    if (normalized !== activeField) {
      attachGrammarChecker(normalized);
      activateField(normalized);
    }
    markTextDirty(normalized);
    scheduleCheck(normalized);
  }

  function applyRewriteResult(rewrittenRaw, ctx) {
    hideRewriteUI();

    const isInputField =
      ctx.inputSelection &&
      (ctx.field instanceof HTMLInputElement ||
        ctx.field instanceof HTMLTextAreaElement);

    suppressGrammarEvents = true;
    let targetField = null;
    try {
      targetField = replaceHighlightedSelectionWithRewrite(rewrittenRaw, ctx);
    } finally {
      suppressGrammarEvents = false;
    }

    clearRewriteWateryState();
    finishRewriteField(targetField, { skipInputDispatch: Boolean(isInputField) });
  }

  function submitRewrite(inputEl) {
    if (rewriteSubmitting) return;

    const input =
      inputEl || rewriteBoxEl?.querySelector("input");
    const prompt = (input?.value || "").trim();

    if (!prompt) {
      input?.focus();
      rewriteBoxEl?.classList.add("humanizer-rewrite-box--error");
      setTimeout(() => {
        rewriteBoxEl?.classList.remove("humanizer-rewrite-box--error");
      }, 1200);
      return;
    }

    const payload = collectTransformationPayload();
    if (!payload) {
      hideRewriteUI({ animate: false });
      return;
    }

    setRewriteLoading(true);

    callRewriteApi(payload.text, prompt, payload.rewriteContext)
      .then((rewrittenRaw) => {
        setRewriteLoading(false);
        if (!isValid()) return;
        applyRewriteResult(rewrittenRaw, payload.resultCtx);
      })
      .catch(() => {
        handleTransformationFailure(() => openRewriteInput());
      });
  }

  function submitGenerate(notesEl) {
    if (rewriteSubmitting || !generateFormat) return;

    const notesInput = notesEl || generatePanelEl?.querySelector("textarea");
    const notes = (notesInput?.value || "").trim();

    const payload = collectTransformationPayload();
    if (!payload) {
      hideRewriteUI({ animate: false });
      return;
    }

    setRewriteLoading(true);

    const settings = readStoredGenerateSettings();

    callGenerateApi(
      payload.text,
      generateFormat,
      notes,
      payload.rewriteContext,
      settings
    )
      .then((generatedRaw) => {
        setRewriteLoading(false);
        if (!isValid()) return;
        applyRewriteResult(generatedRaw, payload.resultCtx);
      })
      .catch(() => {
        handleTransformationFailure(() => openGenerateNotesStep(generateFormat));
      });
  }

  function onRewriteDocumentKeydown(event) {
    if (event.key === "Escape" && rewriteUiVisible()) {
      cancelRewrite();
    }
  }

  let rewriteSelectionChangeTimer = null;

  function onDocumentSelectionChange() {
    if (!isValid() || !enabled || rewriteUiBlockingSelection()) return;
    clearTimeout(rewriteSelectionChangeTimer);
    rewriteSelectionChangeTimer = setTimeout(() => {
      if (!isValid() || !enabled || rewriteUiBlockingSelection()) return;
      const rewriteSel = getRewriteSelectionFromPage();
      if (!rewriteSel || !rewriteAllowedForField(rewriteSel.field)) return;
      if (
        !(rewriteSel.field instanceof HTMLInputElement) &&
        !(rewriteSel.field instanceof HTMLTextAreaElement)
      ) {
        return;
      }
      setRewriteSelection(rewriteSel);
      showRewriteCircle(rewriteSel.range);
    }, 80);
  }

  function onDocumentMouseUp(event) {
    if (!isValid() || !enabled) return;
    if (eventHitsRewriteUi(event.target)) {
      return;
    }

    requestAnimationFrame(() => {
      if (!isValid() || !enabled) return;
      if (eventHitsRewriteUi(event.target)) {
        return;
      }

      const rewriteSel = getRewriteSelectionFromPage();
      const hasValidSelection = Boolean(rewriteSel && rewriteAllowedForField(rewriteSel.field));

      if (rewriteUiVisible() && !hasValidSelection) {
        if (rewriteSubmitting) {
          return;
        }
        if (eventHitsRewriteUi(event.target)) {
          repositionRewriteUi();
          return;
        }
        cancelRewrite();
        return;
      }

      if (rewriteSubmitting) {
        return;
      }

      if (!hasValidSelection) {
        return;
      }

      const currentSel = {
        field: rewriteSel.field,
        text: rewriteSel.text,
        inputSelection: rewriteSel.inputSelection,
        range: rewriteSel.range,
      };
      const previousSel = {
        field: savedRewriteField,
        text: savedRewriteRange
          ? savedRewriteRange.toString()
          : savedInputSelection
            ? savedRewriteField?.value?.slice(
                savedInputSelection.start,
                savedInputSelection.end
              )
            : "",
        inputSelection: savedInputSelection,
        range: savedRewriteRange,
      };

      if (rewriteUiVisible() && rewriteSelectionMatches(currentSel, previousSel)) {
        setRewriteSelection(rewriteSel);
        repositionRewriteUi();
        return;
      }

      setRewriteSelection(rewriteSel);
      showRewriteCircle(rewriteSel.range);
    });
  }

  function escapeHtml(value) {
    return value
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
})();
