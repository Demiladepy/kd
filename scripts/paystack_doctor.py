#!/usr/bin/env python3
"""Paystack key doctor.

Tells you which of the five usual walls you are against, instead of guessing:

  1. no key in .env
  2. wrong kind of key (public key, live key, truncated, quotes/spaces)
  3. key rejected by the API (401) — bad key, wrong environment, or IP allowlist
  4. key valid but the account cannot initialise transactions
  5. all good and ready for Phase 2

Usage:
    python scripts/paystack_doctor.py            # check auth only
    python scripts/paystack_doctor.py --init     # also create a real NGN 50 test link
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from dotenv import load_dotenv

# Windows consoles default to cp1252 and raise on characters like arrows.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "https://api.paystack.co"
DASHBOARD_KEYS = "https://dashboard.paystack.com/v2/developers"
DASHBOARD_SIGNUP = "https://dashboard.paystack.com/#/signup"

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def ok(msg):
    print(f"{GREEN}PASS{RESET}  {msg}")


def bad(msg):
    print(f"{RED}FAIL{RESET}  {msg}")


def warn(msg):
    print(f"{YELLOW}WARN{RESET}  {msg}")


def hint(msg):
    print(f"{DIM}      {msg}{RESET}")


def check_shape(key: str) -> bool:
    """Catch the problems that never reach the network."""
    if not key:
        bad("PAYSTACK_SECRET_KEY is not set")
        hint("cp .env.example .env, then paste the secret key into it")
        hint(f"Get keys at {DASHBOARD_KEYS} (sign up free: {DASHBOARD_SIGNUP})")
        return False

    if key != key.strip():
        warn("the key has leading/trailing whitespace — stripping it for you")
        key = key.strip()

    if key.startswith(("'", '"')) or key.endswith(("'", '"')):
        bad("the key is wrapped in quote characters")
        hint('in .env write:  PAYSTACK_SECRET_KEY=sk_test_xxxx   (no quotes)')
        return False

    if key.startswith("pk_"):
        bad("that is a PUBLIC key (pk_), not a secret key")
        hint("public keys can only start a checkout in the browser; the server needs sk_")
        hint(f"Copy the SECRET key from {DASHBOARD_KEYS}")
        return False

    if key.startswith("sk_live_"):
        bad("that is a LIVE key — this project refuses to boot with one")
        hint("toggle your dashboard out of live mode and copy the sk_test_ key")
        return False

    if not key.startswith("sk_test_"):
        bad(f"unrecognised key prefix: {key[:8]!r}")
        hint("test secret keys are exactly: sk_test_ followed by the key body")
        return False

    if len(key) < 20:
        bad(f"key looks truncated (len={len(key)})")
        hint("re-copy the whole key; a partial paste is the most common cause")
        return False

    ok(f"shape looks right ({key[:8]}…{key[-4:]}, len={len(key)})")
    return True


def check_auth(key: str) -> bool:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(f"{BASE}/balance", headers=headers)
    except httpx.TimeoutException:
        bad("timed out reaching api.paystack.co")
        hint("check your network / VPN; Paystack must be reachable over HTTPS")
        return False
    except httpx.HTTPError as exc:
        bad(f"network error: {type(exc).__name__}: {exc}")
        return False

    if r.status_code == 200:
        body = r.json()
        if body.get("status"):
            ok("API accepted the key (GET /balance → 200)")
            for entry in body.get("data", []) or []:
                print(f"      balance: {entry.get('currency')} {entry.get('balance')}")
            return True
        warn(f"200 but status=false: {body.get('message')}")
        return False

    if r.status_code == 401:
        bad("401 Unauthorized — the key was rejected")
        hint("most likely one of:")
        hint("  • the key was rotated since you copied it (rotate → copy again)")
        hint("  • you copied the key from live mode but it begins sk_test_ by mistake")
        hint("  • IP allowlisting is ON for this environment and your IP is not listed")
        hint(f"  • check both at {DASHBOARD_KEYS}")
        return False

    if r.status_code == 403:
        bad("403 Forbidden")
        hint(f"the key probably lacks permission, or IP allowlisting blocked it: {DASHBOARD_KEYS}")
        return False

    if r.status_code == 404:
        warn("404 on /balance — key may be valid but this endpoint is unavailable")
        hint("continuing; try --init to test the real money path")
        return True

    bad(f"unexpected HTTP {r.status_code}: {r.text[:200]}")
    return False


def check_initialize(key: str) -> bool:
    """Create a real NGN 50 test link. No money moves in test mode."""
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "reference": "kudidesk-doctor",
        "amount": 5000,  # kobo — NGN 50 is Paystack's minimum
        "email": "doctor@customers.example.com",
        "callback_url": "http://localhost:8000/paid",
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(f"{BASE}/transaction/initialize", headers=headers, json=payload)
    except httpx.HTTPError as exc:
        bad(f"initialize failed at the network layer: {type(exc).__name__}: {exc}")
        return False

    body = {}
    try:
        body = r.json()
    except Exception:
        pass

    if r.status_code == 200 and body.get("status"):
        ok("POST /transaction/initialize worked")
        print(f"      checkout URL: {body['data']['authorization_url']}")
        print(f"      reference   : {body['data']['reference']}")
        hint("open that URL and pay with test card 4084 0840 8408 4081, CVV 408, any future expiry")
        return True

    if r.status_code == 400 and "duplicate" in str(body.get("message", "")).lower():
        warn("that reference already exists — that is fine, it means auth works")
        hint("the server reuses quote ids as references, so duplicates are expected")
        return True

    bad(f"initialize failed: HTTP {r.status_code} — {body.get('message', r.text[:200])}")
    if r.status_code == 401:
        hint("401 here with 200 on /balance usually means IP allowlisting is on for writes")
    return False


def main() -> int:
    load_dotenv()
    key = os.getenv("PAYSTACK_SECRET_KEY", "")
    want_init = "--init" in sys.argv

    print("Paystack key doctor\n" + "-" * 60)
    if not check_shape(key):
        return 1
    if not check_auth(key.strip()):
        return 1
    if want_init and not check_initialize(key.strip()):
        return 1

    print("-" * 60)
    print(f"{GREEN}Ready for Phase 2.{RESET}")
    if not want_init:
        hint("run with --init to create a real test checkout link")
    return 0


if __name__ == "__main__":
    sys.exit(main())
