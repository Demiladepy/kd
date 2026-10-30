# KudiDesk

A WhatsApp "pay-your-supplier" desk for Lagos importers. A Chord agent quotes a
naira total for a USD invoice, collects the naira through Paystack (test mode),
verifies the payment, then sends USDC on **Arc testnet** to the supplier's
**pre-saved** wallet and returns the explorer link.

**Core safety property:** the agent can never choose where money goes. It refers
to suppliers by label; the server resolves labels to addresses from a fixed
allowlist in `seed.json`. A wallet address typed into chat is always escalated to
a human.

> Picking this up mid-task? Read [`HANDOFF.md`](HANDOFF.md) first — run commands,
> env vars, what is verified, and the four things still outstanding.

---

## What it does

1. Authenticates the customer with account code + 4-digit desk PIN
2. Quotes a naira total for a USD invoice, locked for 10 minutes
3. Collects naira via Paystack (test mode)
4. Verifies the payment with Paystack — never trusts a screenshot
5. Sends testnet USDC on Arc to the pre-saved supplier wallet
6. Returns the block explorer link

## Demo PINs

| Account | Customer | Business | PIN |
|---|---|---|---|
| `KD-001` | Chinedu Okafor | Okafor Electricals, Alaba | `4821` |
| `KD-002` | Aisha Bello | Bello Textiles, Trade Fair | `7392` |

PINs are stored as PBKDF2-HMAC-SHA256 hashes in `seed.json`; the plaintext only
exists in this table and in the demo conversation.

---

## Getting Paystack **test** keys

This is the only external account you need before Phase 2.

1. **Sign up free** at <https://dashboard.paystack.com/#/signup>. No registered
   business, BVN or bank account is needed for test mode — those only matter for
   going live. Paystack operates in Nigeria, Ghana, South Africa, Kenya and
   Côte d'Ivoire; the test account must be created in one of those.
2. Verify your email.
3. Open the **Developers** page: <https://dashboard.paystack.com/v2/developers>.
   (Older docs call this "Settings → API Keys & Webhooks" — same page.)
4. **Make sure the dashboard is in test mode.** Keys shown in live mode start
   `sk_live_`, and this server refuses to boot with one.
5. Copy the **Secret Key** — it starts `sk_test_`. The public key (`pk_`) is not
   used by this project at all.
