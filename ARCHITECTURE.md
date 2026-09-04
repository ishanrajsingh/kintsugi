# Kintsugi: System Architecture

## The problem

A failed payment is not a dead transaction. It is a decision problem that most
systems solve with a `for` loop.

The industry default is to retry at fixed offsets: an hour, a day, three days —
and send a fixed sequence of reminders, with no reference to *why* the payment
failed. That is not stupid; it recovers real money. It is blind. It retries
closed accounts. It messages customers at 3am. It hammers an account that has no
balance on the 28th and gives up before payday on the 1st. And it keeps
retrying into a bank that is currently down.

Kintsugi treats each open payment as a sequential decision under uncertainty:
given what we know, what is the most valuable thing to do about this claim, and
is *now* the moment to do it?

## The decision

Every action is priced in rupees and the largest wins:

```
EV(retry on rail r)   = P(authorises now | cause, time, rail, issuer) × amount − attempt cost
EV(nudge on channel c)= P(money arrives  | cause, time, channel)      × amount − send cost − churn risk × amount
EV(wait until t)      = max over actions available at t, discounted for expiry risk
EV(stop)              = 0
```

The critical term is `EV(wait)`. Waiting is a **first-class action evaluated
against future moments**, not a default gap between retries. A fixed schedule
asks "has enough time passed?"; Kintsugi asks "is there a better moment coming,
and is it worth waiting for?" For a balance failure on the 26th, the answer is
usually yes: payday is worth more than any number of retries before it.

### Acting now does not forfeit the future

The comparison between acting and waiting is *not* between two alternatives,
and getting this wrong cost real recovery. If the retry fires now and fails,
the better moment is still there afterwards. So the agent compares

```
act now  =  EV(now)  +  P(now fails) × V(best future moment)
wait     =                             V(best future moment)
```

which reduces to acting whenever `EV(now) > P(now succeeds) × V(future)` — that
is, wait only when *succeeding now* would forfeit more future value than acting
is worth. With attempts costing 15 paise against payments worth hundreds of
rupees, that condition is usually false, and the right move is to act and
re-evaluate.

An earlier version compared them as mutually exclusive and consequently
deferred payments past their own expiry: it recovered 75.8% where a
fixed-schedule rules baseline recovered 78.1%, purely by waiting for moments it
then never used.

### Contact is priced per person, not per payment

A 20-paise SMS clears its expected-value bar against almost any payment, so
price alone will message a customer forever. The real cost of contact is
goodwill, and goodwill is spent per *person* and shared across every payment
that person owes. The agent therefore keeps a per-customer contact ledger and a
hard frequency cap, which is exactly why every production dunning system has
one.

## Component map

```mermaid
flowchart TB
    subgraph obs["Observable: what a real gateway sees"]
        RAW["Raw decline string<br/>'91 - Issuer or switch inoperative'<br/>'Z9: Insufficient balance'<br/>'insufficient_funds'<br/>'payment_declined_due_to_high_traffic'"]
    end

    subgraph tax["Taxonomy: normalise open-ended text"]
        RULES["Rule engine<br/>100% on known strings<br/>free, instant, auditable"]
        CACHE["Cache<br/>seen once, never asked again"]
        LLM["Language model<br/>95% on unseen strings<br/>validated against the enum"]
        RULES -->|no match| CACHE -->|miss| LLM
    end

    subgraph agent["Agent"]
        MON["Issuer health monitor<br/>CUSUM on technical decline rate<br/>96% precision at 60k payments<br/>(ablation: contributes nothing)"]
        PRED["Calibrated predictors<br/>P(retry authorises)<br/>P(nudge recovers)<br/>ECE 0.003"]
        EV["Expected-value policy<br/>prices retry / nudge / wait / stop"]
        MON --> EV
        PRED --> EV
    end

    subgraph act["Actions"]
        RETRY["Retry<br/>rail + timing"]
        NUDGE["Nudge<br/>channel + copy"]
        WAIT["Wait until t"]
        STOP["Stop<br/>with a reason"]
    end

    COPY["Message writer<br/>cause-aware copy<br/>validated before send"]
    LEDGER["Decision ledger<br/>every action + the priced<br/>alternatives that lost"]
    ASK["Merchant Q&A<br/>retrieval is deterministic<br/>every figure verified"]

    RAW --> RULES
    tax --> MON
    tax --> EV
    EV --> RETRY & NUDGE & WAIT & STOP
    NUDGE --> COPY
    EV --> LEDGER --> ASK
```

