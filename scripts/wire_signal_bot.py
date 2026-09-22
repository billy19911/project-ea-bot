#!/usr/bin/env python3
"""Point the EA trading service's signal reports at the XynnSignal bot.

Reads XynnSignal's token from the Hermes profile env and writes it into the
trading project's gitignored .env.runtime as TELEGRAM_SIGNAL_BOT_TOKEN.
The token value is NEVER printed.

Idempotent: re-running replaces the value rather than appending a duplicate.
"""
import os
import re
import shutil
import sys
import time

HOME = os.path.expanduser("~")
SIGNAL_ENV = os.path.join(
    HOME, "AppData", "Local", "hermes", "profiles", "xynnsignal", ".env"
)
RUNTIME = r"C:\xampp\htdocs\project-ea-bot\.env.runtime"


def read_key(path, key):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    return ""


def fp(tok):
    return f"{tok[:6]}...{tok[-4:]} (len={len(tok)})" if tok else "<empty>"


# --- 1. Read the XynnSignal token + chat id --------------------------------
sig_token = read_key(SIGNAL_ENV, "TELEGRAM_BOT_TOKEN")
sig_chat = read_key(SIGNAL_ENV, "TELEGRAM_HOME_CHANNEL") or read_key(
    SIGNAL_ENV, "TELEGRAM_ALLOWED_USERS"
)

if not sig_token:
    print("ABORT: no TELEGRAM_BOT_TOKEN in xynnsignal profile env")
    sys.exit(1)
if not sig_chat:
    print("ABORT: no chat id in xynnsignal profile env")
    sys.exit(1)

print(f"source  : {SIGNAL_ENV}")
print(f"token   : {fp(sig_token)}")
print(f"chat_id : {sig_chat}")

# --- 2. Back up .env.runtime ----------------------------------------------
stamp = time.strftime("%Y%m%d-%H%M%S")
backup = f"{RUNTIME}.bak-{stamp}"
shutil.copy2(RUNTIME, backup)
print(f"backup  : {backup}")

# --- 3. Rewrite the two keys (uncomment + set), preserving everything else --
with open(RUNTIME, "r", encoding="utf-8", errors="replace") as fh:
    lines = fh.readlines()

out = []
seen_tok = seen_chat = False
for line in lines:
    s = line.strip()
    if re.match(r"^#?\s*TELEGRAM_SIGNAL_BOT_TOKEN\s*=", s):
        out.append(f"TELEGRAM_SIGNAL_BOT_TOKEN={sig_token}\n")
        seen_tok = True
    elif re.match(r"^#?\s*TELEGRAM_SIGNAL_CHAT_IDS\s*=", s):
        out.append(f"TELEGRAM_SIGNAL_CHAT_IDS={sig_chat}\n")
        seen_chat = True
    else:
        out.append(line)

if not seen_tok:
    out.append(f"\nTELEGRAM_SIGNAL_BOT_TOKEN={sig_token}\n")
if not seen_chat:
    out.append(f"TELEGRAM_SIGNAL_CHAT_IDS={sig_chat}\n")

with open(RUNTIME, "w", encoding="utf-8", newline="") as fh:
    fh.writelines(out)

# --- 4. Verify (value redacted in output) ----------------------------------
tok_back = read_key(RUNTIME, "TELEGRAM_SIGNAL_BOT_TOKEN")
chat_back = read_key(RUNTIME, "TELEGRAM_SIGNAL_CHAT_IDS")
print(
    f"verify token : {'MATCH' if tok_back == sig_token else 'MISMATCH'}  {fp(tok_back)}"
)
print(f"verify chat  : {'MATCH' if chat_back == sig_chat else 'MISMATCH'}  {chat_back}")

# Confirm no duplicate keys
with open(RUNTIME, "r", encoding="utf-8", errors="replace") as fh:
    body = fh.read()
print(
    f"token key occurrences : {len(re.findall(r'^TELEGRAM_SIGNAL_BOT_TOKEN=', body, re.M))}"
)
print(
    f"chat key occurrences  : {len(re.findall(r'^TELEGRAM_SIGNAL_CHAT_IDS=', body, re.M))}"
)
print("DONE")
