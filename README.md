# Kintsugi 金継ぎ

**An expected-value agent for recovering failed payments.**

*Kintsugi is the Japanese craft of repairing broken pottery with gold — the
break becomes part of the object's value rather than the end of its life.*

> A failed payment is not a dead transaction. It is a decision problem — and
> almost everyone solves it with a `for` loop.

Razorpay AI Buildathon 2026 · **AI Revenue Recovery** track

---

## The problem

India has the worst payment success rates of any major digital economy, and the
worst part of it is invisible. Checkout authorises around 90% of the time. But
**UPI Autopay — the rail carrying every subscription renewal in the country —
authorises 30–50%**. More than half of all recurring collections fail on first
attempt.

What happens next is almost always the same: retry at +1h, +1d, +3d, send two
reminder SMS, give up. No reference to *why* the payment failed. That loop:

- retries closed accounts and blocked cards, which can never succeed
- messages customers at 3am
- hammers an empty account on the 28th and gives up before payday on the 1st
- keeps retrying into a bank that is currently down

Each of those is a decision made blind. Kintsugi makes them explicitly.

## The idea

Every action gets a price in rupees, and the largest wins:

```
EV(retry on rail r)    = P(authorises now) × amount − attempt cost
EV(nudge on channel c) = P(money arrives)  × amount − send cost − churn risk × amount
EV(wait until t)       = best action available at t, discounted for expiry risk
EV(stop)               = 0
```

The load-bearing term is `EV(wait)`. **Waiting is a first-class action evaluated
against future moments**, not the default gap between retries. A fixed schedule
asks *"has enough time passed?"* Kintsugi asks *"is there a better moment
coming, and is it worth waiting for?"* For a balance failure on the 26th, the
answer is usually yes — payday beats any number of retries before it.

## Results

20 independent worlds x 12,000 payments over 30 days, 30% recurring.
Every policy faced the **identical** world payment-by-payment, and the pairing
is asserted before any statistic is reported: 12,000 payments across 4
policies, **0 first-attempt mismatches**.

| Policy | Recovery | Value recovered | Cost | Scheme violations | Messages | Wasted retries |
|---|---:|---:|---:|---:|---:|---:|
| Fixed retry + dunning (industry default) | 50.38% | 48.23% | INR 63,104 | 1,822 | 4,399 | 1,043 |
| Cause-aware rules (strong baseline) | 60.81% | 58.43% | INR 1,313 | 0 | 1,663 | 17 |
| **Kintsugi** | **65.72%** | **63.64%** | **INR 978** | **0** | **596** | **0** |

Against the strong baseline: **+8.90%** net value, winning **100% of 20 paired
worlds** (p < 0.0001) — while costing *less*, sending **64% fewer messages**,
and staying compliant.

The industry default's true cost is INR 63,104, of which **INR 61,130 is scheme
fines** — a liability its recovery rate never shows.

**It survives its own assumptions.** Every constant with no published source was
pushed well above and below its default, including settings chosen to be hostile
to the agent: **15 of 15** perturbations keep the lift significantly positive,
**0** negative, range **+5.59% to +13.29%**.

Full numbers, per-cause breakdown, and component measurements: **[RESULTS.md](RESULTS.md)**.
Design and rationale: **[ARCHITECTURE.md](ARCHITECTURE.md)**.

## Where the language model is — and deliberately is not

It does **three** things, each chosen because open-ended natural language is
what it is genuinely better at than a rule table:

**1. Normalising decline strings.** There is no shared decline vocabulary in
Indian payments. The same cause arrives as ISO 8583 `51`, as NPCI `Z9`, as
Razorpay's `insufficient_funds`, as `"A/c balance low"`, or as
`"Txn declined by bank (reason: balance)"` — and banks ship new templates
without telling anyone.

The catalogue carries **Razorpay's own published `reason` identifiers
verbatim** rather than invented strings: 129 strings across 13 classes, 39 of
them held out and never seen while the rules were authored. Measured on that
held-out set:

| | Strings the rules were written for (89) | Strings never seen before (39) |
|---|---:|---:|
| Rules alone | **100%** | **12.8%** |
| + language model | — | **79.5%** |

Rules never guess wrong: every string they cannot match returns `UNKNOWN` and is
handled conservatively, and *zero* held-out strings get a confident wrong class.
That gap is the argument for the model.

