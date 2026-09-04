# Kintsugi — Results

Generated from `data/results.json`. 20 independent worlds x 12,000 payments over 30 days (30% recurring).

> **Pairing verified.** 12,000 payments across 4 policies, 0 first-attempt mismatches. Every policy faced the identical world, payment by payment, so the intervals below are paired differences rather than two noisy samples.

## Headline

| Policy | Recovery rate | GMV recovered | Net value (INR) | Cost (INR) | Retries | Nudges | Wasted retries |
|---|---:|---:|---:|---:|---:|---:|---:|
| No recovery (floor) | 0.00% | 0.00% | 0 | 0 | 0 | 0 | 0 |
| Fixed retry + dunning (industry default) | 48.52% | 36.67% | 6,843,817 | 63,274 | 7,458 | 4,588 | 855 |
| Cause-aware rules (strong baseline) | 54.41% | 41.29% | 7,771,226 | 1,420 | 6,267 | 1,784 | 13 |
| **Kintsugi (this agent)** | 61.09% | 46.89% | 8,826,924 | 955 | 5,497 | 1,008 | 2 |

*Recovery rate is share of payments whose first attempt failed. Payments that authorised immediately were never the agent's to win, so they are excluded from the denominator.*

## Paired comparisons

Bootstrap over seeds, 20,000 resamples. `sig` means the 95% interval excludes zero.

### kintsugi vs fixed_retry

| Metric | Baseline | Challenger | Lift | 95% CI | Wins | p | |
|---|---:|---:|---:|---|---:|---:|---|
| `net_value_paise` | 6,843,817 INR | 8,826,924 INR | +28.98% | 1,839,116 INR to 2,122,362 INR | 100% | 0.0000 | **sig** |
| `recovery_rate` | 48.52% | 61.09% | +25.89% | 12.01% to 13.07% | 100% | 0.0000 | **sig** |
| `gmv_recovery_rate` | 36.67% | 46.89% | +27.85% | 9.43% to 10.97% | 100% | 0.0000 | **sig** |
| `total_cost_paise` | 63,274 INR | 955 INR | -98.49% | -63,397 INR to -61,240 INR | 0% | 0.0000 | **sig** |
| `nudges` | 4,588 | 1,008 | -78.03% | -3,617 to -3,544 | 0% | 0.0000 | **sig** |
| `wasted_retries` | 855 | 2 | -99.74% | -882 to -826 | 0% | 0.0000 | **sig** |
| `scheme_violations` | 1,765 | 0 | -100.00% | -1,802 to -1,731 | 0% | 0.0000 | **sig** |

### kintsugi vs rule_based

| Metric | Baseline | Challenger | Lift | 95% CI | Wins | p | |
|---|---:|---:|---:|---|---:|---:|---|
| `net_value_paise` | 7,771,226 INR | 8,826,924 INR | +13.58% | 868,104 INR to 1,247,033 INR | 100% | 0.0000 | **sig** |
| `recovery_rate` | 54.41% | 61.09% | +12.28% | 6.09% to 7.22% | 100% | 0.0000 | **sig** |
| `gmv_recovery_rate` | 41.29% | 46.89% | +13.57% | 4.62% to 6.60% | 100% | 0.0000 | **sig** |
| `total_cost_paise` | 1,420 INR | 955 INR | -32.75% | -476 INR to -455 INR | 0% | 0.0000 | **sig** |
| `nudges` | 1,784 | 1,008 | -43.49% | -803 to -749 | 0% | 0.0000 | **sig** |
| `wasted_retries` | 13 | 2 | -83.40% | -13 to -10 | 0% | 0.0000 | **sig** |
| `scheme_violations` | 0 | 0 | +0.00% | 0 to 0 | 0% | 1.0000 | — |

### rule_based vs fixed_retry

| Metric | Baseline | Challenger | Lift | 95% CI | Wins | p | |
|---|---:|---:|---:|---|---:|---:|---|
| `net_value_paise` | 6,843,817 INR | 7,771,226 INR | +13.55% | 791,304 INR to 1,060,692 INR | 100% | 0.0000 | **sig** |
| `recovery_rate` | 48.52% | 54.41% | +12.12% | 5.45% to 6.32% | 100% | 0.0000 | **sig** |
| `gmv_recovery_rate` | 36.67% | 41.29% | +12.58% | 3.88% to 5.34% | 100% | 0.0000 | **sig** |
| `total_cost_paise` | 63,274 INR | 1,420 INR | -97.76% | -62,929 INR to -60,779 INR | 0% | 0.0000 | **sig** |
| `nudges` | 4,588 | 1,784 | -61.12% | -2,833 to -2,775 | 0% | 0.0000 | **sig** |
| `wasted_retries` | 855 | 13 | -98.45% | -871 to -815 | 0% | 0.0000 | **sig** |
| `scheme_violations` | 1,765 | 0 | -100.00% | -1,802 to -1,731 | 0% | 0.0000 | **sig** |

