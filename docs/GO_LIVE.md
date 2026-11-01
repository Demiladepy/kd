# Go-live note (for the desk owner)

Read this before you take real customer naira.

## What KudiDesk does

On WhatsApp, a known customer can:

1. Sign in with account code + PIN  
2. Get a locked naira quote for a USD supplier invoice  
3. Pay that naira on Paystack  
4. After payment is verified, send dollar stablecoin to a **supplier already on file**  
5. Get a public explorer link as proof  

## What it does not do

- Add a new supplier or change a wallet in chat  
- Refund anyone  
- Handle other currencies  
- Negotiate the rate  
- Trust a screenshot as proof of payment  

Those stay with a human.

## Must be true before real customers

| Item | Why |
|---|---|
| Live Paystack keys + verified business | Demo uses `sk_test_` only. Server refuses `sk_live_` today on purpose. |
| WhatsApp Business number on the agent | Simulator is not production. |
| Treasury on mainnet, under multisig/custody | Do not leave a raw private key in a server env var. |
| KYC/KYB on importers and suppliers | Compliance before volume. |
| Legal review for crypto/FX desk in Nigeria | Do not skip this. |
| Live FX rate + written spread policy | Today the rate is typed into `seed.json`. |
| Database that survives redeploy | Demo SQLite on Render free disk can reset. |
| Paystack webhook | Demo waits for the customer to say “I’ve paid.” That is not safe at scale. |

## When something breaks

| What you see | Meaning | What to do |
|---|---|---|
| Payment failed or abandoned | No money moved | Customer retries the same link |
| Paid but `TREASURY_LOW` | Naira in, payout blocked | Top up treasury; pay that quote manually same day |
| Settlement pending / timeout | Tx may still be mining | Watch the explorer link. Do **not** resend — the system will not double-pay |
| `SETTLE_FAILED` | On-chain failure | Check explorer; refund or repay by hand |

**Daily:** keep two days of payouts plus gas in the treasury, and reconcile
inflows against outflows by ERC-20 USDC address and tx hash — never sum raw
`Transfer` logs.