The model's remaining eight errors cluster almost entirely on boundaries where
the ground-truth label is itself arguable — `vpa_resolution_failed` (a bad
address, or the network failing to resolve it?), `transaction_on_vpa_restricted`
classed as `RISK_DECLINE` rather than `CARD_BLOCKED`, `debit_instrument_inactive`
as `INVALID_INSTRUMENT` rather than `ACCOUNT_CLOSED`. On at least three of them
the model's answer is defensible and mine is the debatable one.

Accuracy here is *lower* than an earlier 95% because the held-out set got
harder, not because the model got worse: Razorpay's terse snake_case identifiers
carry far less signal than prose like `"A/c balance low"`, and they draw finer
distinctions.

**2. Writing customer-facing copy**, conditioned on the failure cause. Someone
short on balance and someone who closed the app before entering their PIN need
completely different messages, and *"your payment failed, please try again"* is
wrong for both.

**3. Answering the merchant's questions** about what it did — *"why did you not
chase my ₹40,000 payment?"* Retrieval and arithmetic are deterministic: facts
are pulled from the decision ledger and summed in Python, so every number exists
before the model is called. The model only phrases them. Then the answer is
**verified** — any figure that does not appear in the retrieved facts causes the
generated answer to be discarded in favour of the deterministic summary. A
grounded generator that is never audited is just a fluent one.

**It does not choose actions.** Deciding which payment to chase is a
calibrated-probability problem against a cost model. A language model asked to
do it produces fluent, confident, *unpriced* guesses — and a fluent wrong answer
is indistinguishable from a right one, so it would misprice retries with no way
to notice. Keeping it out of the loop is a design decision, not an omission.

All three surfaces are **constrained, validated, and optional**. Taxonomy output
must parse to one of 13 known labels or it becomes `UNKNOWN`. Message copy is
rejected if it exceeds the channel limit, leaves a placeholder unresolved, or
invents an offer, refund, deadline or phone number the system cannot honour.
Explanations are rejected if they contain a figure that is not in the ledger. In
every case a deterministic fallback ships instead — so **the system runs
correctly with no model at all.**

## Scheme rules are constraints, not costs

Retry behaviour in India is governed by rules that are not economic trade-offs,
and an expected-value engine that treats them as prices will break them:

- **NPCI UPI Autopay** (effective 1 Aug 2025): one main debit plus at most
  **three** retries per mandate, executable only in **non-peak windows** —
  before 10:00, 13:00–17:00, and after 21:30.
- **Visa**: card-not-present resubmissions capped at **15 per card per 30 days**,
  with an excessive-reattempt fee beyond it.
- **Both major schemes**: reattempting a decline in the *never-retry* category
  is prohibited outright.

So compliance sits **above** the pricing engine and filters the action set
before anything is valued. No probability estimate can buy past it. The layer is
shared by every serious policy rather than reserved for the agent, because
reserving mandatory rules for the learned policy would manufacture a lead that
has nothing to do with decision quality.

Only the naive fixed schedule breaches — and its headline recovery rate hides
every one of those fines.

Obeying the rules is not free, and `scripts/run_compliance_cost.py` measures
what it costs by running the agent against identical worlds with its rulebook
neutered: **1.6pp of recovery and 2.0pp of value**, in exchange for avoiding
482 violations and about INR 24,000 in fines per 8,000 payments. That variant
exists only in the measurement script — "ignore NPCI" is not a setting a
payments system should expose.

## Does the simulated world behave like the real one?

The world is calibrated to **first-attempt marginals only**. Nothing about
recovery, retry timing, or the value of a schedule change enters that fit — so
these published figures, found after the model was built, are all out-of-sample:

| Quantity | Published | Simulated | |
|---|---:|---:|---|
| Hard declines as a share of failures | 10–15% | 12.5% | ok |
| Cause-aware rules recovery | 45–60% | 59.8% | ok |
| Learned agent recovery | 55–80% | 66.4% | ok |
| Three extra retries in the dunning window | +20.2% | +29.6% | ok |
| First retry moved +2h → +24h | +6.5% | **+5.1%** | ok |
| Fixed-schedule recovery | 15–25% | 50.2% | **miss** |

That timing row took two refuted hypotheses to reach. Measured in isolation the
effect was **+70.7%** — eleven times the published figure. Restricting to card
payments made it *larger* (+76.3%), killing the population-difference
explanation. Only measuring it the way a dunning A/B actually does — moving the
first retry inside an existing three-retry schedule, where later attempts
recover most of what an early one misses — reproduced it at +5.1%.

