import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

env = dict(os.environ)
env.setdefault("MCP_BEARER_TOKEN", "test-token-123")
env.setdefault("PAYSTACK_SECRET_KEY", "sk_test_dummy")
env.setdefault("DB_PATH", "./_smoke.db")

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", "8077"],
    env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
)

def wait_until_up(timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8077/health", timeout=3):
                return True
        except Exception:
            time.sleep(1)
    return False

if not wait_until_up():
    proc.terminate()
    print(proc.stdout.read()[-3000:] if proc.stdout else "no output")
    raise SystemExit("server never came up")

def call(path, headers=None, method="GET", body=None):
    req = urllib.request.Request(f"http://127.0.0.1:8077{path}", method=method,
                                 headers=headers or {}, data=body)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read(200).decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(200).decode(errors="replace")

try:
    print("health:", call("/health"))
    print("paid:", call("/paid")[0])
    print("no token /mcp:", call("/mcp", method="POST", body=b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}',
                                 headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}))
    print("bad token /mcp:", call("/mcp", method="POST", body=b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}',
                                  headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                                           "Authorization": "Bearer wrong"})[0])
    status, body = call("/mcp", method="POST", body=b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}',
                        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                                 "Authorization": "Bearer test-token-123"})
    print("good token /mcp:", status, body[:220])
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    for f in ("_smoke.db", "_smoke.db-journal"):
        try:
            os.unlink(f)
        except OSError:
            pass
