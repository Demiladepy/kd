# Field Notes Raw

Append raw errors and context here as they happen. The human turns these into
`docs/FIELD_NOTES.md`. Never fabricate entries.

---

## 2026-10-29 — `mcp` 2.x breaks the PLAN's import path

Context: fresh `pip install mcp` on Windows, Python 3.11. Building `server/app.py`
exactly as PLAN.md §2 specifies (`from mcp.server.fastmcp import FastMCP`).

Raw error:

```
File "C:\Users\User\AppData\Local\Programs\Python\Python311\Lib\site-packages\mcp\server\fastmcp.py", line 16, in <module>
    raise ModuleNotFoundError(_MESSAGE, name=__name__)
ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was renamed to MCPServer
(from mcp.server.mcpserver import MCPServer) and other APIs changed; see the migration guide at
https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver or pin 'mcp<2' to keep running v1 code.
```

Also seen in the same install: `pip install mcp` pulled `mcp-2.3.0` and
`starlette-1.10.0`, which conflicts with the environment's FastAPI
(`fastapi 0.115.6 requires starlette<0.42.0,>=0.40.0`).

What was tried: reinstalling with `pip install "mcp>=1.2,<2" "starlette>=0.37,<0.42"`
resolved to `mcp-1.30.0` + `starlette-0.41.3` and the import worked.

Fix applied: pinned `mcp>=1.2,<2` and `starlette>=0.37,<0.42` in `requirements.txt`
with a comment explaining why.

---

## 2026-10-29 — `pytest` dies on import of sklearn via nltk

Context: running `pytest` in the same global Python environment.

Raw error (tail):

```
File "sklearn\utils\murmurhash.pyx", line 1, in init sklearn.utils.murmurhash
ValueError: numpy.dtype size changed, may indicate binary incompatibility.
Expected 96 from C header, got 88 from PyObject
```

Cause: an unrelated third-party pytest plugin autoloads `nltk`, which imports
`sklearn`, which is built against a different numpy. Not a KudiDesk bug.

Workaround used for local runs:

```
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest -p pytest_asyncio.plugin
```

Result: `73 passed`. A clean virtualenv would avoid this entirely.

---

## 2026-10-29 — Arc RPC returns 403 to Python's default urllib User-Agent

Context: probing `https://rpc.testnet.arc.network` with `urllib.request` (the
same body that `Invoke-RestMethod` accepted without complaint).

Raw error:

```
urllib.error.HTTPError: HTTP Error 403: Forbidden
```

Cause: the endpoint filters on `User-Agent`. PowerShell sends its own; Python's
default `Python-urllib/3.11` is refused. No body, no JSON-RPC error — just 403.

Fix applied: set an explicit `User-Agent` header on the probe. `web3.py` through
`HTTPProvider` worked without changes, so this only affected hand-rolled
`urllib` calls. Worth knowing before assuming the RPC is down or the URL is
wrong.

---

## 2026-10-29 — Paystack rejects the `.test` email TLD, so PLAN.md §4.3's email fails

Context: first real `POST /transaction/initialize` against the live Paystack test
API, using the address the plan specifies
(`f"{account_code.lower()}@customers.kudidesk.test"`).

Raw response:

```
HTTP 400
{"status": false, "message": "\"email\" must be a valid email"}
```

Isolation: five addresses through the same endpoint, same key, fresh references
each time:

```
BAD 400  doctor@customers.kudidesk.test   "email" must be a valid email
BAD 400  kd-001@customers.kudidesk.test   "email" must be a valid email
BAD 400  kd-001@kudidesk.test             "email" must be a valid email
OK  200  kd-001@example.com               Authorization URL created
OK  200  kd-001@customers.example.com     Authorization URL created
```

So it is the **`.test` TLD**, not the domain, the subdomain structure, or the
local part. Paystack validates against a real-TLD allowlist; `.test` is reserved
by RFC 2606 and will never be in it.

Fix applied: `create_naira_payment` in `tools.py` now builds
`{account_code}@customers.example.com` — RFC 2606-reserved, syntactically valid,
accepted by Paystack, and never deliverable (which is what a generated receipt
address wants). `test_paystack_email_uses_a_valid_tld` pins it so nobody
reintroduces `.test`.

What this cost: one failed request on the first live call. The plan's email rule
was written by someone who never sent it.

---

## 2026-10-29 — One USDC transfer emits **two** ERC-20 Transfer logs on Arc

Context: verifying the first real settlement
(`0x9937effa85f2ed4a553a6f522484fd7818ff7ab0b6b182403e86635e49013dfd`) by
decoding `receipt.logs` rather than trusting the client's own output.

The receipt contains two `Transfer(address,address,uint256)` events, both from
the treasury to the supplier, for the same 12 USDC:

```
topic  : 0xddf252ad... (Transfer)
token  : 0xffffFFFfFFffffffffffffffFfFFFfffFFFfFFfE
from   : 0x611CFAcB...0a090
to     : 0xdE5Dc6e0...18D1
amount : 12000000000000000000   (= 12e18, i.e. 12 USDC at 18 dp)

token  : 0x3600000000000000000000000000000000000000
from   : 0x611CFAcB...0a090
to     : 0xdE5Dc6e0...18D1
amount : 12000000               (= 12e6, i.e. same 12 USDC at 6 dp)
```