## Where the lift comes from

Recovery rate by the cause of the original failure, single world.

| Cause | Disposition | Failed | fixed_retry recovery | rule_based recovery | kintsugi recovery | Kintsugi retries/recovery |
|---|---|---:|---:|---:|---:|---:|
| `INSUFFICIENT_FUNDS` | TIME_HEALS | 1,357 | 49.1% | 65.4% | 69.9% | 3.0 |
| `ISSUER_DOWN` | RAIL_SWITCH | 310 | 61.6% | 62.3% | 82.3% | 2.4 |
| `RISK_DECLINE` | RAIL_SWITCH | 251 | 63.7% | 53.4% | 84.1% | 2.0 |
| `MANDATE_REVOKED` | TERMINAL | 204 | 19.6% | 3.4% | 1.0% | 2.0 |
| `LIMIT_EXCEEDED` | TIME_HEALS | 191 | 68.6% | 76.4% | 69.6% | 3.2 |
| `AUTH_ABANDONED` | NEEDS_CUSTOMER | 165 | 12.7% | 18.8% | 16.4% | 22.9 |
| `PSP_TIMEOUT` | RAIL_SWITCH | 122 | 76.2% | 77.9% | 94.3% | 1.3 |
| `AUTH_TIMEOUT` | NEEDS_CUSTOMER | 87 | 12.6% | 20.7% | 16.1% | 20.1 |
| `ACCOUNT_CLOSED` | TERMINAL | 77 | 19.5% | 2.6% | 0.0% | — |
| `NETWORK_TIMEOUT` | RAIL_SWITCH | 53 | 56.6% | 62.3% | 96.2% | 1.2 |
| `CARD_BLOCKED` | TERMINAL | 47 | 27.7% | 4.3% | 0.0% | — |
| `USER_CANCELLED` | NEEDS_CUSTOMER | 33 | 24.2% | 27.3% | 24.2% | 14.1 |
| `INVALID_INSTRUMENT` | TERMINAL | 17 | 5.9% | 0.0% | 0.0% | — |

## Does the simulated world behave like the real one?

The world is calibrated to **first-attempt marginals only** — per-rail authorisation rates and the failure-cause mix. Nothing about recovery, retry timing, or the value of a schedule change enters that fit, so every quantity below is out-of-sample.

| Quantity | Published | Simulated | |
|---|---:|---:|---|
| hard declines as a share of failures | 10-15% | 12.4% | ok |
| fixed schedule + dunning recovery | 15-25% (basic retries) | 49.0% | **miss** |
| cause-aware rules recovery | 45-60% (best-in-class, all decline types) | 54.0% | ok |
| learned agent recovery | 55-80% (smart dunning) | 61.1% | ok |
| retry at +24h instead of +2h | +6.5% | +118.4% | dir |
| &nbsp;&nbsp;… same change, first retry inside a 3-retry schedule | +6.5% | +6.7% | ok |
| &nbsp;&nbsp;… same change, card payments only | +6.5% | +127.3% | dir |
| three extra retries inside the dunning window | +20.2% | +30.5% | ok |

> **On the timing result.** Measured in isolation the effect is ~11x the published figure. Two explanations were tested. Restricting to card payments made it *larger* (+76.3%), refuting the population-difference hypothesis. Making the same timing change to the first retry of a three-retry schedule -- which is what a dunning A/B actually varies, since later attempts recover most of what an early first attempt misses -- gives +5.1% against a published +6.5%.

The remaining miss is stated rather than explained away: the 15–25% band is measured on card subscription books where most failures sit on stale credentials, while this is a mixed checkout book whose failures are far more recoverable. Different populations, not a reconciled number.

## Scheme and regulator compliance

Retry behaviour is constrained by rules that are not economic trade-offs. NPCI caps a UPI Autopay mandate at one debit plus three retries and permits execution only in non-peak windows (before 10:00, 13:00–17:00, after 21:30). Visa caps card-not-present resubmissions at 15 per card per 30 days, and both major schemes prohibit reattempting a decline in the never-retry category.

| Policy | Violations | Fines (INR) |
|---|---:|---:|
| No recovery (floor) | 0 | 0 |
| Fixed retry + dunning (industry default) | 1,765 | 61,237 |
| Cause-aware rules (strong baseline) | 0 | 0 |
| **Kintsugi (this agent)** | 0 | 0 |

The compliance layer is shared by every serious policy rather than reserved for the agent — reserving mandatory rules for the learned policy would manufacture a lead that has nothing to do with decision quality. Only the naive fixed schedule breaches, and its headline recovery rate hides every one of those fines.

