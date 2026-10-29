"""Tool-level tests: guardrails, state machine, idempotency.

Covers every bullet in PLAN.md Phase 1 plus the session/ownership additions.
"""

import sqlite3

import pytest

from tests.conftest import make_tools
from tests.fakes import FakeChain, FakePaystack

PIN_1 = "4821"
PIN_2 = "7392"


async def auth(tools, account_code="KD-001", pin=PIN_1):
    resp = await tools.start_session(account_code, pin)
    assert resp["ok"] is True, resp
    return resp["data"]["session_token"]


async def quote(tools, token, usd="10", supplier="yiwu-lighting", invoice="INV-1"):
    return await tools.create_quote(token, supplier, usd, invoice)


def quote_id_of(resp):
    assert resp["ok"] is True, resp
    return resp["data"]["quote_id"]


def set_status(db_path, quote_id, status, **fields):
    conn = sqlite3.connect(db_path)
    sets = ", ".join(["status = ?"] + [f"{k} = ?" for k in fields])
    params = [status] + list(fields.values()) + [quote_id]
    conn.execute(f"UPDATE quotes SET {sets} WHERE quote_id = ?", params)
    conn.commit()
    conn.close()


# --- start_session ---------------------------------------------------------


async def test_start_session_returns_masked_suppliers(tools):
    token = await auth(tools)
    resp = await tools.start_session("KD-001", PIN_1)
    data = resp["data"]
    assert data["session_token"] != token
    for supplier in data["suppliers"]:
        assert set(supplier) == {"label", "display", "address_masked"}
        assert "SUPPLIER_WALLET" not in supplier["address_masked"]


async def test_wrong_pin_returns_wrong_pin(tools):
    resp = await tools.start_session("KD-001", "0000")
    assert resp["ok"] is False
    assert resp["code"] == "WRONG_PIN"


async def test_unknown_account_matches_wrong_pin(tools):
    unknown = await tools.start_session("KD-999", "0000")
    wrong = await tools.start_session("KD-001", "0000")
    assert unknown["code"] == wrong["code"] == "WRONG_PIN"


async def test_three_wrong_pins_lock_account(tools):
    for _ in range(3):
        await tools.start_session("KD-001", "0000")
    resp = await tools.start_session("KD-001", PIN_1)
    assert resp["ok"] is False
    assert resp["code"] == "ACCOUNT_LOCKED"


# --- session enforcement ---------------------------------------------------


async def test_tools_reject_missing_session(tools):
    resp = await tools.create_quote("", "yiwu-lighting", "10", "INV-1")
    assert resp["code"] == "SESSION_INVALID"


async def test_tools_reject_unknown_session(tools):
    resp = await tools.create_quote("deadbeef", "yiwu-lighting", "10", "INV-1")
    assert resp["code"] == "SESSION_INVALID"


async def test_expired_session_rejected(tools, db_path):
    token = await auth(tools)
    from datetime import datetime, timedelta, timezone

    past = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE sessions SET expires_at = ? WHERE session_token = ?", (past, token))
    conn.commit()
    conn.close()
    resp = await tools.create_quote(token, "yiwu-lighting", "10", "INV-1")
    assert resp["code"] == "SESSION_INVALID"


async def test_session_without_quote_cannot_settle(tools):
    token = await auth(tools)
    resp = await tools.verify_and_settle(token, "Q-doesnotexist")
    assert resp["code"] == "QUOTE_NOT_FOUND"


# --- create_quote guardrails ----------------------------------------------


async def test_unsaved_supplier_rejected(tools):
    token = await auth(tools)
    resp = await quote(tools, token, supplier="new-supplier")
    assert resp["ok"] is False
    assert resp["code"] == "SUPPLIER_NOT_SAVED"
    assert "human" in resp["say"].lower()


async def test_supplier_from_another_customer_rejected(tools):
    token = await auth(tools, "KD-002", PIN_2)
    # shaoxing-fabrics belongs to KD-002; yiwu-lighting belongs to KD-001.
    resp = await quote(tools, token, supplier="yiwu-lighting")
    assert resp["code"] == "SUPPLIER_NOT_SAVED"


async def test_over_limit_rejected(tools):
    token = await auth(tools)
    resp = await quote(tools, token, usd="60")  # KD-001 cap is 50
    assert resp["ok"] is False
    assert resp["code"] == "AMOUNT_OVER_LIMIT"


async def test_below_minimum_rejected(tools):
    token = await auth(tools)
    resp = await quote(tools, token, usd="3")  # min is 5
    assert resp["ok"] is False
    assert resp["code"] == "AMOUNT_BELOW_MIN"


@pytest.mark.parametrize("bad", ["0", "-5", "abc", "10.001"])
async def test_invalid_amounts_rejected(tools, bad):
    token = await auth(tools)
    resp = await quote(tools, token, usd=bad)
    assert resp["ok"] is False
    assert resp["code"] == "INVALID_AMOUNT"


async def test_quote_is_idempotent(tools):
    token = await auth(tools)
    first = quote_id_of(await quote(tools, token))
    second = quote_id_of(await quote(tools, token))
    assert first == second


