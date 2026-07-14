# Install Humanizer on macOS

Setup is meant to feel like a normal Mac app: download once, open once, then forget.

## Step 1: Download these apps

Install each one:

1. [Google Chrome](https://www.google.com/chrome/)
2. [Python 3.10+](https://www.python.org/downloads/) (or `brew install python`)
3. [Ollama](https://ollama.com) (open the Ollama app once after installing)
4. Java 11+ ([Adoptium](https://adoptium.net/) or `brew install openjdk@17`)

## Step 2: Download Humanizer.app

Open the latest release page:

**[Download Humanizer for Mac](https://github.com/Eshan-khan1/Humanizer/releases/latest)**

1. Under **Assets**, download `Humanizer-macOS.zip` (or `Humanizer-macOS-v….zip`)
2. Also download `humanizer-extension-mac-….zip` for the Chrome extension
3. Unzip both downloads

Direct app download (latest release):

https://github.com/Eshan-khan1/Humanizer/releases/latest

## Step 3: Install the menu bar app

1. Drag **Humanizer.app** into your **Applications** folder
2. Open it once (double-click)
   - If macOS says the app can’t be opened, right-click **Humanizer.app** → **Open** → **Open**
3. You should see **Hz** in the menu bar (top-right). There is no Dock icon or window — that is normal.
4. A notification also says Humanizer is starting
5. The app quietly starts Ollama (if needed) and the grammar server in the background
6. The first time it opens, it also sets itself to relaunch after restart or login. No Terminal steps are required for that.

Menu bar actions:

- **Status** shows whether the server is healthy
- **Restart server** if something looks stuck
- **Quit Humanizer** leaves the Chrome extension for later (the local server may stay running)

The icon changes when the server is online vs offline.

## Step 4: Load the Chrome extension

1. Open Chrome and go to `chrome://extensions`
2. Turn on **Developer mode**
3. Click **Load unpacked**
4. Select the unzipped extension folder (from `humanizer-extension-mac-….zip`), or the `extension` folder if you cloned the repo

## Step 5: Try it

1. Confirm the menu bar icon shows the server as online
2. Type in Gmail, Docs, or any text box
3. Mistakes should get underlines
4. Select text to Rewrite or Generate

Optional check: http://127.0.0.1:8000/health should show `"ok": true`.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No menu bar icon | Look for **Hz** top-right. Open `Humanizer.app` again. Soften Focus / check Control Center › Menu Bar. Logs: `~/Library/Logs/Humanizer/` |
| “App can’t be opened” | Right-click the app → **Open** → **Open**. Or drag a fresh copy from the zip into Applications. |
| Server stays offline | Open the Ollama app, then choose **Restart server** from the menu |
| Extension cannot connect | Confirm the menu bar status is online, then reload the extension |
| Python missing | Install Python 3 from python.org, reopen the app |
| Port 8000 busy | Use **Restart server** from the menu |

## Optional: build from source

If you prefer to build the `.app` yourself instead of downloading it:

```bash
git clone https://github.com/Eshan-khan1/Humanizer.git
cd Humanizer
chmod +x scripts/build_macos_app.sh
./scripts/build_macos_app.sh
open dist/Humanizer.app
```

Older terminal-only server flow (no menu bar app):

```bash
./scripts/install.sh
./start_server.sh
```
