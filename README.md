# Kintsugi

An expected-value agent for recovering failed payments.

Razorpay AI Buildathon 2026 · AI Revenue Recovery

---

## The problem

UPI Autopay carries every subscription renewal in India and authorises 30–50% of
the time. More than half of recurring collections fail on first attempt.

Worse, over 20 million Autopay mandates get revoked every month because the
account was short at debit time — OTT, loans, SIPs, utilities.[^1] Those aren't
failed payments, they're cancelled customers. The mandate registers fine, then
execution fails often enough that people kill it.

[^1]: Business Standard, "UPI autopay revocations hit 20 mn per month on low
customer balance", Sept 2025. Sources disagree on Autopay's success rate:
Razorpay's own guide says 30–50%, some third-party write-ups say 85–92%. The
disagreement and which figure I used are documented on the constant in
`kintsugi/calibration.py`.

What everyone does about it: retry at +1h, +1d, +3d, send two SMS, give up. No
reference to why the payment failed. So it retries closed accounts, messages
people at 3am, hammers an empty account on the 28th and quits before payday.

## The idea

Price every action in rupees, take the largest:

```
EV(retry)  = P(authorises now) × amount − attempt cost
EV(nudge)  = P(money arrives) × amount − send cost − goodwill − churn × amount
EV(wait t) = best action available at t, discounted for expiry risk
EV(stop)   = 0
```

The load-bearing term is `EV(wait)`. Waiting is an action evaluated against
future moments, not the gap between retries. A schedule asks "has enough time
passed?" This asks "is there a better moment coming, and is it worth it?" For a
balance failure on the 26th, usually yes — payday beats any number of retries
before it.

Waiting and acting aren't mutually exclusive, which took me a while to get
right. If the retry fires now and fails, the better moment is still there. So
the comparison is `EV(now) + P(fail) × V(future)` against `V(future)`.

## Results

20 worlds × 12,000 payments, 30 days, 30% recurring. Every policy faces the
identical world payment-by-payment, and the pairing is asserted before any
statistic is computed: 0 first-attempt mismatches.

| Policy | Recovery | Value | Cost | Violations | Messages | Wasted retries |
|---|---:|---:|---:|---:|---:|---:|
| Fixed retry + dunning | 48.52% | 36.67% | ₹63,274 | 1,765 | 4,588 | 855 |
| Cause-aware rules | 54.41% | 41.29% | ₹1,420 | 0 | 1,784 | 13 |
| **Kintsugi** | **61.52%** | **47.60%** | **₹943** | **0** | **879** | **2** |

+15.31% net value over the rules baseline, 100% of 20 paired worlds, p < 0.0001,
on 51% fewer messages and 34% lower cost.

The fixed schedule's ₹63,274 is mostly ₹61,237 of scheme fines, a liability its
recovery rate doesn't show.

Every assumption constant with no published source was pushed hard both ways,
including settings hostile to the agent. 15 of 15 stay significantly positive,
range +13.95% to +22.79%.

Full numbers in [RESULTS.md](RESULTS.md), design in
[ARCHITECTURE.md](ARCHITECTURE.md).

## How much is actually recoverable?

Beating a baseline says nothing about what's left behind. The simulator resolves
an attempt deterministically from (payment, rail, time, attempt number), so a
policy allowed to probe it can find the best moment instead of predicting it.
Not deployable, it reads latent state, but it bounds what any retry policy could
do. See `scripts/run_oracle_ceiling.py`.

| | Recovery | Value | of recoverable payments | of recoverable value |
|---|---:|---:|---:|---:|
| Cause-aware rules | 53.62% | 40.95% | 64.5% | 49.2% |
| Kintsugi | 61.50% | 48.53% | **74.0%** | **58.3%** |
| Oracle ceiling | 83.07% | 83.29% | — | — |

74% of the payments a perfect-information policy could recover, 58% of the
value. A quarter of the payments and two-fifths of the money still on the table.

The gap isn't uniform. The oracle is value-neutral (83.1% of payments, 83.3% of
value), so expensive payments are as recoverable as cheap ones. The agent isn't.
Capture sits near 70–79% in every amount bucket except above ₹10,000, where it
halves to 49.8%. That bucket is 82% of every rupee missed.

Chasing that down produced the wait-search fix below.

## Where the language model is, and isn't

Three jobs, all open-ended natural language.

**Normalising decline strings.** There's no shared decline vocabulary in Indian
payments. The same cause arrives as ISO 8583 `51`, NPCI `Z9`, Razorpay's
`insufficient_funds`, `"A/c balance low"`, or `"Txn declined by bank (reason:
balance)"`, and banks ship new templates without telling anyone. The catalogue
carries Razorpay's own published `reason` identifiers verbatim: 129 strings, 39
held out and never seen while the rules were written.

