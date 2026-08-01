"""Chrome Native Messaging host for Humanizer.

Protocol: 4-byte little-endian length + UTF-8 JSON, one request → one reply.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _read_message() -> dict | None:
    raw_len = sys.stdin.buffer.read(4)
    if not raw_len or len(raw_len) < 4:
        return None
    (length,) = struct.unpack("<I", raw_len)
    if length <= 0 or length > 1_000_000:
        return None
    data = sys.stdin.buffer.read(length)
    if len(data) < length:
        return None
    return json.loads(data.decode("utf-8"))


def _write_message(payload: dict) -> None:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def main() -> int:
    from macos.menubar import extension_bridge, manager

    message = _read_message() or {}
    msg_type = str(message.get("type") or "connect").strip().lower()

    if msg_type in ("ping", "hello"):
        extension_bridge.record_extension_ping({"via": "native"})
        _write_message({"ok": True, "app": "Humanizer", "type": "pong"})
        return 0

    if msg_type == "status":
        snap = manager.check_health()
        link = extension_bridge.extension_link_status()
        _write_message(
            {
                "ok": True,
                "server_ok": snap.server_ok,
                "detail": snap.detail,
                "extension_linked": link.get("linked"),
            }
        )
        return 0

    if msg_type == "restart":
        try:
            root = manager.resolve_project_root()
            ok = manager.restart_server(root)
            snap = manager.check_health()
            extension_bridge.record_extension_ping({"via": "native", "type": "restart"})
            _write_message(
                {
                    "ok": ok and snap.server_ok,
                    "detail": "Server online" if (ok and snap.server_ok) else "Restart failed",
                    "server_ok": snap.server_ok,
                }
            )
            return 0 if (ok and snap.server_ok) else 1
        except Exception as exc:  # noqa: BLE001
            _write_message({"ok": False, "detail": str(exc), "server_ok": False})
            return 1

    # Default: full connect bootstrap (+ optional token when auth is on).
    try:
        info = extension_bridge.connect_info(include_token=True)
    except Exception as exc:  # noqa: BLE001
        info = {
            "ok": True,
            "app": "Humanizer",
            "base_url": f"http://127.0.0.1:{manager.DEFAULT_PORT}",
            "auth_required": False,
            "warning": str(exc),
        }
    extension_bridge.record_extension_ping({"via": "native", "type": msg_type})
    _write_message(info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
