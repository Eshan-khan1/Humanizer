# Install Thoth on macOS

Setup is meant to feel like a normal Mac app: download once, open once, then forget.

## Step 1: Download these apps

Install each one:

1. [Google Chrome](https://www.google.com/chrome/)
2. [Python 3.10+](https://www.python.org/downloads/) (or `brew install python`)
3. [Ollama](https://ollama.com) (open the Ollama app once after installing)
4. Java 11+ ([Adoptium](https://adoptium.net/) or `brew install openjdk@17`)

## Step 2: Download Thoth.app

Open the latest release page:

**[Download Thoth for Mac](https://github.com/Eshan-khan1/Thoth/releases/latest)**

1. Under **Assets**, download `Thoth-macOS.zip` (or `Thoth-macOS-v….zip`)
2. Also download `thoth-extension-mac-….zip` for the Chrome extension
3. Unzip both downloads

## Step 3: Install the menu bar app

1. Drag **Thoth.app** into your **Applications** folder
2. Open it once (double-click)
   - If macOS says the app can’t be opened, right-click **Thoth.app** → **Open** → **Open**
3. Look for the **Thoth diamond icon** near the clock (menu bar). There is no Dock icon by default.
4. If the icon is missing: System Settings → **Menu Bar** → turn **Thoth** ON  
   (or click **Add to Menu Bar…** in the app window)
5. Allow Thoth in **Login Items & Background Activity** if macOS asks — so it can restart the server after login
6. The first time it opens, it starts the local server and can relaunch after restart

Menu bar actions:

- **Status** shows whether the server is healthy
- **Restart server** if something looks stuck
- **Settings** for local models, features, hardware, Chrome connect, and **Privacy & Policy**
- **Connect Chrome Extension…** copies the extension into a stable folder and registers the native host
- **Quit Thoth** leaves the Chrome extension for later (the local server may stay running)

The icon changes when the server is online vs offline.

## Step 4: Install the Chrome extension

**Recommended (public listing):**

1. Open the Chrome Web Store listing:  
   **[Thoth: Local Writing Assistant](https://chromewebstore.google.com/detail/begfbbjincimcjcimpfpkoilbhjphppn)**
2. Click **Add to Chrome**
3. Keep **Thoth.app** running so the local server stays online

**Or load unpacked (from the app):**

1. In Thoth, open **Connect Chrome Extension…** (or follow the one-time setup sheet)
2. Open Chrome → `chrome://extensions`
3. Turn on **Developer mode**
4. Click **Load unpacked**
5. Select the folder the app opened/copied (usually  
   `~/Library/Application Support/Thoth/ChromeExtension`)

**Or from the release zip:**

1. Unzip `thoth-extension-mac-….zip`
2. Chrome → `chrome://extensions` → **Developer mode** → **Load unpacked**
3. Select that unzipped folder

After the first connect, the extension can talk to Thoth via native messaging whenever the app is running. Reload the extension after updating Thoth.

**Keep it installed across Chrome quits**

- Always load from  
  `~/Library/Application Support/Thoth/ChromeExtension`  
  (not a temporary unzip, and not the repo folder if you can avoid it)
- Leave **Developer mode** ON
- When Chrome shows **“Disable developer mode extensions”** after opening, click **Cancel** — choosing Disable removes Thoth until you Load unpacked again
- Do not rely on `scripts/dev_chrome.sh` for daily use — that `--load-extension` profile only lasts for that Chrome session

## Step 5: Try it

1. Confirm the menu bar icon shows the server as online
2. Type in Gmail, Docs, or any text box
3. Mistakes should get underlines
4. Select text to Rewrite or Generate
5. Click the Thoth toolbar icon in Chrome for Settings

Optional check: http://127.0.0.1:8000/health should show `"ok": true`.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No menu bar icon | Look for the diamond near the clock. Open `Thoth.app` again. Soften Focus / check Control Center › Menu Bar. Logs: `~/Library/Logs/Thoth/` |
| “App can’t be opened” | Right-click the app → **Open** → **Open**. Or drag a fresh copy from the zip into Applications. |
| Server stays offline | Open the Ollama app, then choose **Restart server** from the menu |
| Extension cannot connect | Confirm menu bar status is online, use **Connect Chrome Extension…**, then reload the extension |
| Native host / reconnect fails | Quit and reopen Thoth, reload the extension at `chrome://extensions` |
| Python missing | Install Python 3 from python.org, reopen the app |
| Port 8000 busy | Use **Restart server** from the menu |
| Old Humanizer settings | First launch migrates `~/Library/Application Support/Humanizer` → `…/Thoth` automatically |

## Optional: build from source

If you prefer to build the `.app` yourself instead of downloading it:

```bash
git clone https://github.com/Eshan-khan1/Thoth.git
cd Thoth
chmod +x scripts/build_macos_app.sh
./scripts/build_macos_app.sh
open dist/Thoth.app
```

Older terminal-only server flow (no menu bar app):

```bash
./scripts/install.sh
./scripts/setup_models.sh
./start_server.sh
```
