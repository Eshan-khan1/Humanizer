# Generate Feature Rules

Source of truth: `Generate_rules.text`

Generate takes a **short highlighted idea** and expands it into a full email or paragraph.

---

## Length (structure only)

| Value | Structure |
|-------|-----------|
| **Short** | 1 short paragraph or 2–3 sentences. Just the core message, no padding. |
| **Medium** | 2–3 paragraphs. Includes greeting, body, and closing if it's an email. |
| **Long** | 4+ paragraphs. Full detail, context, and elaboration. |

Length must **never** change vocabulary difficulty or tone — a "long, casual, simple" output should still use simple words, just more of them.

---

## Tone (voice only)

| Value | Voice |
|-------|--------|
| **Formal** | Professional language, no contractions, no slang, structured sentences. |
| **Friendly** | Warm, approachable, contractions okay, personable phrasing. |
| **Casual** | Relaxed, conversational, contractions and informal phrasing okay. |

Tone must **never** change how long the output is or how advanced the vocabulary is — "formal" doesn't mean longer, "casual" doesn't mean simpler words.

---

## Complexity (vocabulary only)

| Value | Vocabulary |
|-------|------------|
| **Simple** | Short, common words, short sentences, minimal jargon. |
| **Standard** | Everyday professional vocabulary, moderate sentence length. |
| **Advanced** | Sophisticated vocabulary, longer/more complex sentence structures. |

Complexity must **never** change tone or length — "advanced" doesn't mean more formal, "simple" doesn't mean shorter output.

---

## Independence rule (core constraint)

Length, Tone, and Complexity are **three separate prompt instructions** to the model, applied together but never merged into one instruction.

Changing one setting while holding the other two fixed must only change the dimension it controls.

**Example:** Short + Formal + Advanced vs. Long + Formal + Advanced should differ only in amount of text, not in formality or word choice.

---

## Context fields

| Field | Behavior |
|-------|----------|
| **Personal profile** | Comma-separated key-value pairs auto-injected into the prompt so generated text can reference name, role, or other saved details without the user typing them. |
| **Permanent Note** | Additional standing instruction always included in every generation (e.g. "always sign off as Eshan"). |

Both are **optional** — if empty, generation proceeds with generic phrasing, **no placeholder text**, no errors.

---

## Persistence

All settings (Length, Tone, Complexity, profile, note) are saved in the popup and **auto-apply to every future generation** without re-entry.

Implementation:

1. Popup writes to `chrome.storage.sync` (local fallback).
2. Content script loads settings on init and on `storage.onChanged`.
3. Every Generate call reloads the latest settings from storage before calling the API.

---

## Implementation map

| Layer | File |
|-------|------|
| Prompts + filters | `writing_agent.py` |
| API | `server.py` → `POST /generate` |
| Popup save/load | `extension/popup.js` |
| Auto-apply on generate | `extension/content.js` |
| Option labels | `extension/generate_tones.json` |
| Machine-readable rules | `generate_feature_rules.json` |
