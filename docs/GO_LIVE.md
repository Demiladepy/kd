# Go-Live Checklist (for non-technical owner)

## What it does / doesn't do
**Does:** Quote naira rates, collect via Paystack, settle USDC to pre-saved suppliers on testnet.  
**Doesn't:** Add suppliers in chat, handle refunds, do KYC, use live money, or choose wallet addresses.

## Before real customers
- [ ] **Live Paystack keys** and verified business account
- [ ] **WhatsApp Business number** connected
- [ ] **Real treasury** on mainnet chain with custody plan (multisig/custodian, not raw key on server)
- [ ] **KYC/KYB** on importers and suppliers
- [ ] **Regulatory check** on running crypto/FX desk in Nigeria
- [ ] **Live rate feed** with spread policy
- [ ] **Persistent database** (not ephemeral like Render free tier)
- [ ] **Paystack webhook** (so settlement doesn't depend on customer saying "paid")

## When things break
- **Failed payment:** No money moves. Customer can retry.
- **Paid but not settled:** Owner alerted with quote ID. Check explorer link.
- **Stuck tx:** Check explorer link, escalate to treasury operator.
- **On-call:** Designate someone to monitor payments daily
- **Treasury:** Daily top-up monitoring with alert thresholds
- **Database:** Backup strategy for payment records
