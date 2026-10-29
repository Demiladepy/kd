"""End-to-end check of the declined-card branch, over MCP.

Run this, open the printed link, and pay it with Paystack's DECLINED test card:

    4084 0800 0000 5408   CVV 001   any future expiry

Then press Enter. Expected: verify_and_settle returns PAYMENT_FAILED and the
treasury balance is untouched.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from server.chain import ChainClient


def parse(result) -> dict:
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    return {}


async def main() -> int:
    load_dotenv()
    url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")
    token = os.getenv("MCP_BEARER_TOKEN", "")

    chain = ChainClient()
    before = chain.usdc_from_base_units(chain.get_usdc_balance())
    print(f"treasury before : {before} USDC")

    headers = {"Authorization": f"Bearer {token}"}
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            session_token = parse(
                await session.call_tool(
                    "start_session", {"account_code": "KD-001", "pin": "4821"}
                )
            )["data"]["session_token"]

            quoted = parse(
                await session.call_tool(
                    "create_quote",
                    {
                        "session_token": session_token,
                        "supplier_label": "guangzhou-cables",
                        "usd_amount": "5",
                        "invoice_ref": "INV-DECLINED",
                    },
                )
            )
            quote_id = quoted["data"]["quote_id"]
            print("quote           :", quote_id, quoted["code"])

            linked = parse(
                await session.call_tool(
                    "create_naira_payment",
                    {"session_token": session_token, "quote_id": quote_id},
                )
            )
            print("link            :", linked["data"].get("authorization_url"))

            print("\nPay that link with the DECLINED card:")
            print("  card  4084 0800 0000 5408")
            print("  cvv   001")
            print("  exp   any future date")
            input("\npress Enter once Paystack has shown the decline... ")

            settled = parse(
                await session.call_tool(
                    "verify_and_settle",
                    {"session_token": session_token, "quote_id": quote_id},
                )
            )
            print(f"\nverify_and_settle: {settled['code']}  ok={settled['ok']}")
            print(f"  say: {settled['say']}")

    await asyncio.sleep(2)
    after = chain.usdc_from_base_units(chain.get_usdc_balance())
    moved = before - after
    print(f"\ntreasury after  : {after} USDC")
    print(f"treasury moved  : {moved} USDC")

    if settled["code"] != "PAYMENT_FAILED":
        print(f"FAIL: expected PAYMENT_FAILED, got {settled['code']}")
        return 1
    if moved != Decimal(0):
        print("FAIL: money moved for a declined payment")
        return 1
    print("PASS: declined payment produced PAYMENT_FAILED and moved nothing")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
