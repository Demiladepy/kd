"""Fakes for the Paystack and chain interfaces.

Unit tests never touch the network. These fakes record every call so the
tests can assert exactly-once behaviour.
"""


class FakePaystack:
    def __init__(self, status="success", amount_kobo=None, currency="NGN", fail_initialize=False):
        self.status = status
        self.amount_kobo = amount_kobo
        self.currency = currency
        self.fail_initialize = fail_initialize
        self.initialize_calls = []
        self.verify_calls = []

    async def initialize(self, reference, amount_kobo, email, callback_url, metadata):
        self.initialize_calls.append(
            {
                "reference": reference,
                "amount_kobo": amount_kobo,
                "email": email,
                "callback_url": callback_url,
                "metadata": metadata,
            }
        )
        if self.fail_initialize:
            return {"status": False, "message": "Invalid key"}
        return {
            "status": True,
            "data": {
                "authorization_url": f"https://checkout.paystack.com/{reference}",
                "reference": reference,
            },
        }

    async def verify(self, reference):
        self.verify_calls.append(reference)
        amount = self.amount_kobo
        if amount is None:
            # Mirror a correctly charged quote: let the caller's amount stand in.
            amount = getattr(self, "expected_amount", None)
        return {
            "status": True,
            "data": {
                "status": self.status,
                "amount": amount,
                "currency": self.currency,
                "reference": reference,
            },
        }


class FakeChain:
    def __init__(self, balance_usdc="20", receipt_status=1, receipt_mined=True):
        self.balance_usdc = balance_usdc
        self.receipt_status = receipt_status
        self.receipt_mined = receipt_mined
        self.transfers = []
        self._tx_counter = 0

    def get_usdc_balance(self, address=None):
        from decimal import Decimal

        return int(Decimal(self.balance_usdc) * Decimal(10**6))

    async def transfer_usdc(self, to_address, amount_usdc):
        self._tx_counter += 1
        tx_hash = f"0x{self._tx_counter:064x}"
        self.transfers.append({"to": to_address, "amount": amount_usdc, "tx_hash": tx_hash})
        return {"tx_hash": tx_hash}

    async def wait_for_receipt(self, tx_hash, timeout=45):
        if not self.receipt_mined:
            return {"status": None, "timeout": True}
        return {"status": self.receipt_status, "block_number": 1}

    async def get_transaction_receipt(self, tx_hash):
        if not self.receipt_mined:
            return None
        return {"status": self.receipt_status, "block_number": 1}
