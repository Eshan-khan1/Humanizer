"""CLI for Humanizer server control (no GUI). Used by the native Mac app."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from macos.menubar import autostart, manager, settings  # noqa: E402


def bootstrap_root() -> Path:
    resources = Path(os.environ.get("HUMANIZER_BUNDLE_RESOURCES", "")).expanduser()
    if resources.is_dir() and (resources / "HumanizerHome" / "server.py").is_file():
        return manager.ensure_home_payload(resources)
    return manager.resolve_project_root()


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(
            "usage: python -m macos.menubar.service "
            "[start|stop|restart|status|autostart|models|set-models <grammar> <writing>]",
            file=sys.stderr,
        )
        return 2

    cmd = args[0]
    root = bootstrap_root()

    if cmd == "autostart":
        try:
            autostart.ensure_login_item()
            print(json.dumps({"ok": True, "autostart": True}))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": str(exc)}))
            return 1

    if cmd == "models":
        manager.ensure_ollama_running()
        cfg = settings.load_settings()
        models = settings.list_ollama_models()
        print(
            json.dumps(
                {
                    "ok": True,
                    "ollama_ok": manager.check_health().ollama_ok or bool(models),
                    "models": models,
                    "grammar_model": cfg.get("grammar_model"),
                    "writing_model": cfg.get("writing_model"),
                    "defaults": {
                        "grammar_model": settings.DEFAULT_GRAMMAR_MODEL,
                        "writing_model": settings.DEFAULT_WRITING_MODEL,
                    },
                }
            )
        )
        return 0

    if cmd == "set-models":
        if len(args) < 3:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "usage: set-models <grammar_model> <writing_model>",
                    }
                )
            )
            return 2
        grammar = args[1]
        writing = args[2]
        cfg = settings.save_settings(grammar_model=grammar, writing_model=writing)
        # Restart so the server picks up new model env.
        ok = manager.restart_server(root)
        print(
            json.dumps(
                {
                    "ok": ok,
                    "grammar_model": cfg.get("grammar_model"),
                    "writing_model": cfg.get("writing_model"),
                    "detail": "Server online" if ok else "Saved, but server is offline",
                    "restarted": True,
                }
            )
        )
        return 0 if ok else 1

    if cmd == "status":
        snap = manager.check_health()
        cfg = settings.load_settings()
        print(
            json.dumps(
                {
                    "ok": snap.server_ok,
                    "server_ok": snap.server_ok,
                    "ollama_ok": snap.ollama_ok,
                    "detail": snap.detail,
                    "root": str(root),
                    "grammar_model": cfg.get("grammar_model"),
                    "writing_model": cfg.get("writing_model"),
                }
            )
        )
        return 0 if snap.server_ok else 1

    if cmd == "stop":
        manager.stop_server()
        print(json.dumps({"ok": True, "detail": "Server offline"}))
        return 0

    if cmd == "start":
        manager.ensure_ollama_running()
        ok = manager.start_server(root)
        cfg = settings.load_settings()
        print(
            json.dumps(
                {
                    "ok": ok,
                    "detail": "Server online" if ok else "Server offline",
                    "root": str(root),
                    "grammar_model": cfg.get("grammar_model"),
                    "writing_model": cfg.get("writing_model"),
                }
            )
        )
        return 0 if ok else 1

    if cmd == "restart":
        ok = manager.restart_server(root)
        cfg = settings.load_settings()
        print(
            json.dumps(
                {
                    "ok": ok,
                    "detail": "Server online" if ok else "Server offline",
                    "grammar_model": cfg.get("grammar_model"),
                    "writing_model": cfg.get("writing_model"),
                }
            )
        )
        return 0 if ok else 1

    print(json.dumps({"ok": False, "error": f"unknown command: {cmd}"}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