That investigation also found a real defect: keying the balance draw strictly to
the calendar day made midnight an impassable wall, and balances move intraday.

The remaining miss is stated, not reconciled. The 15–25% band is measured on
card subscription books where most failures sit on stale credentials; this is a
mixed checkout book whose failures are far more recoverable.

## Where this sits in Razorpay's own AI stack

Razorpay already ships AI for payment success, and this is deliberately not a
re-implementation of any of it:

| Their system | What it decides | When |
|---|---|---|
| **Optimizer** | which gateway to route to, over 150+ parameters | at authorisation |
| **Doppler** | reroute traffic when a failure is detected, within seconds | at authorisation |
| **Vulcan** | a payments foundation model | upstream of both |
| **Kintsugi** | whether and when to act on a payment that already failed | *after* authorisation |

Optimizer and Doppler both act on the **spatial** axis — which endpoint, which
gateway, right now. Kintsugi acts on the **temporal** one: given that
authorisation has already failed on every route available, is this worth
chasing, by what means, and at what moment. Razorpay's Optimizer documentation
covers routing rules and gateway priority and stops there; retry logic and
post-authorisation recovery are not in its scope.

They compose in the obvious direction. Better routing shrinks the pool this
agent works on; this agent makes better use of whatever still fails.

**One honest overlap, and the ablation settles it.** Doppler detects issuer
failures in seconds, and this project also built an issuer health detector.
The ablation found that detector contributes *nothing* to per-payment recovery
decisions, because the failure taxonomy already carries the signal — an
attempt returning `ISSUER_DOWN` has said the bank is unavailable. So the
overlap resolves the right way: failure detection belongs in the routing layer
where Razorpay already has it, not duplicated inside a recovery agent. That
conclusion was reached from the ablation before this comparison was written,
which is the only reason it is worth anything.

## Running at payments scale

Razorpay's UPI switch handles ~10,000 transactions per second and the stack is
built for a billion transactions a day. A recovery agent that cannot keep up is
a research artefact, so the cost is measured rather than assumed:

- **~4.9 decisions per failed payment** over its lifetime
- **~1 ms per decision** for feature construction and the expected-value search
- **~2.5 ms per model call**, two batched calls per decision, with threads
  pinned (see `kintsugi/__init__.py` — the default thread pool made this 28x
  slower)

Recovery is not on the authorisation path: it runs asynchronously against
payments that have *already* failed, so its latency budget is seconds, not
milliseconds. At a billion transactions a day with roughly a tenth failing,
that is on the order of 10⁴ decisions per second — a few dozen cores, trivially
shardable by customer since the only cross-payment state (contact budget, card
resubmission count) is per customer.

## Relation to the literature

The problem has a name in the bandit literature, and naming it correctly
clarifies what is and is not hard about it:

- Recovery is a **retry-aware objective** — value accrues to the best outcome
  across several attempts rather than to any single one, the structure studied
  as `max@k`. That is why per-attempt accuracy is the wrong thing to optimise,
  and why the sequential comparison in the agent (acting now does not forfeit
  acting later) is the crux rather than a detail.
- Payments that reach their TTL unrecovered are **right-censored**, the standard
  survival-analysis setting; the evaluation measures recovery within a fixed
  horizon rather than eventual recovery, which keeps the censoring
  non-informative.
- Contact fatigue is a **satiation** effect: repeated exposure degrades response
  and the resource recovers slowly. Pricing it per customer rather than per
  payment is the same correction that satiation-aware formulations make.

Nothing here needed a novel algorithm. What the problem needed was the right
objective, an honest simulator, and constraints that are real.

## Related work