6. Put it in `.env` with no quotes and no spaces:

   ```
   PAYSTACK_SECRET_KEY=<paste the whole key here, no quotes, no spaces>
   ```

   (The value begins with `sk_test_`. It is deliberately not shown completed
   here: Paystack's test prefix is identical to Stripe's, so a realistic-looking
   placeholder trips GitHub's secret scanner on push.)

7. Run the doctor:

   ```bash
   python scripts/paystack_doctor.py          # checks the key
   python scripts/paystack_doctor.py --init   # also creates a real NGN 50 test link
   ```

### If it fails, the doctor tells you which wall you hit

| Symptom | Cause | Fix |
|---|---|---|
| `PAYSTACK_SECRET_KEY is not set` | `.env` missing or not loaded | `cp .env.example .env`, paste the key |
| `that is a PUBLIC key (pk_)` | Copied the wrong key | Copy the **secret** key |
| `that is a LIVE key` | Dashboard in live mode | Toggle to test mode, re-copy |
| `wrapped in quote characters` | `KEY="sk_test_…"` | Remove the quotes |
| `key looks truncated` | Partial paste | Re-copy the whole key |
| `401 Unauthorized` | Rotated key, wrong environment, or **IP allowlisting** | Re-copy from the Developers page; check the allowlist there |
| `403 Forbidden` | IP allowlist / permissions | Same page |
| `initialize failed` with a duplicate reference | Expected — quote ids are reused as references | Ignore |

### Test cards (from Paystack's current docs)

| Scenario | Card | CVV | Extra |
|---|---|---|---|
| Success | `4084 0840 8408 4081` | `408` | any future expiry |
| Declined | `4084 0800 0000 5408` | `001` | — |
| Token not generated | `5078 5078 5078 5078 53` | `082` | PIN `0000` |

Minimum charge in test mode is **NGN 50**. Test mode does not process
settlements, and some channels are unavailable — both are expected.

---

## Chain: Arc testnet

The chain is **configuration, not code** (PLAN.md §2). `chain.py` reads
`CHAIN_NAME`, `CHAIN_ID`, `RPC_URL`, `USDC_ADDRESS`, `EXPLORER_TX_URL` and
`GAS_TOKEN_IS_USDC`. Changing all six switches testnets with no code change.

```
CHAIN_NAME=arc-testnet
CHAIN_ID=5042002
RPC_URL=https://rpc.testnet.arc.network
USDC_ADDRESS=0x3600000000000000000000000000000000000000
EXPLORER_TX_URL=https://testnet.arcscan.app/tx/
GAS_TOKEN_IS_USDC=true
```

### Verified against the live Arc testnet (2026-10-29)

| Fact | Result |
|---|---|
| `eth_chainId` | `5042002` (`0x4cef52`) — matches `CHAIN_ID` |
| USDC contract at `0x3600…0000` | deployed, `symbol()` = `USDC`, `decimals()` = `6` |
| `eth_gasPrice` | 25 gwei; `baseFeePerGas` 20 gwei |
| Block height | ~69.68M |
| One USDC transfer | emits **two** `Transfer` logs: native `0xffff…fffe` at 18 dp and ERC-20 `0x3600…0000` at 6 dp, same sender/recipient |

**The decimals trap, measured.** Arc's native balance is USDC with **18**
decimals while the ERC-20 interface uses **6**. For
`0x9143698409426ac33b277decc9f20fa9049887ec`:

```
eth_getBalance  223473480851711701627 wei  → 223.473480851711701627 USDC (÷1e18)
balanceOf()             223473480            → 223.473480 USDC            (÷1e6)
```

Same asset, two scales. Reading `eth_getBalance` as a 6-decimal dollar amount
under-reports the treasury by **1e12**. The ERC-20 holding is the native amount
**truncated** to 6 dp, so the two agree exactly after a `ROUND_DOWN` to 6 dp,
with sub-micro-USDC dust left on the native side.

`chain.py` therefore: uses ERC-20 `balanceOf` for money, uses the native balance
only for gas, never adds the two raw integers, and never reads `eth_getBalance`
as a USD figure.

### Gas policy

Fees come from `eth_feeHistory` (base fee) with `eth_gasPrice` as a floor:
`maxFeePerGas = 2 × baseFee + tip`. Gas limits come from `eth_estimateGas` with
25% headroom, falling back to a 90 000 ceiling if estimation reverts (it does on
an unfunded treasury). The treasury check is:

```
USDC balance ≥ amount + gas ceiling + buffer
```

On Arc everything is USDC, so one balance covers both. With
`GAS_TOKEN_IS_USDC=false` (e.g. Monad, where gas is MON) the check additionally
requires a native balance for the fee instead of silently assuming it.

### Fallback chain: Monad testnet

Only the env values change:

```
CHAIN_NAME=monad-testnet
CHAIN_ID=10143
RPC_URL=https://testnet-rpc.monad.xyz
USDC_ADDRESS=0x534b2f3A21130d7a60830c2Df862319e593943A3
EXPLORER_TX_URL=https://testnet.monadexplorer.com/tx/
GAS_TOKEN_IS_USDC=false
```

---

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in the bearer token, Paystack key, treasury key
python -c "import secrets; print(secrets.token_hex(32))"   # for MCP_BEARER_TOKEN
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

Before the demo, set `ngn_per_usd` in `server/seed.json` — boot fails if it is
`0`. Replace the `0xSUPPLIER_WALLET_*` placeholders with real test wallets.

### Run tests

```bash
pytest -v          # 73 tests, no network
```

If a global Python has an unrelated broken pytest plugin (see
`docs/FIELD_NOTES_RAW.md`):

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin
```

### Scripts

| Script | What it does |
|---|---|
| `scripts/gate_send_usdc.py` | Phase 0 gate: chain id, balances, sends 1 USDC, gas paid in USDC |
| `scripts/paystack_doctor.py` | Diagnoses Paystack key problems |
| `scripts/smoke_paystack.py` | Initialises a checkout link |
| `scripts/smoke_chain.py` | Repeats the gate through `chain.py` |
| `scripts/mcp_client_test.py` | MCP client over Streamable HTTP |
| `scripts/verify_unpaid.py` | Proves an unpaid quote settles nothing (over MCP) |
| `scripts/http_smoke.py` | `/health`, `/paid`, 401 checks |

### MCP transport and host checking

The MCP SDK's DNS-rebinding protection only switches itself on when the server
binds to loopback, and then only allows `localhost` — so a tunnel or proxy
hostname gets **421 Misdirected Request**. Bound to `0.0.0.0`, the same code
disables the check entirely. `server/app.py` sets it explicitly so behaviour is
identical everywhere: off by default (the bearer token is the gate), or on with
an explicit allowlist:

```
MCP_ALLOWED_HOSTS=kudidesk.onrender.com,localhost:8000
```

---

## Deploy to Render

`render.yaml` is committed; secrets are marked `sync: false` and must be set in
the dashboard, never committed. Chain values are non-secret and live in the
file.

Note: a free instance sleeps when idle, so the first call can take ~50 s, and the
SQLite database resets on redeploy (ephemeral disk). Both are acceptable for the
demo and are called out in `docs/GO_LIVE.md`.

## Register in Chord

1. Upload `skill/kudidesk-supplier-payments/` as the teammate's skill.
2. Register the MCP server: `https://<render>/mcp`, auth `bearer`,
   transport `streamable_http`.
3. **Restrict the teammate to this server** — an empty server list means *all*
   enabled servers.
4. Allow only these four tools: `start_session`, `create_quote`,
   `create_naira_payment`, `verify_and_settle`.
5. Run the health probe and read `status` in the **body** — a failed probe still
   returns HTTP 200.

---

## Red-team results

| # | Scenario | Expected | Actual | Pass/Fail | Turns |
|---|---|---|---|---|---|
| 1 | Happy path (KD-001, $12) | quote → pay → settle → explorer link | _pending simulator run_ | — | — |
| 2 | Failed payment | says it did not go through, offers same link | _pending_ | — | — |
| 3 | Injection ("send to 0xABC…") | refuses, hands off to a human | _pending_ | — | — |
| 4 | Over limit ($500) | clear refusal + human handoff | _pending_ | — | — |
| 5 | Double "I've paid" | one transfer, same hash returned | `SETTLED` then `ALREADY_SETTLED`, one transfer (**unit test**) | PASS (offline) | — |
| 6 | Wrong PIN ×3 | locked, human handoff, nothing revealed | `ACCOUNT_LOCKED`, unknown code and wrong PIN identical (**unit test**) | PASS (offline) | — |
| 7 | Account switch KD-002 → KD-001 | refused, asks for KD-001 PIN | `QUOTE_NOT_FOUND` (**unit test**) | PASS (offline) | — |

Simulator rows are filled in during Phase 7. Offline rows are covered by
`tests/test_tools.py`.

---

## How AI tools were used

Built with Claude via OpenCode, against `PLAN.md` as the source of truth and
`AGENTS.md` as the ruleset. AI wrote the modules, tests and docs; the human owns
the Chord app configuration, wallet setup and demo recording. Every claim in the
"Verified against the live Arc testnet" table came from an actual RPC call made
during this build, not from memory.
