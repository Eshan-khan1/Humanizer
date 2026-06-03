"""Text humanization: cliché replacement, contractions, hedging, rhythm, AI scoring."""

from __future__ import annotations

import json
import re
import statistics
import urllib.error
import urllib.request
from typing import Literal

import nltk

SERVER_BASE_URL = "http://127.0.0.1:8000"
SERVER_REQUEST_TIMEOUT_SEC = 600.0


class OllamaError(Exception):
    """Humanizer server or Ollama is unavailable."""

Intensity = Literal["mild", "moderate", "aggressive"]

# At least 50 AI cliché phrases → human replacements ("" = delete).
AI_CLICHES: dict[str, str] = {
    "utilize": "use",
    "utilizes": "uses",
    "utilized": "used",
    "utilizing": "using",
    "leverage": "use",
    "leverages": "uses",
    "leveraged": "used",
    "leveraging": "using",
    "delve into": "look into",
    "delving into": "looking into",
    "delved into": "looked into",
    "furthermore": "also",
    "moreover": "plus",
    "additionally": "and",
    "nevertheless": "still",
    "consequently": "so",
    "subsequently": "then",
    "accordingly": "so",
    "henceforth": "from now on",
    "heretofore": "before",
    "in conclusion": "so",
    "to conclude": "so",
    "in summary": "so",
    "all in all": "overall",
    "it is important to note that": "",
    "it is worth noting that": "",
    "it should be noted that": "",
    "it is worth mentioning that": "",
    "it bears mentioning that": "",
    "needless to say": "",
    "without a doubt": "",
    "certainly!": "",
    "certainly,": "",
    "absolutely!": "",
    "of course!": "",
    "great question!": "",
    "as an ai language model": "",
    "as a language model": "",
    "i'd be happy to": "I'll",
    "i would be happy to": "I'll",
    "as per": "per",
    "in order to": "to",
    "due to the fact that": "because",
    "owing to the fact that": "because",
    "in light of the fact that": "because",
    "at this point in time": "now",
    "at the present time": "now",
    "in the event that": "if",
    "with regard to": "about",
    "with respect to": "about",
    "in regard to": "about",
    "prior to": "before",
    "subsequent to": "after",
    "a multitude of": "many",
    "a myriad of": "many",
    "numerous": "many",
    "plethora of": "lots of",
    "myriad of": "many",
    "facilitate": "help",
    "facilitates": "helps",
    "facilitated": "helped",
    "implement": "do",
    "implements": "does",
    "implementation": "setup",
    "commence": "start",
    "commences": "starts",
    "commenced": "started",
    "terminate": "end",
    "terminates": "ends",
    "terminated": "ended",
    "endeavor": "try",
    "endeavors": "tries",
    "endeavored": "tried",
    "robust": "solid",
    "comprehensive": "full",
    "holistic": "whole",
    "paradigm": "model",
    "synergy": "teamwork",
    "synergies": "benefits",
    "optimize": "improve",
    "optimizes": "improves",
    "optimized": "improved",
    "streamline": "simplify",
    "streamlines": "simplifies",
    "streamlined": "simplified",
    "underscore": "highlight",
    "underscores": "highlights",
    "underscored": "highlighted",
    "tapestry of": "mix of",
    "landscape of": "world of",
    "realm of": "area of",
    "in today's digital age": "today",
    "in this day and age": "today",
    "it goes without saying": "",
    "at the end of the day": "ultimately",
    "when all is said and done": "ultimately",
    "plays a crucial role": "matters",
    "plays a vital role": "matters",
    "serves as a testament to": "shows",
    "it's important to remember": "",
    "keep in mind that": "",
    "rest assured": "",
    "moving forward": "next",
    "going forward": "next",
    "it's crucial to understand": "you should know",
    "it is crucial to understand": "you should know",
    "it's essential to": "you need to",
    "it is essential to": "you need to",
    "it's imperative to": "you have to",
    "it is imperative to": "you have to",
    "in the realm of": "in",
    "in the world of": "in",
    "multifaceted": "varied",
    "nuanced": "subtle",
    "nuances": "details",
    "harness": "use",
    "harnessing": "using",
    "pivotal": "key",
    "showcase": "show",
    "showcases": "shows",
    "showcasing": "showing",
    "foster": "build",
    "fosters": "builds",
    "fostering": "building",
    "elevate": "raise",
    "elevates": "raises",
    "empower": "help",
    "empowers": "helps",
    "cutting-edge": "modern",
    "game-changer": "big deal",
    "game changer": "big deal",
    "dive deep": "dig into",
    "unlock": "open up",
    "unleash": "release",
    "seamless": "smooth",
    "tailored": "fitted",
    "as mentioned earlier": "",
    "as mentioned above": "",
    "as previously stated": "",
    "in summary": "so",
    "to summarize": "so",
    "key takeaway": "main point",
    "it's worth highlighting": "",
    "it is worth highlighting": "",
    "in today's fast-paced world": "today",
    "in an ever-changing world": "today",
    "ever-evolving": "changing",
    "testament to": "sign of",
    "serves to": "helps",
    "serves as": "is",
    "a wide range of": "many",
    "wide range of": "many",
    "a broad range of": "many",
    "on the other hand": "but",
    "that being said": "still",
    "having said that": "still",
    "at its core": "basically",
    "the fact of the matter is": "the thing is",
    "when it comes to": "for",
    "in terms of": "for",
    "with that in mind": "so",
    "it is no secret that": "",
    "there is no denying that": "",
    "plays a key role": "matters",
    "plays an important role": "matters",
    "rich tapestry": "mix",
    "vibrant community": "community",
    "bustling": "busy",
    "nestled": "in",
    "boasts": "has",
    "underscores the importance": "shows why",
    "highlight the importance": "show why",
    "shed light on": "explain",
    "sheds light on": "explains",
    "navigate": "handle",
    "navigating": "handling",
    "landscape": "space",
    "ecosystem": "world",
    "bandwidth": "time",
    "synergize": "work together",
    "operationalize": "put to work",
    "ideate": "brainstorm",
    "learnings": "lessons",
    "actionable insights": "useful ideas",
    "double down": "focus more",
    "circle back": "follow up",
    "touch base": "check in",
    "low-hanging fruit": "easy wins",
    "move the needle": "make a difference",
    "at the forefront of": "leading",
    "spearhead": "lead",
    "spearheaded": "led",
}

