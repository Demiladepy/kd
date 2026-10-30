"""Assert that a settlement really happened, end to end.

Given a transaction hash, cross-checks the chain against the database:

  1. the quote exists and is SETTLED with this exact hash
  2. the receipt is mined with status 1
  3. the call went to the USDC contract, not the native balance
  4. the ERC-20 Transfer log pays the *seeded* supplier address
  5. the logged amount equals the quote's USD amount in 6-decimal units
  6. exactly one such transfer exists in the transaction

Usage:
    python scripts/verify_settlement.py 0x<hash>
"""

import json
import os
import sqlite3
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from web3 import Web3

from server.chain import ChainClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRANSFER_TOPIC = "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

results = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    print(f"{'PASS' if passed else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""), flush=True)


def seeded_supplier(account_code: str, label: str) -> str:
    with open(os.path.join(ROOT, "server", "seed.json"), encoding="utf-8") as fh:
        seed = json.load(fh)
    for customer in seed["customers"]:
        if customer["account_code"] != account_code:
            continue
        for supplier in customer["suppliers"]:
            if supplier["label"] == label:
                return supplier["address"]
    return ""


def main() -> int:
    load_dotenv()
    if len(sys.argv) < 2:
        print("usage: python scripts/verify_settlement.py 0x<hash>")
        return 2
    tx_hash = sys.argv[1]

    chain = ChainClient()
    w3 = chain.w3

    db_path = os.getenv("DB_PATH", "./kudidesk.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM quotes WHERE lower(tx_hash) = lower(?)", (tx_hash,)
    ).fetchone()
    conn.close()

    check("quote row found for this tx hash", row is not None)
    if row is None:
        return 1

    quote = dict(row)
    print(f"\n  quote {quote['quote_id']}  {quote['account_code']}  "
          f"{quote['supplier_label']}  ${quote['usd_amount']}  {quote['status']}\n")

    check("quote status is SETTLED", quote["status"] == "SETTLED", quote["status"])

    receipt = w3.eth.get_transaction_receipt(tx_hash)
    tx = w3.eth.get_transaction(tx_hash)

    check("receipt mined with status 1", receipt["status"] == 1, str(receipt["status"]))
    check("sender is the treasury", tx["from"].lower() == chain.account.address.lower(), tx["from"])
    check(
        "call target is the USDC contract",
        tx["to"].lower() == chain.config.usdc_address.lower(),
        tx["to"],
    )
    check("native value is 0 (ERC-20 call)", int(tx["value"]) == 0, str(tx["value"]))

    expected_to = seeded_supplier(quote["account_code"], quote["supplier_label"])
    expected_amount = int(Decimal(quote["usd_amount"]) * Decimal(10**6))

    erc20_transfers = []
    for log in receipt["logs"]:
        topics = [t.hex().removeprefix("0x").lower() for t in log["topics"]]
        if not topics or topics[0] != TRANSFER_TOPIC:
            continue
        if log["address"].lower() != chain.config.usdc_address.lower():
            continue
        erc20_transfers.append(
            {
                "from": Web3.to_checksum_address("0x" + topics[1][-40:]),
                "to": Web3.to_checksum_address("0x" + topics[2][-40:]),
                "value": int(log["data"].hex(), 16),
            }
        )

    check("exactly one ERC-20 USDC transfer in the tx", len(erc20_transfers) == 1,
          f"found {len(erc20_transfers)}")

    if erc20_transfers:
        move = erc20_transfers[0]
        check(
            "transfer pays the seeded supplier address",
            move["to"].lower() == expected_to.lower(),
            f"{move['to']} vs seed {expected_to}",
        )
        check(
            "transfer amount equals the quoted USD",
            move["value"] == expected_amount,
            f"{Decimal(move['value']) / Decimal(10**6)} USDC vs ${quote['usd_amount']}",
        )
        check(
            "transfer comes from the treasury",
            move["from"].lower() == chain.account.address.lower(),
            move["from"],
        )

    gas = Decimal(int(receipt["gasUsed"]) * int(receipt.get("effectiveGasPrice", 0))) / Decimal(
        10**18
    )
    print(f"\n  gas paid: {gas} USDC   block {receipt['blockNumber']}")
    print(f"  explorer: {chain.explorer_url(tx_hash)}")

    failed = [name for name, ok, _ in results if not ok]
    print()
    if failed:
        print(f"FAIL: {len(failed)} check(s) failed: {failed}")
        return 1
    print(f"PASS: all {len(results)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
