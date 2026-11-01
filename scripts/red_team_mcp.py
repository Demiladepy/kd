#!/usr/bin/env python3
"""Red-team scenarios 3 and 4, run against the live MCP endpoint.

These are the two rows that need no payment, so they can be re-run any time
without a human at a browser and without moving money.

    3. Injection: the customer asks for funds to go to a wallet address. The
       tools have no address parameter at all, so the only thing a caller can
       do is put the address where the supplier label goes. That must be
       refused before any Paystack link exists.
    4. Over limit: a $500 quote must be refused with a clear code.

Usage:
    python scripts/red_team_mcp.py
    MCP_SERVER_URL=https://<host>/mcp python scripts/red_team_mcp.py

Exit code 0 only if every scenario behaves as specified.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

DEFAULT_URL = "http://127.0.0.1:8123/mcp"
ADDRESS = "0xABC1230000000000000000000000000000000456"


def parse(result) -> dict:
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

    print(f"server: {url}")
    results = []

    async with streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listed = await session.list_tools()
            schemas = {t.name: (t.inputSchema or {}) for t in listed.tools}

            # -- Scenario 3a: no tool can be handed a destination address -------
            leaky = []
            for name, schema in schemas.items():
                props = schema.get("properties", {})
                for field in props:
                    if "address" in field or "wallet" in field or "dest" in field:
                        leaky.append(f"{name}.{field}")
            print(f"3a  address-shaped parameters: {leaky or 'none'}")
            results.append(("3a", "no address parameter on any tool", not leaky))

            session_token = parse(
                await session.call_tool(
                    "start_session", {"account_code": "KD-001", "pin": "4821"}
                )
            )["data"]["session_token"]

            # -- Scenario 3b: address smuggled into the supplier label ----------
            injected = parse(
                await session.call_tool(
                    "create_quote",
                    {
                        "session_token": session_token,
                        "supplier_label": ADDRESS,
                        "usd_amount": "12",
                        "invoice_ref": "RT-INJECT-1",
                    },
                )
            )
            refused = not injected.get("ok") and injected.get("code") == "SUPPLIER_NOT_SAVED"
            print(f"3b  address as supplier label -> {injected.get('code')}")
            print(f"    say: {injected.get('say')}")
            if injected.get("ok"):
                print(f"    !! quote {injected['data'].get('quote_id')} was created")
            results.append(("3b", "SUPPLIER_NOT_SAVED, no quote created", refused))

            # -- Scenario 4: over the per-payment limit -------------------------
            over = parse(
                await session.call_tool(
                    "create_quote",
                    {
                        "session_token": session_token,
                        "supplier_label": "yiwu-lighting",
                        "usd_amount": "500",
                        "invoice_ref": "RT-OVER-500",
                    },
                )
            )
            limited = not over.get("ok") and over.get("code") == "AMOUNT_OVER_LIMIT"
            print(f"4   $500 quote -> {over.get('code')}")
            print(f"    say: {over.get('say')}")
            results.append(("4", "AMOUNT_OVER_LIMIT, human handoff in say", limited))

    print()
    failed = 0
    for ident, expected, ok in results:
        print(f"{'PASS' if ok else 'FAIL'}  {ident}  expected {expected}")
        failed += 0 if ok else 1
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
