# HANDOFF — continue here in Cursor

KudiDesk: an MCP server that quotes naira for a supplier invoice, collects the
naira through Paystack (test mode), confirms the money landed, then settles USDC
on Arc testnet to a supplier address fixed in `seed.json`. The agent never
accepts a wallet address from the customer.

**Everything below has been run for real.** 74 offline tests pass; one live
Paystack collection settled one real on-chain payout, and one abandoned checkout
moved nothing.

---

## 1. Run it

Needs Python 3.11 and the deps in `requirements.txt`.

```powershell
cd C:\Users\User\Desktop\work\kudidesk
python -m pip install -r requirements.txt
Copy-Item .env.example .env      # only if .env is missing — then fill it in
$env:PYTHONPATH="."
python -m uvicorn server.app:app --host 127.0.0.1 --port 8123
```

Check it:

```powershell
Invoke-WebRequest http://127.0.0.1:8123/health -UseBasicParsing | % Content   # {"ok":true}
```

**Use port 8123.** A server from an older build may still be running on 8000
(pid 30500); it returns 421 to every MCP call and will waste your afternoon.

### Env vars (`.env`, gitignored — never commit it)

| Var | Notes |
|---|---|
| `MCP_BEARER_TOKEN` | required; MCP rejects anything else |
| `PAYSTACK_SECRET_KEY` | `sk_test_…`. Server **refuses to boot** on `sk_live_` |
| `PUBLIC_BASE_URL` | base for the `/paid` link; set it to the public URL you deploy on |
| `CHAIN_*`, `RPC_URL`, `USDC_ADDRESS`, `EXPLORER_TX_URL`, `GAS_TOKEN_IS_USDC` | Arc testnet values are in `.env.example` |
| `TREASURY_PRIVATE_KEY` | test wallet only. The funded key is in `.wallets.json` (gitignored) |
| `DB_PATH` | defaults to `./kudidesk.db`; delete it to re-seed |
| `MCP_ALLOWED_HOSTS` | optional comma-separated host list for MCP's DNS-rebinding check. Leave unset behind a proxy or tunnel |

Seeding only runs against an empty database, so changing `server/seed.json`
after the first boot has no effect until you delete `kudidesk.db`.

### Tests

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest -p pytest_asyncio.plugin      # 74 passed
```

The env var is only there because some unrelated installed plugin imports a
broken sklearn. A clean virtualenv does not need it.

---

## 2. Reach it from Chord

Chord cannot call `localhost` — the server must be on a public HTTPS URL.

**Stable:** deploy to Render (`render.yaml` is in the repo). Set the env vars
from the table above in the dashboard; `PUBLIC_BASE_URL` becomes the Render URL.

**Quick and temporary:** a Cloudflare quick tunnel works for a demo, but the
hostname is deleted the moment the connection drops and never comes back — the
process keeps retrying with `Unauthorized: Tunnel not found` and the browser
shows "site can't be reached". That is what happened to the last one.

```powershell
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://127.0.0.1:8123 --no-autoupdate
```

Copy the `https://….trycloudflare.com` URL **after** it prints, and register
`<url>/mcp` in Chord as transport `streamable_http` with the bearer token.
If the tunnel restarts, the URL changes and Chord must be updated.

---

## 3. Verify a real run

```powershell
python scripts\mcp_client_test.py        # full MCP path; SKIP_SETTLE=1 stops before payout
python scripts\verify_settlement.py      # re-checks a settlement tx against DB + seed
python scripts\verify_unpaid.py          # proves an abandoned checkout moves nothing
python scripts\verify_declined.py        # declined card — needs a human at the Paystack page
python scripts\paystack_doctor.py        # diagnoses Paystack key/account walls
```

Test card: `4084 0840 8408 4081`, CVV `408`, any future expiry. Declined:
`4084 0800 0000 5408`, CVV `001`. Paystack's test minimum is NGN 50.

Money reads are ERC-20 `balanceOf()` at 6 dp. `eth_getBalance` is the same asset
at 18 dp and is used **only** for gas. Arc logs two `Transfer` events per
transfer — see `docs/FIELD_NOTES.md` before writing any reconciliation.

---

## 4. What is left

| Task | Owner | Notes |
|---|---|---|
| Register the MCP server in Chord, create the teammate, upload the skill, publish | you | needs the public URL above |
| Run the simulator: happy path + red-team 2–7 | you | needs Chord |
| Declined-card run | you | `scripts\verify_declined.py` is ready |
| ~~Render deploy~~ | — | **done**: `https://kudidesk.onrender.com/health` returns `{"ok":true}`; the MCP client path passes against it |
| 3-minute recording, upload, reply to Emmanuel | you | last |

Done and pushed: the server, 4 MCP tools, bearer auth, `/health`, `/paid`,
forensics to `logs/inbound.jsonl`, the field notes, the go-live note, and the
scripts above.

**Do not commit:** `.env`, `.wallets.json`, `kudidesk.db`, `logs/`.