Same transfer, logged twice at the two decimal scales already measured. The
first event comes from Arc's native-token address, the second from the USDC
ERC-20.

Why it matters: any reconciliation code that counts or sums `Transfer` events
without filtering by token address will double-count every settlement. For a
payment desk that reconciles daily Paystack collections against on-chain
payouts, that is a silent 2x error in the books.

Fix applied: nothing to fix in settlement — `chain.py` reads ERC-20 `balanceOf`
and does not aggregate logs. Recorded here so the reconciliation advice in
`docs/GO_LIVE.md` says "filter by the ERC-20 token address and dedupe by
transaction hash", not "sum the transfers".

---

## 2026-10-29 — Server read a placeholder bearer token because it never loaded `.env`

Context: local `uvicorn server.app:app` run, then the official MCP client with the
real `MCP_BEARER_TOKEN` from `.env`.

Raw response:

```
httpx.HTTPStatusError: Client error '401 Unauthorized' for url
'http://127.0.0.1:8000/mcp'
```

What made it confusing: `scripts/http_smoke.py` passed with a *good* token in the
same minute. That script boots its own app in-process with
`MCP_BEARER_TOKEN=test-token-123`, so it was proving the middleware worked, not
that the running server had the right token.

How I found the cause: `os.getenv("MCP_BEARER_TOKEN", "change-me-long-random")`
in `app.py` — the default was in use. Each script called `load_dotenv()`; the
server itself never did. On Render the dashboard provides env vars so nothing
looked wrong there, which is exactly why it survived until the first real local
client call.

Fix applied: `load_dotenv()` at the top of `server/app.py`, before `KudiDeskTools`
is constructed. It is a no-op when no `.env` exists, so Render is unaffected.

Worth noting for the write-up: a smoke script that boots its own app can pass
while the real server is misconfigured. Test the thing you deploy.

---

## 2026-10-29 — Arc native balance is 18 dp while USDC ERC-20 is 6 dp

Context: PLAN.md §2 says "sources disagree on the native balance's decimals.
Verify this on day one and log what you find." Verified by comparing
`eth_getBalance` against `balanceOf()` for live addresses.

Measured at block 69,684,820:

```
address                                      native / 1e18                    erc20 / 1e6
0x9143698409426ac33b277decc9f20fa9049887ec   223.473480851711701627           223.473480
0xd731d8b19205fe7a9a93ebed1da2f35d54af9c82    85.604548819568282194            85.604548
0x24a078b7eb595c6b0f43dbf574a7282931a50d1a     5.483392876667516447             5.483392
```

Ratio in every sample: `~1e12`. The native amount divided by 1e18 equals the
ERC-20 amount divided by 1e6 (after truncation to 6 dp; the native side carries
sub-micro-USDC dust).

Conclusion: **native balance = 18 decimals, ERC-20 USDC = 6 decimals, same
asset.** Any code that treats `eth_getBalance` as a 6-decimal dollar figure
under-reports by 1e12 — which would make a treasury look empty or, worse, make a
payout look affordable when it is not.

Fix applied: `chain.py` never mixes the two. Money reads use ERC-20 `balanceOf`;
the native balance is only used for gas, and `native_to_usdc()` divides by 1e18
with an explicit constant. Unit tests pin the 1e12 relationship.

---

## 2026-10-29 — `eth_estimateGas` reverts on an unfunded treasury

Context: computing a gas estimate for an informational balance check, from a
freshly generated throwaway key with 0 USDC.

Raw error:

```
web3.exceptions.ContractLogicError: ('execution reverted: ERC20: transfer amount
exceeds balance', '0x08c379a0...45524332303a207472616e7366657220616d6f756e7420
657863656564732062616c616e6365')
```

Cause: the node simulates the transfer, so `estimate_gas` fails when the sender
cannot cover it. Correct behaviour, but it crashed a read-only check.

Fix applied: `estimate_gas_limit()` falls back to a 90 000 ceiling on any
estimation failure. The fallback is a fee *ceiling* — unused gas is refunded — so
being generous costs nothing but headroom. A real out-of-gas would still surface
as `SETTLE_FAILED` rather than a crash.

---

## 2026-10-29 — seed.json placeholders would take money for an impossible payout

Not an error message — a design hole found by reading the plan against the code.
`seed.json` ships `"address": "0xSUPPLIER_WALLET_1"`. If a human forgets to
replace them, `create_quote` succeeds, the customer pays through Paystack, and
only then does the transfer fail on an invalid checksum — money in, nothing out.

Fix applied: `create_quote` validates the resolved address with
`Web3.is_address` and returns `SUPPLIER_NOT_SAVED` with
`data.reason == "SUPPLIER_ADDRESS_NOT_CONFIGURED"` **before** any Paystack link
is created. Covered by `test_quote_refused_while_supplier_address_is_a_placeholder`.
