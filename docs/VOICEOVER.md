# Voiceover script (~2:45–3:00)

Speak naturally. Short pauses where it says `[beat]`. Match cuts to your video.

---

**0:00 — Simulator open**

Lagos importers already pay China suppliers on WhatsApp. Today that means
screenshots, shaky rates, and money going to the wrong wallet.  
KudiDesk is a Chord agent that runs that desk end to end — with guardrails.

**0:20 — Auth**

Customer signs in with account code and PIN.  
`[open How I did this]`  
That’s a real tool call — `start_session` — not the model inventing identity.

**0:45 — Quote**

They want to pay Yiwu Lighting twelve dollars.  
`[show quote]`  
The naira total comes from the server as a locked quote. The model does not make
up the rate.

**1:05 — Paystack link**

Customer confirms. We create a Paystack checkout link — test mode.  
`[show link / How I did this → create_naira_payment]`

**1:25 — Paid + settle**

They pay, then say they’ve paid.  
`[settle message]`  
We verify with Paystack first. Then we send dollar stablecoin only to a supplier
already on file.  
`[open explorer]`  
Here’s the public proof on Arc testnet.

**2:10 — Red team**

If someone asks to send to a new wallet address…  
`[refuse]`  
We refuse and hand off to a human. The agent can never choose where money goes.
That’s the product.

**2:35 — Close**

Code and notes are in the repo — including what broke on Arc decimals, Paystack
emails, and Chord’s MCP health on a cold server.  
Go-live note covers what must be true before real customers.  
Agent is live on the WhatsApp simulator for you to try.

---

## How to record the voice (pick one)

**Best for hiring (recommended):** your own voice on a phone, quiet room, then
drop the audio onto the video in CapCut / Premiere / DaVinci.

**Best AI voice if you will not narrate:** [ElevenLabs](https://elevenlabs.io) —
most natural English; pick a calm conversational voice, paste this script,
export MP3, align in CapCut.

**Best if the video is already cut and you need sync + edits:**
[Descript](https://www.descript.com) — paste script as Overdub / record
yourself, edit by transcript, export.

Avoid CapCut’s default AI voices for this submission — they sound generic and
undermine the “honest builder” signal.
