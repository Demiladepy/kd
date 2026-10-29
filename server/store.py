import json
import os
import sqlite3
import secrets
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple
import uuid


class Store:
    def __init__(self, db_path: str = "./kudidesk.db"):
        self.db_path = db_path
        self._init_db()
        self._seed_if_empty()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS quotes (
                quote_id TEXT PRIMARY KEY,
                account_code TEXT NOT NULL,
                supplier_label TEXT NOT NULL,
                invoice_ref TEXT NOT NULL,
                usd_amount TEXT NOT NULL,
                ngn_total INTEGER NOT NULL,
                kobo INTEGER NOT NULL,
                rate REAL NOT NULL,
                fee_pct TEXT NOT NULL,
                status TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                authorization_url TEXT,
                paystack_reference TEXT,
                tx_hash TEXT,
                supplier_address TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                account_code TEXT PRIMARY KEY,
                phone TEXT NOT NULL,
                name TEXT NOT NULL,
                business TEXT NOT NULL,
                max_usd_per_payment TEXT NOT NULL,
                suppliers_json TEXT NOT NULL,
                pin_hash TEXT,
                pin_salt TEXT
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS desk_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_token TEXT PRIMARY KEY,
                account_code TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pin_attempts (
                account_code TEXT PRIMARY KEY,
                attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT
            )
        """)
        
        conn.commit()
        conn.close()
    
    def _seed_if_empty(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM customers")
        count = cur.fetchone()[0]
        conn.close()
        
        if count == 0:
            seed_path = os.path.join(os.path.dirname(__file__), "seed.json")
            with open(seed_path, "r") as f:
                seed = json.load(f)
            
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            
            for key, value in seed["desk"].items():
                cur.execute("INSERT OR REPLACE INTO desk_config (key, value) VALUES (?, ?)", 
                           (key, json.dumps(value) if not isinstance(value, str) else value))
            
            for cust in seed["customers"]:
                cur.execute("""
                    INSERT OR REPLACE INTO customers (account_code, phone, name, business, max_usd_per_payment, suppliers_json, pin_hash, pin_salt)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (cust["account_code"], cust["phone"], cust["name"], cust["business"], 
                      cust["max_usd_per_payment"], json.dumps(cust["suppliers"]),
                      cust.get("pin_hash"), cust.get("pin_salt")))
            
            conn.commit()
            conn.close()
    
    def get_desk_config(self) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM desk_config")
        rows = cur.fetchall()
        conn.close()
        
        config = {}
        for key, value in rows:
            try:
                if key in ["ngn_per_usd", "quote_ttl_minutes"]:
                    if value == "0":
                        config[key] = 0
                    elif value.isdigit() or (value.startswith('-') and value[1:].isdigit()):
                        config[key] = int(value)
                    else:
                        config[key] = float(value)
                elif key == "ngn_per_usd" and value == "0":
                    config[key] = 0
                else:
                    config[key] = value
            except:
                config[key] = value
        
        if config.get("ngn_per_usd", 0) == 0:
            raise ValueError("ngn_per_usd is 0")
        
        return config
    
    MAX_PIN_ATTEMPTS = 3
    LOCK_MINUTES = 15
    PIN_KDF_ITERATIONS = 120_000

    @classmethod
    def hash_pin(cls, pin: str, salt_hex: str) -> str:
        """PBKDF2-HMAC-SHA256. Demo PINs live only as hashes in seed.json."""
        return hashlib.pbkdf2_hmac(
            "sha256", pin.encode("utf-8"), bytes.fromhex(salt_hex), cls.PIN_KDF_ITERATIONS
        ).hex()

    def _record_failed_attempt(self, cur, key: str, attempts: int, now: datetime) -> str:
        """Bump the counter for `key` and lock it once the limit is reached."""
        new_attempts = attempts + 1
        if new_attempts >= self.MAX_PIN_ATTEMPTS:
            locked_until = (now + timedelta(minutes=self.LOCK_MINUTES)).isoformat()
            cur.execute(
                "INSERT INTO pin_attempts (account_code, attempts, locked_until) VALUES (?, ?, ?) "
                "ON CONFLICT(account_code) DO UPDATE SET attempts = excluded.attempts, "
                "locked_until = excluded.locked_until",
                (key, new_attempts, locked_until),
            )
            return "ACCOUNT_LOCKED"
        cur.execute(
            "INSERT INTO pin_attempts (account_code, attempts) VALUES (?, ?) "
            "ON CONFLICT(account_code) DO UPDATE SET attempts = excluded.attempts",
            (key, new_attempts),
        )
        return "WRONG_PIN"

    def verify_pin(self, account_code: str, pin: str) -> tuple[bool, str]:
        """Check a PIN. An unknown code and a wrong PIN return the same code."""
        key = (account_code or "").strip().upper()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        now = datetime.now(timezone.utc)

        cur.execute("SELECT * FROM pin_attempts WHERE account_code = ?", (key,))
        attempt = cur.fetchone()
        if attempt and attempt["locked_until"]:
            locked_until = datetime.fromisoformat(attempt["locked_until"].replace("Z", "+00:00"))
            if locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=timezone.utc)
            if now < locked_until:
                conn.close()
                return False, "ACCOUNT_LOCKED"

        cur.execute("SELECT * FROM customers WHERE UPPER(account_code) = ?", (key,))
        customer = cur.fetchone()
        attempts = attempt["attempts"] if attempt else 0

        if customer is None:
            # Never reveal whether the account code exists.
            code = self._record_failed_attempt(cur, key, attempts, now)
            conn.commit()
            conn.close()
            return False, code

        expected_hash = customer["pin_hash"]
        salt = customer["pin_salt"]
        supplied_pin = (pin or "").strip()

        if expected_hash and salt and hmac.compare_digest(
            self.hash_pin(supplied_pin, salt), expected_hash
        ):
            cur.execute("DELETE FROM pin_attempts WHERE account_code = ?", (customer["account_code"],))
            conn.commit()
            conn.close()
            return True, "OK"

        code = self._record_failed_attempt(cur, customer["account_code"], attempts, now)
        conn.commit()
        conn.close()
        return False, code
    
    def create_session(self, account_code: str) -> str:
        session_token = secrets.token_hex(32)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=30)
        cur.execute("INSERT INTO sessions (session_token, account_code, created_at, expires_at) VALUES (?, ?, ?, ?)",
                   (session_token, account_code, now.isoformat(), expires_at.isoformat()))
        conn.commit()
        conn.close()
        return session_token
    
    def validate_session(self, session_token: str) -> Optional[Dict[str, Any]]:
        if not session_token:
            return None
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM sessions WHERE session_token = ?", (session_token,))
        session = cur.fetchone()
        if not session:
            conn.close()
            return None
        expires_at = datetime.fromisoformat(session["expires_at"].replace('Z', '+00:00'))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if now > expires_at:
            conn.close()
            return None
        conn.close()
        return dict(session)
    
    def get_customer_by_account(self, account_code: str) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM customers WHERE UPPER(account_code) = UPPER(?)", (account_code,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        suppliers = json.loads(row["suppliers_json"])
        masked_suppliers = []
        for s in suppliers:
            addr = s["address"]
            if len(addr) > 10:
                masked = addr[:6] + "…" + addr[-4:]
            else:
                masked = addr
            masked_suppliers.append({
                "label": s["label"],
                "display": s["display"],
                "address_masked": masked
            })
        return {
            "account_code": row["account_code"],
            "phone": row["phone"],
            "name": row["name"],
            "business": row["business"],
            "max_usd_per_payment": row["max_usd_per_payment"],
            "suppliers": masked_suppliers,
            "suppliers_full": suppliers
        }
    
    def get_customer(self, account_code: str = None, phone: str = None) -> Optional[Dict[str, Any]]:
        if account_code:
            return self.get_customer_by_account(account_code)
        # Keep old behavior for backward compat if needed
        return None
    
    def get_supplier_address(self, account_code: str, supplier_label: str) -> Optional[str]:
        customer = self.get_customer_by_account(account_code)
        if not customer:
            return None
        for s in customer.get("suppliers_full", []):
            if s["label"] == supplier_label:
                return s["address"]
        return None
    
    def create_quote(self, account_code: str, supplier_label: str, usd_amount: str, 
                     invoice_ref: str, quote_id: str = None) -> Dict[str, Any]:
        if not quote_id:
            quote_id = f"Q-{uuid.uuid4().hex[:8]}"
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        now = datetime.now(timezone.utc)
        config = self.get_desk_config()
        fee_pct = Decimal(str(config["fee_pct"]))
        ngn_per_usd = Decimal(str(config["ngn_per_usd"]))
        ttl_minutes = int(config["quote_ttl_minutes"])
        usd = Decimal(usd_amount)
        ngn_total_decimal = (usd * ngn_per_usd * (Decimal(1) + fee_pct / Decimal(100))).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        ngn_total = int(ngn_total_decimal)
        kobo = ngn_total * 100
        expires_at = now + timedelta(minutes=ttl_minutes)
        cur.execute("""
            INSERT INTO quotes (quote_id, account_code, supplier_label, invoice_ref, usd_amount, 
                               ngn_total, kobo, rate, fee_pct, status, expires_at, 
                               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (quote_id, account_code, supplier_label, invoice_ref, usd_amount,
              ngn_total, kobo, float(ngn_per_usd), str(config["fee_pct"]), "QUOTED", 
              expires_at.isoformat(), now.isoformat(), now.isoformat()))
        conn.commit()
        conn.close()
        return {
            "quote_id": quote_id,
            "usd": usd_amount,
            "rate": float(ngn_per_usd),
            "fee": str(config["fee_pct"]),
            "ngn_total": ngn_total,
            "kobo": kobo,
            "expires_at": expires_at.astimezone(timezone(timedelta(hours=1))).isoformat(),
            "status": "QUOTED"
        }
    
    def get_quote(self, quote_id: str) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM quotes WHERE quote_id = ?", (quote_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return dict(row)
    
    def find_existing_quote(self, account_code: str, supplier_label: str, invoice_ref: str, usd_amount: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM quotes 
            WHERE account_code = ? AND supplier_label = ? AND invoice_ref = ? AND usd_amount = ?
            AND status IN ('QUOTED', 'LINK_CREATED') 
            ORDER BY created_at DESC LIMIT 1
        """, (account_code, supplier_label, invoice_ref, usd_amount))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        quote = dict(row)
        expires_at = datetime.fromisoformat(quote["expires_at"].replace('Z', '+00:00'))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if now > expires_at and quote["status"] == "QUOTED":
            return None
        return quote
    
    def update_quote_status(self, quote_id: str, status: str, **kwargs):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        sets = ["status = ?", "updated_at = ?"]
        params = [status, now]
        for k, v in kwargs.items():
            sets.append(f"{k} = ?")
            params.append(v)
        params.append(quote_id)
        cur.execute(f"UPDATE quotes SET {', '.join(sets)} WHERE quote_id = ?", params)
        conn.commit()
        conn.close()
    
    def update_quote_status_if_paid(self, quote_id: str, new_status: str, **kwargs):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        sets = ["status = ?", "updated_at = ?"]
        params = [new_status, now]
        for k, v in kwargs.items():
            sets.append(f"{k} = ?")
            params.append(v)
        params.append(quote_id)
        cur.execute(f"UPDATE quotes SET {', '.join(sets)} WHERE quote_id = ? AND status = 'PAID'", params)
        changed = cur.rowcount
        conn.commit()
        conn.close()
        return changed > 0