## Where the language model is, and deliberately is not

**It is used in three places**, each chosen because open-ended natural language
is the thing it is actually better at than a rule table:

1. **Normalising decline strings.** There is no shared decline vocabulary in
   Indian payments. A card decline arrives as ISO 8583 (`"51"`), a UPI decline
   as an NPCI code (`"Z9"`, `"U30"`), Razorpay surfaces its own `reason`
   identifiers (`insufficient_funds`, `payment_declined_due_to_high_traffic`),
   and every bank and PSP wraps those in its own free text — often truncated,
   sometimes misspelled, occasionally just `"Payment failed"`. New templates
   ship without notice.

   The catalogue carries Razorpay's published vocabulary verbatim rather than
   invented strings. Their `source` field (customer / business / gateway /
   razorpay) turns out to be an independent derivation of the same idea as this
   project's `Disposition`: `gateway` maps overwhelmingly onto `RAIL_SWITCH`,
   `customer` splits across `NEEDS_CUSTOMER` and `TERMINAL`, which is
   reassuring precisely because the two were arrived at separately.
2. **Writing customer-facing copy**, conditioned on the failure cause. A
   customer who is short on balance and one who closed the app before entering
   their PIN need completely different messages, and *"your payment failed,
   please try again"* is wrong for both.
3. **Answering the merchant's questions** over the decision ledger. Retrieval
   and arithmetic stay deterministic and the model only phrases the retrieved
   facts, so every figure exists before it is called -- and the answer is then
   verified against those facts, with any unsupported number causing the
   generated text to be discarded.

**It does not choose actions.** Deciding which payment to chase is a
calibrated-probability problem against a cost model. A language model asked to
do it produces fluent, confident, *unpriced* guesses, and a fluent wrong answer
is indistinguishable from a right one, so it would misprice retries with no way
to notice. Keeping it out of the decision loop is a design decision, not an
omission.

All three surfaces are **constrained, validated, and optional**:

| | Taxonomy | Messaging | Explanation |
|---|---|---|---|
| Output space | 13 known labels | short text | short text |
| Validation | must parse to the enum, else `UNKNOWN` | length, no invented offers/refunds/phone numbers, no unresolved placeholders | every figure must appear in the retrieved ledger facts |
| Caching | per string; vocabularies are small and repetitive | per (cause, channel); 39 combinations total | n/a — answers are per question |
| If unavailable | rules only, residue marked `UNKNOWN`, handled conservatively | deterministic template per cause | deterministic fact summary |

The system runs correctly with **no model at all**. A payments component that
stops working when an inference endpoint is down has no business near the
authorisation path.

## Layers

### 1. World (`kintsugi/world/`)

A simulated payments book, because no public dataset of payment *failures*
exists: issuers and PSPs do not publish transaction-level decline data.

Failures are generated **cause-first from latent state**, not sampled from a
static table. Each attempt runs a sequence of gates, and each gate is keyed to
the timescale on which that condition actually changes:

| Gate | Keyed by | So a retry… |
|---|---|---|
| Instrument alive | payment | never helps |
| Issuer healthy | wall-clock health timeline | helps once it recovers |
| Balance sufficient | payment + **day** | helps after payday |
| Within limits | payment + **day** | helps tomorrow |
| Risk accepted | payment + attempt | may help immediately |
| Customer authorises | payment + attempt + hour | helps if well timed |

One further distinction matters more than it looks: **being able to re-prompt
the payer is not the same as needing them present.** A UPI *collect* request is
merchant-initiated, so a retry pushes a fresh approval request into the payer's
app and genuinely re-prompts. A UPI *intent* payment is payer-initiated: they
tapped Pay and were deep-linked out, and netbanking is a redirect the payer
drives; for those, no server-side retry reaches anyone, and the only way back is
to send the customer a message.