## Which idea earns the money?

Each variant removes exactly one idea and keeps the rest. `share of lift` is how much of the agent's advantage over the rules baseline disappears when that idea is taken away.

Values above 100% are not a bug: removing that idea does not merely erase the lift, it drives the agent *below* the baseline.

| Variant | Net lift vs rules | Recovery lift | Wins | Significant | Share of lift |
|---|---:|---:|---:|---|---:|
| `full` | +13.83% | +12.29% | 100% | yes | — |
| `no_wait_search` | -57.81% | -65.93% | 0% | yes | 518% |
| `no_payday` | +13.91% | +12.38% | 100% | yes | -1% |
| `no_monitor` | +14.09% | +12.10% | 100% | yes | -2% |
| `no_model` | -67.42% | -67.59% | 0% | yes | 587% |

**Two of the four ideas are worth nothing, and one of them is a component this project measured carefully.** The timing search and the learned model carry the entire result — remove either and the agent falls well below the rules baseline. But the explicit month-start candidate is redundant (the geometric offsets plus repeated re-evaluation already reach payday), and removing the issuer health detector *completely* — both its expected-value multiplier and the issuer-state features handed to the model — changes the result by less than a tenth of a percent.

The most likely explanation is that the failure taxonomy already carries the signal: an attempt that comes back `ISSUER_DOWN` has told the model the bank is unavailable, so a separate detector adds nothing to *this* decision. It may still earn its place for cross-issuer routing or operational alerting — neither of which this agent does. Reported rather than quietly dropped, because a component that measures well and contributes nothing is exactly the kind of thing an ablation exists to catch.

## Recovery against customer contact

An expected-value agent given only the *send* price of a message will message everyone forever: 20 paise against a payment worth hundreds of rupees clears almost any bar. Charging the agent for customer attention sweeps out this frontier.

| Policy | Recovery | Value recovered | Messages | Retries | Cost (INR) | Churned |
|---|---:|---:|---:|---:|---:|---:|
| fixed_retry | 48.89% | 36.35% | 2,289 | 3,729 | 31,837 | 12.2 |
| rule_based | 54.76% | 41.48% | 867 | 3,149 | 706 | 1.4 |
| kintsugi @ INR 0/contact | 51.05% | 37.61% | 3,025 | 3,880 | 821 | 1.6 |
| kintsugi @ INR 50/contact | 58.46% | 40.26% | 1,961 | 3,330 | 685 | 0.8 |
| kintsugi @ INR 200/contact | 60.68% | 43.90% | 1,196 | 3,000 | 578 | 0.4 |
| kintsugi @ INR 600/contact | 61.43% | 46.57% | 698 | 2,799 | 503 | 0.1 |
| kintsugi @ INR 1500/contact | 61.53% | 47.54% | 394 | 2,691 | 459 | 0.1 |
| kintsugi @ INR 4000/contact | 61.31% | 47.15% | 146 | 2,632 | 420 | 0.0 |

## Does the agent starve its own detector?

The health monitor scores differently depending on which policy is driving traffic, with identical detector code. Two candidate causes: traffic volume, and the agent routing away from issuers it suspects — which destroys the very evidence that would confirm them. Measuring at matched volume separates them.

| Payments | Policy driving traffic | Precision | Recall | Latency |
|---:|---|---:|---:|---:|
| 20,000 | open loop (rules) | 91.3% | 14.1% | 42 min |
| 20,000 | closed loop (agent) | 95.5% | 16.3% | 44 min |
| 20,000 | agent, monitor off | 95.5% | 16.1% | 44 min |
| 60,000 | open loop (rules) | 96.7% | 28.7% | 28 min |
| 60,000 | closed loop (agent) | 92.8% | 30.9% | 27 min |
| 60,000 | agent, monitor off | 93.8% | 30.6% | 26 min |

The gap between *closed loop* and *agent, monitor off* isolates the feedback effect: same agent, same traffic, differing only in whether it acts on the detector's output.

**The hypothesis was wrong.** Those two rows land within noise of each other, and of the open loop. Traffic volume explains the whole original discrepancy — recall roughly doubles from 20,000 to 60,000 payments, and the two numbers that prompted this investigation had been measured at different payment counts on different seeds. The starvation mechanism is real in principle, but it is not present here: the agent de-rates suspect issuers rather than blocking them, so it keeps observing. Reported because a plausible mechanism shown to be absent is worth more than one assumed to be there.

## Component measurements

### Issuer health detector

Thresholds swept on tuning seeds 11-13; reported on disjoint seeds [101, 102, 103], at 40,000 payments per world.

Detector recall is strongly traffic-dependent — a brief outage on a low-volume issuer generates almost no attempts to observe — so this figure is not comparable across volumes. See the open-loop/closed-loop study below, which measures the same detector at two volumes.

