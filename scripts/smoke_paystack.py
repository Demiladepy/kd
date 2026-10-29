#!/usr/bin/env python3
import os
import sys
import asyncio
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.paystack import PaystackClient


async def test_initialize():
    load_dotenv()
    client = PaystackClient()
    
    # Test initialize
    try:
        result = await client.initialize(
            reference="TEST-123",
            amount_kobo=10000,  # ₦100
            email="test@example.com",
            callback_url="http://localhost:8000/paid",
            metadata={"test": True}
        )
        print("Initialize result:", result)
        if result.get("status"):
            print("Auth URL:", result["data"]["authorization_url"])
        return result
    except Exception as e:
        print(f"Error: {e}")
        return None


async def test_verify():
    load_dotenv()
    client = PaystackClient()
    # This would need a real reference from a paid transaction
    pass


if __name__ == "__main__":
    asyncio.run(test_initialize())
