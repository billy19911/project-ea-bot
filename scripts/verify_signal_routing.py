#!/usr/bin/env python3
"""Verify the EA trading service routes signal reports to XynnSignal (not Xynn).

Loads .env.runtime exactly like start-all.ps1 does, imports the REAL notifier
module, and confirms:
  1. the signal gateway resolves to XynnSignal's token
  2. the report gateway picks the signal bot (not the primary Xynn bot)
  3. a controlled test alert actually delivers, and lands on XynnSignal

Token values are never printed — only fingerprints.
"""
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(r"C:\xampp\htdocs\project-ea-bot")
SRC = ROOT / "services" / "python" / "src"
RUNTIME = ROOT / ".env.runtime"

# --- Load .env.runtime the same way start-all.ps1 does --------------------
env_map = {}
for raw in RUNTIME.read_text(encoding="utf-8", errors="replace").splitlines():
    s = raw.strip()
    if not s or s.startswith("#") or "=" not in s:
        continue
    k, _, v = s.partition("=")
    env_map[k.strip()] = v.strip()

for k in (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_CHAT_IDS",
    "TELEGRAM_SIGNAL_BOT_TOKEN",
    "TELEGRAM_SIGNAL_CHAT_IDS",
    "TELEGRAM_DIGEST_ENABLED",
    "TELEGRAM_DIGEST_WINDOW_S",
    "TELEGRAM_DIGEST_MAX_ITEMS",
):
    if env_map.get(k):
        os.environ[k] = env_map[k]

print("=== ENV LOADED FROM .env.runtime ===")
for k in (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_SIGNAL_BOT_TOKEN",
    "TELEGRAM_ALLOWED_CHAT_IDS",
    "TELEGRAM_SIGNAL_CHAT_IDS",
):
    v = os.environ.get(k, "")
    print(
        f"  {k:32} = {v[:6] + '...' + v[-4:] if len(v) > 12 else ('<set>' if v else '<EMPTY>')}"
    )

sys.path.insert(
    0, str(SRC.parent)
)  # services/python — makes `src` importable as a package
sys.path.insert(0, str(SRC))

# --- Import the real notifier ---------------------------------------------
import src.telegram.notifier as N  # noqa: E402

importlib.reload(N)

print("\n=== GATEWAY RESOLUTION ===")
primary = N.get_gateway()
signal = N.get_signal_gateway()
report = N.get_report_gateway()


def describe(name, gw):
    if gw is None:
        print(f"  {name:18} = None")
        return None
    tr = getattr(gw, "transport", None)
    tok = getattr(tr, "_token", "") if tr is not None else ""
    al = getattr(gw, "allowlist", None) or []
    fp = f"{tok[:6]}...{tok[-4:]}" if len(tok) > 12 else "<none>"
    print(
        f"  {name:18} transport={'YES' if tr else 'NO':3} token={fp:22} allowlist={al}"
    )
    return tok


tok_primary = describe("primary gateway", primary)
tok_signal = describe("signal gateway", signal)
tok_report = describe("REPORT gateway", report)

print("\n=== ASSERTIONS ===")
ok = True


def check(label, cond):
    global ok
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        ok = False


xynn_tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
sig_tok = os.environ.get("TELEGRAM_SIGNAL_BOT_TOKEN", "")

check("primary gateway == Xynn token", tok_primary == xynn_tok and bool(xynn_tok))
check("signal gateway == XynnSignal token", tok_signal == sig_tok and bool(sig_tok))
check("report gateway == XynnSignal (signals NOT on Xynn)", tok_report == sig_tok)
check("report gateway != Xynn", tok_report != xynn_tok)
check("Xynn != XynnSignal tokens", xynn_tok != sig_tok)

# --- Controlled end-to-end test alert --------------------------------------
print("\n=== CONTROLLED TEST ALERT (end-to-end through trading code) ===")
test_summary = {
    "symbol": "XAUUSD",
    "decision": "TEST",
    "reason": "controlled connectivity test from Hermes multi-bot setup",
    "confidence": 0.0,
    "executed": False,
    "cycle": "verification",
}
try:
    sent = N.notify_pipeline_result(test_summary)
    print(f"  notify_pipeline_result returned: {sent}")
    check("test alert dispatched via signal gateway", bool(sent))
except Exception as exc:  # noqa: BLE001
    print(f"  EXCEPTION: {type(exc).__name__}: {exc}")
    ok = False

print("\n=== RESULT:", "ALL PASS" if ok else "SOME FAILED", "===")
sys.exit(0 if ok else 1)
