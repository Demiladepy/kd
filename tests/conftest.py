import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEMO_RATE = "1500"
DEMO_PIN_1 = "4821"
DEMO_PIN_2 = "7392"

# Stand-in supplier wallets. seed.json ships obvious placeholders
# ("0xSUPPLIER_WALLET_1") that the human replaces with real test wallets;
# tests use valid-shaped addresses so the payable-address guard passes.
ADDR_1 = "0x1111111111111111111111111111111111111111"
ADDR_2 = "0x2222222222222222222222222222222222222222"
ADDR_3 = "0x3333333333333333333333333333333333333333"


def install_supplier_addresses(db_path):
    """Replace seed placeholders with valid EVM addresses for tests."""
    import json

    mapping = {
        "0xSUPPLIER_WALLET_1": ADDR_1,
        "0xSUPPLIER_WALLET_2": ADDR_2,
        "0xSUPPLIER_WALLET_3": ADDR_3,
    }
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT account_code, suppliers_json FROM customers").fetchall()
    for row in rows:
        suppliers = json.loads(row["suppliers_json"])
        for s in suppliers:
            s["address"] = mapping.get(s["address"], s["address"])
        conn.execute(
            "UPDATE customers SET suppliers_json = ? WHERE account_code = ?",
            (json.dumps(suppliers), row["account_code"]),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    yield path
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except OSError:
            pass


@pytest.fixture
def store(db_path):
    from server.store import Store

    s = Store(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE desk_config SET value = ? WHERE key = 'ngn_per_usd'", (DEMO_RATE,))
    conn.commit()
    conn.close()
    install_supplier_addresses(db_path)
    return s


def make_tools(store, monkeypatch, fake_paystack=None, fake_chain=None):
    """Build KudiDeskTools with network layers replaced by fakes."""
    monkeypatch.setenv("DB_PATH", store.db_path)
    from server.tools import KudiDeskTools

    tools = KudiDeskTools()
    tools.store = store
    tools.paystack = fake_paystack
    tools.chain = fake_chain
    return tools


@pytest.fixture
def tools(store, monkeypatch):
    return make_tools(store, monkeypatch)
