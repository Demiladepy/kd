import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEMO_RATE = "1500"
DEMO_PIN_1 = "4821"
DEMO_PIN_2 = "7392"


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