async def test_treasury_low_blocks_quote(store, monkeypatch):
    tools = make_tools(store, monkeypatch, fake_paystack=None, fake_chain=FakeChain(balance_usdc="3"))
    token = await auth(tools)
    # 10 + 2 buffer = 12 > 3 available
    resp = await quote(tools, token, usd="10")
    assert resp["code"] == "TREASURY_LOW"


# --- create_naira_payment -------------------------------------------------


async def test_link_created_once_and_reused(store, monkeypatch):
    paystack = FakePaystack()
    tools = make_tools(store, monkeypatch, fake_paystack=paystack, fake_chain=FakeChain())
    token = await auth(tools)
    qid = quote_id_of(await quote(tools, token))

    first = await tools.create_naira_payment(token, qid)
    assert first["ok"] is True
    url = first["data"]["authorization_url"]

    second = await tools.create_naira_payment(token, qid)
    assert second["ok"] is True
    assert second["code"] == "LINK_EXISTS"
    assert second["data"]["authorization_url"] == url
    assert len(paystack.initialize_calls) == 1


async def test_expired_quote_cannot_get_link(store, monkeypatch, db_path):
    paystack = FakePaystack()
    tools = make_tools(store, monkeypatch, fake_paystack=paystack, fake_chain=FakeChain())
    token = await auth(tools)
    qid = quote_id_of(await quote(tools, token))

    from datetime import datetime, timedelta, timezone

    past = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE quotes SET expires_at = ? WHERE quote_id = ?", (past, qid))
    conn.commit()
    conn.close()

    resp = await tools.create_naira_payment(token, qid)
    assert resp["ok"] is False
    assert resp["code"] == "QUOTE_EXPIRED"
    assert paystack.initialize_calls == []


async def test_other_customer_cannot_get_link(store, monkeypatch):
    paystack = FakePaystack()
    tools = make_tools(store, monkeypatch, fake_paystack=paystack, fake_chain=FakeChain())
    token_1 = await auth(tools)
    qid = quote_id_of(await quote(tools, token_1, supplier="yiwu-lighting"))

    token_2 = await auth(tools, "KD-002", PIN_2)
    resp = await tools.create_naira_payment(token_2, qid)
    assert resp["code"] == "QUOTE_NOT_FOUND"
    assert paystack.initialize_calls == []


async def test_provider_down_is_retryable(store, monkeypatch):
    tools = make_tools(store, monkeypatch, fake_paystack=None, fake_chain=FakeChain())
    token = await auth(tools)
    qid = quote_id_of(await quote(tools, token))
    resp = await tools.create_naira_payment(token, qid)
    assert resp["ok"] is False
    assert resp["code"] == "PAYMENT_PROVIDER_DOWN"


# --- verify_and_settle ----------------------------------------------------


async def test_abandoned_payment_sends_nothing(store, monkeypatch):
    chain = FakeChain()
    tools = make_tools(store, monkeypatch, fake_paystack=FakePaystack(status="abandoned"), fake_chain=chain)
    token = await auth(tools)
    qid = quote_id_of(await quote(tools, token))

    resp = await tools.verify_and_settle(token, qid)
    assert resp["ok"] is False
    assert resp["code"] == "PAYMENT_NOT_COMPLETED"
    assert chain.transfers == []


async def test_failed_payment_sends_nothing(store, monkeypatch):
    chain = FakeChain()
    tools = make_tools(store, monkeypatch, fake_paystack=FakePaystack(status="failed"), fake_chain=chain)
    token = await auth(tools)
    qid = quote_id_of(await quote(tools, token))

    resp = await tools.verify_and_settle(token, qid)
    assert resp["code"] == "PAYMENT_FAILED"
    assert chain.transfers == []


async def test_amount_mismatch_escalates_without_sending(store, monkeypatch):
    chain = FakeChain()
    paystack = FakePaystack(amount_kobo=1)
    tools = make_tools(store, monkeypatch, fake_paystack=paystack, fake_chain=chain)
    token = await auth(tools)
    qid = quote_id_of(await quote(tools, token))

    resp = await tools.verify_and_settle(token, qid)
    assert resp["ok"] is False
    assert resp["code"] == "PAYMENT_MISMATCH"
    assert chain.transfers == []


async def test_currency_mismatch_escalates(store, monkeypatch):
    chain = FakeChain()
    tools = make_tools(store, monkeypatch, fake_paystack=FakePaystack(currency="USD"), fake_chain=chain)
    token = await auth(tools)
    qid = quote_id_of(await quote(tools, token))
    resp = await tools.verify_and_settle(token, qid)
    assert resp["code"] == "PAYMENT_MISMATCH"
    assert chain.transfers == []


async def _paid_tools(store, monkeypatch, chain=None, status="success"):
    """Tools plus a quote whose Paystack amount matches the stored kobo."""
    chain = chain or FakeChain()
    paystack = FakePaystack(status=status)
    tools = make_tools(store, monkeypatch, fake_paystack=paystack, fake_chain=chain)
    token = await auth(tools)
    qid = quote_id_of(await quote(tools, token))
    paystack.expected_amount = store.get_quote(qid)["kobo"]
    return tools, chain, token, qid


