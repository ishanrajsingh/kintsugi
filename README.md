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

| Policy | Recovery | Value recovered | Cost | Wasted retries |
|---|---:|---:|---:|---:|
| No recovery (floor) | 0.00% | 0.00% | — | 0 |
| Fixed retry + dunning (industry default) | 49.66% | 47.68% | INR 1,992 | 1,068 |
| Cause-aware rules (strong baseline) | 61.41% | 59.34% | INR 1,128 | 0 |
| **Kintsugi** | **67.91%** | **66.32%** | INR 1,808 | **0** |

Against the strong baseline: **+11.75%** more value recovered, winning **100%
of 20 paired worlds** (p < 0.0001). Against the industry default: **+39%** more
value recovered for **9% less cost**, and 1,068 fewer retries fired at
instruments that were already dead.

**It survives its own assumptions.** Every constant with no published source was
pushed well above and below its default, including settings chosen to be hostile
to the agent: **15 of 15** perturbations keep the lift significantly positive,
**0** negative, range **+9.78% to +17.83%**.

**It is not just messaging more.** Throttled until it sends 633 messages —
close to the baseline's 472 — it still recovers **65.89%** of value against the
baseline's **58.99%**.


Full numbers, per-cause breakdown, and component measurements: **[RESULTS.md](RESULTS.md)**.
Design and rationale: **[ARCHITECTURE.md](ARCHITECTURE.md)**.

## Where the language model is — and deliberately is not

It does **three** things, each chosen because open-ended natural language is
what it is genuinely better at than a rule table:

**1. Normalising decline strings.** There is no shared decline vocabulary in
Indian payments. The same cause arrives as `51`, `Z9`, `insuff_funds`,
`"A/c balance low"`, or `"Txn declined by bank (reason: balance)"` — and banks
ship new templates without telling anyone. Measured on strings held out while
the rules were authored:

| | Strings the rules were written for | Strings never seen before |
|---|---:|---:|
| Rules alone | **100%** | **0%** |
| + language model | — | **95%** |

Rules never guess wrong — unmatched strings return `UNKNOWN` and are handled
conservatively. That gap *is* the argument for the model.

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
| Mandate authorisation | 0.4000 | **0.3979** |
| Technical decline share (checkout-only) | 0.1830 | **0.1763** |

Worst per-cause relative error: **1.7%**.

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
  world/
    issuers.py         latent issuer-health timelines
    customers.py       latent liquidity, attention, patience
    simulator.py       cause-first failure generation
    fitting.py         IPF to published marginals
  taxonomy/
    codes.py           79 realistic decline strings, 20 held out
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
- **Churn is modelled but not validated against real data.** The prior that
  over-contacting drives customers away is deliberately pessimistic; the
  sensitivity sweep moves it in both directions.

## Licence

MIT.