| | Strings the rules were written for (90) | Never seen (39) |
|---|---:|---:|
| Rules alone | 100% | 12.8% |
| + model | — | 79.5% |

Rules never guess wrong: anything they can't match returns `UNKNOWN` and gets
handled conservatively. Zero held-out strings get a confident wrong class. That
gap is the argument for the model.

**Writing customer copy**, per cause. Someone whose balance was short doesn't
need "please try again", they need to know how much and by when. Generated copy
is validated before it ships: length limits, no unresolved placeholders, no
invented offers or deadlines. Every cause has a template fallback, and a
cold-start test proves the system works with no model at all.

**Answering merchant questions** about what it did. Retrieval and arithmetic are
deterministic; the model only phrases facts it's handed, and every number in its
answer must appear in the fact block or the response is rejected.

It does not choose actions. That's a calibrated-probability problem against a
cost model, where a fluent wrong answer is indistinguishable from a right one and
prices a retry incorrectly with nothing to catch it.

## Scheme rules are limits, not costs

These aren't trade-offs to price, they're enforced by the network. So compliance
sits above the EV engine and filters the action set before anything is valued.

- **NPCI UPI Autopay**: one debit plus at most three retries, executable only
  before 10:00, 13:00–17:00, and after 21:30.
- **Visa**: 15 card-not-present resubmissions per card per merchant per rolling
  30 days.
- **Mastercard**: a dual threshold instead, 10 in 24 hours and 35 in 30 days,
  plus penalties for retrying after Merchant Advice Code 03 or 21.
- Both prohibit reattempting a never-retry decline outright.

Enforcing Visa's 15 satisfies all of them. Neither other threshold binds: the
worst card carries 12 merchant resubmissions in 30 days, and even counting every
card attempt (originals and customer returns included, which the rule doesn't
govern) the worst 24-hour window holds 6 against Mastercard's 10.

Obeying the rules costs 1.2pp of recovery and 0.7pp of value, measured by running
the agent with its rulebook neutered. It avoids 723 violations and about ₹36,100
in fines per 8,000 payments. Only the fixed schedule breaches.

## Does the simulated world behave like the real one?

No public dataset of payment failures exists, so the world is calibrated against
published aggregates. Everything below is out-of-sample with respect to that fit.

| Quantity | Published | Simulated | |
|---|---:|---:|---|
| Hard declines as share of failures | 10–15% | 12.4% | ok |
| Cause-aware rules recovery | 45–60% | 54.0% | ok |
| Learned agent recovery | 55–80% | 61.7% | ok |
| Retry moved +2h → +24h | +6.5% | +6.7% | ok |
| Three extra retries in window | +20.2% | +30.5% | ok |
| Fixed-schedule recovery | 15–25% | 49.0% | **miss** |

The miss is real and I've left it in. Those published figures come from
card-based Western books; this world is UPI-heavy, where a retry on a collect
request re-prompts the payer and recovers far more than a card resubmission
would. It means absolute recovery rates here should be read as relative
comparisons between policies, not forecasts.

## What went wrong

The process that found these is more of the claim than the numbers are.

**The simulator's physics made blind retrying beat intelligence.** Every attempt
re-rolled its outcome, so persistence always won: 98.9% for a blind schedule
against 96.8% for the smart policy. Fixed by making each failure cause resolve on
the timescale it actually changes on — balance by day, issuer by wall clock,
instrument permanently. Retrying an `INSUFFICIENT_FUNDS` failure twenty minutes
later now draws the same value and fails again, because no money arrived.

**I strawmanned my own baseline, and fixing it reversed the result.** The rules
policy refused to re-prompt on UPI, where a retry *is* a fresh prompt: 5.4% on
`AUTH_ABANDONED` where other policies got 99%. Corrected, it beat my agent 78.08%
to 75.82%. Most of the reported lift had been a broken comparison.

**Five defects in the agent**, all found by chasing something that looked too
good. Acting and waiting treated as exclusive. Contact fatigue priced per payment
instead of per customer. No calendar-boundary feature, so it retried daily limits
inside the same day. Contact scarcity priced multiplicatively on goodwill, so a
zero price switched the penalty off entirely and it spent every customer's whole
budget. And a wait search too coarse in the first two days.

**Four hypotheses I predicted and got wrong.**

*Correcting a real 86% bias made things worse.* The nudge model learns
P(recover | nudged) and the policy pays for it. Wrong quantity: on randomised
data P(recover | nudged) is 0.1237 and P(recover | not nudged) is 0.1061, so 86%
of what follows a nudge isn't caused by it. The mechanism prediction was
confirmed exactly — correcting it collapsed the optimal contact price from ₹2,500
to ₹200, twelvefold — and the corrected agent still lost at every price, 0 of 6
seeds. Differencing two models compounds their errors, and the policy only ranks
actions, so a biased low-variance estimate beats an unbiased noisy one.

