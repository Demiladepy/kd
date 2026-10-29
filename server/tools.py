import json
import os
import time
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from .store import Store
from .paystack import PaystackClient
from .chain import ChainClient, is_valid_address


class KudiDeskTools:
    def __init__(self):
        self.store = Store(os.getenv("DB_PATH", "./kudidesk.db"))
        try:
            self.paystack = PaystackClient()
        except Exception as e:
            self.paystack = None
        try:
            self.chain = ChainClient()
        except Exception as e:
            self.chain = None
        self._quote_locks = {}

    def _explorer(self, tx_hash: str) -> str:
        if self.chain is not None and hasattr(self.chain, "explorer_url"):
            return self.chain.explorer_url(tx_hash)
        base = os.getenv("EXPLORER_TX_URL", "")
        if base:
            return f"{base.rstrip('/')}/{tx_hash}"
        return tx_hash

    def _treasury_check(self, amount_usdc: Decimal, buffer_usdc: Decimal, gas_limit=None):
        """Delegate to the chain adapter so gas policy lives in one place."""
        if self.chain is None:
            return {"ok": True, "skipped": "no chain configured"}
        try:
            return self.chain.check_treasury(amount_usdc, buffer_usdc, gas_limit)
        except Exception as exc:  # node hiccup must not fake a pass
            return {"ok": False, "reason": "BALANCE_UNAVAILABLE", "error": str(exc)}
    
    def _log_call(self, tool: str, code: str, latency_ms: float, args: Dict = None):
        log_entry = {
            "tool": tool,
            "code": code,
            "latency_ms": round(latency_ms, 2)
        }
        print(json.dumps(log_entry))
    
    def _make_response(self, ok: bool, code: str, data: Dict = None, say: str = "") -> Dict[str, Any]:
        return {
            "ok": ok,
            "code": code,
            "data": data or {},
            "say": say
        }
    
    async def start_session(self, account_code: str, pin: str) -> Dict[str, Any]:
        start = time.time()
        try:
            if not account_code or not pin:
                resp = self._make_response(False, "WRONG_PIN", {}, 
                                         "Please provide account code and PIN.")
                self._log_call("start_session", "WRONG_PIN", (time.time() - start) * 1000)
                return resp
            
            success, code = self.store.verify_pin(account_code, pin)
            if not success:
                if code == "ACCOUNT_LOCKED":
                    resp = self._make_response(False, "ACCOUNT_LOCKED", {}, 
                                             "Account locked due to too many failed attempts. A human will help you.")
                elif code == "WRONG_PIN":
                    resp = self._make_response(False, "WRONG_PIN", {}, 
                                             "Incorrect PIN. Please try again.")
                else:
                    resp = self._make_response(False, code, {}, "Authentication failed.")
                self._log_call("start_session", code, (time.time() - start) * 1000)
                return resp
            
            customer = self.store.get_customer_by_account(account_code)
            if not customer:
                resp = self._make_response(False, "CUSTOMER_NOT_FOUND", {}, 
                                         "Customer not found.")
                self._log_call("start_session", "CUSTOMER_NOT_FOUND", (time.time() - start) * 1000)
                return resp
            
            session_token = self.store.create_session(customer["account_code"])
            data = {
                "session_token": session_token,
                "account_code": customer["account_code"],
                "name": customer["name"],
                "business": customer["business"],
                "max_usd_per_payment": customer["max_usd_per_payment"],
                "suppliers": customer["suppliers"]
            }
            resp = self._make_response(True, "OK", data, 
                                     f"Welcome {customer['name']}. Session started.")
            self._log_call("start_session", "OK", (time.time() - start) * 1000)
            return resp
        except Exception as e:
            resp = self._make_response(False, "ERROR", {"error": str(e)}, 
                                     "Something went wrong starting session.")
            self._log_call("start_session", "ERROR", (time.time() - start) * 1000)
            return resp
    
    async def create_quote(self, session_token: str, supplier_label: str, usd_amount: str, invoice_ref: str) -> Dict[str, Any]:
        start = time.time()
        try:
            session = self.store.validate_session(session_token)
            if not session:
                resp = self._make_response(False, "SESSION_INVALID", {}, 
                                         "Session expired. Please provide account code and PIN again.")
                self._log_call("create_quote", "SESSION_INVALID", (time.time() - start) * 1000)
                return resp
            
            account_code = session["account_code"]
            
            # Check for existing quote
            existing = self.store.find_existing_quote(account_code, supplier_label, invoice_ref, usd_amount)
            if existing:
                config = self.store.get_desk_config()
                customer = self.store.get_customer_by_account(account_code)
                supplier_name = None
                for s in customer.get("suppliers_full", []):
                    if s["label"] == supplier_label:
                        supplier_name = s["display"]
                        break
                resp = self._make_response(True, "OK", {
                    "quote_id": existing["quote_id"],
                    "usd": existing["usd_amount"],
                    "rate": existing["rate"],
                    "fee": existing["fee_pct"],
                    "ngn_total": existing["ngn_total"],
                    "expires_at": existing["expires_at"],
                    "supplier_display": supplier_name
                }, "Here's your existing quote.")
                self._log_call("create_quote", "OK", (time.time() - start) * 1000)
                return resp
            
            # Validation
            customer = self.store.get_customer_by_account(account_code)
            if not customer:
                resp = self._make_response(False, "CUSTOMER_NOT_FOUND", {}, 
                                         "Customer not found.")
                self._log_call("create_quote", "CUSTOMER_NOT_FOUND", (time.time() - start) * 1000)
                return resp
            
            # Check supplier is saved for this customer AND payable
            supplier_found = False
            supplier_display = None
            supplier_address = None
            for s in customer.get("suppliers_full", []):
                if s["label"] == supplier_label:
                    supplier_found = True
                    supplier_display = s["display"]
                    supplier_address = s.get("address")
                    break

            if not supplier_found:
                resp = self._make_response(False, "SUPPLIER_NOT_SAVED", {}, 
                                         "That supplier isn't on file for this customer. I need to escalate this to a human - I can't add new suppliers or accept wallet addresses in chat.")
                self._log_call("create_quote", "SUPPLIER_NOT_SAVED", (time.time() - start) * 1000)
                return resp

            # Refuse to quote for an address we cannot actually pay, otherwise the
            # customer pays and the payout fails afterwards.
            if not is_valid_address(supplier_address or ""):
                resp = self._make_response(
                    False,
                    "SUPPLIER_NOT_SAVED",
                    {"reason": "SUPPLIER_ADDRESS_NOT_CONFIGURED"},
                    "That supplier's payout details aren't set up properly yet, so I "
                    "can't take payment for this one. A human will sort it out and come "
                    "back to you.",
                )
                self._log_call("create_quote", "SUPPLIER_NOT_SAVED", (time.time() - start) * 1000)
                return resp
            
            # Validate amount
            try:
                usd = Decimal(usd_amount)
                if usd <= 0:
                    raise ValueError
                # Check decimal places
                if usd.as_tuple().exponent < -2:
                    raise ValueError
            except:
                resp = self._make_response(False, "INVALID_AMOUNT", {}, 
                                         "Amount must be a positive number with at most 2 decimal places.")
                self._log_call("create_quote", "INVALID_AMOUNT", (time.time() - start) * 1000)
                return resp
            
            config = self.store.get_desk_config()
            min_usd = Decimal(str(config["min_usd"]))
            max_usd = Decimal(str(customer["max_usd_per_payment"]))
            
            if usd < min_usd:
                resp = self._make_response(False, "AMOUNT_BELOW_MIN", {"min_usd": config["min_usd"]}, 
                                         f"Amount is below the minimum of ${min_usd}.")
                self._log_call("create_quote", "AMOUNT_BELOW_MIN", (time.time() - start) * 1000)
                return resp
            
            if usd > max_usd:
                resp = self._make_response(False, "AMOUNT_OVER_LIMIT", {"max_usd": customer["max_usd_per_payment"]}, 
                                         f"Amount exceeds your limit of ${max_usd}.")
                self._log_call("create_quote", "AMOUNT_OVER_LIMIT", (time.time() - start) * 1000)
                return resp
            
            # Check treasury: amount + gas ceiling + buffer, all in USDC on Arc
            if self.chain:
                config = self.store.get_desk_config()
                buffer_usdc = Decimal(str(config["treasury_min_buffer_usdc"]))
                check = self._treasury_check(usd, buffer_usdc)
                if not check.get("ok"):
                    resp = self._make_response(False, "TREASURY_LOW", {
                        "reason": check.get("reason"),
                        "required_usdc": check.get("required_usdc"),
                    }, "Treasury is low right now. I need to escalate to a human for assistance.")
                    self._log_call("create_quote", "TREASURY_LOW", (time.time() - start) * 1000)
                    return resp
            
            quote = self.store.create_quote(account_code, supplier_label, usd_amount, invoice_ref)
            quote["supplier_display"] = supplier_display
            
            resp = self._make_response(True, "OK", quote, 
                                     f"Quote created: ${quote['usd']} = ₦{quote['ngn_total']}, expires in 10 minutes.")
            self._log_call("create_quote", "OK", (time.time() - start) * 1000)
            return resp
        except Exception as e:
            resp = self._make_response(False, "ERROR", {"error": str(e)}, 
                                     "Something went wrong creating the quote.")
            self._log_call("create_quote", "ERROR", (time.time() - start) * 1000)
            return resp
    
    async def create_naira_payment(self, session_token: str, quote_id: str) -> Dict[str, Any]:
        start = time.time()
        try:
            session = self.store.validate_session(session_token)
            if not session:
                resp = self._make_response(False, "SESSION_INVALID", {}, 
                                         "Session expired. Please provide account code and PIN again.")
                self._log_call("create_naira_payment", "SESSION_INVALID", (time.time() - start) * 1000)
                return resp
            
            quote = self.store.get_quote(quote_id)
            if not quote:
                resp = self._make_response(False, "QUOTE_NOT_FOUND", {}, 
                                         "Quote not found.")
                self._log_call("create_naira_payment", "QUOTE_NOT_FOUND", (time.time() - start) * 1000)
                return resp
            
            if quote["account_code"] != session["account_code"]:
                resp = self._make_response(False, "QUOTE_NOT_FOUND", {}, 
                                         "Quote not found.")
                self._log_call("create_naira_payment", "QUOTE_NOT_FOUND", (time.time() - start) * 1000)
                return resp
            
            expires_at = datetime.fromisoformat(quote["expires_at"].replace('Z', '+00:00'))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if now > expires_at and quote["status"] == "QUOTED":
                resp = self._make_response(False, "QUOTE_EXPIRED", {}, 
                                         "This quote has expired. I'll need to create a new quote.")
                self._log_call("create_naira_payment", "QUOTE_EXPIRED", (time.time() - start) * 1000)
                return resp
            
            if quote["status"] == "LINK_CREATED" and quote.get("authorization_url"):
                resp = self._make_response(True, "LINK_EXISTS", {
                    "quote_id": quote_id,
                    "authorization_url": quote["authorization_url"]
                }, "Here's the payment link again.")
                self._log_call("create_naira_payment", "LINK_EXISTS", (time.time() - start) * 1000)
                return resp
            
            if not self.paystack:
                resp = self._make_response(False, "PAYMENT_PROVIDER_DOWN", {}, 
                                         "Payment provider is down. Please try again.")
                self._log_call("create_naira_payment", "PAYMENT_PROVIDER_DOWN", (time.time() - start) * 1000)
                return resp
            
            public_base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
            callback_url = public_base_url + "/paid"
            # Paystack rejects the .test TLD outright ("email" must be a valid
            # email), so PLAN.md section 4.3's literal form cannot be used.
            # example.com is RFC 2606-reserved, syntactically valid, and never
            # deliverable - which is exactly what a generated receipt address wants.
            email = f"{quote['account_code'].lower()}@customers.example.com"
            metadata = {
                "quote_id": quote_id,
                "invoice_ref": quote["invoice_ref"],
                "supplier_label": quote["supplier_label"]
            }
            
            try:
                result = await self.paystack.initialize(
                    reference=quote_id,
                    amount_kobo=quote["kobo"],
                    email=email,
                    callback_url=callback_url,
                    metadata=metadata
                )
                if result.get("status") is False:
                    resp = self._make_response(False, "PAYMENT_LINK_FAILED", 
                                             {"message": result.get("message")}, 
                                             "Failed to create payment link.")
                    self._log_call("create_naira_payment", "PAYMENT_LINK_FAILED", (time.time() - start) * 1000)
                    return resp
                
                auth_url = result["data"]["authorization_url"]
                self.store.update_quote_status(quote_id, "LINK_CREATED", 
                                             authorization_url=auth_url,
                                             paystack_reference=quote_id)
                
                resp = self._make_response(True, "OK", {
                    "quote_id": quote_id,
                    "authorization_url": auth_url,
                    "amount_kobo": quote["kobo"]
                }, "Here's the payment link. Please pay it and let me know when done.")
                self._log_call("create_naira_payment", "OK", (time.time() - start) * 1000)
                return resp
            except TimeoutError:
                resp = self._make_response(False, "PAYMENT_PROVIDER_DOWN", {}, 
                                         "Payment provider timed out. Please try again.")
                self._log_call("create_naira_payment", "PAYMENT_PROVIDER_DOWN", (time.time() - start) * 1000)
                return resp
            except Exception as e:
                resp = self._make_response(False, "PAYMENT_PROVIDER_DOWN", {"error": str(e)}, 
                                         "Payment provider is having issues. Please try again.")
                self._log_call("create_naira_payment", "PAYMENT_PROVIDER_DOWN", (time.time() - start) * 1000)
                return resp
        except Exception as e:
            resp = self._make_response(False, "ERROR", {"error": str(e)}, 
                                     "Something went wrong creating the payment link.")
            self._log_call("create_naira_payment", "ERROR", (time.time() - start) * 1000)
            return resp
    
    async def verify_and_settle(self, session_token: str, quote_id: str) -> Dict[str, Any]:
        start = time.time()
        try:
            session = self.store.validate_session(session_token)
            if not session:
                resp = self._make_response(False, "SESSION_INVALID", {}, 
                                         "Session expired. Please provide account code and PIN again.")
                self._log_call("verify_and_settle", "SESSION_INVALID", (time.time() - start) * 1000)
                return resp
            
            quote = self.store.get_quote(quote_id)
            if not quote:
                resp = self._make_response(False, "QUOTE_NOT_FOUND", {}, 
                                         "Quote not found.")
                self._log_call("verify_and_settle", "QUOTE_NOT_FOUND", (time.time() - start) * 1000)
                return resp
            
            if quote["account_code"] != session["account_code"]:
                resp = self._make_response(False, "QUOTE_NOT_FOUND", {}, 
                                         "Quote not found.")
                self._log_call("verify_and_settle", "QUOTE_NOT_FOUND", (time.time() - start) * 1000)
                return resp
            
            if quote["status"] == "SETTLED" and quote.get("tx_hash"):
                resp = self._make_response(True, "ALREADY_SETTLED", {
                    "quote_id": quote_id,
                    "tx_hash": quote["tx_hash"],
                    "explorer_url": self._explorer(quote['tx_hash'])
                }, "This payment has already been settled.")
                self._log_call("verify_and_settle", "ALREADY_SETTLED", (time.time() - start) * 1000)
                return resp
            
            if quote["status"] == "SETTLING" and quote.get("tx_hash"):
                if self.chain:
                    receipt = await self.chain.get_transaction_receipt(quote["tx_hash"])
                    if receipt:
                        if receipt["status"] == 1:
                            self.store.update_quote_status(quote_id, "SETTLED")
                            resp = self._make_response(True, "SETTLED", {
                                "quote_id": quote_id,
                                "tx_hash": quote["tx_hash"],
                                "explorer_url": self._explorer(quote['tx_hash'])
                            }, "Payment has been settled on-chain.")
                            self._log_call("verify_and_settle", "SETTLED", (time.time() - start) * 1000)
                            return resp
                        elif receipt["status"] == 0:
                            self.store.update_quote_status(quote_id, "SETTLE_FAILED")
                            resp = self._make_response(False, "SETTLE_FAILED", {
                                "quote_id": quote_id,
                                "tx_hash": quote["tx_hash"]
                            }, "Settlement failed on-chain. I need to escalate to a human.")
                            self._log_call("verify_and_settle", "SETTLE_FAILED", (time.time() - start) * 1000)
                            return resp
                    else:
                        resp = self._make_response(True, "SETTLEMENT_PENDING", {
                            "quote_id": quote_id,
                            "tx_hash": quote["tx_hash"],
                            "explorer_url": self._explorer(quote['tx_hash'])
                        }, "Settlement is still pending. The funds are on their way.")
                        self._log_call("verify_and_settle", "SETTLEMENT_PENDING", (time.time() - start) * 1000)
                        return resp
                else:
                    resp = self._make_response(True, "SETTLEMENT_PENDING", {
                        "quote_id": quote_id,
                        "tx_hash": quote["tx_hash"],
                        "explorer_url": self._explorer(quote['tx_hash'])
                    }, "Settlement is still pending.")
                    self._log_call("verify_and_settle", "SETTLEMENT_PENDING", (time.time() - start) * 1000)
                    return resp
            
            if not self.paystack:
                resp = self._make_response(False, "PAYMENT_PROVIDER_DOWN", {}, 
                                         "Payment provider is down.")
                self._log_call("verify_and_settle", "PAYMENT_PROVIDER_DOWN", (time.time() - start) * 1000)
                return resp
            
            try:
                verify_result = await self.paystack.verify(quote_id)
                if not verify_result.get("status"):
                    resp = self._make_response(False, "PAYMENT_VERIFY_FAILED", 
                                             {"message": verify_result.get("message")}, 
                                             "Payment verification failed.")
                    self._log_call("verify_and_settle", "PAYMENT_VERIFY_FAILED", (time.time() - start) * 1000)
                    return resp
                
                data = verify_result.get("data", {})
                pay_status = data.get("status")
                
                if pay_status != "success":
                    if pay_status == "failed":
                        resp = self._make_response(False, "PAYMENT_FAILED", {}, 
                                                 "The payment didn't go through. Here's the link again if you'd like to try.")
                        self._log_call("verify_and_settle", "PAYMENT_FAILED", (time.time() - start) * 1000)
                        return resp
                    elif pay_status == "abandoned":
                        resp = self._make_response(False, "PAYMENT_NOT_COMPLETED", {}, 
                                                 "The payment wasn't completed.")
                        self._log_call("verify_and_settle", "PAYMENT_NOT_COMPLETED", (time.time() - start) * 1000)
                        return resp
                    elif pay_status in ["ongoing", "pending"]:
                        resp = self._make_response(True, "PAYMENT_PENDING", {}, 
                                                 "Payment is still processing. Please try again in a moment.")
                        self._log_call("verify_and_settle", "PAYMENT_PENDING", (time.time() - start) * 1000)
                        return resp
                    else:
                        resp = self._make_response(False, "PAYMENT_NOT_COMPLETED", {"status": pay_status}, 
                                                 "Payment wasn't completed successfully.")
                        self._log_call("verify_and_settle", "PAYMENT_NOT_COMPLETED", (time.time() - start) * 1000)
                        return resp
                
                if data.get("amount") != quote["kobo"] or data.get("currency") != "NGN":
                    resp = self._make_response(False, "PAYMENT_MISMATCH", {}, 
                                             "There's a mismatch with the payment. I need to escalate to a human.")
                    self._log_call("verify_and_settle", "PAYMENT_MISMATCH", (time.time() - start) * 1000)
                    return resp
                
                self.store.update_quote_status(quote_id, "PAID")
                quote = self.store.get_quote(quote_id)
                
                if self.chain:
                    config = self.store.get_desk_config()
                    usd_amount = Decimal(quote["usd_amount"])
                    buffer_usdc = Decimal(str(config["treasury_min_buffer_usdc"]))
                    check = self._treasury_check(usd_amount, buffer_usdc)
                    if not check.get("ok"):
                        # Money in, nothing out: stay PAID so a human can settle.
                        resp = self._make_response(
                            False,
                            "TREASURY_LOW",
                            {
                                "quote_id": quote_id,
                                "reason": check.get("reason"),
                                "required_usdc": check.get("required_usdc"),
                            },
                            "I'm really sorry - your payment came through, but our treasury is "
                            "short right now so I can't send it yet. A human will follow up "
                            "shortly and your money is safe with us.",
                        )
                        self._log_call("verify_and_settle", "TREASURY_LOW", (time.time() - start) * 1000)
                        return resp
                
                supplier_address = self.store.get_supplier_address(quote["account_code"], quote["supplier_label"])
                if not supplier_address:
                    resp = self._make_response(False, "ERROR", {}, 
                                             "Could not find supplier details. Escalating to human.")
                    self._log_call("verify_and_settle", "ERROR", (time.time() - start) * 1000)
                    return resp
                
                if not self.chain:
                    resp = self._make_response(False, "ERROR", {}, 
                                             "Chain service not available. Escalating to human.")
                    self._log_call("verify_and_settle", "ERROR", (time.time() - start) * 1000)
                    return resp
                
                try:
                    import asyncio
                    if quote_id not in self._quote_locks:
                        self._quote_locks[quote_id] = asyncio.Lock()
                    
                    async with self._quote_locks[quote_id]:
                        quote_check = self.store.get_quote(quote_id)
                        if quote_check["status"] == "SETTLED":
                            resp = self._make_response(True, "ALREADY_SETTLED", {
                                "quote_id": quote_id,
                                "tx_hash": quote_check.get("tx_hash"),
                                "explorer_url": self._explorer(quote_check.get('tx_hash'))
                            }, "Already settled.")
                            self._log_call("verify_and_settle", "ALREADY_SETTLED", (time.time() - start) * 1000)
                            return resp
                        if quote_check["status"] == "SETTLING" and quote_check.get("tx_hash"):
                            # Check receipt
                            receipt = await self.chain.get_transaction_receipt(quote_check["tx_hash"])
                            if receipt:
                                if receipt["status"] == 1:
                                    self.store.update_quote_status(quote_id, "SETTLED")
                                    resp = self._make_response(True, "SETTLED", {
                                        "quote_id": quote_id,
                                        "tx_hash": quote_check["tx_hash"],
                                        "explorer_url": self._explorer(quote_check['tx_hash'])
                                    }, "Payment has been settled on-chain.")
                                    self._log_call("verify_and_settle", "SETTLED", (time.time() - start) * 1000)
                                    return resp
                                elif receipt["status"] == 0:
                                    self.store.update_quote_status(quote_id, "SETTLE_FAILED")
                                    resp = self._make_response(False, "SETTLE_FAILED", {"quote_id": quote_id}, 
                                                             "Settlement failed. I need to escalate to a human.")
                                    self._log_call("verify_and_settle", "SETTLE_FAILED", (time.time() - start) * 1000)
                                    return resp
                            resp = self._make_response(True, "SETTLEMENT_PENDING", {
                                "quote_id": quote_id,
                                "tx_hash": quote_check["tx_hash"],
                                "explorer_url": self._explorer(quote_check['tx_hash'])
                            }, "Settlement is still pending.")
                            self._log_call("verify_and_settle", "SETTLEMENT_PENDING", (time.time() - start) * 1000)
                            return resp
                        
                        transfer_result = await self.chain.transfer_usdc(supplier_address, quote["usd_amount"])
                        tx_hash = transfer_result["tx_hash"]
                        self.store.update_quote_status(quote_id, "SETTLING", tx_hash=tx_hash)
                        
                        receipt_result = await self.chain.wait_for_receipt(tx_hash, timeout=45)
                        if receipt_result.get("timeout"):
                            resp = self._make_response(True, "SETTLEMENT_PENDING", {
                                "quote_id": quote_id,
                                "tx_hash": tx_hash,
                                "explorer_url": self._explorer(tx_hash)
                            }, "Settlement is on the way. Here's the explorer link.")
                            self._log_call("verify_and_settle", "SETTLEMENT_PENDING", (time.time() - start) * 1000)
                            return resp
                        if receipt_result.get("status") == 1:
                            self.store.update_quote_status(quote_id, "SETTLED")
                            resp = self._make_response(True, "SETTLED", {
                                "quote_id": quote_id,
                                "tx_hash": tx_hash,
                                "explorer_url": self._explorer(tx_hash)
                            }, "Payment settled successfully! Here's the explorer link.")
                            self._log_call("verify_and_settle", "SETTLED", (time.time() - start) * 1000)
                            return resp
                        else:
                            self.store.update_quote_status(quote_id, "SETTLE_FAILED")
                            resp = self._make_response(False, "SETTLE_FAILED", {
                                "quote_id": quote_id,
                                "tx_hash": tx_hash,
                                "explorer_url": self._explorer(tx_hash)
                            }, "Settlement failed. I need to escalate to a human.")
                            self._log_call("verify_and_settle", "SETTLE_FAILED", (time.time() - start) * 1000)
                            return resp
                except Exception as e:
                    resp = self._make_response(False, "SETTLE_FAILED", {"error": str(e)}, 
                                             "Settlement failed. I need to escalate to a human.")
                    self._log_call("verify_and_settle", "SETTLE_FAILED", (time.time() - start) * 1000)
                    return resp
            except Exception as e:
                resp = self._make_response(False, "ERROR", {"error": str(e)}, 
                                         "Error verifying payment.")
                self._log_call("verify_and_settle", "ERROR", (time.time() - start) * 1000)
                return resp
        except Exception as e:
            resp = self._make_response(False, "ERROR", {"error": str(e)}, 
                                     "Something went wrong during settlement.")
            self._log_call("verify_and_settle", "ERROR", (time.time() - start) * 1000)
            return resp
