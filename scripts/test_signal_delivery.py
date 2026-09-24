"""Live end-to-end test: trading notifier -> XynnSignal bot.

Sends ONE clearly-labelled test alert through the REAL notifier code path
(TelegramGateway.notify -> transport.send_message) and reports the outcome.
Proves the trading alert route actually delivers to XynnSignal
(master prompt rule: CONNECTED requires an actual Telegram API test).

Never prints tokens.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "services" / "python" / "src"
sys.path.insert(0, str(SRC.parent))

# Load the same env the service uses (start-all.ps1 does this).
from dotenv import load_dotenv  # noqa: E402

for candidate in (ROOT / ".env.runtime", ROOT / ".env"):
    if candidate.exists():
        load_dotenv(candidate, override=False)

import src.telegram.notifier as N  # noqa: E402


def fp(tok: str) -> str:
    return f"{tok[:6]}...{tok[-4:]}" if tok else "<none>"


def main() -> int:
    print("=== SIGNAL GATEWAY RESOLUTION ===")
    gateway = N.get_signal_gateway()
    if gateway is None:
        print("signal gateway: None  -> trading alerts would fall back to Xynn")
        return 1
    print("signal gateway: present (XynnSignal)")

    transport = getattr(gateway, "transport", None)
    token = getattr(transport, "_token", None) or getattr(transport, "token", None)
    print(f"token fingerprint: {fp(token)}")
    print(f"allowlist (targets): {sorted(gateway.allowlist)}")

    if not gateway.allowlist:
        print("no allowlist targets -> cannot send")
        return 1

    print("\n=== LIVE SEND TEST (real notify() path) ===")
    payload = {
        "note": "Automated routing verification, NOT a trading signal.",
        "source": "scripts/test_signal_delivery.py",
    }
    ok = gateway.notify("system_alert", payload)
    print(f"notify() returned: {ok}")
    print("STATUS: DELIVERED" if ok else "STATUS: FAILED")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