# Extra formal words → everyday speech (moderate+).
FORMAL_TO_CASUAL: dict[str, str] = {
    "individual": "person",
    "individuals": "people",
    "commence": "start",
    "terminate": "end",
    "purchase": "buy",
    "assist": "help",
    "obtain": "get",
    "regarding": "about",
    "approximately": "about",
    "sufficient": "enough",
    "attempt": "try",
    "component": "part",
    "demonstrate": "show",
    "demonstrates": "shows",
    "demonstrated": "showed",
    "indicate": "show",
    "indicates": "shows",
    "indicated": "showed",
    "facilitate": "help",
    "numerous": "many",
    "substantial": "big",
    "significant": "big",
    "various": "different",
    "primarily": "mainly",
    "additionally": "also",
    "furthermore": "also",
    "nevertheless": "still",
    "therefore": "so",
    "thus": "so",
    "hence": "so",
    "whilst": "while",
    "amongst": "among",
    "prior": "before",
    "subsequent": "next",
    "concerning": "about",
    "utilize": "use",
    "beneficial": "helpful",
    "methodology": "method",
    "functionality": "features",
    "objective": "goal",
    "objectives": "goals",
    "endeavor": "try",
    "endeavours": "tries",
}

# Conversational rewrites (moderate+).
CONVERSATIONAL_PHRASES: dict[str, str] = {
    "one should": "you should",
    "one must": "you must",
    "one can": "you can",
    "one might": "you might",
    "one could": "you could",
    "the reader should": "you should",
    "it is recommended that": "you should",
    "it is advised that": "you should",
    "it is suggested that": "you could",
    "there are many reasons why": "here's why",
    "there are several reasons why": "here's why",
    "this essay will": "I'll",
    "this paper will": "I'll",
    "we will explore": "I'll cover",
    "we will examine": "I'll look at",
    "let us explore": "let's look at",
    "let us examine": "let's look at",
    "in this article, we": "I",
    "in this post, we": "I",
}

_EXTRA_FILLERS: tuple[str, ...] = (
    "basically,",
    "basically ",
    "literally,",
    "literally ",
    "actually,",
    "actually ",
    "honestly,",
    "honestly ",
    "frankly,",
    "frankly ",
    "simply put,",
    "simply put ",
    "to be honest,",
    "to be honest ",
    "at the end of the day,",
    "the bottom line is that",
    "the bottom line is ",
)

