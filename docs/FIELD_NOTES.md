# Field Notes

*Three real entries, written as the problems happened. Raw logs are in
[`FIELD_NOTES_RAW.md`](FIELD_NOTES_RAW.md); nothing here was reconstructed.*

---

## The same USDC is 18 decimals and 6 decimals at once

**What happened:** before trusting a treasury balance, I compared
`eth_getBalance` with the ERC-20 `balanceOf()` for three live Arc addresses at
block 69,684,820:

```
address                                      native / 1e18        erc20 / 1e6
0x9143698409426ac33b277decc9f20fa9049887ec   223.473480851711701627  223.473480
0xd731d8b19205fe7a9a93ebed1da2f35d54af9c82    85.604548819568282194   85.604548
0x24a078b7eb595c6b0f43dbf574a7282931a50d1a     5.483392876667516447    5.483392
```

Ratio in every sample: ~1e12. Same asset, two scales.

**How I found the cause:** PLAN.md §2 flagged that sources disagree and told me
to verify on day one. The native number is not a 6-decimal dollar figure — it is
the same USDC at 18 dp, with sub-micro dust that `balanceOf()` truncates.

**Fix / workaround:** `server/chain.py` never mixes the two. Every money read uses
ERC-20 `balanceOf()`; the native balance is used only for gas, converted by an
explicit `native_to_usdc()` that divides by 1e18. A unit test pins the 1e12
relationship so nobody "simplifies" it later.

**What Chord should change:** the simulator's Arc primer should state the two
scales side by side with one worked example. A builder who treats
`eth_getBalance` as dollars under-reports the treasury by 1e12 — it looks empty,
or worse, a payout looks affordable when it is not.

---

## Paystack rejects the email address the plan specifies

**What happened:** the first real `POST /transaction/initialize` against the
Paystack test API, using PLAN.md §4.3's generated receipt address:

```
HTTP 400
{"status": false, "message": "\"email\" must be a valid email"}
```

**How I found the cause:** five addresses through the same endpoint, same key,
fresh reference each time:

```
BAD 400  doctor@customers.kudidesk.test   "email" must be a valid email
BAD 400  kd-001@customers.kudidesk.test   "email" must be a valid email
BAD 400  kd-001@kudidesk.test             "email" must be a valid email
OK  200  kd-001@example.com               Authorization URL created
OK  200  kd-001@customers.example.com     Authorization URL created
```

So it is the **`.test` TLD**, not the domain, the subdomain, or the local part.
Paystack validates against a real-TLD allowlist, and `.test` is reserved by
RFC 2606 — it can never be on that list.

**Fix / workaround:** `create_naira_payment` now builds
`{account_code}@customers.example.com`: reserved, syntactically valid, accepted
by Paystack, and guaranteed undeliverable, which is what you want for a receipt
address. `test_paystack_email_uses_a_valid_tld` pins it.

**What Chord should change:** any prompt or sample code that generates an email
for a payment provider should use `example.com`, not `.test`. Three of the four
failing addresses were plausible; only the TLD was wrong, and the API's error
message points at the whole field.

---

## One settlement logs two `Transfer` events

**What happened:** verifying the first real payout
(`0x9937effa85f2ed4a553a6f522484fd7818ff7ab0b6b182403e86635e49013dfd`) by
decoding `receipt.logs` instead of trusting my own client output. Two
`Transfer(address,address,uint256)` events, same treasury, same supplier, same
12 USDC:

```
token  : 0xffffFFFfFFffffffffffffffFfFFFfffFFFfFFfE   amount: 12000000000000000000  (12e18)
token  : 0x3600000000000000000000000000000000000000   amount: 12000000              (12e6)
```

**How I found the cause:** the two token addresses are exactly the two decimal
scales from the entry above — Arc logs the transfer once from its native-token
address and once from the USDC ERC-20. Filtering by `from`/`to` alone returns
both.

**Fix / workaround:** settlement never aggregates logs — it reads ERC-20
`balanceOf()` before and after, and the transaction hash is the idempotency key.
`docs/GO_LIVE.md` now says a reconciliation job must filter by the ERC-20 token
address and dedupe by transaction hash, never "sum the transfers".

**What Chord should change:** this is the kind of detail that belongs in the
platform's Arc notes next to the decimals. Silent 2x errors in a payment desk's
books are found at month-end, not at build time.

---

## Also worth reading

`FIELD_NOTES_RAW.md` has the rest, all from real runs: the `mcp` 2.x rename that
breaks the plan's import path, the MCP 421 that only fires when the server binds
to loopback (strict locally, permissive in production), a bearer token that was
never loaded because the server skipped `load_dotenv()`, `eth_estimateGas`
reverting on an unfunded treasury, and a placeholder supplier address that would
have taken the customer's money for a payout that could not happen.
