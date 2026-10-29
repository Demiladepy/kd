#!/usr/bin/env python3
"""Phase 2 smoke test: initialise a Paystack link, then verify it.

The human pays the printed link with a test card, then this script verifies.
Run it three times to cover the three cases:

    1. success card   -> status success
    2. declined card  -> status failed
    3. never paid     -> status abandoned

Usage:
    python scripts/smoke_paystack.py            # initialise and print the link
    python scripts/smoke_paystack.py --verify   # verify the last reference
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from server.paystack import PaystackClient

REF_FILE = ".paystack_smoke_ref"


async def do_initialize() -> None:
    client = PaystackClient()
    reference = f"smoke-{int(time.time())}"
    result = await client.initialize(
        reference=reference,
        amount_kobo=5000,  # NGN 50 — Paystack's minimum
        email="smoke@customers.example.com",
        callback_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000") + "/paid",
        metadata={"smoke": True},
    )
    print(json.dumps(result, indent=2))
    if not result.get("status"):
        print("\nFAIL: initialize returned status=false")
        return
    data = result["data"]
    with open(REF_FILE, "w") as f:
        f.write(data["reference"])
    print(f"\nreference: {data['reference']}")
    print(f"pay here : {data['authorization_url']}")
    print("\nSuccess card : 4084 0840 8408 4081  CVV 408")
    print("Declined card: 4084 0800 0000 5408  CVV 001")
    print("\nthen run: python scripts/smoke_paystack.py --verify")


async def do_verify() -> None:
    if not os.path.exists(REF_FILE):
        print("no reference saved — run without --verify first")
        return
    reference = open(REF_FILE).read().strip()
    client = PaystackClient()
    result = await client.verify(reference)
    print(json.dumps(result, indent=2))
    status = (result.get("data") or {}).get("status")
    expected = os.getenv("EXPECT_STATUS")
    print(f"\nreference: {reference}")
    print(f"status   : {status}")
    if expected:
        print("PASS" if status == expected else f"FAIL expected {expected}")
    else:
        print("set EXPECT_STATUS=success|failed|abandoned to assert")


if __name__ == "__main__":
    load_dotenv()
    asyncio.run(do_verify() if "--verify" in sys.argv else do_initialize())
