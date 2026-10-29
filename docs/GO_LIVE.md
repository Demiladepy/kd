# Go-Live Checklist

**For the desk owner. Half a page. Read this before taking a single real naira.**

## What it does

Quotes a naira rate for a supplier invoice, collects the naira by card or bank
transfer through Paystack, confirms the money actually arrived, then pays the
supplier in dollar stablecoin and gives you a public link to the transfer.

## What it does not do

It cannot add a new supplier, change where money goes, refund anyone, handle a
second currency, or negotiate a price. Those always go to a human. It also does
not confirm payment by itself — see the webhook note below.

## Before real customers

- [ ] **Live Paystack keys** and a verified business (test keys start `sk_test_`, live `sk_live_`; the server refuses to boot on a live key today, on purpose)
- [ ] **WhatsApp Business number** connected to the agent
- [ ] **A real treasury on a mainnet chain**, held by a multisig or a custodian — never a raw private key in a server environment variable
- [ ] **KYC/KYB** on every importer and every supplier
- [ ] **Regulatory review** of running a crypto/FX desk in Nigeria before the first customer
- [ ] **A live rate feed** with a written spread policy; today the rate is typed into `seed.json`
- [ ] **A persistent database** — the demo uses SQLite on an ephemeral disk and loses state on redeploy
- [ ] **A Paystack webhook** so settlement does not depend on the customer typing "I've paid"

## When things break

| Situation | What it means | What to do |
|---|---|---|
| Payment failed or abandoned | **No money moved** | Nothing. The customer can retry the same link |
| Paid but not settled (`TREASURY_LOW`) | Customer's naira is in, payout did not happen | The alert carries the quote id. Top up the treasury and pay it manually the same day |
| Settlement timed out | Transaction is in flight | Open the explorer link from the alert and wait. **Never re-send** — the system will not send twice |
| Transaction reverted (`SETTLE_FAILED`) | Paid out but failed on-chain | Check the explorer link; refund or re-pay manually |

## Daily operating routine

- Check the treasury balance every morning. Keep at least two days of expected
  payouts, plus the gas buffer.
- Alert if the treasury falls below one day of expected volume.
- Reconcile Paystack collections against on-chain payouts daily.
- One named person on call for `TREASURY_LOW` and `SETTLE_FAILED` alerts, with a
  published response time during business hours.
