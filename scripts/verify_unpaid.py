"""End-to-end check of the 'customer never paid' branch, over MCP.

Expected: verify_and_settle returns PAYMENT_NOT_COMPLETED and the treasury
balance is untouched.
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
    token = os.getenv("MCP_BEARER_TOKEN")

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
                        "invoice_ref": "INV-ABANDONED",
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
            print("link            :", linked["code"], linked["data"].get("authorization_url"))
            print("  (deliberately never paid)")

            # Same call twice, as a customer would if they tapped "I've paid" twice.
            for attempt in (1, 2):
                settled = parse(
                    await session.call_tool(
                        "verify_and_settle",
                        {"session_token": session_token, "quote_id": quote_id},
                    )
                )
                print(f"verify_and_settle #{attempt}: {settled['code']}  ok={settled['ok']}")
                print(f"  say: {settled['say']}")

    await asyncio.sleep(2)
    after = chain.usdc_from_base_units(chain.get_usdc_balance())
    print(f"\ntreasury after  : {after} USDC")
    moved = before - after
    print(f"treasury moved  : {moved} USDC")

    if moved != Decimal(0):
        print("FAIL: money moved for an unpaid quote")
        return 1
    print("PASS: unpaid quote moved nothing on chain")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
