# Install Thoth on Windows

Setup matches the Mac experience: a **system tray app** runs the local server in the background (no console window).

## Step 1: Download these apps

Install each one before you continue:

1. [Google Chrome](https://www.google.com/chrome/)
2. [Python 3.10+](https://www.python.org/downloads/)  
   Important: during setup, check **Add python.exe to PATH** (and install **py launcher**)
3. [Ollama for Windows](https://ollama.com/download)  
   Open the Ollama app once after installing
4. [Java 11+](https://adoptium.net/) (Temurin JRE is fine)

## Step 2: Get Thoth

**Option A — GitHub release (recommended)**

1. Open [Thoth Releases](https://github.com/Eshan-khan1/Thoth/releases/latest)
2. Download **`Thoth-Windows.zip`** (when available) or clone the repo
3. Unzip to a folder such as `C:\Users\YourName\Thoth`
4. Double-click **`Start Thoth.bat`** — a tray icon appears (no command window)

**Option B — Clone from GitHub**

```bat
git clone https://github.com/Eshan-khan1/Thoth.git
cd Thoth
scripts\install.bat
```

Then double-click **`Start Thoth.bat`** in the repo folder.

## Step 3: Tray app

After **`Start Thoth.bat`**:

- Look for the **Thoth icon** in the system tray (notification area)
- Right-click for: server status, **Restart server**, **Connect Chrome extension**, **Install extension (Chrome Web Store)**, **Start with Windows**, **Quit**
- The app copies server files to `%LOCALAPPDATA%\Thoth\Home` and creates a local `.venv` on first run

**Legacy console mode:** run `start_server.bat` if you prefer a visible terminal window.

## Step 4: Install the Chrome extension

**Install from the Chrome Web Store:**

1. Open **[Thoth: Local Writing Assistant](https://chromewebstore.google.com/detail/begfbbjincimcjcimpfpkoilbhjphppn?utm_source=item-share-cb)**
2. Click **Add to Chrome**
3. Keep the Thoth tray app running; check http://127.0.0.1:8000/health shows `"ok": true`

Tray menu → **Connect Chrome extension…** opens Chrome extensions and registers native messaging.

**Developers only — load unpacked:**

1. Open `chrome://extensions`
2. Turn on **Developer mode**
3. **Load unpacked** → select the `extension` folder in your Thoth repo

## Step 5: Try it

1. Type in Gmail, Docs, or any text box
2. Mistakes should get underlines
3. Select text to Rewrite or Generate
4. Click the Thoth icon in Chrome for Settings

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No tray icon | Click the ^ arrow in the taskbar notification area; pin Thoth |
| `python` not found | Reinstall Python with **Add to PATH**, open a new Command Prompt |
| Tray app won't start | Run `scripts\install.bat`, then `Start Thoth.bat` again |
| Port 8000 in use | Tray → **Restart server**, or close the other app on port 8000 |
| Ollama errors | Open the Ollama app, then run `scripts\setup_models.bat` |
| No underlines | Install Java, tray → Restart server, reload the extension |
| Extension cannot connect | Confirm tray shows server online; use **Connect Chrome extension…** |

## Optional: use a cloud API key

In the extension popup, open **Settings**, then **AI & API keys**, choose **API**, paste your key, and click **Connect**.

## Models (Ollama)

`scripts\setup_models.bat` registers:

| Model | Used for |
|-------|----------|
| `thoth-grammar` | Optional deep grammar fixes |
| `thoth-writing` | Rewrite & Generate (local) |

## Build the Windows package (developers)

On Windows, from the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows_app.ps1
```

Output: `dist\ThothWindows\` and `dist\Thoth-Windows.zip`
