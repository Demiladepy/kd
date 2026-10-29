#!/usr/bin/env python3
import asyncio
import os
import sys
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def test_mcp_server():
    base_url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")
    token = os.getenv("MCP_BEARER_TOKEN", "change-me-long-random")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    async with streamablehttp_client(base_url, headers=headers) as (read_stream, write_stream, get_session_id):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            
            # List tools
            tools = await session.list_tools()
            print("Tools:", [t.name for t in tools.tools])
            
            # Test lookup customer
            result = await session.call_tool("lookup_customer", {"account_code": "KD-001"})
            print("Lookup:", result.content[0].text if result.content else result)
            
            # Create quote
            quote_result = await session.call_tool("create_quote", {
                "account_code": "KD-001",
                "supplier_label": "yiwu-lighting",
                "usd_amount": "12",
                "invoice_ref": "INV-2207"
            })
            print("Quote:", quote_result.content[0].text if quote_result.content else quote_result)


if __name__ == "__main__":
    asyncio.run(test_mcp_server())
