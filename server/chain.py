"""Chain access for USDC settlement.

The chain is **configuration, not code** (PLAN.md §2): `ChainConfig` reads
CHAIN_NAME / CHAIN_ID / RPC_URL / USDC_ADDRESS / EXPLORER_TX_URL /
GAS_TOKEN_IS_USDC from the environment, so switching Arc -> Monad is an env
change only.

Units — the part that bites:
  * ERC-20 USDC always has 6 decimals. Balances and transfers use base units.
  * The **native** balance on Arc is USDC denominated with **18 decimals**
    (measured on 2026-10-29: native/1e18 == erc20/1e6 for the same address).
    So gas costs are 18-decimal quantities of the same asset. Never add the
    two raw integers together.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

from web3 import Web3
from web3.exceptions import TimeExhausted

USDC_DECIMALS = 6
NATIVE_DECIMALS = 18

# One lock for the whole process: nonces are per-account, so two coroutines
# allocating a nonce at the same time would collide.
_TREASURY_NONCE_LOCK: Optional[asyncio.Lock] = None


def _nonce_lock() -> asyncio.Lock:
    global _TREASURY_NONCE_LOCK
    if _TREASURY_NONCE_LOCK is None:
        _TREASURY_NONCE_LOCK = asyncio.Lock()
    return _TREASURY_NONCE_LOCK


class ChainConfigError(ValueError):
    """Raised when chain configuration is missing or inconsistent."""


def is_valid_address(value: str) -> bool:
    """True only for a real 20-byte EVM address. seed.json ships placeholders
    like '0xSUPPLIER_WALLET_1' until the human fills in test wallets."""
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        return Web3.is_address(value.strip())
    except Exception:
        return False


@dataclass(frozen=True)
class ChainConfig:
    name: str
    chain_id: int
    rpc_url: str
    usdc_address: str
    explorer_tx_url: str
    gas_token_is_usdc: bool

    @classmethod
    def from_env(cls, env: Optional[Dict[str, str]] = None) -> "ChainConfig":
        env = env if env is not None else os.environ

        def need(key: str) -> str:
            value = (env.get(key) or "").strip()
            if not value:
                raise ChainConfigError(f"{key} is not set")
            return value

        raw_chain_id = need("CHAIN_ID")
        try:
            chain_id = int(raw_chain_id)
        except ValueError as exc:
            raise ChainConfigError(f"CHAIN_ID must be an integer, got {raw_chain_id!r}") from exc

        usdc = need("USDC_ADDRESS")
        if not Web3.is_address(usdc):
            raise ChainConfigError(f"USDC_ADDRESS is not a valid address: {usdc}")

        return cls(
            name=(env.get("CHAIN_NAME") or "unnamed").strip(),
            chain_id=chain_id,
            rpc_url=need("RPC_URL"),
            usdc_address=Web3.to_checksum_address(usdc),
            explorer_tx_url=need("EXPLORER_TX_URL"),
            gas_token_is_usdc=(env.get("GAS_TOKEN_IS_USDC") or "false").strip().lower()
            in {"1", "true", "yes"},
        )

    @property
    def explorer_base(self) -> str:
        return self.explorer_tx_url if self.explorer_tx_url.endswith("/") else self.explorer_tx_url + "/"


ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
]


class ChainClient:
    """USDC balance / transfer / receipt access. Never touches a wallet address
    supplied by an agent — callers resolve those from seed.json."""

    def __init__(
        self,
        config: Optional[ChainConfig] = None,
        private_key: Optional[str] = None,
        w3: Optional[Web3] = None,
    ):
        self.config = config or ChainConfig.from_env()
        self.private_key = private_key or os.getenv("TREASURY_PRIVATE_KEY")
        if not self.private_key:
            raise ChainConfigError("TREASURY_PRIVATE_KEY is not set")
        if not self.private_key.startswith("0x"):
            self.private_key = "0x" + self.private_key

        self.w3 = w3 or Web3(Web3.HTTPProvider(self.config.rpc_url, request_kwargs={"timeout": 20}))
        self.account = self.w3.eth.account.from_key(self.private_key)
        self.usdc = self.w3.eth.contract(address=self.config.usdc_address, abi=ERC20_ABI)

    # --- identity ---------------------------------------------------------

    def rpc_chain_id(self) -> int:
        return int(self.w3.eth.chain_id)

    def assert_chain_id(self) -> int:
        """Fail loudly if CHAIN_ID and the RPC disagree."""
        actual = self.rpc_chain_id()
        if actual != self.config.chain_id:
            raise ChainConfigError(
                f"CHAIN_ID={self.config.chain_id} but {self.config.rpc_url} reports {actual}"
            )
        return actual

    def explorer_url(self, tx_hash: str) -> str:
        h = tx_hash if tx_hash.startswith("0x") else "0x" + tx_hash
        return self.config.explorer_base + h

    # --- balances ---------------------------------------------------------

    def get_usdc_balance(self, address: Optional[str] = None) -> int:
        """ERC-20 USDC in base units (6 decimals)."""
        addr = Web3.to_checksum_address(address or self.account.address)
        return int(self.usdc.functions.balanceOf(addr).call())

    def get_native_balance(self, address: Optional[str] = None) -> int:
        """Raw native balance in wei-equivalent (18 decimals). On Arc this is
        USDC; on a gas-token chain it is the gas token."""
        addr = Web3.to_checksum_address(address or self.account.address)
        return int(self.w3.eth.get_balance(addr))

    def usdc_from_base_units(self, base_units: int) -> Decimal:
        return Decimal(base_units) / Decimal(10**USDC_DECIMALS)

    def native_to_usdc(self, wei: int) -> Decimal:
        """Convert a native amount to whole USDC.

        Only meaningful when the native token *is* USDC (Arc). When gas is a
        different token there is no price feed here, so we do not pretend.
        """
        if not self.config.gas_token_is_usdc:
            raise ChainConfigError("native balance is not USDC on this chain")
        return Decimal(wei) / Decimal(10**NATIVE_DECIMALS)

    # --- fees -------------------------------------------------------------

    def suggested_fees(self) -> Dict[str, int]:
        """EIP-1559 fees from eth_feeHistory, with eth_gasPrice as a floor."""
        base_fee = 0
        try:
            history = self.w3.eth.fee_history(5, "latest", [])
            base_fees = history.get("baseFeePerGas") or []
            if base_fees:
                base_fee = int(base_fees[-1])
        except Exception:
            base_fee = 0

        gas_price = int(self.w3.eth.gas_price)
        if base_fee <= 0:
            return {"max_fee_per_gas": gas_price, "max_priority_fee_per_gas": gas_price // 10}

        priority = max(gas_price - base_fee, 10**9)  # >= 1 gwei tip
        return {
            "max_fee_per_gas": base_fee * 2 + priority,
            "max_priority_fee_per_gas": priority,
            "base_fee_per_gas": base_fee,
        }

    DEFAULT_GAS_LIMIT = 90_000

    def estimate_gas_limit(self, to_address: str, amount_base_units: int) -> int:
        """Estimate gas, falling back to a generous constant.

        eth_estimateGas reverts when the treasury cannot cover the transfer
        ("ERC20: transfer amount exceeds balance"), and a node hiccup should not
        crash a read-only balance check. The fallback is a ceiling: unused gas
        is refunded, so being generous only costs a larger *allowance*.
        """
        to_addr = Web3.to_checksum_address(to_address)
        try:
            estimate = self.usdc.functions.transfer(to_addr, int(amount_base_units)).estimate_gas(
                {"from": self.account.address}
            )
            # 25% headroom: the fee is a ceiling, unused gas is refunded.
            return int(estimate * 125 // 100)
        except Exception:
            return self.DEFAULT_GAS_LIMIT

    def estimate_fee_wei(self, gas_limit: Optional[int] = None) -> int:
        fees = self.suggested_fees()
        limit = gas_limit if gas_limit is not None else self.DEFAULT_GAS_LIMIT
        return int(limit) * int(fees["max_fee_per_gas"])

    def estimate_fee_usdc(self, gas_limit: Optional[int] = None) -> Decimal:
        """Gas cost expressed in USDC. Only valid when USDC is the gas token."""
        if not self.config.gas_token_is_usdc:
            return Decimal(0)
        return self.native_to_usdc(self.estimate_fee_wei(gas_limit))

    # --- treasury policy --------------------------------------------------

    def check_treasury(
        self,
        amount_usdc: Decimal,
        buffer_usdc: Decimal,
        gas_limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Balance must cover the transfer + a gas ceiling + the buffer.

        On Arc everything is USDC, so one balance covers both. On a chain where
        gas is a different token we additionally require a native balance for
        the fee, instead of silently assuming it is covered.
        """
        usdc_balance = self.usdc_from_base_units(self.get_usdc_balance())
        gas_usdc = self.estimate_fee_usdc(gas_limit)
        required = Decimal(amount_usdc) + Decimal(buffer_usdc) + gas_usdc

        snapshot: Dict[str, Any] = {
            "chain": self.config.name,
            "usdc_balance": str(usdc_balance),
            "gas_usdc": str(gas_usdc),
            "buffer_usdc": str(buffer_usdc),
            "required_usdc": str(required),
            "gas_token_is_usdc": self.config.gas_token_is_usdc,
        }

        if not self.config.gas_token_is_usdc:
            native = self.get_native_balance()
            fee_wei = self.estimate_fee_wei(gas_limit)
            snapshot["native_balance_wei"] = str(native)
            snapshot["fee_wei"] = str(fee_wei)
            if native < fee_wei:
                snapshot["ok"] = False
                snapshot["reason"] = "NATIVE_GAS_LOW"
                return snapshot

        snapshot["ok"] = usdc_balance >= required
        if not snapshot["ok"]:
            snapshot["reason"] = "USDC_LOW"
        return snapshot

    # --- transfer ---------------------------------------------------------

    async def transfer_usdc(self, to_address: str, amount_usdc: str) -> Dict[str, Any]:
        """Sign and send a USDC transfer. Returns the tx hash immediately."""
        to_addr = Web3.to_checksum_address(to_address)
        amount_base_units = int(Decimal(str(amount_usdc)) * Decimal(10**USDC_DECIMALS))

        async with _nonce_lock():
            # Pending nonce: another in-flight tx must not reuse this slot.
            nonce = self.w3.eth.get_transaction_count(self.account.address, "pending")
            gas_limit = self.estimate_gas_limit(to_addr, amount_base_units)
            fees = self.suggested_fees()

            tx = self.usdc.functions.transfer(to_addr, amount_base_units).build_transaction(
                {
                    "chainId": self.config.chain_id,
                    "from": self.account.address,
                    "gas": gas_limit,
                    "maxFeePerGas": int(fees["max_fee_per_gas"]),
                    "maxPriorityFeePerGas": int(fees["max_priority_fee_per_gas"]),
                    "nonce": nonce,
                    "value": 0,
                }
            )
            signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
            raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
            tx_hash = self.w3.eth.send_raw_transaction(raw)
            tx_hash_hex = tx_hash.hex()
            if not tx_hash_hex.startswith("0x"):
                tx_hash_hex = "0x" + tx_hash_hex

            return {
                "tx_hash": tx_hash_hex,
                "nonce": nonce,
                "gas_limit": gas_limit,
                "max_fee_per_gas": int(fees["max_fee_per_gas"]),
            }

    async def wait_for_receipt(self, tx_hash: str, timeout: int = 45) -> Dict[str, Any]:
        try:
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
            return self._receipt_summary(receipt)
        except TimeExhausted:
            return {"status": None, "timeout": True}

    async def get_transaction_receipt(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        try:
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)
        except Exception:
            return None
        return self._receipt_summary(receipt)

    def _receipt_summary(self, receipt: Any) -> Dict[str, Any]:
        gas_used = int(receipt.get("gasUsed", 0) or 0)
        effective = int(receipt.get("effectiveGasPrice", 0) or 0)
        gas_wei = gas_used * effective
        summary: Dict[str, Any] = {
            "status": int(receipt["status"]),
            "block_number": int(receipt["blockNumber"]),
            "transaction_hash": receipt["transactionHash"].hex(),
            "gas_used": gas_used,
            "effective_gas_price": effective,
            "gas_paid_wei": gas_wei,
        }
        if self.config.gas_token_is_usdc:
            summary["gas_paid_usdc"] = str(self.native_to_usdc(gas_wei))
        return summary
