# KudiDesk Build Checklist

Source of truth: `PLAN.md`. One phase at a time; run the named tests/scripts and report pass/fail.

## Phase 0 — Gate
- [x] `scripts/gate_send_usdc.py` — loads `.env`, prints treasury ETH + USDC, sends 1 USDC to supplier wallet 1, waits for receipt, prints explorer URL
- [ ] **PASS = mined tx with status 1** (needs the human's funded test wallets + Base Sepolia faucet)

**Status:** script ready, blocked on funded test wallets.

## Phase 1 — Core logic, no network
- [x] `server/store.py` — SQLite state machine, quotes, sessions, PIN attempts
- [x] PBKDF2 PIN hashes in `seed.json` (no plaintext PINs)
- [x] Pricing: `round_half_up(usd × ngn_per_usd × (1 + fee/100))`, Decimal only
- [x] `paystack.py` / `chain.py` behind interfaces, fakes in `tests/fakes.py`
- [x] `tools.py` — 4 tools, all guardrails server-side
- [x] Session binding: every tool takes `session_token`, never `account_code`
- [x] Per-quote lock + `WHERE status = 'PAID'` guard
- [x] tx hash written before the receipt wait

Tests — **48 passed**
- [x] unsaved supplier rejected
- [x] supplier belonging to another customer rejected
- [x] over the limit rejected
- [x] below minimum rejected
- [x] invalid amounts (0, negative, non-numeric, 3 dp) rejected
- [x] expired, unpaid quote cannot get a link
- [x] same quote returns the same link (one Paystack initialize)
- [x] verify while abandoned sends nothing
- [x] amount mismatch escalates without sending
- [x] currency mismatch escalates without sending
- [x] **`verify_and_settle` twice sends exactly one transfer**
- [x] pending tx is not re-sent
- [x] tx hash + `SETTLING` persisted before the receipt wait
- [x] treasury low after payment leaves status `PAID`
- [x] wrong PIN 3× locks the account
- [x] unknown account code and wrong PIN return the same code
- [x] KD-002 session cannot create a link for, or settle, a KD-001 quote
- [x] expired session rejected
- [x] every tool returns the `{ok, code, data, say}` envelope

## Phase 2 — Real Paystack
- [x] `paystack.py` with httpx, 10 s timeout, one retry on 5xx/timeout
- [x] `scripts/smoke_paystack.py` initialises a link
- [ ] Human pays success test card → verify returns `success`
- [ ] Failed test card → `PAYMENT_FAILED`
- [ ] Abandoned link → `PAYMENT_NOT_COMPLETED`

**Status:** code ready, needs test keys + a human to pay.

## Phase 3 — Real chain
- [x] `chain.py` — balance, transfer, receipt check, 45 s wait, nonce lock
- [x] `scripts/smoke_chain.py`
- [ ] Gate repeated through `chain.py`

**Status:** code ready, needs faucet USDC + ETH on Base Sepolia.

## Phase 4 — MCP server
- [x] 4 tools registered on `FastMCP(stateless_http=True, json_response=True)`
- [x] bearer auth middleware, `/health` + `/paid` exempt
- [x] `/health` → `{"ok": true}`
- [x] `/paid` → HTML page
- [x] request forensics → `logs/inbound.jsonl` (headers redacted, JSON-RPC method, `params._meta`)
- [x] `scripts/mcp_client_test.py`
- [x] `scripts/http_smoke.py` — verified locally:
  - `/health` 200 `{"ok":true}`, `/paid` 200
  - no token → 401, wrong token → 401
  - correct token → 200 MCP `initialize` result
- [ ] Full happy path through the MCP client with a human paying the link
- [ ] Watch for 406 `Accept` header issues when Chord calls

## Phase 5 — Deploy
- [x] `render.yaml` (uvicorn start command, env vars marked `sync: false`)
- [ ] Set env vars in Render dashboard
- [ ] Run `mcp_client_test.py` against the public URL
- [ ] Note cold-start behaviour

## Phase 6 — Skill
- [x] `SKILL.md` (frontmatter: name + description only)
- [x] `references/desk-policy.md`
- [x] `references/faq.md` (8 questions)
- [x] Error table covers every code, escalation codes marked
- [x] Never repeat PIN or token rule included

## Phase 7 — Chord (human drives the app)
- [ ] Create teammate, upload skill folder
- [ ] Register MCP server (bearer, streamable_http)
- [ ] Restrict teammate to this server only
- [ ] Allow only the 4 tool names
- [ ] Health probe — read `status` in the body
- [ ] Publish + activate, test in-app chat then simulator
- [ ] Record credits used per conversation

## Phase 8 — Write-up
- [x] `README.md` (run, env, deploy, Chord, red-team table, AI usage)
- [x] `docs/FIELD_NOTES_RAW.md` — 2 real entries
- [ ] `docs/FIELD_NOTES.md` — human to write from raw entries
- [x] `docs/GO_LIVE.md`
- [x] `docs/SUBMISSION.md`
- [x] `docs/LATER.md`, `docs/QUESTIONS.md`
- [ ] Record 3 minutes
- [ ] Upload to Drive, reply to Emmanuel

## Scope fence (§10) — respected
No dashboard, no frontend beyond `/paid`, no live FX API, no KYC, no refunds,
no adding suppliers in chat, no multiple chains, no webhook, no auth beyond bearer.
