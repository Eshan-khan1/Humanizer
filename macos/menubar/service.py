"""CLI for Humanizer server control (no GUI). Used by the native Mac app."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from macos.menubar import autostart, extension_bridge, manager, settings  # noqa: E402


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
            "[start|stop|restart|status|autostart|connect-extension|"
            "models|set-models <grammar> <writing>|"
            "get-ai|set-ai <provider> [api_key] [base_url] [model]]",
            file=sys.stderr,
        )
        return 2

    cmd = args[0]
    root = bootstrap_root()

    if cmd == "connect-extension":
        try:
            # Refresh Home first so bundled extension/ lands under Application Support.
            resources = Path(os.environ.get("HUMANIZER_BUNDLE_RESOURCES", "")).expanduser()
            if resources.is_dir():
                root = manager.ensure_home_payload(resources)
            result = extension_bridge.prepare_extension_connection(root)
            print(json.dumps(result))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": str(exc)}))
            return 1

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
                    **settings.ai_status_summary(),
                    # Include key only for the local Mac app Settings UI.
                    "ai_api_key": cfg.get("ai_api_key") or "",
                    **settings.features_summary(),
                }
            )
        )
        return 0

    if cmd == "get-ai":
        cfg = settings.load_settings()
        print(
            json.dumps(
                {
                    "ok": True,
                    **settings.ai_status_summary(),
                    "ai_api_key": cfg.get("ai_api_key") or "",
                    **settings.features_summary(),
                }
            )
        )
        return 0

    if cmd == "set-features":
        if len(args) < 2:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": 'usage: set-features \'{"grammar":true,"rewrite":true,"generate":true}\'',
                    }
                )
            )
            return 2
        try:
            payload = json.loads(args[1])
        except json.JSONDecodeError as exc:
            print(json.dumps({"ok": False, "error": f"invalid JSON: {exc}"}))
            return 2
        if not isinstance(payload, dict):
            print(json.dumps({"ok": False, "error": "set-features payload must be an object"}))
            return 2

        def _flag(key: str) -> bool | None:
            for name in (key, f"feature_{key}"):
                if name in payload:
                    return bool(payload[name])
            return None

        settings.save_settings(
            feature_grammar=_flag("grammar"),
            feature_rewrite=_flag("rewrite"),
            feature_generate=_flag("generate"),
        )
        print(json.dumps({"ok": True, "detail": "Features saved", **settings.features_summary()}))
        return 0

    if cmd == "set-ai":
        if len(args) < 2:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": 'usage: set-ai \'{"provider":"api","apiKey":"..."}\'',
                    }
                )
            )
            return 2
        provider = "local"
        api_key = None
        base_url = None
        model = None
        raw_arg = args[1].strip()
        if raw_arg.startswith("{"):
            try:
                payload = json.loads(raw_arg)
            except json.JSONDecodeError as exc:
                print(json.dumps({"ok": False, "error": f"invalid JSON: {exc}"}))
                return 2
            if not isinstance(payload, dict):
                print(json.dumps({"ok": False, "error": "set-ai payload must be an object"}))
                return 2
            provider = str(payload.get("provider") or payload.get("ai_provider") or "local")
            if "apiKey" in payload or "ai_api_key" in payload:
                api_key = str(payload.get("apiKey") or payload.get("ai_api_key") or "")
            if "baseUrl" in payload or "ai_base_url" in payload:
                base_url = str(payload.get("baseUrl") or payload.get("ai_base_url") or "")
            if "model" in payload or "ai_model" in payload:
                model = str(payload.get("model") or payload.get("ai_model") or "")
        else:
            provider = args[1]
            api_key = args[2] if len(args) > 2 else None
            base_url = args[3] if len(args) > 3 else None
            model = args[4] if len(args) > 4 else None
        cfg = settings.save_settings(
            ai_provider=provider,
            ai_api_key=api_key,
            ai_base_url=base_url,
            ai_model=model,
        )
        test: dict = {"ok": True, "detail": "Using local models"}
        if settings.cloud_ai_config() is not None:
            try:
                import urllib.request

                payload = json.dumps(
                    {
                        "ai": {
                            "provider": cfg.get("ai_provider"),
                            "apiKey": cfg.get("ai_api_key") or "",
                            "baseUrl": cfg.get("ai_base_url") or "",
                            "model": cfg.get("ai_model") or "",
                        }
                    }
                ).encode("utf-8")
                req = urllib.request.Request(
                    "http://127.0.0.1:8000/ai/test",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=25) as resp:
                    test = json.loads(resp.read().decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                test = {"ok": False, "detail": str(exc)}
        print(
            json.dumps(
                {
                    "ok": bool(test.get("ok", True)),
                    "detail": test.get("detail")
                    or (
                        "API key saved"
                        if settings.cloud_ai_config()
                        else "Using local models"
                    ),
                    "provider": test.get("provider") or cfg.get("ai_provider"),
                    "model": test.get("model") or cfg.get("ai_model") or "",
                    **settings.ai_status_summary(),
                }
            )
        )
        return 0 if test.get("ok", True) else 1

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
        link = extension_bridge.extension_link_status()
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
                    "extension_linked": link.get("linked"),
                    "extension_path": str(extension_bridge.extension_install_dir()),
                    **settings.ai_status_summary(),
                    **settings.features_summary(),
                }
            )
        )
        return 0 if snap.server_ok else 1

    if cmd == "stop":
        manager.stop_server()
        print(json.dumps({"ok": True, "detail": "Server offline"}))
        return 0

    if cmd == "start":
        try:
            extension_bridge.sync_chrome_extension(root)
            extension_bridge.register_native_messaging_host()
        except Exception:  # noqa: BLE001
            pass
        manager.ensure_ollama_running()
        ok = manager.start_server(root)
        cfg = settings.load_settings()
        link = extension_bridge.extension_link_status()
        print(
            json.dumps(
                {
                    "ok": ok,
                    "detail": "Server online" if ok else "Server offline",
                    "root": str(root),
                    "grammar_model": cfg.get("grammar_model"),
                    "writing_model": cfg.get("writing_model"),
                    "extension_linked": link.get("linked"),
                    "extension_path": str(extension_bridge.extension_install_dir()),
                    **settings.ai_status_summary(),
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
                    **settings.ai_status_summary(),
                }
            )
        )
        return 0 if ok else 1

    print(json.dumps({"ok": False, "error": f"unknown command: {cmd}"}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