_LIST_MARKERS = (
    r"\bfirstly,?\s*",
    r"\bsecondly,?\s*",
    r"\bthirdly,?\s*",
    r"\bfinally,?\s*",
    r"\blastly,?\s*",
    r"\bin the first place,?\s*",
    r"\bin the second place,?\s*",
)

_FORMAL_ORDER = sorted(FORMAL_TO_CASUAL.keys(), key=len, reverse=True)
_CONVERSATIONAL_ORDER = sorted(CONVERSATIONAL_PHRASES.keys(), key=len, reverse=True)

# Longer phrases first so partial matches do not fire early.
_CLICHE_ORDER = sorted(AI_CLICHES.keys(), key=len, reverse=True)

# Hedging phrases removed entirely (moderate+ intensity).
HEDGING_PHRASES: tuple[str, ...] = (
    "it should be noted",
    "it should be noted that",
    "one might argue",
    "one might argue that",
    "one could argue",
    "one could argue that",
    "it can be said that",
    "it could be argued that",
    "it may be argued that",
    "it is often said that",
    "it is sometimes said that",
    "it is fair to say that",
    "it is safe to say that",
    "it is worth noting",
    "it is worth noting that",
    "it bears noting that",
    "arguably,",
    "arguably ",
    "in some sense,",
    "in some sense ",
    "to some extent,",
    "to some extent ",
    "it seems that",
    "it appears that",
    "it would seem that",
    "one might say that",
    "one could say that",
    "it has been suggested that",
    "some might say that",
    "it is plausible that",
    "there is reason to believe that",
)

# Formal phrase → contraction (23+ pairs).
CONTRACTIONS: dict[str, str] = {
    "do not": "don't",
    "does not": "doesn't",
    "did not": "didn't",
    "is not": "isn't",
    "are not": "aren't",
    "was not": "wasn't",
    "were not": "weren't",
    "have not": "haven't",
    "has not": "hasn't",
    "had not": "hadn't",
    "will not": "won't",
    "would not": "wouldn't",
    "could not": "couldn't",
    "should not": "shouldn't",
    "must not": "mustn't",
    "might not": "mightn't",
    "cannot": "can't",
    "can not": "can't",
    "it is": "it's",
    "it was": "it was",  # no common contraction; skip below via filter
    "that is": "that's",
    "there is": "there's",
    "there are": "there're",
    "here is": "here's",
    "what is": "what's",
    "who is": "who's",
    "where is": "where's",
    "when is": "when's",
    "how is": "how's",
    "they are": "they're",
    "we are": "we're",
    "you are": "you're",
    "I am": "I'm",
    "he is": "he's",
    "she is": "she's",
    "let us": "let's",
    "I will": "I'll",
    "you will": "you'll",
    "he will": "he'll",
    "she will": "she'll",
    "we will": "we'll",
    "they will": "they'll",
    "I have": "I've",
    "you have": "you've",
    "we have": "we've",
    "they have": "they've",
    "would have": "would've",
    "could have": "could've",
    "should have": "should've",
}

# Drop entries that are not real contractions.
CONTRACTIONS = {k: v for k, v in CONTRACTIONS.items() if k != v}

_CONTRACTION_ORDER = sorted(CONTRACTIONS.keys(), key=len, reverse=True)

# Cliché keys used for scoring (lowercase lookup).
_CLICHE_SCORE_TERMS = set(k.lower() for k in AI_CLICHES)


def _ensure_nltk_data() -> None:
    for resource in ("punkt", "punkt_tab"):
        try:
            nltk.data.find(f"tokenizers/{resource}")
        except LookupError:
            nltk.download(resource, quiet=True)


def _normalize_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" +([,.;:!?])", r"\1", text)
    return text.strip()


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    escaped = re.escape(phrase)
    if phrase.endswith("!") or phrase.endswith(","):
        return re.compile(escaped, re.IGNORECASE)
    return re.compile(rf"\b{escaped}\b", re.IGNORECASE)


def replace_cliches(text: str) -> tuple[str, list[str]]:
    """
    Replace AI clichés with human alternatives.

    Returns:
        (cleaned text, list of human-readable change descriptions)
    """
    changes: list[str] = []
    result = text

    for phrase in _CLICHE_ORDER:
        replacement = AI_CLICHES[phrase]
        pattern = _phrase_pattern(phrase)

        def _repl(match: re.Match[str], rep: str = replacement, orig: str = phrase) -> str:
            matched = match.group(0)
            if rep == "":
                changes.append(f"removed '{matched}'")
                return ""
            changes.append(f"'{matched}' → '{rep}'")
            if matched[0].isupper() and rep:
                rep_out = rep[0].upper() + rep[1:] if len(rep) > 1 else rep.upper()
            else:
                rep_out = rep
            return rep_out

        new_result, count = pattern.subn(_repl, result)
        if count:
            result = new_result

    result = _normalize_whitespace(result)
    return result, changes


