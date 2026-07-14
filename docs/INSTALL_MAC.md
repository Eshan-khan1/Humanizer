# Install Humanizer on macOS

Follow these steps in order.

## Step 1: Download these apps

Install each one before you continue:

1. [Google Chrome](https://www.google.com/chrome/)
2. [Python 3.10+](https://www.python.org/downloads/) (or run `brew install python` if you use Homebrew)
3. [Ollama](https://ollama.com) (open the app once after installing)
4. Java 11+ ([Adoptium](https://adoptium.net/) or `brew install openjdk@17`)

## Step 2: Download Humanizer

Open Terminal, then paste this and press Enter:

```bash
git clone https://github.com/Eshan-khan1/Humanizer.git
```

Then paste this and press Enter:

```bash
cd Humanizer
```

**No Git?** Download the ZIP instead:

1. Open https://github.com/Eshan-khan1/Humanizer
2. Click **Code**, then **Download ZIP**
3. Unzip the folder
4. In Terminal, go into that folder (example):

```bash
cd ~/Downloads/Humanizer-main
```

## Step 3: Paste this into Terminal (one-time setup)

Paste this and press Enter:

```bash
chmod +x scripts/install.sh start_server.sh "Start Humanizer.command"
```

Then paste this and press Enter:

```bash
./scripts/install.sh
```

Wait until it finishes. Make sure the Ollama app is open.

If models were not set up yet, paste this and press Enter:

```bash
./scripts/setup_models.sh
```

## Step 4: Paste this into Terminal (start the server)

Paste this and press Enter:

```bash
./start_server.sh
```

Keep that Terminal window open.

**Shortcut:** you can also double-click `Start Humanizer.command` in Finder.

Check that it worked: open http://127.0.0.1:8000/health  
You should see `"ok": true`.

## Step 5: Load the Chrome extension

1. Open Chrome and go to `chrome://extensions`
2. Turn on **Developer mode** (top right)
3. Click **Load unpacked**
4. Select the `extension` folder inside your Humanizer folder

## Step 6: Try it

1. Type in Gmail, Docs, or any text box
2. Mistakes should get underlines
3. Select text to Rewrite or Generate
4. Click the Humanizer icon in Chrome for Settings

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Ollama errors | Open the Ollama app, then run `./scripts/setup_models.sh` |
| Port 8000 busy | `./start_server.sh` usually clears it. Close anything else using port 8000 |
| No underlines | Install Java, restart the server, reload the extension |
| Extension cannot connect | Confirm http://127.0.0.1:8000/health works, then reload the extension |
