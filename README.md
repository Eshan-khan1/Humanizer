# Humanizer

**A local-first writing assistant for Chrome.** Grammar checking, tone rewriting, and content generation — without sending your drafts to a cloud service by default.

[![Chrome Extension](https://img.shields.io/badge/Chrome-Extension-FF4D8D)](https://github.com/Eshan-khan1/Humanizer)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB)](https://www.python.org/)
[![Local First](https://img.shields.io/badge/Privacy-Local%20First-9B6BFF)](#privacy)

---

## What is Humanizer?

Humanizer is an open-source alternative to cloud writing tools like Grammarly. It runs a **small API server on your computer** and pairs it with a **Chrome extension** that works on Gmail, Google Docs, search bars, and most editable fields on the web.

| Feature | What it does |
|---------|----------------|
| **Grammar & spelling** | Pink underlines on mistakes; click to accept a fix |
| **Auto-fix** | Optionally correct all issues as you type |
| **Rewrite** | Select text → change tone (friendly, formal, simpler, etc.) |
| **Generate** | Turn short notes into emails, messages, or essays |

Everything can run **fully offline** if you use local Ollama models. Cloud AI (Groq / OpenAI) is optional for faster Rewrite and Generate.

---

## How it works

Humanizer is two parts that talk over `localhost`:

```
┌─────────────────────────────────────────────────────────────────┐
│  Chrome (any website)                                             │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  extension/content.js                                      │  │
│  │  • Mirrors text fields, draws grammar underlines           │  │
│  │  • Rewrite / Generate UI on text selection               │  │
│  └───────────────────────────┬───────────────────────────────┘  │
│                              │ chrome.runtime.sendMessage        │
│  ┌───────────────────────────▼───────────────────────────────┐  │
│  │  extension/background.js  →  fetch(127.0.0.1:8000)        │  │
│  └───────────────────────────────────────────────────────────┘  │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTP (localhost only)
┌──────────────────────────────▼──────────────────────────────────┐
│  server.py  (FastAPI + uvicorn, port 8000)                        │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────┐ │
│  │ LanguageTool│  │ Ollama       │  │ writing_agent.py        │ │
│  │ (Java)      │  │ :11434       │  │ prompts + hard filters  │ │
│  │ grammar     │  │ local LLMs   │  │ rewrite / generate      │ │
│  └─────────────┘  └──────────────┘  └─────────────────────────┘ │
│  Optional: cloud_ai.py → Groq / OpenAI (keys from extension only) │
└───────────────────────────────────────────────────────────────────┘
```

### Grammar flow

1. You type in a text field (Gmail compose, Docs, etc.).
2. `content.js` debounces input and sends text to `POST /grammar`.
3. The server runs **LanguageTool** (and optionally a local grammar model).
4. Matches return as offsets; the extension draws **pink underlines** (Humanizer design system).
5. Click an underline → suggestion card → accept replaces the text in-place.

### Rewrite flow

1. Select text → floating **↗** button → pick **Rewrite**.
2. Enter a tone (e.g. “more formal”) → `POST /rewrite`.
3. `writing_agent.py` builds a prompt, calls Ollama or cloud AI, applies **hard filters** (no extra greetings, same length, etc.).
4. Selection is replaced with the rewritten text.

### Generate flow

1. Select seed text → **Generate** → choose format (email, message, essay).
2. Optional note and settings (length, tone, complexity, profile).
3. `POST /generate` expands the note using saved defaults from the extension popup.
4. Post-generation filters enforce length, tone, and name placeholders.

---

## Download & install

### Requirements

| Tool | Why |
|------|-----|
| [Google Chrome](https://www.google.com/chrome/) | Extension host |
| [Python 3.10+](https://www.python.org/downloads/) | API server |
| [Ollama](https://ollama.com) | Local Rewrite / Generate (and optional grammar model) |
| [Java 11+](https://adoptium.net/) | LanguageTool grammar engine |

### Step 1 — Get the code

**Clone (recommended for developers):**

```bash
git clone https://github.com/Eshan-khan1/Humanizer.git
cd Humanizer
```

**Or download without git:**

- [Download ZIP (main branch)](https://github.com/Eshan-khan1/Humanizer/archive/refs/heads/main.zip)
- Unzip and open the folder in Terminal

**Extension only (no full repo):**

- [GitHub Releases](https://github.com/Eshan-khan1/Humanizer/releases) → download `humanizer-extension.zip`

### Step 2 — One-time setup

```bash
chmod +x scripts/install.sh
./scripts/install.sh
```

This will:

- Create a Python virtual environment (`.venv`)
- Install packages from `requirements.txt`
- Download NLTK data
- Register Ollama models (`humanizer-grammar`, `humanizer-writing`) if Ollama is running

### Step 3 — Start the server

```bash
./start_server.sh
```

Keep this terminal open while using Humanizer.

**macOS shortcut:** double-click `Start Humanizer.command` in Finder.

Verify: open [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) — you should see a JSON OK response.

### Step 4 — Load the Chrome extension

1. Open `chrome://extensions`
2. Enable **Developer mode** (top-right)
3. Click **Load unpacked**
4. Select the `extension/` folder from this repo  
   (or the folder you unzipped from a release)

### Step 5 — Try it

- Type in any text box → pink underlines on errors
- Select text → gradient button → **Rewrite** or **Generate** icons
- Click the toolbar icon → **Settings** for toggles, AI keys, and Generate profile

---

## Project structure

```
Humanizer/
├── extension/                 # Chrome extension (Manifest V3)
│   ├── manifest.json
│   ├── content.js             # In-page UI: grammar, rewrite, generate
│   ├── content.css            # Design system styles
│   ├── design-tokens.css      # Brand colors & tokens
│   ├── background.js          # API calls to local server
│   ├── popup.html / popup.js  # Settings UI
│   └── icons/                 # Rewrite & Generate menu icons
│
├── server.py                  # FastAPI app — all HTTP endpoints
├── writing_agent.py           # Rewrite/Generate prompts & filters
├── security.py                # Localhost-only, rate limits, auth
├── cloud_ai.py                # Optional Groq / OpenAI routing
├── rag.py                     # RAG utilities for training/tuning
│
├── start_server.sh            # Start API on :8000
├── run.sh                     # Desktop app entry (pywebview)
├── requirements.txt           # Python dependencies
│
├── scripts/
│   ├── install.sh             # One-command setup
│   ├── setup_models.sh        # Ollama model registration
│   ├── package_extension.sh   # Build dist/*.zip
│   └── create_release.sh      # Publish GitHub Release
│
├── test_data/                 # Pairs, benchmarks, training samples
├── benchmark_tests.json       # Rewrite/Generate test cases
└── Humanizer design system.json  # UI brand tokens
```

---

## API reference (local server)

Base URL: `http://127.0.0.1:8000`

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Server + dependency check |
| `POST` | `/grammar` | Full grammar check |
| `POST` | `/grammar/quick` | Fast path for typing |
| `POST` | `/humanize` | Legacy humanize endpoint |
| `POST` | `/rewrite` | Tone/style rewrite |
| `POST` | `/generate` | Expand notes to email/essay/etc. |

Optional header when auth is enabled:

```
Authorization: Bearer <HUMANIZER_API_TOKEN>
```

Rewrite/Generate bodies may include optional cloud AI:

```json
{
  "text": "...",
  "tone": "friendly",
  "ai": { "provider": "groq", "apiKey": "..." }
}
```

Keys are sent from the extension to **your** local server only; they are not stored server-side.

---

## Configuration

### Extension settings (popup)

- **Check writing while I type** — grammar on/off
- **Fix all mistakes automatically** — auto-apply corrections
- **Rewrite in search bars** — enable rewrite on search inputs
- **AI & API keys** — Local Ollama, Groq, or OpenAI
- **Generate** — profile fields, length, tone, complexity, permanent note

### Server environment variables

| Variable | Effect |
|----------|--------|
| `HUMANIZER_REQUIRE_AUTH=1` | Require Bearer token on all requests |
| `HUMANIZER_API_TOKEN` | Token value (auto-generated if unset) |
| `HUMANIZER_DEBUG=1` | Verbose server errors |

Example:

```bash
HUMANIZER_REQUIRE_AUTH=1 ./start_server.sh
```

Paste the printed token into the extension → Settings → AI & API keys → Local server token.

---

## Development

### Run in dev mode

```bash
./scripts/install.sh          # once
./start_server.sh             # terminal 1
# Chrome → load unpacked extension/
# Optional: ./scripts/dev_chrome.sh  (macOS test profile)
```

### Package extension for others

```bash
./scripts/package_extension.sh
# → dist/humanizer-extension-v1.8.0.zip
```

### Publish a GitHub Release

```bash
./scripts/create_release.sh
```

### Run benchmarks

With the server running:

```bash
# benchmark_tests.json defines rewrite/generate cases
python scripts/benchmark_rewrite.py   # if present
```

### Fine-tuning (advanced)

- `scripts/finetune_grammar_lora.py` — MLX LoRA for grammar model
- `prepare_data.py` — training pair preparation
- `requirements-finetune.txt` — extra training deps

---

## Models

Humanizer expects these **Ollama** models (created by `scripts/setup_models.sh`):

| Model | Used for |
|-------|----------|
| `humanizer-grammar` | Optional grammar assistance |
| `humanizer-writing` | Rewrite & Generate (local) |

If local Modelfiles exist under `models/`, setup uses them. Otherwise setup pulls small **Qwen2.5** bases from Ollama Hub.

Model weights are **not** committed to git (too large). Each user downloads via Ollama.

---

## Design system

UI colors, typography, and components are defined in [`Humanizer design system.json`](Humanizer%20design%20system.json):

- Dark-first UI (`#0E1117` background)
- Pink → violet gradient for primary actions (`#FF4D8D` → `#B14DFF`)
- Inter font family
- Pink grammar underlines (not red/green)

---

## Privacy

- **Default:** text is processed on your machine via localhost.
- **Grammar** uses LanguageTool locally (Java).
- **Rewrite/Generate** use local Ollama unless you opt into Groq/OpenAI in settings.
- API keys live in **Chrome storage** on your device and are only sent to `127.0.0.1:8000`.
- No Humanizer account, telemetry, or central server.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Server offline in popup | Run `./start_server.sh`; check `/health` |
| No underlines | Enable “Check writing while I type”; ensure Java is installed |
| Rewrite/Generate error | Start Ollama; run `./scripts/setup_models.sh` |
| `humanizer-grammar` missing | `ollama list` then `./scripts/setup_models.sh` |
| Extension not updating | `chrome://extensions` → Reload |
| Port 8000 in use | `start_server.sh` kills the old process; or change port in code |

---

## Contributing

Contributions are welcome.

1. Fork the repo
2. Create a branch (`git checkout -b feature/my-change`)
3. Commit with a clear message
4. Open a Pull Request on GitHub

Ideas for contributors:

- Windows/Linux install polish
- Chrome Web Store listing
- More language support
- Additional Generate formats
- Benchmark coverage

---

## License

Open source — use, study, and modify on your own machine. See the repository for license details.

---

## Links

- **Repository:** https://github.com/Eshan-khan1/Humanizer
- **Releases (extension zip):** https://github.com/Eshan-khan1/Humanizer/releases
- **Issues:** https://github.com/Eshan-khan1/Humanizer/issues
