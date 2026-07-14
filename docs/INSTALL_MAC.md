# Install Humanizer on macOS

Setup is meant to feel like a normal Mac app: open once, then forget.

## Step 1: Download these apps

Install each one:

1. [Google Chrome](https://www.google.com/chrome/)
2. [Python 3.10+](https://www.python.org/downloads/) (or `brew install python`)
3. [Ollama](https://ollama.com) (open the Ollama app once after installing)
4. Java 11+ ([Adoptium](https://adoptium.net/) or `brew install openjdk@17`)

## Step 2: Download Humanizer

1. Open https://github.com/Eshan-khan1/Humanizer
2. Click **Code**, then **Download ZIP** (or clone with Git)
3. Unzip the folder somewhere easy to find

If you use Terminal instead:

```bash
git clone https://github.com/Eshan-khan1/Humanizer.git
cd Humanizer
```

## Step 3: Build or open the menu bar app

From the Humanizer folder, paste this into Terminal once to create the Mac app:

```bash
chmod +x scripts/build_macos_app.sh
./scripts/build_macos_app.sh
```

Then:

1. Open `dist/Humanizer.app` (double-click), or drag it into **Applications** and open it from there
2. A Humanizer icon appears in the menu bar at the top of your screen
3. The app quietly starts Ollama (if needed) and the grammar server in the background
4. The first time it opens, it also sets itself to relaunch after restart or login. You will not be asked to paste any extra command for that.

Menu bar actions:

- **Status** shows whether the server is healthy
- **Restart server** if something looks stuck
- **Quit Humanizer** leaves the Chrome extension for later (the local server may stay running)

The icon changes when the server is online vs offline.

## Step 4: Load the Chrome extension

1. Open Chrome and go to `chrome://extensions`
2. Turn on **Developer mode**
3. Click **Load unpacked**
4. Select the `extension` folder inside your Humanizer folder

## Step 5: Try it

1. Confirm the menu bar icon shows the server as online
2. Type in Gmail, Docs, or any text box
3. Mistakes should get underlines
4. Select text to Rewrite or Generate

Optional check: http://127.0.0.1:8000/health should show `"ok": true`.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No menu bar icon | Open `Humanizer.app` again. Check Console or `~/Library/Logs/Humanizer/` |
| Server stays offline | Open the Ollama app, then choose **Restart server** from the menu |
| Extension cannot connect | Confirm the menu bar status is online, then reload the extension |
| Python missing | Install Python 3 from python.org, reopen the app |
| Port 8000 busy | Use **Restart server** from the menu |

## Optional: terminal-only setup

If you prefer not to use the menu bar app, see the older script flow:

```bash
./scripts/install.sh
./start_server.sh
```
