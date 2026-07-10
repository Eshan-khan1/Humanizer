# Install Humanizer on macOS

## Requirements

| Tool | Install |
|------|---------|
| Chrome | [google.com/chrome](https://www.google.com/chrome/) |
| Python 3.10+ | `brew install python` or [python.org](https://www.python.org/downloads/) |
| Ollama | [ollama.com](https://ollama.com) |
| Java 11+ | `brew install openjdk@17` or [Adoptium](https://adoptium.net/) |

## Steps

```bash
git clone https://github.com/Eshan-khan1/Humanizer.git
cd Humanizer
chmod +x scripts/install.sh start_server.sh "Start Humanizer.command"
./scripts/install.sh
./start_server.sh
```

**Finder shortcut:** double-click `Start Humanizer.command` (first run may ask to allow Terminal).

Then Chrome → `chrome://extensions` → Developer mode → **Load unpacked** → select `extension/`.

Health check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Ollama / Metal issues | `./scripts/fix_ollama.sh` |
| Models missing | Open Ollama app, then `./scripts/setup_models.sh` |
| Port 8000 busy | `start_server.sh` stops the old process automatically |
