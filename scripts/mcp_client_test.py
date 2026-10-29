#!/usr/bin/env python3
"""Phase 4 acceptance: drive the server with the official MCP Python client.

Usage:
    python scripts/mcp_client_test.py                     # localhost
    MCP_SERVER_URL=https://<render>/mcp MCP_BEARER_TOKEN=... python scripts/mcp_client_test.py

Runs: list tools -> start_session -> create_quote, then offers to continue to
the payment link. Settlement needs a real Paystack payment, so it is prompted.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

DEFAULT_URL = "http://127.0.0.1:8000/mcp"
EXPECTED_TOOLS = {"start_session", "create_quote", "create_naira_payment", "verify_and_settle"}


def parse(result) -> dict:
    """MCP results carry text content; our tools return a JSON object."""
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}
    return {}


async def main() -> int:
    load_dotenv()
    url = os.getenv("MCP_SERVER_URL", DEFAULT_URL)
    token = os.getenv("MCP_BEARER_TOKEN", "")
    if not token:
        print("MCP_BEARER_TOKEN is not set")
        return 1

    headers = {"Authorization": f"Bearer {token}"}
    print(f"server: {url}")

    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listed = await session.list_tools()
            names = {t.name for t in listed.tools}
            print(f"tools: {sorted(names)}")
            missing = EXPECTED_TOOLS - names
            extra = names - EXPECTED_TOOLS
            if missing:
                print(f"FAIL missing tools: {sorted(missing)}")
                return 1
            if extra:
                print(f"WARN unexpected extra tools: {sorted(extra)}")

            # 1. Auth
            account = os.getenv("TEST_ACCOUNT_CODE", "KD-001")
            pin = os.getenv("TEST_PIN", "4821")
            started = parse(await session.call_tool("start_session", {"account_code": account, "pin": pin}))
            print(f"start_session: {started.get('code')}")
            if not started.get("ok"):
                print(json.dumps(started, indent=2))
                return 1
            token_value = started["data"]["session_token"]
            print(f"  customer: {started['data']['name']} ({started['data']['business']})")
            for supplier in started["data"]["suppliers"]:
                print(f"  supplier: {supplier['label']} -> {supplier['address_masked']}")
                assert "0x" not in supplier["address_masked"].split("…")[0] or len(
                    supplier["address_masked"]
                ) < 20, "full address leaked"

            # 2. Quote
            quoted = parse(
                await session.call_tool(
                    "create_quote",
                    {
                        "session_token": token_value,
                        "supplier_label": os.getenv("TEST_SUPPLIER", "yiwu-lighting"),
                        "usd_amount": os.getenv("TEST_USD", "12"),
                        "invoice_ref": os.getenv("TEST_INVOICE", "INV-2207"),
                    },
                )
            )
            print(f"create_quote: {quoted.get('code')}")
            if not quoted.get("ok"):
                print(json.dumps(quoted, indent=2))
                return 1
            quote_id = quoted["data"]["quote_id"]
            print(f"  {quoted['data']['quote_id']}  {quoted['data']['usd']} USD -> NGN {quoted['data']['ngn_total']}")

            if os.getenv("SKIP_LINK") == "1":
                print("\nPASS (stopped before the payment link)")
                return 0

            # 3. Payment link
            linked = parse(
                await session.call_tool(
                    "create_naira_payment", {"session_token": token_value, "quote_id": quote_id}
                )
            )
            print(f"create_naira_payment: {linked.get('code')}")
            print(f"  pay here: {linked.get('data', {}).get('authorization_url')}")

            if os.getenv("SKIP_SETTLE") == "1":
                print("\nPASS (stopped before settlement)")
                return 0

            input("\nPay that link with the test card, then press Enter to settle... ")

            settled = parse(
                await session.call_tool(
                    "verify_and_settle", {"session_token": token_value, "quote_id": quote_id}
                )
            )
            print(f"verify_and_settle: {settled.get('code')}")
            print(f"  {settled.get('say')}")
            if settled.get("data", {}).get("explorer_url"):
                print(f"  explorer: {settled['data']['explorer_url']}")

            # 4. Idempotency: a second call must not send again.
            again = parse(
                await session.call_tool(
                    "verify_and_settle", {"session_token": token_value, "quote_id": quote_id}
                )
            )
            print(f"verify_and_settle (2nd): {again.get('code')}")
            if again.get("code") not in {"SETTLED", "ALREADY_SETTLED", "SETTLEMENT_PENDING"}:
                print("FAIL second call did not return an idempotent code")
                return 1

            print("\nPASS")
            return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
