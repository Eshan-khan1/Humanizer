# Humanizer — Project Documentation

**Repository:** https://github.com/Eshan-khan1/Humanizer  
**Extension version:** 1.8.0  
**API:** FastAPI on `http://127.0.0.1:8000`

---

## Table of contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Grammar pipeline](#3-grammar-pipeline)
4. [Rewrite pipeline](#4-rewrite-pipeline)
5. [Generate pipeline](#5-generate-pipeline)
6. [Chrome extension](#6-chrome-extension)
7. [API reference](#7-api-reference)
8. [Installation](#8-installation)
9. [Models (Ollama)](#9-models-ollama)
10. [Project structure](#10-project-structure)
11. [Configuration](#11-configuration)
12. [Development & testing](#12-development--testing)
13. [Privacy](#13-privacy)
14. [Troubleshooting](#14-troubleshooting)
15. [Related files](#15-related-files)

---

## 1. Overview

Humanizer is a **local-first writing assistant** made of two parts:

1. **Chrome extension** — grammar underlines, rewrite, and generate on any website (Gmail, Google Docs, search bars, etc.)
2. **Local API server** (`server.py`) — runs on `http://127.0.0.1:8000` and processes all text on your machine

By default, nothing is sent to the cloud. Optional Groq/OpenAI can be enabled in extension settings for faster rewrite/generate.

| Feature | Description |
|---------|-------------|
| **Grammar & spelling** | Pink underlines; click to accept a fix |
| **Auto-fix** | Optionally correct all issues as you type |
| **Rewrite** | Select text → change tone/style (formal, casual, etc.) |
| **Generate** | Turn short notes into emails or essays |
| **Humanize** | Legacy endpoint to make text sound more natural |

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Chrome (Gmail, Docs, any site)                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  content.js — UI, underlines, rewrite/generate menus     │ │
│  └───────────────────────┬─────────────────────────────────┘ │
│                          │ chrome.runtime.sendMessage        │
│  ┌───────────────────────▼─────────────────────────────────┐ │
│  │  background.js — fetch → 127.0.0.1:8000                 │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP (localhost only)
┌──────────────────────────▼──────────────────────────────────┐
│  server.py (FastAPI + uvicorn :8000)                         │
│  ├─ LanguageTool (Java)     — grammar Agent 1                │
│  ├─ Ollama :11434           — deep grammar + rewrite/generate│
│  ├─ writing_agent.py        — prompts + hard output filters  │
│  └─ cloud_ai.py (optional)  — Groq / OpenAI                  │
└─────────────────────────────────────────────────────────────┘
```

**Important:** API calls go through the **background script** (extension origin), not directly from the page. That avoids CORS failures on sites like Gmail.

### Data flow summary

| Feature | Extension path | Server endpoint |
|---------|----------------|-----------------|
| Grammar | `content.js` → `background.js` | `POST /grammar`, `POST /grammar/quick` |
| Rewrite | `content.js` → `background.js` | `POST /rewrite` |
| Generate | `content.js` → `background.js` | `POST /generate` |
| Health check | `popup.js` | `GET /health` |

---

## 3. Grammar pipeline

### Fast path (`POST /grammar/quick`)

- **LanguageTool only** — used while typing for snappy underlines
- Returns match offsets for the extension mirror overlay

### Full path (`POST /grammar`)

Two-agent pipeline:

| Agent | Engine | Role |
|-------|--------|------|
| **Agent 1** | LanguageTool (`language-tool-python` 2.8.1) | High-confidence spelling/grammar matches |
| **Agent 2** | Ollama `humanizer-grammar` | Full-sentence rewrite for hard sentences LT misses |

**Flow:**

1. Extension debounces input → sends text to server
2. LanguageTool finds matches (offsets + suggestions)
3. Sentences with incomplete LT coverage go to the deep fixer
4. Response: `matches[]` + `corrected` full text
5. Extension draws pink underlines; click opens suggestion card

**Match shape:**

```json
{
  "word": "Their ",
  "offset": 0,
  "length": 6,
  "suggestions": ["They're "],
  "type": "grammar",
  "message": "Use \"They're\" instead of \"Their\"",
  "rule_id": "ENGLISH_WORD_REPEAT_RULE",
  "category": "GRAMMAR"
}
```

### Auto-fix

When enabled in the popup, the extension applies fixes chunk-by-chunk across multiple passes, rescans after each fix, and stops when no fixable matches remain or a pass limit is reached.

### RAG note

`rag.py` and `grammar_rules.json` exist for **training and tuning** but are **not** wired into the live grammar API. The `/reload-rules` endpoint is a no-op kept for `auto_tune.py` compatibility.

---

## 4. Rewrite pipeline

1. User selects text → floating **↗** button → **Rewrite** icon
2. User enters instruction (e.g. “make it formal”)
3. `content.js` → `background.js` → `POST /rewrite`
4. `writing_agent.py`:
   - Builds prompt (direct mode when `prompt` is sent from the extension)
   - Calls Ollama `humanizer-writing` or cloud AI
   - Applies **hard filters**: no extra greetings, similar length, no added filler
5. Rewritten text replaces **only** the selection

**Request:**

```json
{
  "text": "The meeting has been moved to Thursday at 3pm.",
  "prompt": "make it casual",
  "context": { "surroundingText": "..." },
  "ai": { "provider": "groq", "apiKey": "..." }
}
```

**Response:**

```json
{
  "text": "The meeting has been moved to Thursday at 3pm.",
  "tone": "make it casual",
  "rewritten": "The meeting is now on Thursday at 3pm."
}
```

### Hard filters (rewrite)

`apply_rewrite_hard_filters` in `writing_agent.py` ensures:

- No added greeting/sign-off lines unless the original had them
- No extra filler sentences (“hope you're doing well”, etc.)
- Similar sentence count to the original
- Selection-only replacement semantics

---

## 5. Generate pipeline

1. User selects seed text → **Generate** icon
2. Chooses format (email / essay), optional one-time note
3. Settings from popup: **length**, **tone**, **complexity**, **profile**
4. `POST /generate` → `writing_agent.py`

### Three independent settings

| Setting | Values | Controls |
|---------|--------|----------|
| **Length** | `short`, `medium`, `long` | Paragraph/sentence structure only |
| **Tone** | `formal`, `friendly`, `casual` | How it sounds (greeting, phrasing, sign-off) |
| **Complexity** | `simple`, `standard`, `advanced` | Vocabulary only |

These must not bleed into each other. Post-generation filters enforce structure, tone phrases, and name placeholders (`[Name]`, `[Your Name]`).

**Official spec:** [GENERATE_RULES.md](GENERATE_RULES.md)

### Length targets (email body)

| Length | Body structure |
|--------|----------------|
| **short** | 1 paragraph, 2 sentences |
| **medium** | 3 paragraphs, 3 sentences each |
| **long** | 4+ paragraphs, 3–4 sentences each |

### Request

```json
{
  "text": "Follow up with the client about the contract.",
  "format": "email",
  "notes": "I have a family emergency this week.",
  "settings": {
    "tonePreset": "friendly",
    "length": "medium",
    "complexity": "simple",
    "includeSubject": true,
    "profile": {
      "fullName": "Alex Chen",
      "jobTitle": "Project Manager",
      "permanentNote": "Always sign off with Best,"
    }
  }
}
```

### Notes behavior

- **Informational notes** (facts) are woven into the body without changing tone
- **Tone override notes** (e.g. “make it more formal”) apply for that generation only
- **Permanent note** from profile is included in every generate call

---

## 6. Chrome extension

### Files

| File | Purpose |
|------|---------|
| `manifest.json` | MV3 config, permissions, content scripts |
| `content.js` | Grammar overlay, rewrite/generate UI, selection handling |
| `content.css` + `design-tokens.css` | Dark theme, pink underlines, menus |
| `background.js` | All HTTP calls to local server |
| `api_auth.js` | Bearer token + cloud AI config from storage |
| `popup.html` / `popup.js` / `popup.css` | Settings UI |
| `generate_tones.json` | Length/tone/complexity option definitions |
| `icons/` | Rewrite & Generate menu icons |

### Permissions

- `activeTab`, `scripting`, `storage`
- `host_permissions`: `http://127.0.0.1:8000/*`

### Default settings (popup)

| Setting | Default |
|---------|---------|
| Grammar enabled | `true` |
| Auto-fix all | `true` |
| Rewrite in search bars | `true` |
| Generate length | `medium` |
| Generate tone | `friendly` |
| Generate complexity | `standard` |
| Include subject line | `true` |

Settings sync via `chrome.storage.sync` (profile and API keys use `chrome.storage.local`).

### UI / design system

Defined in `Humanizer ui theme.json`:

- Warm cream / charcoal Claude-inspired palette (light + dark)
- Orange accent `#c96442` only
- Source Serif 4 editorial type
- Terracotta grammar underlines

---

## 7. API reference

**Base URL:** `http://127.0.0.1:8000`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Server + Ollama + LanguageTool status |
| `POST` | `/grammar` | Full two-agent grammar check |
| `POST` | `/grammar/quick` | Fast LanguageTool-only check |
| `POST` | `/humanize` | Make text sound more human/natural |
| `POST` | `/rewrite` | Tone/style rewrite of selection |
| `POST` | `/generate` | Expand notes to email/essay |
| `POST` | `/reload-rules` | No-op (legacy RAG compatibility) |

### Health response

```json
{
  "ok": true,
  "ollama_available": true,
  "grammar_available": true,
  "grammar_model": "humanizer-grammar",
  "writing_model": "humanizer-writing",
  "writing_agent": "rewrite, generate",
  "cloud_ai_providers": ["groq", "openai"]
}
```

### Grammar response

```json
{
  "text": "Their going to the store.",
  "matches": [
    {
      "word": "Their ",
      "offset": 0,
      "length": 6,
      "suggestions": ["They're "],
      "type": "grammar",
      "message": "...",
      "rule_id": "...",
      "category": "..."
    }
  ],
  "corrected": "They're going to the store."
}
```

### Auth (optional)

```bash
HUMANIZER_REQUIRE_AUTH=1 HUMANIZER_API_TOKEN=your-token ./start_server.sh
```

Paste the token in the extension → Settings → AI & API keys → Local server token.

Header on all protected endpoints:

```
Authorization: Bearer <token>
```

### Security (`security.py`)

- **Localhost-only** clients (`LocalClientMiddleware`)
- Rate limiting (`RateLimitMiddleware`)
- Request size limits
- CORS: `chrome-extension://` + `127.0.0.1:8000`
- API keys never stored server-side

---

## 8. Installation

### Requirements

| Tool | Purpose |
|------|---------|
| [Google Chrome](https://www.google.com/chrome/) | Extension host |
| [Python 3.10+](https://www.python.org/downloads/) | API server |
| [Java 11+](https://adoptium.net/) | LanguageTool grammar engine |
| [Ollama](https://ollama.com) | Local LLM (rewrite, generate, deep grammar) |

### Quick start

```bash
git clone https://github.com/Eshan-khan1/Humanizer.git
cd Humanizer
chmod +x scripts/install.sh
./scripts/install.sh          # venv + deps + NLTK + models
./start_server.sh             # API on :8000
```

**macOS shortcut:** double-click `Start Humanizer.command`

**Chrome:**

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select the `extension/` folder

**Verify:** open http://127.0.0.1:8000/health

### Python dependencies (`requirements.txt`)

| Package | Purpose |
|---------|---------|
| `fastapi`, `uvicorn` | API server |
| `language-tool-python==2.8.1` | Grammar engine wrapper |
| `nltk`, `textblob` | NLP utilities |
| `requests` | HTTP client |
| `pywebview` | Desktop app shell |
| `datasets`, `zstandard` | Training data tools |

---

## 9. Models (Ollama)

Created by `scripts/setup_models.sh`:

| Model | Used for |
|-------|----------|
| `humanizer-grammar` | Deep grammar fixes (Agent 2) |
| `humanizer-writing` | Rewrite & Generate |

Custom Modelfiles can live under `models/` (not committed to GitHub — too large). Users pull base models via Ollama.

### Environment overrides

| Variable | Default | Effect |
|----------|---------|--------|
| `OLLAMA_GRAMMAR_MODEL` | `humanizer-grammar` | Grammar deep fixer model |
| `OLLAMA_WRITING_MODEL` | `humanizer-writing` | Rewrite/Generate model |
| `OLLAMA_GRAMMAR_NUM_PREDICT` | `768` | Max tokens (grammar) |
| `OLLAMA_GRAMMAR_NUM_CTX` | `4096` | Context window (grammar) |
| `OLLAMA_REWRITE_TEMPERATURE` | `0.55` | Rewrite sampling |
| `OLLAMA_GENERATE_TEMPERATURE` | `0.6` | Generate sampling |

---

## 10. Project structure

```
Humanizer/
├── extension/                  # Chrome extension (Manifest V3)
│   ├── manifest.json
│   ├── content.js              # In-page UI: grammar, rewrite, generate
│   ├── content.css
│   ├── design-tokens.css
│   ├── background.js           # API calls to local server
│   ├── api_auth.js
│   ├── popup.html / popup.js / popup.css
│   ├── generate_tones.json
│   └── icons/
│
├── server.py                   # FastAPI app — all HTTP endpoints
├── writing_agent.py            # Rewrite/Generate prompts & filters
├── security.py                 # Localhost-only, rate limits, auth
├── cloud_ai.py                 # Optional Groq / OpenAI routing
├── humanizer.py                # Standalone humanization library
├── rag.py                      # RAG utilities (training/tuning only)
├── grammar_rules.json          # Rule database for fine-tuning
├── auto_tune.py                # Grammar rule learning
│
├── start_server.sh             # Start API on :8000
├── Start Humanizer.command     # macOS double-click launcher
├── Start Humanizer.bat         # Windows launcher
├── run.sh                      # Desktop app entry (pywebview)
├── requirements.txt
├── requirements-finetune.txt
│
├── scripts/
│   ├── install.sh              # One-command setup
│   ├── setup_models.sh         # Ollama model registration
│   ├── package_extension.sh    # Build dist/*.zip
│   ├── create_release.sh       # Publish GitHub Release
│   ├── finetune_grammar_lora.py
│   ├── benchmark_rewrite.py
│   ├── run_benchmarks.py
│   └── dev_chrome.sh           # Dev Chrome profile
│
├── test_data/                  # Pairs, benchmarks, test HTML
├── benchmark_tests.json        # Generate/Rewrite test matrix
├── web/                        # Optional web UI
├── docs/                       # Project documentation (this file)
├── nltk_data/                  # Bundled NLTK tokenizers
└── models/                     # Local model weights (gitignored)
```

---

## 11. Configuration

### Server environment variables

| Variable | Effect |
|----------|--------|
| `HUMANIZER_HOST` | Bind host (default `127.0.0.1`) |
| `HUMANIZER_PORT` | Port (default `8000`) |
| `HUMANIZER_REQUIRE_AUTH` | Require Bearer token on all endpoints |
| `HUMANIZER_API_TOKEN` | Token value (auto-generated if unset when auth required) |
| `HUMANIZER_DEBUG` | Verbose server error messages |
| `HUMANIZER_DEBUG_OLLAMA` | Ollama debug logging |
| `HUMANIZER_CORS_ORIGINS` | Extra CORS origins (comma-separated) |
| `HUMANIZER_RATE_LIMIT_REQUESTS` | Rate limit per window |
| `HUMANIZER_GROQ_MODEL` | Default Groq model |
| `HUMANIZER_OPENAI_MODEL` | Default OpenAI model |

### Extension storage keys

| Key | Storage | Purpose |
|-----|---------|---------|
| `enabled` | sync | Grammar on/off |
| `autoFixAll` | sync | Auto-fix mode |
| `rewriteInSearchBars` | sync | Rewrite on search inputs |
| `generateProfile` | sync | Name, job, sign-off, etc. |
| `generateLength` | sync | Default generate length |
| `generateTonePreset` | sync | Default generate tone |
| `generateComplexity` | sync | Default generate complexity |
| `humanizerApiToken` | local | Server auth token |
| `aiProvider` | local | `local`, `groq`, or `openai` |
| `aiApiKey` | local | Cloud API key (never synced) |

---

## 12. Development & testing

### Dev workflow

```bash
./scripts/install.sh          # once
./start_server.sh             # terminal 1
# Chrome → chrome://extensions → Load unpacked → extension/
./scripts/dev_chrome.sh       # optional: isolated Chrome profile (macOS)
```

### Benchmarks

With the server running:

```bash
.venv/bin/python scripts/run_benchmarks.py
.venv/bin/python scripts/benchmark_rewrite.py
```

Test cases are defined in `benchmark_tests.json` (tone/length/complexity separation, rewrite length, note behavior).

### Package extension

```bash
./scripts/package_extension.sh
# → dist/humanizer-extension-v1.8.0.zip
```

### Publish a GitHub Release

```bash
./scripts/create_release.sh
```

### Fine-tuning (advanced)

```bash
pip install -r requirements-finetune.txt
python scripts/finetune_grammar_lora.py
python prepare_data.py
```

### Local test page

Open `test_data/rewrite_test.html` in Chrome with the extension loaded to test grammar and rewrite without Gmail.

---

## 13. Privacy

- Text is processed on **your machine** via localhost
- **Grammar** uses LanguageTool locally (Java)
- **Rewrite/Generate** use local Ollama unless you opt into Groq/OpenAI in settings
- API keys live in **Chrome local storage** and are only sent to `127.0.0.1:8000`
- No Humanizer account, telemetry, or central server

---

## 14. Troubleshooting

| Problem | Solution |
|---------|----------|
| Server offline in popup | Run `./start_server.sh`; check http://127.0.0.1:8000/health |
| No underlines | Enable “Check writing while I type”; ensure Java is installed |
| Rewrite/Generate error | Start Ollama; run `./scripts/setup_models.sh` |
| `humanizer-grammar` missing | `ollama list` then `./scripts/setup_models.sh` |
| `OPTIONS /rewrite 400` | Reload extension — API must go through background script |
| Extension not updating | `chrome://extensions` → Reload |
| Port 8000 in use | `start_server.sh` kills the old process automatically |
| Ollama generate fails | Run `./scripts/fix_ollama.sh` |
| Grammar only, no deep fixes | Ollama not running — LT-only mode still works |

---

## 15. Related files

| File | Description |
|------|-------------|
| [README.md](../README.md) | GitHub-facing install guide and quick reference |
| [Humanizer ui theme.json](../Humanizer%20ui%20theme.json) | Claude-inspired UI tokens (light/dark) |
| [Features.txt](../Features.txt) | Product feature notes |
| [benchmark_tests.json](../benchmark_tests.json) | Automated test cases |
| [GENERATE_RULES.md](GENERATE_RULES.md) | Generate feature rules (length/tone/complexity independence) |
| [generate_feature_rules.json](../generate_feature_rules.json) | Machine-readable Generate rules |
| [generate_tones.json](../extension/generate_tones.json) | Generate UI option definitions |

---

## Contributing

1. Fork https://github.com/Eshan-khan1/Humanizer
2. Create a branch (`git checkout -b feature/my-change`)
3. Commit with a clear message
4. Open a Pull Request

Ideas for contributors: Windows/Linux install polish, Chrome Web Store listing, more languages, additional Generate formats, benchmark coverage.
