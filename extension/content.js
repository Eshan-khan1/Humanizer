console.log("✅ Grammar checker loaded on:", window.location.href);

(() => {
  const CHECK_DELAY_MS = 2000;
  const MIN_TEXT_LENGTH = 2;

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
  let debounceTimer = null;
  let lastRequestId = 0;
  let suggestionPopup = null;
  let suggestionPopupAnchor = null;
  let ignoreNextFocusOut = false;
  let currentMatches = [];
  let fieldMutationObserver = null;
  let bodyMutationObserver = null;
  let scanDebounceTimer = null;
  let floatingPositionHandler = null;
  let enabled = true;
  let checkerStarted = false;
  let sidePanelRoot = null;
  let sidePanelOpen = false;
  let overlaySetupInProgress = false;
  let suppressGrammarEvents = false;
  let lastCheckedText = "";
  let fieldMutationDebounceTimer = null;

  const PUNCTUATION_ONLY_RE =
    /^[\s"'‘’“”`´.,!?;:—–\-…()\[\]{}\\/|@#$%^&*+=<>~]+$/;

  const attachedFields = new WeakSet();
  const SCAN_DEBOUNCE_MS = 150;

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
    waitForBody(() => startGrammarChecker());

    loadEnabledSetting();

    if (chrome.storage?.onChanged) {
      chrome.storage.onChanged.addListener((changes, area) => {
        if (area !== "sync" || !changes.enabled) return;
        enabled = changes.enabled.newValue !== false;
        if (!enabled) {
          deactivateField();
          closeSidePanel();
        } else {
          startGrammarChecker();
          scanForEditableFields();
        }
      });
    }

    document.addEventListener("focusin", onDocumentFocusIn, true);
    document.addEventListener("input", onDocumentInput, true);

    document.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onWindowChange);

    chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (message?.type === "toggleSidePanel") {
        toggleSidePanel();
        sendResponse({ ok: true });
        return true;
      }
      return false;
    });
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
      });
    }
  }

  function loadEnabledSetting() {
    if (!isValid() || !chrome.storage?.sync) return;
    chrome.storage.sync.get({ enabled: true }, (result) => {
      enabled = result.enabled !== false;
      if (!enabled) {
        deactivateField();
        closeSidePanel();
        return;
      }
      waitForBody(() => {
        startGrammarChecker();
        scanForEditableFields();
      });
    });
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

  function ensureActiveSession() {
    if (!activeField || !activeMirror) return false;
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

  function findEditableFields() {
    const fields = new Set();

    document.querySelectorAll("textarea").forEach((node) => {
      if (node instanceof HTMLElement && isVisibleField(node)) {
        fields.add(node);
      }
    });

    document.querySelectorAll("input").forEach((node) => {
      if (node instanceof HTMLInputElement && isTextInput(node) && isVisibleField(node)) {
        fields.add(node);
      }
    });

    document
      .querySelectorAll('[contenteditable]:not([contenteditable="false"])')
      .forEach((node) => {
        if (node instanceof HTMLElement && isEditableElement(node) && isVisibleField(node)) {
          fields.add(node);
        }
      });

    return [...fields];
  }

  function isEditableElement(el) {
    if (el instanceof HTMLTextAreaElement) return true;
    if (el instanceof HTMLInputElement) return isTextInput(el);
    return (
      el instanceof HTMLElement &&
      el.tagName !== "INPUT" &&
      el.tagName !== "TEXTAREA" &&
      el.isContentEditable
    );
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
      if (
        el instanceof HTMLElement &&
        el.tagName !== "INPUT" &&
        el.tagName !== "TEXTAREA" &&
        el.isContentEditable &&
        isVisibleField(el)
      ) {
        return el;
      }
      el = el.parentElement;
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
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function isTextInput(input) {
    const type = (input.getAttribute("type") || "text").toLowerCase();
    return !IGNORED_INPUT_TYPES.has(type);
  }

  function isContentEditableField(field) {
    return (
      field instanceof HTMLElement &&
      field.tagName !== "INPUT" &&
      field.tagName !== "TEXTAREA" &&
      field.isContentEditable
    );
  }

  function attachGrammarChecker(field) {
    if (attachedFields.has(field)) return;
    attachedFields.add(field);

    field.addEventListener("focusin", onFieldFocusIn);
    field.addEventListener("focusout", onFieldFocusOut);
    field.addEventListener("input", onFieldInput);

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
      if (sidePanelRoot?.contains(focused)) return;
      deactivateField();
    }, 150);
  }

  function onFieldInput(event) {
    if (!isValid() || !enabled || suppressGrammarEvents) return;
    const field = event.currentTarget;
    if (!(field instanceof HTMLElement)) return;
    handleFieldTyping(field, { fromUser: event.isTrusted !== false });
  }

  function handleFieldTyping(field, { fromUser = true } = {}) {
    if (!isValid() || !enabled) return;
    if (!(field instanceof HTMLElement)) return;

    if (field !== activeField) {
      activateField(field);
      return;
    }

    if (fromUser) {
      lastCheckedText = "";
    }

    syncMirrorText(field, currentMatches);
    scheduleCheck(field);
  }

  function activateField(field) {
    if (!isValid() || !enabled) return;
    if (!isConnectedElement(field)) return;

    if (activeField === field && activeMirror) {
      scheduleCheck(field);
      return;
    }

    deactivateField();
    overlaySetupInProgress = true;
    activeField = field;
    setupFloatingOverlay(field);
    scheduleCheck(field);
    if (sidePanelOpen) {
      updateSidePanel(currentMatches);
    }
    setTimeout(() => {
      overlaySetupInProgress = false;
    }, 200);
  }

  function deactivateField() {
    hideSuggestionPopup();
    detachFieldMutationObserver();
    clearTimeout(debounceTimer);
    debounceTimer = null;

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
    updateSidePanel([]);
    updateBadge(0);
  }

  function setupFloatingOverlay(field) {
    const mirror = document.createElement("div");
    mirror.className = "grammar-overlay grammar-overlay-floating";
    mirror.setAttribute("aria-hidden", "true");
    document.body.appendChild(mirror);

    activeMirror = mirror;

    copyFieldStyles(field, mirror);
    positionFloatingOverlay();
    syncMirrorText(field, currentMatches);
    mirror.addEventListener("mousedown", onMirrorMouseDown, true);
    mirror.addEventListener("click", onMirrorClick, true);

    if (isContentEditableField(field)) {
      attachFieldMutationObserver(field);
    }

    floatingPositionHandler = () => positionFloatingOverlay();
    window.addEventListener("scroll", floatingPositionHandler, true);
    window.addEventListener("resize", floatingPositionHandler);
  }

  function detachOverlay() {
    if (!activeMirror) return;

    activeMirror.removeEventListener("mousedown", onMirrorMouseDown, true);
    activeMirror.removeEventListener("click", onMirrorClick, true);
    activeMirror.remove();

    clearTimeout(fieldMutationDebounceTimer);
    fieldMutationDebounceTimer = null;
    activeMirror = null;
  }

  function attachFieldMutationObserver(field) {
    detachFieldMutationObserver();

    fieldMutationObserver = new MutationObserver(() => {
      if (!isValid() || suppressGrammarEvents || overlaySetupInProgress) return;
      if (field !== activeField) return;
      if (!ensureActiveSession()) return;

      clearTimeout(fieldMutationDebounceTimer);
      fieldMutationDebounceTimer = setTimeout(() => {
        if (field !== activeField || suppressGrammarEvents) return;
        const { trimmed } = getGrammarTextContext(field);
        syncMirrorText(field, currentMatches);
        positionFloatingOverlay();
        if (trimmed === lastCheckedText) return;
        scheduleCheck(field);
      }, 400);
    });

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
    return field.innerText || field.textContent || "";
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
    range.setStart(startNode, startOffset);
    range.setEnd(endNode, endOffset);
    return range;
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
    const word = getMatchWord(match, text).trim();
    if (!word) return true;
    if (PUNCTUATION_ONLY_RE.test(word)) return true;
    if (word.length === 1 && /['"''""`´]/.test(word)) return true;

    const category = String(match.category || "").toUpperCase();
    const ruleId = String(match.rule_id || "").toUpperCase();
    if (
      category.includes("PUNCTUATION") ||
      category.includes("TYPOGRAPHY") ||
      /UNPAIRED|QUOTE|APOSTROPHE|COMMA_PAREN|WHITESPACE/i.test(ruleId)
    ) {
      if (PUNCTUATION_ONLY_RE.test(word)) return true;
    }

    const suggestions = getMatchSuggestions(match);
    if (
      suggestions.length > 0 &&
      suggestions.every((s) => PUNCTUATION_ONLY_RE.test(String(s).trim()))
    ) {
      return true;
    }

    return false;
  }

  function filterMatches(matches, text) {
    return matches.filter((m) => !isFalsePositiveMatch(m, text));
  }

  function scheduleCheck(field) {
    if (!isValid() || suppressGrammarEvents || overlaySetupInProgress) return;
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => checkGrammar(field), CHECK_DELAY_MS);
  }

  function checkGrammar(field) {
    if (!isValid()) return;
    if (!ensureActiveSession() || field !== activeField) return;
    if (suppressGrammarEvents || overlaySetupInProgress) return;

    const { trimmed, trimStart } = getGrammarTextContext(field);
    if (trimmed.length < MIN_TEXT_LENGTH) {
      lastCheckedText = "";
      currentMatches = [];
      syncMirrorText(field, []);
      updateSidePanel([]);
      updateBadge(0);
      return;
    }

    if (trimmed === lastCheckedText) return;

    const requestId = ++lastRequestId;

    chrome.runtime.sendMessage({ type: "checkGrammar", text: trimmed }, (response) => {
      if (!isValid()) return;
      if (requestId !== lastRequestId || field !== activeField) return;
      if (!ensureActiveSession()) return;

      if (chrome.runtime.lastError || !response?.ok) {
        // #region agent log
        debugLog("H2", "content.js:checkGrammar", "client grammar failed", {
          lastError: chrome.runtime.lastError?.message || null,
          error: response?.error || null,
        });
        // #endregion
        currentMatches = [];
        syncMirrorText(field, []);
        updateSidePanel([]);
        updateBadge(0);
        return;
      }

      currentMatches = mapMatchesToRawOffsets(
        filterMatches(response.data.matches || [], trimmed),
        trimStart
      );
      lastCheckedText = trimmed;
      // #region agent log
      debugLog("H5", "content.js:checkGrammar", "client grammar ok", {
        matchCount: currentMatches.length,
        fieldTag: activeField?.tagName || null,
      });
      // #endregion
      suppressGrammarEvents = true;
      try {
        syncMirrorText(field, currentMatches);
      } finally {
        suppressGrammarEvents = false;
      }
      updateSidePanel(currentMatches);
      updateBadge(currentMatches.length);
    });
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
      if (match.offset < cursor) continue;
      const start = match.offset;
      const end = match.offset + match.length;
      if (start > text.length) continue;

      html += escapeHtml(text.slice(cursor, start));
      const snippet = getMatchWord(match, text);
      const matchType = getMatchType(match);
      const typeClass = matchType === "spelling" ? "spelling-match" : "grammar-match";
      const suggestions = JSON.stringify(getMatchSuggestions(match)).replace(/'/g, "&#39;");
      const message = escapeHtml(match.message || "Suggestion").replace(/'/g, "&#39;");

      html += `<span class="grammar-error ${typeClass}" data-offset="${start}" data-length="${match.length}" data-match-type="${matchType}" data-replacements='${suggestions}' data-message='${message}' title="Click for suggestion">${escapeHtml(snippet)}</span>`;
      cursor = end;
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

  function showSuggestionPopup(anchor, match, field) {
    hideSuggestionPopup();
    setActiveHighlight(match.offset);

    const popup = document.createElement("div");
    popup.className = "grammar-inline-card";
    popup.setAttribute("role", "dialog");
    popup.setAttribute("aria-label", "Grammar suggestion");

    const header = document.createElement("div");
    header.className = "grammar-inline-card-header";

    const dismissBtn = document.createElement("button");
    dismissBtn.type = "button";
    dismissBtn.className = "grammar-inline-dismiss";
    dismissBtn.setAttribute("aria-label", "Dismiss");
    dismissBtn.textContent = "×";
    dismissBtn.addEventListener("mousedown", (event) => event.preventDefault());
    dismissBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      hideSuggestionPopup();
    });
    header.appendChild(dismissBtn);
    popup.appendChild(header);

    const suggestions = getMatchSuggestions(match);
    const primary = suggestions[0];

    if (primary) {
      const applyBtn = document.createElement("button");
      applyBtn.type = "button";
      applyBtn.className = "grammar-inline-suggestion";
      applyBtn.textContent = primary;
      applyBtn.title = `Replace with “${primary}”`;
      applyBtn.addEventListener("mousedown", (event) => event.preventDefault());
      applyBtn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (!isValid()) return;
        const anchorEl = suggestionPopupAnchor;
        hideSuggestionPopup();
        applySuggestionReplacement(field, anchorEl, match, primary);
        scheduleCheck(field);
      });
      popup.appendChild(applyBtn);
    } else {
      const empty = document.createElement("p");
      empty.className = "grammar-inline-empty";
      empty.textContent = "No suggestion found";
      popup.appendChild(empty);
    }

    popup.addEventListener("mousedown", (event) => {
      event.preventDefault();
    });

    document.body.appendChild(popup);
    suggestionPopup = popup;
    suggestionPopupAnchor = anchor;
    positionSuggestionPopup(popup, anchor);
  }

  function positionSuggestionPopup(popup, anchor) {
    const rect = anchor.getBoundingClientRect();
    const popupRect = popup.getBoundingClientRect();
    const gap = 6;

    let left = rect.left + rect.width / 2 - popupRect.width / 2;
    let top = rect.top - popupRect.height - gap;

    if (top < 8) {
      top = rect.bottom + gap;
    }
    if (left < 8) {
      left = 8;
    }
    if (left + popupRect.width > window.innerWidth - 8) {
      left = window.innerWidth - popupRect.width - 8;
    }

    popup.style.top = `${top}px`;
    popup.style.left = `${left}px`;
  }

  function hideSuggestionPopup() {
    suggestionPopup?.remove();
    suggestionPopup = null;
    suggestionPopupAnchor = null;
    clearActiveHighlight();
  }

  function setActiveHighlight(offset) {
    if (!activeMirror) return;
    activeMirror.querySelectorAll(".grammar-error-active").forEach((el) => {
      el.classList.remove("grammar-error-active");
    });
    if (offset == null) return;
    const span = activeMirror.querySelector(
      `.grammar-error[data-offset="${offset}"]`
    );
    span?.classList.add("grammar-error-active");
  }

  function clearActiveHighlight() {
    activeMirror?.querySelectorAll(".grammar-error-active").forEach((el) => {
      el.classList.remove("grammar-error-active");
    });
  }

  function jumpToMatch(match) {
    if (!ensureActiveSession() || !activeField) return;

    activeField.focus();
    positionOverlay();

    const span = activeMirror?.querySelector(
      `.grammar-error[data-offset="${match.offset}"][data-length="${match.length}"]`
    );
    if (!span) return;

    try {
      const fieldRect = activeField.getBoundingClientRect();
      const spanRect = span.getBoundingClientRect();
      const lineOffset = spanRect.top - fieldRect.top;
      if (typeof activeField.scrollTop === "number") {
        activeField.scrollTop += lineOffset - fieldRect.height / 3;
      }
      span.scrollIntoView({ block: "nearest", inline: "nearest" });
    } catch {
      /* scroll not supported */
    }

    showSuggestionPopup(span, match, activeField);
  }

  function applySuggestionReplacement(field, mirrorSpan, match, replacement) {
    if (!isConnectedElement(field)) return;

    const offset = match.offset;
    const length = match.length;
    const wrongText =
      (mirrorSpan?.textContent || "").trim() ||
      match.word ||
      getFieldText(field).slice(offset, offset + length);

    suppressGrammarEvents = true;
    lastCheckedText = "";
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

    const delta = replacement.length - length;
    currentMatches = currentMatches
      .filter((m) => m.offset < offset || m.offset >= offset + length)
      .map((m) => {
        if (m.offset > offset) {
          return { ...m, offset: m.offset + delta };
        }
        return m;
      });

    syncMirrorText(field, currentMatches);
    updateSidePanel(currentMatches);
    updateBadge(currentMatches.length);
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

  function ensureSidePanel() {
    if (sidePanelRoot?.isConnected) return;

    sidePanelRoot = document.createElement("div");
    sidePanelRoot.className = "humanizer-side-panel";
    sidePanelRoot.hidden = true;
    sidePanelRoot.innerHTML = `
      <header class="humanizer-side-header">
        <div class="humanizer-side-title">
          <strong>Humanizer</strong>
          <span class="humanizer-side-count">0 issues</span>
        </div>
        <button type="button" class="humanizer-side-dismiss" aria-label="Dismiss panel">×</button>
      </header>
      <p class="humanizer-side-hint"></p>
      <ul class="humanizer-side-issues"></ul>
      <footer class="humanizer-side-footer">
        <label class="humanizer-side-toggle">
          <input type="checkbox" class="humanizer-enabled-toggle" checked />
          Check writing while I type
        </label>
        <p class="humanizer-side-status">All checks run locally on your machine.</p>
      </footer>
    `;

    document.body.appendChild(sidePanelRoot);

    sidePanelRoot.addEventListener("mousedown", (event) => {
      event.preventDefault();
    });

    sidePanelRoot
      .querySelector(".humanizer-side-dismiss")
      ?.addEventListener("click", () => closeSidePanel());

    const toggle = sidePanelRoot.querySelector(".humanizer-enabled-toggle");
    if (toggle && chrome.storage?.sync) {
      chrome.storage.sync.get({ enabled: true }, (result) => {
        toggle.checked = result.enabled !== false;
      });
      toggle.addEventListener("change", () => {
        enabled = toggle.checked;
        chrome.storage.sync.set({ enabled: toggle.checked });
        if (!enabled) {
          deactivateField();
          closeSidePanel();
        } else {
          startGrammarChecker();
          scanForEditableFields();
        }
      });
    }
  }

  function toggleSidePanel() {
    sidePanelOpen = !sidePanelOpen;
    ensureSidePanel();
    if (!sidePanelRoot) return;

    if (sidePanelOpen) {
      sidePanelRoot.hidden = false;
      updateSidePanel(currentMatches);
      if (activeField) {
        scheduleCheck(activeField);
      }
    } else {
      sidePanelRoot.hidden = true;
      hideSuggestionPopup();
    }
  }

  function closeSidePanel() {
    sidePanelOpen = false;
    if (sidePanelRoot) {
      sidePanelRoot.hidden = true;
    }
    hideSuggestionPopup();
  }

  function updateSidePanel(matches) {
    if (!sidePanelOpen) return;
    ensureSidePanel();
    if (!sidePanelRoot) return;

    const countEl = sidePanelRoot.querySelector(".humanizer-side-count");
    const hintEl = sidePanelRoot.querySelector(".humanizer-side-hint");
    const list = sidePanelRoot.querySelector(".humanizer-side-issues");
    const total = matches.length;

    if (countEl) {
      countEl.textContent = `${total} ${total === 1 ? "issue" : "issues"}`;
    }

    if (!activeField) {
      if (hintEl) {
        hintEl.textContent = "Click in a text field and start typing to check your writing.";
      }
      if (list) list.innerHTML = "";
      return;
    }

    if (hintEl) {
      hintEl.textContent =
        total === 0
          ? "Looking good — no issues found in this field."
          : "Click an issue to jump to it in your text.";
    }

    if (!list) return;
    list.innerHTML = "";

    const fieldText = getFieldText(activeField);
    matches.forEach((match) => {
      const wrong = getMatchWord(match, fieldText) || "…";
      const correct = getMatchSuggestions(match)[0] || "—";
      const li = document.createElement("li");
      li.className = "humanizer-side-issue";
      li.innerHTML = `
        <span class="humanizer-side-wrong">${escapeHtml(wrong)}</span>
        <span class="humanizer-side-arrow" aria-hidden="true">→</span>
        <span class="humanizer-side-correct">${escapeHtml(correct)}</span>
      `;
      li.addEventListener("click", () => {
        if (!isValid() || !activeField) return;
        jumpToMatch(match);
      });
      list.appendChild(li);
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
