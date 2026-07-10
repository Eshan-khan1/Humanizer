# Install Humanizer on Windows

Humanizer has two parts: a **local Python server** and a **Chrome extension**. Both run on your Windows laptop.

## Requirements

| Tool | Download | Notes |
|------|----------|--------|
| [Google Chrome](https://www.google.com/chrome/) | — | Extension host |
| [Python 3.10+](https://www.python.org/downloads/) | Windows installer | **Check “Add python.exe to PATH”** |
| [Ollama](https://ollama.com/download) | Windows app | For Rewrite / Generate / Humanize |
| [Java 11+](https://adoptium.net/) | Temurin JRE | For LanguageTool grammar |

## Step 1 — Get the code

**Option A — Git**

```bat
git clone https://github.com/Eshan-khan1/Humanizer.git
cd Humanizer
```

**Option B — ZIP**

1. Open [https://github.com/Eshan-khan1/Humanizer](https://github.com/Eshan-khan1/Humanizer)
2. Click **Code → Download ZIP**
3. Unzip to a folder such as `C:\Users\YourName\Humanizer`
4. Open that folder in File Explorer

## Step 2 — One-time install

In File Explorer, open the `scripts` folder and **double-click** `install.bat`.

Or from **Command Prompt** / **PowerShell** inside the repo:

```bat
scripts\install.bat
```

This creates `.venv`, installs Python packages, and (if Ollama is running) registers the models.

If Ollama was not running during install:

1. Open **Ollama** from the Start menu
2. Run:

```bat
scripts\setup_models.bat
```

## Step 3 — Start the server

**Easiest:** double-click `Start Humanizer.bat` in the project root.

Or:

```bat
start_server.bat
```

Keep that window open. Confirm the server is up:

[http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

You should see JSON with `"ok": true`.

## Step 4 — Load the Chrome extension

1. Open `chrome://extensions`
2. Turn on **Developer mode** (top right)
3. Click **Load unpacked**
4. Select the `extension` folder inside this repo  
   (or unzip `humanizer-extension-windows-v*.zip` from [Releases](https://github.com/Eshan-khan1/Humanizer/releases) and select that folder)

## Step 5 — Use it

- Type in Gmail, Docs, or any text field → underlines on mistakes
- Select text → Rewrite or Generate
- Click the Humanizer toolbar icon → Settings (Local vs API, theme, Generate profile)

## Windows troubleshooting

| Problem | Fix |
|---------|-----|
| `python` not found | Reinstall Python and enable **Add to PATH**, then open a **new** Command Prompt |
| `scripts\install.bat` fails on pip | Run Command Prompt **as Administrator**, or: `python -m pip install -r requirements.txt` inside `.venv` |
| Port 8000 in use | `start_server.bat` tries to free it; or close the other app using 8000 |
| Ollama errors | Open the Ollama app; run `ollama list`; then `scripts\setup_models.bat` |
| No grammar underlines | Install Java 11+ from Adoptium; restart the server |
| Extension cannot reach server | Confirm [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health); reload the extension |
| Antivirus blocks Python | Allow `python.exe` / `uvicorn` for localhost |

## Optional: cloud API instead of local models

In the extension popup → **Settings → AI & API keys → API**, paste an OpenAI-compatible key, click **Connect**. Humanize / Rewrite / Generate will use that API; grammar underlines still use the local server + LanguageTool.