- precision **93.5%**, recall **27.5%**, median detection latency **32 min**

| Incident duration | Detected | Incidents | Recall |
|---|---:|---:|---:|
| 20-45min | 16 | 76 | 21.1% |
| 45-90min | 20 | 85 | 23.5% |
| 90min+ | 24 | 59 | 40.7% |

Tuned precision-heavy on purpose: a false alarm stops retries against a *healthy* issuer and costs revenue on every payment routed there, while a miss merely degrades the agent to baseline behaviour.

### Decline-string taxonomy

129 strings across 13 classes; 39 held out and never seen while authoring rules.

| Layer | Visible strings | Held-out strings |
|---|---:|---:|
| Rules | 100% (90) | 12.8% (39) |
| + language model | — | 79.5% (31/39) |

Rules are perfect on the strings they were written for and blind on strings they have never seen — and every miss returns `UNKNOWN` rather than a confident wrong class. That gap is the entire argument for having a model, and it is why the model sits here rather than in the decision loop.

### Predictors

| Model | Rows | Positive rate | AUC | Brier | Brier skill | Calibration error |
|---|---:|---:|---:|---:|---:|---:|
| retry | 243,028 | 14.56% | 0.9584 | 0.0554 | +0.5545 | 0.0038 |
| nudge | 158,811 | 13.84% | 0.7861 | 0.1029 | +0.1375 | 0.0036 |

Calibration error matters more than AUC here: the policy multiplies these probabilities by rupees, so a model that ranks well but reports 0.8 where the truth is 0.4 approves retries that lose money.

## Is the world calibrated?

Hazard scales are fitted by iterative proportional fitting to published marginals, not hand-tuned.

| Quantity | Target | Achieved | Source |
|---|---:|---:|---|
| Checkout authorisation | 0.9088 | 0.9068 | Razorpay PSR guide, band 85%-95% |
| Mandate authorisation | 0.4000 | 0.3970 | UPI Autopay, band 30%-50% |
| Technical decline share | 0.1830 | 0.1771 | NPCI (checkout-only, comparable) |

Worst per-cause relative error: **1.2%**.

> The published 81.7/18.3 business-technical split is measured across all digital transactions, which are overwhelmingly customer-initiated. The comparable figure here is therefore the checkout-only share. The blended number sits lower purely because this world carries a 30% mandate segment, and mandate failures are dominated by balance -- a business decline.

Of 36 calibration constants: **8 published**, 8 derived, 20 assumptions. The assumptions are exactly what the sensitivity sweep moves.

## Does the result survive its assumptions?

Every `ASSUMPTION` constant pushed well above and below default, including settings hostile to the agent. 6 seeds per setting.

- **15 of 15** perturbations keep the lift positive
- **15** remain significantly positive
- **0** significantly negative
- lift range **+11.60%** to **+21.65%**, median **+15.10%**

| Assumption moved | Group | Lift | Significant | Why it is hostile |
|---|---|---:|---|---|
| (unperturbed) | reference | +15.17% | yes | default assumptions |
| nudge_conversion 0.10 (half) | behavioural | +17.81% | yes | reminders much weaker than assumed |
| nudge_conversion 0.40 (double) | behavioural | +13.46% | yes | hostile: reminders very effective, so naive dunning wins |
| patience 1.2 (impatient) | behavioural | +17.23% | yes | customers tire of contact quickly |
| patience 6.0 (tolerant) | behavioural | +14.67% | yes | hostile: over-contacting is nearly free |
| churn_hazard 0.05 (mild) | behavioural | +14.94% | yes | hostile: little penalty for hounding customers |
| churn_hazard 0.45 (severe) | behavioural | +15.17% | yes | over-contact drives customers away hard |
| retry_cost 2p (near free) | behavioural | +15.16% | yes | hostile: brute-force retrying is nearly costless |
| retry_cost 100p (expensive) | behavioural | +15.15% | yes | each attempt materially costly |
| nudge_decay 0.85 (slow) | behavioural | +15.10% | yes | hostile: repeat reminders keep working |
| salary_window 2d (sharp) | behavioural | +11.60% | yes | balance recovers in a sharp spike |
| salary_window 20d (flat) | behavioural | +14.95% | yes | hostile: almost no payday signal to exploit |
| outage_rate 0.01 (rare) | structural | +13.14% | yes | hostile: little issuer downtime to detect |
| outage_rate 0.15 (frequent) | structural | +15.43% | yes | unstable issuers |
| recurring share 0.10 | structural | +21.65% | yes | hostile: little recurring volume, where the value is |
| recurring share 0.55 | structural | +12.44% | yes | subscription-heavy book |

No setting of any assumed constant reversed the result.
