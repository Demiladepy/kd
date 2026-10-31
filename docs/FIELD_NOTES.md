# Field Notes

Three problems I hit while building. Each one was real. Raw scrapes are in
[`FIELD_NOTES_RAW.md`](FIELD_NOTES_RAW.md).

---

## 1. Arc USDC has two decimal systems

**What happened**

I checked the same wallet with `eth_getBalance` and ERC-20 `balanceOf()`. The
numbers looked unrelated until I divided them:

| Address (short) | Native ÷ 1e18 | ERC-20 ÷ 1e6 |
|---|---|---|
| `0x9143…87ec` | 223.473480851711701627 | 223.473480 |
| `0xd731…9c82` | 85.604548819568282194 | 85.604548 |
| `0x24a0…0d1a` | 5.483392876667516447 | 5.483392 |

Same USDC. Native uses 18 decimals. ERC-20 uses 6. Ratio is about 1e12.

**Cause**

I treated `eth_getBalance` like a dollar balance. On Arc it is not.

**Fix**

Money checks use `balanceOf()` only. Native balance is for gas. A unit test locks
the 1e12 relationship so nobody “simplifies” this later.

**Ask for Chord**

Put one worked example in the Arc notes: native vs ERC-20 side by side. Builders
who miss this think the treasury is empty — or approve a payout they cannot fund.

---

## 2. Paystack rejects `.test` emails

**What happened**

First live `POST /transaction/initialize` failed:

```text
HTTP 400
"email" must be a valid email
```

I was using addresses like `kd-001@customers.kudidesk.test` from the plan.

**Cause**

I tried five addresses. Anything ending in `.test` failed. `example.com` worked.
Paystack wants a real TLD. `.test` is reserved and never will be.

**Fix**

Receipt emails are now `{account_code}@customers.example.com`. Valid for the API,
not a real inbox. Covered by a unit test.

**Ask for Chord**

If sample code invents emails for Paystack, use `example.com`, not `.test`. The
error message blames the whole email field, so you waste time on the wrong part.

---

## 3. One payout shows two Transfer logs

**What happened**

I decoded the first real settlement receipt. Same 12 USDC, same parties, two
`Transfer` events — one at 18 decimals on the native token address, one at 6
decimals on the USDC contract.

**Cause**

Same decimals split as above. Arc emits both. If you sum Transfers by
from/to only, books look 2× too high.

**Fix**

We do not sum logs for reconciliation. We use ERC-20 balances and the tx hash as
the idempotency key. The go-live note tells the operator the same rule.

**Ask for Chord**

Document this next to the decimals note. A silent 2× error shows up at month-end,
not in the first demo.

---

## 4. Chord MCP health timed out on a sleeping Render box

**What happened**

Workspace showed `kudidesk` Enabled. Chord → Tools / Health returned **504**.
WhatsApp simulator then said it had no payment tools — skill loaded, MCP not
reachable in that session.

**Cause**

Free Render sleeps when idle. Cold start can take 30–50s. Chord’s probe gave up
before the process was up. Our own client worked after waking `/health` first.

**Fix / workaround**

Hit `https://kudidesk.onrender.com/health` until `{"ok":true}`, then re-run
Health / Tools in Chord. For demos, wake the box before the reviewer opens the
simulator.

**Ask for Chord**

Longer timeout on MCP health for known cold hosts, or a clearer error like
“upstream timed out / try again” instead of a bare 504. Also: teammate Tools UI
made it hard to see that a workspace MCP was already attached — “Add tool” only
opened the workspace registry again.

---

## Other real issues (raw log)

MCP 2.x rename vs pinned v1, 421 Misdirected Request on tunnel hostnames,
`.env` not loaded so a placeholder bearer was used, `eth_estimateGas` on an
empty treasury, refusing placeholder supplier addresses before payment. Details
in `FIELD_NOTES_RAW.md`.
