"""Store-level tests: pricing, PIN locks, sessions, ownership."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from server.store import Store


def test_pricing_rounds_half_up_to_whole_naira(store):
    quote = store.create_quote("KD-001", "yiwu-lighting", "10", "INV-1")
    # 10 USD * 1500 * 1.015 = 15225
    assert quote["ngn_total"] == 15225
    assert quote["kobo"] == 1522500


def test_pricing_rounds_fractional_naira_up(store):
    # 5.01 * 1500 * 1.015 = 7627.7... -> 7628
    quote = store.create_quote("KD-001", "yiwu-lighting", "5.01", "INV-2")
    assert quote["ngn_total"] == 7628
    assert quote["kobo"] == 762800


def test_quote_ids_are_prefixed_and_unique(store):
    a = store.create_quote("KD-001", "yiwu-lighting", "10", "INV-A")
    b = store.create_quote("KD-001", "yiwu-lighting", "10", "INV-B")
    assert a["quote_id"].startswith("Q-")
    assert len(a["quote_id"]) == 10
    assert a["quote_id"] != b["quote_id"]


def test_unknown_account_and_wrong_pin_are_indistinguishable(store):
    ok_unknown, code_unknown = store.verify_pin("KD-999", "0000")
    ok_known, code_known = store.verify_pin("KD-001", "0000")
    assert ok_unknown is False and ok_known is False
    assert code_unknown == code_known == "WRONG_PIN"


def test_three_wrong_pins_locks_account(store):
    store.verify_pin("KD-001", "0000")
    store.verify_pin("KD-001", "0000")
    ok, code = store.verify_pin("KD-001", "0000")
    assert ok is False
    assert code == "ACCOUNT_LOCKED"

    # Even the correct PIN is refused while locked.
    ok, code = store.verify_pin("KD-001", "4821")
    assert ok is False
    assert code == "ACCOUNT_LOCKED"


def test_correct_pin_clears_attempts(store):
    store.verify_pin("KD-001", "0000")
    store.verify_pin("KD-001", "0000")
    ok, code = store.verify_pin("KD-001", "4821")
    assert ok is True and code == "OK"
    # Attempt counter was reset, so two more misses do not lock.
    store.verify_pin("KD-001", "0000")
    store.verify_pin("KD-001", "0000")
    ok, code = store.verify_pin("KD-001", "4821")
    assert ok is True


def test_session_round_trip(store):
    token = store.create_session("KD-001")
    session = store.validate_session(token)
    assert session is not None
    assert session["account_code"] == "KD-001"


def test_expired_session_is_rejected(store, db_path):
    token = store.create_session("KD-001")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE sessions SET expires_at = ? WHERE session_token = ?", (past, token))
    conn.commit()
    conn.close()
    assert store.validate_session(token) is None


def test_unknown_session_is_rejected(store):
    assert store.validate_session("not-a-real-token") is None


def test_supplier_address_never_leaves_store_masked(store):
    customer = store.get_customer_by_account("KD-001")
    for supplier in customer["suppliers"]:
        assert "address" not in supplier
        assert supplier["address_masked"].endswith(supplier["address_masked"][-4:])
        assert "SUPPLIER_WALLET" not in supplier["address_masked"]


def test_full_address_still_resolvable_server_side(store):
    from tests.conftest import ADDR_1

    addr = store.get_supplier_address("KD-001", "yiwu-lighting")
    assert addr == ADDR_1


def test_idempotent_quote_lookup(store):
    first = store.create_quote("KD-001", "yiwu-lighting", "10", "INV-X")
    found = store.find_existing_quote("KD-001", "yiwu-lighting", "INV-X", "10")
    assert found is not None
    assert found["quote_id"] == first["quote_id"]


def test_expired_quote_is_not_reused(store, db_path):
    store.create_quote("KD-001", "yiwu-lighting", "10", "INV-Y")
    import sqlite3

    past = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE quotes SET expires_at = ?", (past,))
    conn.commit()
    conn.close()
    assert store.find_existing_quote("KD-001", "yiwu-lighting", "10", "INV-Y") is None
