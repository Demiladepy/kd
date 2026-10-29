#!/usr/bin/env python3
"""Phase 0 gate: prove the treasury can move USDC on the configured testnet.

Prints, in order:
  1. the chain id the RPC reports (must equal CHAIN_ID)
  2. the treasury's ERC-20 USDC balance
  3. the treasury's raw native balance, plus how it is interpreted
  4. the transfer, its receipt, the explorer URL and the gas paid in USDC

Pass = a mined receipt with status 1.
"""

import asyncio
import json
import os
import sys
from decimal import Decimal, ROUND_DOWN

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from server.chain import ChainClient, ChainConfigError, is_valid_address

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEND_USDC = "1"


def configured_supplier(customer: str = "KD-001", label: str = "yiwu-lighting") -> str:
    """The address the server would actually pay for this supplier.

    Read from seed.json so the gate tests the same address settlement uses,
    instead of a copy that can drift.
    """
    override = os.getenv("GATE_SUPPLIER_ADDRESS")
    if override:
        return override
    with open(os.path.join(ROOT, "server", "seed.json"), encoding="utf-8") as fh:
        seed = json.load(fh)
    for cust in seed.get("customers", []):
        if cust.get("account_code") != customer:
            continue
        for sup in cust.get("suppliers", []):
            if sup.get("label") == label:
                return sup.get("address", "")
    return ""


def fail(msg: str) -> None:
    print(f"\nFAIL: {msg}")
    sys.exit(1)


async def main() -> None:
    load_dotenv()

    try:
        chain = ChainClient()
    except ChainConfigError as exc:
        fail(f"chain config: {exc}")

    cfg = chain.config
    print(f"chain name (env)   : {cfg.name}")
    print(f"rpc                : {cfg.rpc_url}")
    print(f"treasury address   : {chain.account.address}")

    # 1. The RPC must agree with CHAIN_ID, or every later fact is suspect.
    try:
        reported = chain.assert_chain_id()
    except ChainConfigError as exc:
        fail(str(exc))
    print(f"chain id (rpc)     : {reported}  (matches CHAIN_ID)")

    # 2/3. Balances. ERC-20 is authoritative for money; native is gas.
    usdc_base = chain.get_usdc_balance()
    usdc = chain.usdc_from_base_units(usdc_base)
    native_wei = chain.get_native_balance()
    print(f"USDC (ERC-20)      : {usdc} USDC   [{usdc_base} base units, 6 dp]")
    print(f"native (raw)       : {native_wei} wei")
    if cfg.gas_token_is_usdc:
        native_usdc = chain.native_to_usdc(native_wei)
        print(f"native interpreted : {native_usdc} USDC   [18 dp — gas token is USDC]")
        # Native carries 18 dp, the ERC-20 holds 6, so a sub-micro-USDC dust
        # remainder is normal. Compare at ERC-20 precision.
        dust = native_usdc - usdc
        if native_usdc.quantize(Decimal("0.000001"), rounding=ROUND_DOWN) != usdc:
            print(f"  NOTE: balances disagree beyond 6 dp by {dust} USDC")
            print("  On Arc they normally match to within 1e-6; a larger gap means a")
            print("  contract-level transfer moved one side but not the other.")
        elif dust:
            print(f"  (native dust below ERC-20 precision: {dust} USDC — expected)")
    else:
        print("native interpreted : gas token (not USDC) — no USD value assumed here")

    fees = chain.suggested_fees()
    fee_usdc = chain.estimate_fee_usdc()
    print(f"max fee per gas    : {fees['max_fee_per_gas']} wei")
    print(f"estimated gas cost : {fee_usdc} USDC")

    if usdc < Decimal(SEND_USDC) + fee_usdc:
        fail(f"treasury needs at least {Decimal(SEND_USDC) + fee_usdc} USDC, has {usdc}")

    # 4. Send 1 USDC to the supplier the server would really pay.
    supplier = configured_supplier()
    if not is_valid_address(supplier):
        fail(
            f"supplier address is not configured (got {supplier!r}). "
            "Fix server/seed.json or set GATE_SUPPLIER_ADDRESS."
        )
    print(f"paying supplier    : {supplier}")
    try:
        sent = await chain.transfer_usdc(supplier, SEND_USDC)
    except Exception as exc:
        fail(f"transfer failed: {type(exc).__name__}: {exc}")

    tx_hash = sent["tx_hash"]
    print(f"\ntx sent            : {tx_hash}")
    print(f"gas limit          : {sent['gas_limit']}")
    print(f"explorer           : {chain.explorer_url(tx_hash)}")

    print("\nwaiting for receipt (up to 120s)...")
    receipt = await chain.wait_for_receipt(tx_hash, timeout=120)

    if receipt.get("timeout"):
        fail("timed out waiting for the receipt (tx may still land — check the explorer)")

    if receipt["status"] != 1:
        fail(f"transaction reverted (status={receipt['status']}) — {chain.explorer_url(tx_hash)}")

    print(f"status             : {receipt['status']} (mined)")
    print(f"block              : {receipt['block_number']}")
    print(f"gas used           : {receipt['gas_used']}")
    if "gas_paid_usdc" in receipt:
        print(f"gas paid           : {receipt['gas_paid_usdc']} USDC")
    else:
        print(f"gas paid           : {receipt['gas_paid_wei']} wei (native gas token)")

    after = chain.usdc_from_base_units(chain.get_usdc_balance())
    print(f"USDC after         : {after}")
    print("\nPASS: mined transaction with status 1")


if __name__ == "__main__":
    asyncio.run(main())
