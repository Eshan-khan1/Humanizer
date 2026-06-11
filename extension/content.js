console.log("✅ Grammar checker loaded on:", window.location.href);

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
  let rescanIntervalId = null;

  const isValid = () => {
    try {
      return !!chrome.runtime?.id;
    } catch {
      return false;
    }
  };

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

  init();

  function init() {
    document.querySelectorAll(".humanizer-side-panel").forEach((el) => el.remove());

    waitForBody(() => startGrammarChecker());

    loadEnabledSetting();

    if (chrome.storage?.onChanged) {
      chrome.storage.onChanged.addListener((changes, area) => {
        if (area !== "sync") return;
        if (changes.enabled) {
          enabled = changes.enabled.newValue !== false;
          if (!enabled) {
            stopAutoFixLoop();
            deactivateField();
          } else {
            startGrammarChecker();
            scanForEditableFields();
          }
        }
        if (changes.autoFixAll) {
          autoFixAll = changes.autoFixAll.newValue !== false;
          if (!autoFixAll) stopAutoFixLoop();
        }
      });
    }

    document.addEventListener("focusin", onDocumentFocusIn, true);
    document.addEventListener("input", onDocumentInput, true);

    document.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onWindowChange);
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

  function loadEnabledSetting() {
    if (!isValid() || !chrome.storage?.sync) return;
    chrome.storage.sync.get({ enabled: true, autoFixAll: true }, (result) => {
      enabled = result.enabled !== false;
      autoFixAll = result.autoFixAll !== false;
      if (!enabled) {
        deactivateField();
        return;
      }
      waitForBody(() => {
        startGrammarChecker();
        scanForEditableFields();
      });
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
        leftBound = offset;
        applied += 1;
      }
    } finally {
      suppressGrammarEvents = false;
    }

    if (applied > 0) {
      field.focus();
      currentMatches = [];
      syncGrammarDisplay(field, []);
      updateBadge(0);
    }

    return applied;
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

    const correctedTrimmed = (corrected || "").trim();
    if (correctedTrimmed && trimmed === correctedTrimmed) {
      stopAutoFixLoop();
      return;
    }

    const fixable = getFixableMatches(matches, trimmed);
    if (!fixable.length) {
      stopAutoFixLoop();
      return;
    }

    if (autoFixPass >= MAX_AUTO_FIX_PASSES) {
      stopAutoFixLoop();
      return;
    }

    const fingerprint = matchFingerprint(fixable, trimmed);
    if (fingerprint === lastAutoFixFingerprint) {
      stopAutoFixLoop();
      return;
    }

    const beforeText = trimmed;
    autoFixInProgress = true;
    hideSuggestionPopup();

    const applied = applyAllSuggestionsInField(field, fixable);
    const { trimmed: afterText } = getGrammarTextContext(field);

    autoFixPass += 1;
    lastAutoFixFingerprint = fingerprint;

    if (applied === 0 || afterText === beforeText) {
      stopAutoFixLoop();
      return;
    }

    if (correctedTrimmed && afterText === correctedTrimmed) {
      stopAutoFixLoop();
      return;
    }

    lastCheckedText = "";
    runFullCheckImmediately(field);
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
    ].join(", ");

    for (const node of queryAllDeep(editableSelector)) {
      if (!isEditableElement(node) || !isVisibleField(node)) continue;
      if (isNestedTextbox(node)) continue;
      fields.add(normalizeEditableField(node));
    }

    for (const node of queryAllDeep(
      '[role="textbox"], [role="searchbox"], [role="combobox"]'
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
      '[contenteditable="true"], [contenteditable=""], [contenteditable="plaintext-only"], [role="textbox"][contenteditable], [role="searchbox"][contenteditable]'
    );
    return root instanceof HTMLElement ? root : field;
  }

  function isEditableElement(el) {
    if (!(el instanceof HTMLElement)) return false;
    if (el.classList?.contains("grammar-overlay-floating")) return false;
    if (el.closest?.(".grammar-overlay-floating, .grm-suggestion-popup")) return false;
    if (el === document.body || el === document.documentElement) return false;

    if (el instanceof HTMLTextAreaElement) {
      return !el.disabled && !el.readOnly;
    }
    if (el instanceof HTMLInputElement) {
      return isTextInput(el) && !el.disabled && !el.readOnly;
    }

    if (el.isContentEditable) return true;

    const role = (el.getAttribute("role") || "").toLowerCase();
    if (role === "textbox" || role === "searchbox" || role === "combobox") {
      return el.isContentEditable || el.querySelector?.("[contenteditable='true']") != null;
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

    const rect = el.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) return true;

    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
      return !el.disabled;
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
    if (suggestionPopup && suggestionPopupAnchor) {
      positionSuggestionPopup(suggestionPopup, suggestionPopupAnchor);
    }
    if (!ensureActiveSession()) return;
    if (event.target === activeField || activeField.contains(event.target)) {
      positionOverlay();
    }
  }

  function onWindowChange() {
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
        text-decoration: underline solid #e53e3e;
        text-decoration-thickness: 2px;
        text-underline-offset: 2px;
        background-color: transparent;
      }
      ::highlight(humanizer-grammar-active) {
        text-decoration: underline solid #e53e3e;
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
          if (!quick) {
            debugLog("H2", "content.js:checkGrammar", "client grammar failed", {
              lastError: chrome.runtime.lastError?.message || null,
              error: response?.error || null,
            });
          }
          if (!quick && !currentMatches.length) {
            syncGrammarDisplay(field, []);
            updateBadge(0);
          }
          return;
        }

        if (quick && trimmed === lastCheckedText) {
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
    return `<svg class="grm-card__icon grm-icon--correctness" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true"><path fill="#E53E3E" d="M10 2L3 5v5c0 4.2 3 7.9 7 9 4-1.1 7-4.8 7-9V5l-7-3z"/></svg>`;
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
      (mirrorSpan?.textContent || "").trim() ||
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

    const delta = replacement.length - length;
    currentMatches = filterMatchesForDisplay(
      currentMatches
        .filter((m) => m.offset < offset || m.offset >= offset + length)
        .map((m) => {
          if (m.offset > offset) {
            return { ...m, offset: m.offset + delta };
          }
          return m;
        })
    );

    const { trimmed } = getGrammarTextContext(field);
    lastCheckedText = trimmed;

    syncGrammarDisplay(field, currentMatches);
    updateBadge(currentMatches.length);

    if (autoFixAll && currentMatches.length > 0) {
      autoFixPass = 0;
      lastAutoFixFingerprint = "";
      autoFixInProgress = true;
      lastCheckedText = "";
      runFullCheckImmediately(field);
    }
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

  function escapeHtml(value) {
    return value
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
})();