def add_contractions(text: str) -> str:
    """Replace formal phrases with common contractions."""
    result = text
    for phrase in _CONTRACTION_ORDER:
        contraction = CONTRACTIONS[phrase]
        pattern = re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)

        def _repl(match: re.Match[str], c: str = contraction) -> str:
            matched = match.group(0)
            if matched.isupper():
                return c.upper()
            if matched[0].isupper():
                return c[0].upper() + c[1:]
            return c

        result = pattern.sub(_repl, result)
    return result


def remove_hedging(text: str) -> str:
    """Remove hedging and filler phrases."""
    result = text
    for phrase in sorted(HEDGING_PHRASES, key=len, reverse=True):
        pattern = _phrase_pattern(phrase.rstrip(", "))
        result = pattern.sub("", result)
    return _normalize_whitespace(result)


def simplify_formal_words(text: str) -> str:
    """Swap stiff formal words for everyday ones."""
    result = text
    for word in _FORMAL_ORDER:
        replacement = FORMAL_TO_CASUAL[word]
        pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)

        def _repl(match: re.Match[str], rep: str = replacement) -> str:
            matched = match.group(0)
            if matched.isupper():
                return rep.upper()
            if matched[0].isupper():
                return rep.capitalize()
            return rep

        result = pattern.sub(_repl, result)
    return result


def humanize_phrasing(text: str) -> str:
    """Rewrite stiff third-person / essay-style phrasing into direct speech."""
    result = text
    for phrase in _CONVERSATIONAL_ORDER:
        replacement = CONVERSATIONAL_PHRASES[phrase]
        result = _phrase_pattern(phrase).sub(replacement, result)
    return result


def remove_fillers(text: str) -> str:
    """Remove empty filler openers often added by models."""
    result = text
    for phrase in sorted(_EXTRA_FILLERS, key=len, reverse=True):
        result = _phrase_pattern(phrase.rstrip()).sub("", result)
    return _normalize_whitespace(result)


def strip_list_markers(text: str) -> str:
    """Remove robotic Firstly/Secondly enumeration."""
    result = text
    for pattern in _LIST_MARKERS:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)
    return _normalize_whitespace(result)


def lighten_passive_voice(text: str) -> str:
    """Convert simple past passive (subject was verbed by agent) to active voice."""

    def _passive_repl(match: re.Match[str]) -> str:
        subject = match.group(1).strip()
        verb = match.group(3)
        agent = match.group(4).strip()
        if len(agent.split()) > 4:
            return match.group(0)
        obj = subject[0].lower() + subject[1:] if subject else subject
        result = f"{agent} {verb} {obj}"
        return result[0].upper() + result[1:] if result else result

    return re.sub(
        r"\b([\w][\w\s'-]{0,40}?) (was|were) (\w+ed) by ([A-Za-z][\w'-]+(?:\s+[A-Za-z][\w'-]+){0,3})\b",
        _passive_repl,
        text,
        flags=re.IGNORECASE,
    )


def reduce_repeated_starts(text: str) -> str:
    """Break runs of sentences that start with the same word (common in AI text)."""
    sentences = _split_sentences(text)
    if len(sentences) < 3:
        return text

    out: list[str] = []
    prev_start: str | None = None
    repeat = 0

    for s in sentences:
        words = s.split()
        start = words[0].lower() if words else ""
        if start and start == prev_start:
            repeat += 1
        else:
            repeat = 0
            prev_start = start

        if repeat >= 2 and words:
            # Prefix with "And" or "But" to vary rhythm
            joiner = "But" if repeat % 2 else "And"
            s = f"{joiner} {s[0].lower() + s[1:]}" if s[0].isupper() else f"{joiner} {s}"
            repeat = 0
        out.append(s)

    return " ".join(out)


def add_burstiness(text: str) -> str:
    """
    Add short sentences after long ones to mimic human burstiness
    (detectors flag overly uniform sentence length).
    """
    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return text

    out: list[str] = []
    for i, s in enumerate(sentences):
        out.append(s)
        wc = _word_count(s)
        if wc >= 24 and i % 4 == 2:
            # Short punchy follow-up derived from sentence topic (generic human pattern)
            short = _short_followup(s)
            if short:
                out.append(short)
    return " ".join(out)