[Hyperswitch](https://hyperswitch.io/) (Juspay) is the closest open-source
system: a payments orchestrator in Rust with an agentic recovery sub-system
whose retry engine is configurable across 30+ parameters — decline code, error
type, card BIN, ticket size, region, payment method. Commercial smart-dunning
products (Churnkey, Solidgate, Gr4vy, Slicker) occupy the same space.

The difference is where the intelligence sits. Those engines are **rule
engines you configure**: an operator encodes the policy across parameters.
Kintsugi **learns** the policy and prices every action in rupees, which makes
waiting a first-class action rather than a gap between configured retries —
and, per the ablation, that timing search is where nearly all of the lift
comes from.

## Honesty, by construction

No public dataset of payment *failures* exists — issuers and PSPs do not publish
transaction-level decline data. So the world is simulated, and the entire design
is built around not letting that become a way to grade our own homework.

**The simulator generates failures cause-first from latent state**, not by
sampling a static table. Each gate is keyed to the timescale on which that
condition actually changes — the balance gate by *day*, so retrying twenty
minutes later draws the same value and fails again, exactly as it would in
reality since no money arrived.

> This is not a detail. The first version of this simulator re-rolled each
> retry, which made blind `fixed_retry` beat the smart rule-based policy 98.9%
> to 96.8%. If retries are free rolls of the dice, any policy that retries more
> wins, and the evaluation measures persistence rather than intelligence.

**Hazard rates are fitted, not hand-tuned.** Iterative proportional fitting
solves for per-segment scales reproducing published NPCI and Razorpay marginals:

| Quantity | Target | Achieved |
|---|---:|---:|
| Checkout authorisation | 0.9088 | **0.9068** |
| Mandate authorisation | 0.4000 | **0.3982** |
| Technical decline share (checkout-only) | 0.1830 | **0.1763** |

Worst per-cause relative error: **1.2%**.

**Every calibration constant carries its provenance** — `PUBLISHED`, `DERIVED`,
or `ASSUMPTION` — and the table is emitted into the results so a reader can
audit exactly how much of the model is evidence and how much is us.

**Policies are compared under common random numbers**, and the pairing is
*asserted*, not assumed. For each seed one world is built and every policy runs
against it; `verify_crn` checks that all policies saw byte-identical first
attempts on every payment, and the harness refuses to report if they did not.
CRN is easy to break by accident and fails silently — the confidence intervals
keep printing as if nothing happened.

**The assumptions are swept.** Every `ASSUMPTION` constant is pushed well above
and below default, including settings actively hostile to the agent (retries
nearly free, reminders highly effective, customers infinitely patient, almost no
payday signal). Regressions are reported as loudly as improvements.

**Nothing is reported on the worlds it was fitted on:**

| Purpose | Seeds |
|---|---|
| Predictor training | 2000–2029 |
| Detector threshold tuning | 11–13 |
| Detector reporting | 101–105 |
| Policy evaluation | 1000–1203 |

## Two things I built that turned out not to matter

Reported because an ablation that only ever confirms your design is not an
ablation, and because both of these are components this project measured
carefully and was pleased with.

**The issuer health detector contributes nothing.** A CUSUM change detector on
per-issuer technical decline rate, tuned on held-out seeds, reaching 96%
precision at 60,000 payments — and removing it *completely*, both its
expected-value multiplier and the issuer-state features handed to the model,
moves the headline result by less than a tenth of a percent. The most likely
reason is that the failure taxonomy already carries the signal: an attempt that
returns `ISSUER_DOWN` has told the model the bank is unavailable, so a separate
detector adds nothing to *this* decision. It may still earn its place for
cross-issuer routing or operational alerting, neither of which this agent does.

**The agent does not starve its own detector.** I predicted it would — it routes
away from issuers it suspects, which should destroy the evidence that would
confirm them, and that is a real production concern. Measured at matched volume,
the closed loop, the open loop, and the agent with its monitor disabled all land
within noise of each other. Traffic volume explained the entire original
discrepancy that prompted the investigation. The hypothesis was clean, plausible,
and wrong.

What *does* carry the result is narrower than the pitch would like: the timing
search and the learned model. Remove either and the agent falls ~60% below the
rules baseline. Even the explicit payday candidate is redundant — the geometric
offsets plus repeated re-evaluation already reach month-start without being told
it is special.

## What went wrong, and how I found it

Every one of these was producing plausible numbers before it was caught. They
are listed because the process that found them is the actual claim this project
is making.

> The figures in this section are the diagnostics **as measured at the moment
> each bug was found**, against the world model as it stood then. Several were
> found before a later correction to the world itself (the fifth item), so they
> will not reproduce exactly against the code as it ships. They are kept at
> their original values because rewriting them to match today's numbers would
> misrepresent what was actually observed. The headline results in
> [RESULTS.md](RESULTS.md) are all generated from the current code.

### The baseline was strawmanned, and fixing it reversed the result

The per-cause breakdown showed my "strong" rules baseline recovering **5.4%** of
`AUTH_ABANDONED` failures where both other policies recovered ~99%. It refused
to retry customer-present failures at all, on the reasoning that a server-side
retry cannot help if the customer never authenticated.

That reasoning is wrong on the rail carrying most of India's volume. On UPI a
retry **is** a fresh prompt — a new collect request lands in the payer's app. My
baseline was declining a legitimate recovery action, and a large part of the
agent's reported lift was simply that.

Fixing the baseline **reversed the headline**: rules 78.08%, agent 75.82%. The
agent had been winning against a policy I had accidentally broken.

### Then three real defects in the agent

Chasing that reversal down found problems that a favourable baseline had been
hiding:

**Waiting was treated as mutually exclusive with acting.** The agent compared
"act now" against "act at the better moment" as alternatives. They are not — if
the retry fires now and fails, the better moment is still there afterwards.
Waiting forfeited a free option, and the agent deferred itself past the
payment's expiry. The correct comparison is `EV(now) + P(fail) × V(future)`
against `V(future)`.

**Contact fatigue was priced per payment.** Patience belongs to the person, not
the invoice. A customer with three open payments got messaged three times over
while each payment believed it had spent one contact. Real dunning systems
impose a per-customer frequency cap for exactly this reason — on price alone a
20-paise SMS clears its cost against almost any payment, so the arithmetic
alone will message forever.

**There was no calendar-boundary feature.** Daily limits reset at midnight, and
23:50 → 00:10 is twenty minutes and a completely different day — something
elapsed-time features cannot express. Without it the agent retried
`LIMIT_EXCEEDED` failures within the same day, where they *cannot* succeed:
65.9% against the baseline's 92.9%.

### A realism error in the world itself

Pricing customer contact properly produced a result too clean to believe: the
agent's best configuration sent **zero** messages and still beat everything
else. Chasing that down found a modelling error rather than a finding.

The simulator let a plain retry re-prompt the payer on *every* customer-present
rail. That is true of a UPI collect request, which the merchant pushes into the
payer's app, and false of a UPI intent or a netbanking redirect, which the payer
drives and which no server-side retry can reach. Conflating them made retries
into strictly cheaper reminders, and outbound messaging into decoration.

Separating `requires_customer_present` from `server_can_reprompt` made the world
harder and the problem real: recovery rates fell across every policy, the rules
baseline started needing reminders too, and the messaging channel became a
genuine decision rather than a redundant one.

### Two more, caught by tests

**An unbounded CUSUM.** The outage detector accumulated evidence without a cap,
so a two-hour outage banked so much that it then took ~390 healthy attempts to
decay below the alarm threshold. The alarm stayed stuck on a bank that had
recovered, and the policy kept refusing to route to a healthy issuer.

**70ms of thread overhead per inference.** The agent scores ~22 candidate
(moment, rail) rows per decision, thousands of times per run. On batches that
small, OpenMP's per-call thread dispatch costs far more than the tree traversal
it parallelises: 70.13 ms/call default versus 2.50 ms/call pinned to one thread.
A policy evaluation went from 25 minutes to 25 seconds.

## Running it

```bash
python -m venv .venv && ./.venv/bin/pip install -r requirements.txt
```

```bash
./.venv/bin/python -m pytest
```

```bash
./.venv/bin/python -m scripts.run_evaluation --seeds 20 --payments 12000
```

See the agent decide, with its reasoning and the priced alternatives that lost:

```bash
./.venv/bin/python -m scripts.demo_decisions
```

Everything, in dependency order:

```bash
./scripts/run_all.sh
```

Or step by step:

```bash
./.venv/bin/python -m kintsugi.world.fitting        # fit the world to published marginals
./.venv/bin/python -m scripts.train_predictor       # train on exploration data
./.venv/bin/python -m scripts.run_evaluation        # paired evaluation
./.venv/bin/python -m scripts.run_ablation          # which idea earns the lift
./.venv/bin/python -m scripts.run_sensitivity       # assumption sweep
./.venv/bin/python -m scripts.run_detector_study    # open vs closed loop
./.venv/bin/python -m scripts.run_contact_frontier  # recovery vs contact
./.venv/bin/python -m scripts.render_report         # RESULTS.md
./.venv/bin/python -m scripts.build_dashboard       # dashboard.html
```

Everything runs on CPU with **no paid services**. The language model defaults to
a local one through [Ollama](https://ollama.com); a free hosted tier
(`GEMINI_API_KEY`) or a paid API (`ANTHROPIC_API_KEY`) is used only if a key is
present, and the system degrades cleanly to rules and templates when none is.

## Layout

```
kintsugi/
  domain.py            failure taxonomy, actions, payment records
  calibration.py       every constant with its provenance
  rng.py               counter-based randomness (common random numbers)
  compliance.py        NPCI and card-scheme retry rules, as hard constraints
  world/
    issuers.py         latent issuer-health timelines
    customers.py       latent liquidity, attention, patience
    simulator.py       cause-first failure generation
    fitting.py         IPF to published marginals
  taxonomy/
    codes.py           129 decline strings incl. Razorpay's published
                       reason identifiers; 39 held out
    rules.py           deterministic matcher
    providers.py       Ollama / Gemini / Anthropic / none
    classifier.py      rules -> cache -> model -> UNKNOWN
  agent/
    health_monitor.py  CUSUM outage detection
    explorer.py        randomised policies for unbiased training data
    features.py        observable-only feature extraction
    predictor.py       calibrated gradient-boosted models
    policy.py          baselines, including a strong rule-based one
    kintsugi.py        the expected-value agent
    messaging.py       cause-aware copy with guardrails
    explain.py         merchant Q&A, grounded and verified
  eval/
    metrics.py         recovery, cost, contact intensity, waste
    harness.py         paired evaluation with asserted CRN
    sensitivity.py     assumption sweep
```

Studies under `scripts/`: `run_ablation` (which idea earns the lift),
`run_sensitivity` (assumption sweep), `run_detector_study` (open vs closed
loop), `run_contact_frontier` (recovery against contact volume),
`run_external_validation` (published figures the world never saw).

## Limitations

Stated plainly, because they are the first thing a reviewer should want to know.

- **The world is simulated.** Its marginals match published aggregates and its
  mechanisms are defensible, but no simulator is reality. The lift is evidence
  that this *class* of policy beats a fixed schedule under conditions matching
  what NPCI and Razorpay publish — not a forecast of a specific merchant's
  recovery rate.
- **The rules baseline has privileged knowledge, and that understates the
  agent.** I wrote both the world and the rules, so the rules encode the true
  generative mechanisms directly: they retry balance failures on the salary
  cycle because I know the salary cycle exists, and back off from outages for
  the duration I chose for outages. The learned agent has to discover all of
  that from data and can only approximate it. That makes this a *harder*
  comparison than reality, where nobody knows the true process and hand-written
  rules are guesses. It is the right way round for honesty, but it means a tie
  against these rules is a stronger result than it looks.
- **Correlated multi-bank outages are not modelled.** Issuer incidents are
  drawn independently, which makes this world *conservative* for the agent:
  rail switching would look better than it does here if outages clustered.
- **Detector recall on short incidents is low** (~15% on 20–45 minute events).
  That is partly an information limit — a brief outage on a low-volume issuer
  generates almost no observations — and partly a deliberate precision-heavy
  operating point, since a false alarm stops retries against a healthy issuer
  and costs real revenue.
- **The salary-cycle model is a population-level assumption.** Real payday
  timing varies by employer and sector; the agent only ever sees the calendar,
  never a customer's actual payday, so it learns a weaker signal than the one
  generating the world.
- **One published band is not reproduced.** The simulated fixed-schedule
  recovery rate (50.2%) sits far above the published 15–25% for basic retries.
  The populations differ — that band comes from card subscription books whose
  failures sit largely on stale credentials — but the gap is real and
  unreconciled, and it means absolute recovery rates here should be read as
  *relative* comparisons between policies, not as forecasts.
- **Only the customer-asked credential path is modelled.** A hard decline here
  is recovered by asking the customer for new details and having them supply
  them. Real stacks also run **automatic account updaters**, where the card
  networks push refreshed credentials with no customer involvement at all —
  worth 3–5% of recurring revenue on its own. That lever is not modelled,
  partly for scope and partly because it is automatic and therefore identical
  across policies, so it would raise every number without changing any
  comparison.
- **Scheme fines are modelled at assumed magnitudes.** Visa's excessive-retry
  fee is public (~$0.25); NPCI does not publish a per-breach figure, so that
  one is a stand-in chosen so a non-compliant policy carries *some* cost rather
  than none.
- **Churn is modelled but not validated against real data.** The prior that
  over-contacting drives customers away is deliberately pessimistic; the
  sensitivity sweep moves it in both directions.

## Licence

MIT.
