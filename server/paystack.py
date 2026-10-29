import httpx
import os
from typing import Dict, Any, Optional


class PaystackClient:
    def __init__(self, secret_key: str = None):
        self.secret_key = secret_key or os.getenv("PAYSTACK_SECRET_KEY")
        if not self.secret_key:
            raise ValueError("PAYSTACK_SECRET_KEY not set")
        if self.secret_key.startswith("sk_live_"):
            raise ValueError("Refusing to start with live key")
        if not self.secret_key.startswith("sk_test_"):
            raise ValueError("Must use test key")
        self.base_url = "https://api.paystack.co"
        self.headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json"
        }
    
    async def initialize(self, reference: str, amount_kobo: int, email: str, 
                        callback_url: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/transaction/initialize",
                    headers=self.headers,
                    json={
                        "reference": reference,
                        "amount": amount_kobo,
                        "email": email,
                        "callback_url": callback_url,
                        "metadata": metadata
                    }
                )
                if response.status_code >= 500:
                    # Retry once
                    response = await client.post(
                        f"{self.base_url}/transaction/initialize",
                        headers=self.headers,
                        json={
                            "reference": reference,
                            "amount": amount_kobo,
                            "email": email,
                            "callback_url": callback_url,
                            "metadata": metadata
                        }
                    )
                
                if response.status_code >= 400 and response.status_code < 500:
                    return {
                        "status": False,
                        "message": response.json().get("message", "Request failed"),
                        "data": response.json()
                    }
                
                return response.json()
            except httpx.TimeoutException:
                raise TimeoutError("Paystack timeout")
            except Exception as e:
                raise
    
    async def verify(self, reference: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/transaction/verify/{reference}",
                    headers=self.headers
                )
                if response.status_code >= 500:
                    response = await client.get(
                        f"{self.base_url}/transaction/verify/{reference}",
                        headers=self.headers
                    )
                return response.json()
            except httpx.TimeoutException:
                raise TimeoutError("Paystack timeout")
            except Exception as e:
                raise