Modelling every customer-present rail as re-promptable made outbound messaging
vestigial: retries were simply cheaper reminders, and the agent's best
configuration sent *zero* messages. That was an artefact of the abstraction, not
a finding about payments, and it was caught only because pricing customer
attention produced a result too clean to believe.

Because two of the gates reset at **midnight**, the feature set carries
explicit calendar-boundary features. Elapsed time cannot express the
distinction: 23:50 → 00:10 is twenty minutes and a completely different day.
Without them the agent retried `LIMIT_EXCEEDED` failures inside the same day,
where a daily limit cannot have reset, and scored 65.9% against the baseline's
92.9%.

The keying is the whole point. Because the balance gate is keyed by day,
retrying twenty minutes later draws the *same* value and fails again — as it
would in reality, since no money arrived. Under naive per-attempt sampling a
retry is just another roll of the dice, so any policy that retries more recovers
more, and the evaluation measures persistence rather than intelligence. (The
first version of this simulator had exactly that bug: blind `fixed_retry` beat
the smart rule-based policy 98.9% to 96.8%.)

### 2. Calibration (`kintsugi/calibration.py`, `world/fitting.py`)

Hazard scales are **fitted, not hand-tuned**. Iterative proportional fitting
solves for per-segment scales that reproduce published marginals. Fitting them
per segment rather than globally is what makes the problem well posed: checkout
and mandate debits have different published success rates *and* different cause
mixes, and one shared scale per cause cannot satisfy both.

Every calibration constant carries its provenance: `PUBLISHED`, `DERIVED`, or
`ASSUMPTION`, and the table is emitted into the results, so a reader can audit
exactly how much of the model is evidence and how much is us.

### 3. Agent (`kintsugi/agent/`)

- **Health monitor** — CUSUM change detection on per-issuer *technical decline
  rate*. Measured at 96% precision, and shown by ablation to contribute nothing
  to this agent's decisions: the failure taxonomy already carries the signal.
  Kept, documented, and reported as such. Not overall success rate: with a meaningful recurring segment, baseline
  failure is ~25% because mandate debits bounce on balance, which swamps the
  outage signal entirely (recall 1.3%). Technical decline separates cleanly —
  0.7% healthy, 11.9% degraded, 49.6% outage. This is also what NPCI publishes
  per bank.
- **Predictors**: gradient-boosted trees, isotonically calibrated. Trained on
  data from *randomised explorer* policies, never from a sensible policy: a
  policy's own logs have no support where it never acts, so a model fitted on
  them would confidently recommend actions whose consequences were never
  observed.
- **Policy**: the EV optimiser above, with terminal causes settled by the
  taxonomy rather than the model. No probability estimate can talk the agent
  into retrying a closed account.

### 4. Evaluation (`kintsugi/eval/`)

Paired comparison under **common random numbers**. For each seed one world is
built and every policy runs against it; because randomness is counter-based, the
k-th attempt on payment *P* resolves against the same underlying draw whichever
policy made it. Policies face the same world payment-by-payment, so the shared
noise cancels.

CRN is easy to break by accident and fails *silently*: the intervals keep
printing as if nothing happened. So the harness asserts it: `verify_crn` checks
that every policy saw byte-identical first attempts on every payment, and the
evaluation refuses to report if that fails.

The sensitivity sweep re-runs the whole comparison with each `ASSUMPTION`
constant moved well above and below its default, including settings actively
hostile to the agent.

## Seed discipline

Nothing is reported on the worlds it was fitted on.

| Purpose | Seeds |
|---|---|
| Predictor training | 2000–2029 |
| Detector threshold tuning | 11–13 |
| Detector reporting | 101–105 |
| Policy evaluation | 1000–1203 |

## Running it

```bash
python -m kintsugi.world.fitting      # refit the world to published marginals
python -m scripts.train_predictor     # train predictors on exploration data
python -m scripts.run_evaluation      # paired evaluation -> data/results.json
python -m scripts.run_sensitivity     # assumption sweep
pytest                                # 80 tests
```

Everything runs on CPU with no paid services. The language model defaults to a
local one via Ollama; a free hosted tier or a paid API is used only if a key is
present, and the system degrades cleanly to rules and templates when none is.