*Pricing the retry budget backfired.* The diagnosis held: on big payments the
oracle recovers and the agent misses, it had spent 3.78 of 6 retries inside 3.5
days, and 54% of those were balance failures waiting on a salary credit. But
charging for depletion made the retry span *shorter*. It just retried less,
equally early.

*Extending the search horizon was worth nothing.* The grid stopped at day 10 and
payments live 14 days, which looked like the obvious cause of the big-payment
gap. Worth ₹396. Adding resolution inside the first two days was worth ₹92,952.
That's the fix that shipped.

*More patience is harmful.* Halving the wait discount costs ₹76,596, quartering
it costs ₹131,856.

Every idea with a clean theoretical story failed. The two that worked were a
finer search grid and separating two costs that had been sharing one number.

**Two components that don't matter.** Removing the issuer-health detector
entirely moves the lift from +15.31% to +14.97%. The explicit payday feature is
redundant: removing it is very slightly *better*, because the geometric offsets
already reach month-start. Reported because an ablation that only confirms your
design isn't an ablation.

**A compliance claim that was wrong three ways.** Counting every card attempt
reads 15.8 and looks pinned to Visa's cap. Counting decision-log entries reads 17
and looks like a breach. The policy's ledger, appended only after the rulebook
allows an action, reads 12. Only the last is what Visa governs, and I'd published
the first.

**Tuning on the wrong seeds.** A credential-price change looked worth ₹20,636 on
evaluation seeds and lost money on tuning seeds. The seed discipline this project
claims exists for exactly that, and I broke it and got a plausible wrong answer.

## What carries the result

| Remove | Net lift vs rules |
|---|---:|
| nothing | +15.31% |
| the wait search | **−59.22%** |
| the learned models | **−67.43%** |
| the health detector | +14.97% |
| the payday feature | +15.35% |

Two components carry everything. Remove either and the agent doesn't just lose
its edge, it falls far below the baseline it otherwise beats.

## Running it

```bash
python -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m pytest                        # 98 tests
./.venv/bin/python -m scripts.demo_decisions        # worked decisions
./scripts/run_all.sh                                # full pipeline
```

Everything runs on CPU with no paid services. The language model defaults to a
local one through [Ollama](https://ollama.com); a free hosted tier
(`GEMINI_API_KEY`) is used if a key is present, and it degrades cleanly to rules
and templates when none is.

Run the pipeline on its own. Each stage holds a full simulated world in memory,
and running several at once on a small machine gets processes killed.

## Layout

```
kintsugi/
  domain.py         payments, attempts, failure classes
  calibration.py    every constant with its provenance
  compliance.py     NPCI and card-scheme limits
  rng.py            counter-based randomness for paired comparison
  world/            the simulator and its calibration
  agent/            the EV policy, predictors, messaging, explanation
  taxonomy/         decline-string normalisation
  eval/             paired harness, metrics, sensitivity
scripts/            pipeline stages, demo, report, dashboard
tests/              98 tests
```

## Limitations

- **The world is simulated.** Its marginals match published aggregates but no
  simulator is reality. The lift is evidence that this class of policy beats a
  fixed schedule under conditions matching what NPCI and Razorpay publish, not a
  forecast of any merchant's recovery rate.
- **The rules baseline knows things it shouldn't.** I wrote both the world and
  the rules, so the rules encode the true generative mechanisms directly while
  the learned agent has to discover them. That makes this a harder comparison
  than reality, which is the right way round, but it means a tie against these
  rules is stronger than it looks.
- **A quarter of recoverable payments and 40% of recoverable value are still
  missed**, concentrated above ₹10,000. Diagnosed, partly addressed, not solved.
- **Correlated multi-bank outages aren't modelled.** Independent draws make this
  conservative for the agent; rail switching would look better if outages
  clustered.
- **Detector recall on short incidents is poor** (21% on 20–45 minute events, 39%
  above 90 minutes). Partly an information limit, partly a deliberate
  precision-heavy operating point.
- **Raising the retry cap from 6 to 12 is worth about +0.5pp** on the big-payment
  bucket and measured compliant, but validating it needs its own pipeline run, so
  it isn't shipped.
- **Scheme fines are modelled at assumed magnitudes.** Visa's fee is public; NPCI
  doesn't publish a per-breach figure, so that one is a stand-in.
- **Churn is modelled but not validated** against real data. The prior that
  over-contacting drives customers away is deliberately pessimistic.

## Licence

MIT.