def _short_followup(sentence: str) -> str:
    """Generate a brief follow-up sentence for burstiness."""
    lower = sentence.lower()
    if "important" in lower or "matter" in lower or "need" in lower:
        return "That matters."
    if "however" in lower or "but" in lower or "although" in lower:
        return "Still, it's worth thinking about."
    if "?" in sentence:
        return "Good question."
    if any(w in lower for w in ("benefit", "help", "improve", "better")):
        return "It helps."
    if any(w in lower for w in ("problem", "issue", "challenge", "risk")):
        return "That's the hard part."
    return "Makes sense."


def _pipeline_layers(intensity: Intensity) -> list:
    """Ordered transforms for the given intensity level."""
    layers: list = [
        lambda t: replace_cliches(t)[0],
        simplify_formal_words,
        add_contractions,
    ]
    if intensity in ("moderate", "aggressive"):
        layers.extend(
            [
                remove_hedging,
                remove_fillers,
                humanize_phrasing,
                strip_list_markers,
                lighten_passive_voice,
            ]
        )
    if intensity == "aggressive":
        layers.extend([vary_rhythm, reduce_repeated_starts, add_burstiness])
    return layers


def count_pipeline_edits(text: str, intensity: Intensity) -> int:
    """Estimate how many transformations were applied."""
    _, cliche_changes = replace_cliches(text)
    total = len(cliche_changes)

    current = text
    for layer in _pipeline_layers(intensity):
        new = layer(current)
        if new != current:
            total += max(1, abs(len(new.split()) - len(current.split())) // 5)
        current = new
    return total


def apply_humanize_layers(text: str, intensity: Intensity) -> str:
    """Run the full humanization pipeline for the given intensity."""
    current = text
    for layer in _pipeline_layers(intensity):
        current = layer(current)
    return _normalize_whitespace(current)


def _word_count(sentence: str) -> int:
    return len(nltk.word_tokenize(sentence))


def _split_sentences(text: str) -> list[str]:
    _ensure_nltk_data()
    return [s.strip() for s in nltk.sent_tokenize(text) if s.strip()]


def _break_sentence(sentence: str) -> list[str]:
    """Split a long uniform sentence at natural breakpoints."""
    for sep in (r";\s+", r",\s+(?=(?:and|but|or|which|who|where|when)\s)", r"\s+—\s+"):
        parts = re.split(sep, sentence, maxsplit=1)
        if len(parts) == 2 and all(p.strip() for p in parts):
            left, right = parts[0].strip(), parts[1].strip()
            if not left.endswith((".", "!", "?")):
                left = left.rstrip(",") + "."
            if right and right[0].islower():
                right = right[0].upper() + right[1:]
            return [left, right]

    for conj in (" and ", " but ", " so ", " because "):
        idx = sentence.lower().find(conj)
        if idx > 20:
            left = sentence[:idx].strip().rstrip(",") + "."
            right = sentence[idx + len(conj) :].strip()
            if right:
                right = right[0].upper() + right[1:]
            return [left, right]
    return [sentence]


def _combine_sentences(a: str, b: str) -> str:
    """Merge two short adjacent sentences."""
    a = a.rstrip(".!?")
    b = b[0].lower() + b[1:] if len(b) > 1 else b.lower()
    return f"{a}, {b}"


def vary_rhythm(text: str) -> str:
    """
    Detect overly uniform sentence lengths and break up or combine sentences.

    Uses NLTK tokenization; breaks long sentences and merges pairs of very short ones.
    """
    _ensure_nltk_data()
    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return text

    lengths = [_word_count(s) for s in sentences]
    if len(lengths) < 2:
        return text

    stdev = statistics.pstdev(lengths)
    mean_len = statistics.mean(lengths)
    # Uniform rhythm: low spread relative to mean length.
    uniform = stdev < 3.0 or (mean_len > 0 and stdev / mean_len < 0.25)

    if not uniform:
        return text

    out: list[str] = []
    i = 0
    while i < len(sentences):
        s = sentences[i]
        wc = lengths[i]

        if wc > mean_len + 4:
            out.extend(_break_sentence(s))
            i += 1
            continue

        if (
            i + 1 < len(sentences)
            and wc <= 8
            and lengths[i + 1] <= 8
        ):
            out.append(_combine_sentences(s, sentences[i + 1]))
            i += 2
            continue

        out.append(s)
        i += 1

    return " ".join(out)


def _count_cliche_hits(text: str) -> int:
    lower = text.lower()
    hits = 0
    for phrase in AI_CLICHES:
        if phrase.lower() in lower:
            hits += lower.count(phrase.lower())
    return hits


def _contraction_opportunities(text: str) -> int:
    lower = text.lower()
    return sum(1 for phrase in CONTRACTIONS if phrase.lower() in lower)


def _contraction_count(text: str) -> int:
    return len(re.findall(
        r"\b(?:'t|'re|'ve|'ll|'d|'s|'m)\b|n't\b",
        text,
        flags=re.IGNORECASE,
    ))


def _sentence_uniformity_score(text: str) -> float:
    """Return 0–1 where 1 means very uniform (AI-like) sentence lengths."""
    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return 0.0
    lengths = [_word_count(s) for s in sentences]
    mean_len = statistics.mean(lengths)
    if mean_len == 0:
        return 0.0
    stdev = statistics.pstdev(lengths)
    if stdev < 2.0:
        return 1.0
    ratio = stdev / mean_len
    if ratio < 0.2:
        return 0.9
    if ratio < 0.35:
        return 0.6
    if ratio < 0.5:
        return 0.3
    return 0.0


def calculate_ai_score(text: str) -> int:
    """
    Score text from 0 (human-like) to 100 (AI-like).

    Based on cliché density, missing contractions, and sentence-length uniformity.
    """
    if not text or not text.strip():
        return 0

    words = max(1, len(nltk.word_tokenize(text)))
    cliche_hits = _count_cliche_hits(text)
    cliche_density = min(1.0, (cliche_hits / words) * 25)

    opportunities = _contraction_opportunities(text)
    if opportunities == 0:
        missing_contractions = 0.0
    else:
        present = _contraction_count(text)
        missing_contractions = min(1.0, max(0.0, 1.0 - (present / opportunities)))

    uniformity = _sentence_uniformity_score(text)

    raw = (
        0.45 * cliche_density
        + 0.30 * missing_contractions
        + 0.25 * uniformity
    )
    return int(round(min(100, max(0, raw * 100))))


def _server_request(
    method: str,
    path: str,
    body: dict | None = None,
    *,
    timeout: float = SERVER_REQUEST_TIMEOUT_SEC,
) -> dict:
    url = f"{SERVER_BASE_URL.rstrip('/')}{path}"
    headers: dict[str, str] = {}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(detail).get("detail", detail)
        except json.JSONDecodeError:
            message = detail or exc.reason
        raise OllamaError(f"Server error ({exc.code}): {message}") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise OllamaError(
            f"Cannot reach Humanizer server at {SERVER_BASE_URL}. "
            f"Start it with: python server.py ({reason})"
        ) from exc
    except json.JSONDecodeError as exc:
        raise OllamaError("Humanizer server returned invalid JSON") from exc


def is_ollama_running() -> bool:
    """Return True if the API server reports Ollama is available."""
    try:
        data = _server_request("GET", "/health", timeout=2.0)
        return bool(data.get("ollama_available"))
    except OllamaError:
        return False


def humanize_via_ollama(text: str) -> str:
    """
    Rewrite text via the local Humanizer server (Ollama / mistral).

    Raises OllamaError if the server or Ollama is unavailable.
    """
    if not text or not text.strip():
        return ""

    data = _server_request("POST", "/humanize", {"text": text.strip()})
    result = (data.get("result") or "").strip()
    if not result:
        raise OllamaError("Humanizer server returned an empty result")
    return result


def _humanize_rules(text: str, intensity: Intensity) -> str:
    intensity = intensity.lower()  # type: ignore[assignment]
    if intensity not in ("mild", "moderate", "aggressive"):
        raise ValueError("intensity must be 'mild', 'moderate', or 'aggressive'")
    return apply_humanize_layers(text, intensity)


def humanize(text: str, intensity: Intensity = "moderate") -> str:
    """
    Transform AI-style text into more natural, human-sounding writing.

    Uses the local Humanizer server (Ollama / mistral) when available.
    falls back to the rule-based pipeline controlled by ``intensity``:

    - mild: clichés + simpler words + contractions
    - moderate: mild + hedging/fillers + conversational phrasing + light passive fixes
    - aggressive: moderate + rhythm variation + burstiness + less repetition
    """
    if not text or not text.strip():
        return ""

    _ensure_nltk_data()

    try:
        return humanize_via_ollama(text)
    except OllamaError:
        return _humanize_rules(text, intensity)