async def test_happy_path_settles(store, monkeypatch):
    tools, chain, token, qid = await _paid_tools(store, monkeypatch)
    resp = await tools.verify_and_settle(token, qid)
    assert resp["ok"] is True
    assert resp["code"] == "SETTLED"
    assert resp["data"]["explorer_url"].startswith("https://sepolia.basescan.org/tx/0x")
    assert len(chain.transfers) == 1
    assert chain.transfers[0]["to"] == "0xSUPPLIER_WALLET_1"
    assert chain.transfers[0]["amount"] == "10"
    assert store.get_quote(qid)["status"] == "SETTLED"


async def test_double_settle_sends_exactly_one_transfer(store, monkeypatch):
    tools, chain, token, qid = await _paid_tools(store, monkeypatch)

    first = await tools.verify_and_settle(token, qid)
    second = await tools.verify_and_settle(token, qid)

    assert first["code"] == "SETTLED"
    assert second["ok"] is True
    assert second["code"] == "ALREADY_SETTLED"
    assert second["data"]["tx_hash"] == first["data"]["tx_hash"]
    assert len(chain.transfers) == 1


async def test_pending_tx_is_not_resent(store, monkeypatch):
    chain = FakeChain(receipt_mined=False)
    tools, chain, token, qid = await _paid_tools(store, monkeypatch, chain=chain)

    first = await tools.verify_and_settle(token, qid)
    assert first["code"] == "SETTLEMENT_PENDING"
    assert len(chain.transfers) == 1

    second = await tools.verify_and_settle(token, qid)
    assert second["ok"] is True
    assert second["code"] == "SETTLEMENT_PENDING"
    assert second["data"]["tx_hash"] == first["data"]["tx_hash"]
    assert len(chain.transfers) == 1


async def test_tx_hash_written_before_receipt_wait(store, monkeypatch):
    """The DB must carry SETTLING + tx hash even when the receipt never lands."""
    chain = FakeChain(receipt_mined=False)
    tools, chain, token, qid = await _paid_tools(store, monkeypatch, chain=chain)
    await tools.verify_and_settle(token, qid)

    row = store.get_quote(qid)
    assert row["status"] == "SETTLING"
    assert row["tx_hash"] == chain.transfers[0]["tx_hash"]


async def test_reverted_tx_marks_settle_failed(store, monkeypatch):
    chain = FakeChain(receipt_status=0)
    tools, chain, token, qid = await _paid_tools(store, monkeypatch, chain=chain)

    resp = await tools.verify_and_settle(token, qid)
    assert resp["ok"] is False
    assert resp["code"] == "SETTLE_FAILED"
    assert store.get_quote(qid)["status"] == "SETTLE_FAILED"


async def test_treasury_low_after_payment_keeps_status_paid(store, monkeypatch, db_path):
    chain = FakeChain()
    tools, chain, token, qid = await _paid_tools(store, monkeypatch, chain=chain)

    # Treasury drained between the quote and the settlement.
    chain.balance_usdc = "1"

    resp = await tools.verify_and_settle(token, qid)
    assert resp["ok"] is False
    assert resp["code"] == "TREASURY_LOW"
    assert "apolog" in resp["say"].lower() or "sorry" in resp["say"].lower()
    assert store.get_quote(qid)["status"] == "PAID"
    assert chain.transfers == []


async def test_other_customer_cannot_settle(store, monkeypatch):
    chain = FakeChain()
    tools, chain, token_1, qid = await _paid_tools(store, monkeypatch, chain=chain)
    token_2 = await auth(tools, "KD-002", PIN_2)

    resp = await tools.verify_and_settle(token_2, qid)
    assert resp["code"] == "QUOTE_NOT_FOUND"
    assert chain.transfers == []


async def test_payment_succeeds_even_if_quote_expired(store, monkeypatch, db_path):
    chain = FakeChain()
    tools, chain, token, qid = await _paid_tools(store, monkeypatch, chain=chain)

    from datetime import datetime, timedelta, timezone

    past = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE quotes SET expires_at = ?, status = 'LINK_CREATED' WHERE quote_id = ?", (past, qid))
    conn.commit()
    conn.close()

    resp = await tools.verify_and_settle(token, qid)
    assert resp["code"] == "SETTLED"


# --- envelope contract -----------------------------------------------------


async def test_every_tool_returns_the_standard_envelope(tools):
    token = await auth(tools)
    responses = [
        await tools.start_session("KD-001", PIN_1),
        await tools.create_quote(token, "yiwu-lighting", "10", "INV-1"),
        await tools.create_naira_payment(token, "Q-missing"),
        await tools.verify_and_settle(token, "Q-missing"),
    ]
    for resp in responses:
        assert set(resp) == {"ok", "code", "data", "say"}
        assert isinstance(resp["ok"], bool)
        assert resp["code"].isupper()
        assert isinstance(resp["data"], dict)
        assert isinstance(resp["say"], str)
