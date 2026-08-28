# Install Thoth on Windows

Follow these steps in order.

## Step 1: Download these apps

Install each one before you continue:

1. [Google Chrome](https://www.google.com/chrome/)
2. [Python 3.10+](https://www.python.org/downloads/)  
   Important: during setup, check **Add python.exe to PATH**
3. [Ollama for Windows](https://ollama.com/download)  
   Open the Ollama app once after installing
4. [Java 11+](https://adoptium.net/) (Temurin JRE is fine)

## Step 2: Download Thoth

**Option A: Download ZIP (easiest)**

1. Open https://github.com/Eshan-khan1/Thoth
2. Click **Code**, then **Download ZIP**
3. Unzip it to a simple folder, for example:
   `C:\Users\YourName\Thoth`
4. Open that folder in File Explorer

**Option B: Git**

Open **Command Prompt** or **PowerShell**, then paste this and press Enter:

```bat
git clone https://github.com/Eshan-khan1/Thoth.git
```

Then paste this and press Enter:

```bat
cd Thoth
```

## Step 3: Paste this into Command Prompt (one-time setup)

1. Open **Command Prompt**
2. Go into your Thoth folder. Example: paste this and press Enter (change the path if yours is different):

```bat
cd C:\Users\YourName\Thoth
```

3. Paste this and press Enter:

```bat
scripts\install.bat
```

Wait until it finishes. Keep the Ollama app open.

If models were not set up yet, paste this and press Enter:

```bat
scripts\setup_models.bat
```

**No Command Prompt?** In File Explorer, open the `scripts` folder and double-click `install.bat`.

## Step 4: Start the server

In your Thoth folder, double-click:

`Start Thoth.bat`

Or in Command Prompt, paste this and press Enter:

```bat
start_server.bat
```

Keep that window open while you use Thoth.

Check that it worked: open http://127.0.0.1:8000/health  
You should see `"ok": true`.

## Step 5: Install the Chrome extension

**Recommended (public listing):**

1. Open the Chrome Web Store listing:  
   **[Thoth: Local Writing Assistant](https://chromewebstore.google.com/detail/begfbbjincimcjcimpfpkoilbhjphppn)**
2. Click **Add to Chrome**
3. Start the local server first (`Start Thoth.bat` or `start_server.bat`) and confirm http://127.0.0.1:8000/health shows `"ok": true`

**Or load unpacked (developers):**

1. Open Chrome and go to `chrome://extensions`
2. Turn on **Developer mode** (top right)
3. Click **Load unpacked**
4. Select the `extension` folder inside your Thoth folder

You can also download **`thoth-extension-windows-….zip`** from [Releases](https://github.com/Eshan-khan1/Thoth/releases/latest), unzip it, and load that folder.

## Step 6: Try it

1. Type in Gmail, Docs, or any text box
2. Mistakes should get underlines
3. Select text to Rewrite or Generate
4. Click the Thoth icon in Chrome for Settings

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `python` not found | Reinstall Python with **Add to PATH**, then open a new Command Prompt |
| Install fails | Open Command Prompt as Administrator and run `scripts\install.bat` again |
| Port 8000 in use | Close the other app using 8000, or run `start_server.bat` again |
| Ollama errors | Open the Ollama app, then run `scripts\setup_models.bat` |
| No underlines | Install Java, restart the server, reload the extension |
| Extension cannot connect | Confirm http://127.0.0.1:8000/health works, then reload the extension |
| `thoth-grammar` / `thoth-writing` missing | Keep Ollama open and run `scripts\setup_models.bat` |

## Optional: use a cloud API key

In the extension popup, open **Settings**, then **AI & API keys**, choose **API**, paste your key, and click **Connect**.

## Models (Ollama)

`scripts\setup_models.bat` registers:

| Model | Used for |
|-------|----------|
| `thoth-grammar` | Optional deep grammar fixes |
| `thoth-writing` | Rewrite & Generate (local) |
