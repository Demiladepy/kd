# KudiDesk Build Checklist

Source of truth: `PLAN.md`. One phase at a time; run the named tests/scripts and report pass/fail.

## Phase 0 — Gate (Arc testnet)
- [x] `scripts/gate_send_usdc.py` — prints RPC chain id (must match `CHAIN_ID`), ERC-20 USDC balance, raw native balance + interpretation, sends 1 USDC, prints explorer URL and gas paid in USDC
- [x] Live RPC facts verified 2026-10-29: chain id `5042002`, USDC `0x3600…0000` deployed with `decimals()=6`, `symbol()=USDC`
- [x] Decimals question answered: native = 18 dp, ERC-20 = 6 dp (see `docs/FIELD_NOTES_RAW.md`)
- [x] **PASS = mined tx with status 1** — 2026-10-29, `0xa6e4b71d…617a151`, block 69704555, gas 0.00184875 USDC, supplier credited 1 USDC

**Status:** PASSED on Arc testnet with 60 USDC from the faucet.

## Phase 1 — Core logic, no network
- [x] `server/store.py` — SQLite state machine, quotes, sessions, PIN attempts
- [x] PBKDF2 PIN hashes in `seed.json`
- [x] Pricing: `round_half_up(usd × ngn_per_usd × (1 + fee/100))`, Decimal only
- [x] `paystack.py` / `chain.py` behind interfaces; fakes in `tests/fakes.py`
- [x] `tools.py` — 4 tools, guardrails server-side
- [x] Session binding; `session_token` only, never `account_code`
- [x] Per-quote lock + `WHERE status = 'PAID'` guard
- [x] tx hash written before the receipt wait
- [x] Treasury check includes gas ceiling + buffer
- [x] Placeholder supplier addresses refused **before** payment

Tests — **73 passed**
- [x] unsaved supplier rejected
- [x] supplier belonging to another customer rejected
- [x] placeholder supplier address refused before any link is issued
- [x] over the limit / below minimum / invalid amounts rejected
- [x] expired, unpaid quote cannot get a link
- [x] same quote returns the same link (one Paystack initialize)
- [x] verify while abandoned / failed sends nothing
- [x] amount and currency mismatch escalate without sending
- [x] **`verify_and_settle` twice sends exactly one transfer**
- [x] pending tx is not re-sent
- [x] tx hash + `SETTLING` persisted before the receipt wait
- [x] treasury low after payment leaves status `PAID`
- [x] gas counts against the treasury (fails at amount+buffer+gas)
- [x] native gas shortfall blocks quoting
- [x] wrong PIN 3× locks; unknown code and wrong PIN identical
- [x] KD-002 session cannot quote for, link, or settle a KD-001 quote
- [x] expired session rejected
- [x] every tool returns the `{ok, code, data, say}` envelope
- [x] chain config from env; Monad config differs only by env
- [x] native 18 dp vs ERC-20 6 dp maths pinned

## Phase 2 — Real Paystack
- [x] `paystack.py` — httpx, 10 s timeout, one retry on 5xx/timeout
- [x] `scripts/paystack_doctor.py` — diagnoses all five common key walls
- [x] `scripts/smoke_paystack.py` — initialises a link
- [x] Key verified live: `GET /balance` 200, `POST /transaction/initialize` 200
- [x] Human paid success test card → `SETTLED`, one on-chain transfer, second call `ALREADY_SETTLED`
- [x] Abandoned link → `PAYMENT_NOT_COMPLETED`, treasury unchanged (`scripts/verify_unpaid.py`)
- [ ] Failed test card → `PAYMENT_FAILED` (needs one declined-card checkout in a browser)

**Status:** success and abandoned verified end to end. Declined card is the only unrun case.

## Phase 3 — Real chain
- [x] `chain.py` — ERC-20 balance, transfer, receipt, pending nonce, 45 s wait, fee history, gas estimate with fallback
- [x] Chain id asserted against `CHAIN_ID` at call time
- [x] Explorer URL built from `EXPLORER_TX_URL`
- [x] `scripts/smoke_chain.py`
- [x] Gate repeated through `chain.py` with a funded treasury
- [x] Receipt decoded independently: 1 mined tx, status 1, ERC-20 `Transfer` to the seeded supplier address

## Phase 4 — MCP server
- [x] 4 tools on `FastMCP(stateless_http=True, json_response=True)`
- [x] Bearer middleware; `/health` + `/paid` exempt
- [x] `/health` → `{"ok": true}`; `/paid` → HTML
- [x] Request forensics → `logs/inbound.jsonl` (auth redacted, JSON-RPC method, `params._meta`)
- [x] `scripts/mcp_client_test.py`, `scripts/http_smoke.py`
- [x] Local verification: `/health` 200, `/paid` 200, no token 401, wrong token 401, correct token 200
- [x] Full happy path through the MCP client: quote → link → pay → `SETTLED` → explorer link
- [x] Double "I've paid" over MCP: second call `ALREADY_SETTLED`, one transfer
- [x] `/paid` page renders in a real browser after Paystack redirect
- [ ] Watch for 406 on `Accept` when Chord calls

## Phase 5 — Deploy
- [x] `render.yaml` — secrets `sync: false`, chain config in file
- [ ] Set env vars in Render dashboard
- [ ] Run `mcp_client_test.py` against the public URL
- [ ] Note cold-start behaviour

## Phase 6 — Skill
- [x] `SKILL.md` (frontmatter: name + description only)
- [x] `references/desk-policy.md`
- [x] `references/faq.md` (8 questions)
- [x] Error table covers every code; escalation codes marked
- [x] Never repeat PIN or token rule

## Phase 7 — Chord (human drives the app)
- [ ] Create teammate, upload skill folder
- [ ] Register MCP server (bearer, streamable_http)
- [ ] Restrict teammate to this server only
- [ ] Allow only the 4 tool names
- [ ] Health probe — read `status` in the body
- [ ] Publish + activate; in-app chat, then simulator
- [ ] Record credits used per conversation

## Phase 8 — Write-up
- [x] `README.md` (run, env, Paystack keys, Arc facts, deploy, Chord, red-team, AI usage)
- [x] `docs/FIELD_NOTES_RAW.md` — 6 real entries
- [ ] `docs/FIELD_NOTES.md` — human to write from the raw entries
- [x] `docs/GO_LIVE.md`
- [x] `docs/SUBMISSION.md`
- [x] `docs/LATER.md`, `docs/QUESTIONS.md`
- [ ] Record 3 minutes
- [ ] Upload to Drive, reply to Emmanuel

## Scope fence (§10) — respected
No dashboard, no frontend beyond `/paid`, no live FX API, no KYC, no refunds,
no adding suppliers in chat, no multiple chains (one configurable chain), no
webhook, no auth beyond bearer.
