"""Kill switch: stop all automatic replies immediately, without a deployment (FR-17).

    python -m src.killswitch on  --reason "wrong answers reported"   # every ticket now escalates
    python -m src.killswitch off
    python -m src.killswitch status

Mechanism: the presence of a file (storage/KILL_SWITCH by default). The pipeline checks it for every
ticket, so it takes effect on the next ticket processed - no restart. Tickets already past the routing
step finish on their current path (at most one per worker); every later ticket escalates.
"""
from __future__ import annotations

import argparse
import getpass
import json
from datetime import datetime, timezone

from .config import Settings


def status(settings: Settings) -> dict:
    p = settings.kill_switch_path
    info = {"engaged": p.exists() or not settings.auto_respond_enabled, "file": str(p),
            "env_AUTO_RESPOND_ENABLED": settings.auto_respond_enabled}
    if p.exists():
        try:
            info.update(json.loads(p.read_text(encoding="utf-8") or "{}"))
        except Exception:
            pass
    return info


def engage(settings: Settings, reason: str) -> dict:
    settings.kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        who = getpass.getuser()
    except Exception:
        who = "unknown"
    settings.kill_switch_path.write_text(json.dumps({
        "engaged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "by": who, "reason": reason}), encoding="utf-8")
    return status(settings)


def release(settings: Settings) -> dict:
    if settings.kill_switch_path.exists():
        settings.kill_switch_path.unlink()
    return status(settings)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Switch automatic replies off or on.")
    ap.add_argument("action", choices=["on", "off", "status"], help="on = stop automatic replies")
    ap.add_argument("--reason", default="manual")
    a = ap.parse_args(argv)
    s = Settings()
    res = engage(s, a.reason) if a.action == "on" else release(s) if a.action == "off" else status(s)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
