# Kintsugi — Results

Generated from `data/results.json`. 20 independent worlds x 12,000 payments over 30 days (30% recurring).

> **Pairing verified.** 12,000 payments across 4 policies, 0 first-attempt mismatches. Every policy faced the identical world, payment by payment, so the intervals below are paired differences rather than two noisy samples.

## Headline

| Policy | Recovery rate | GMV recovered | Net value (INR) | Cost (INR) | Retries | Nudges | Wasted retries |
|---|---:|---:|---:|---:|---:|---:|---:|
| No recovery (floor) | 0.00% | 0.00% | 0 | 0 | 0 | 0 | 0 |
| Fixed retry + dunning (industry default) | 50.38% | 48.23% | 9,012,087 | 63,104 | 7,295 | 4,399 | 1,043 |
| Cause-aware rules (strong baseline) | 60.81% | 58.43% | 10,988,324 | 1,313 | 5,764 | 1,663 | 17 |
| **Kintsugi (this agent)** | 65.72% | 63.64% | 11,965,846 | 978 | 5,130 | 596 | 0 |

*Recovery rate is share of payments whose first attempt failed. Payments that authorised immediately were never the agent's to win, so they are excluded from the denominator.*

## Paired comparisons

Bootstrap over seeds, 20,000 resamples. `sig` means the 95% interval excludes zero.

### kintsugi vs fixed_retry

| Metric | Baseline | Challenger | Lift | 95% CI | Wins | p | |
|---|---:|---:|---:|---|---:|---:|---|
| `net_value_paise` | 9,012,087 INR | 11,965,846 INR | +32.78% | 2,802,459 INR to 3,091,105 INR | 100% | 0.0000 | **sig** |
| `recovery_rate` | 50.38% | 65.72% | +30.46% | 14.81% to 15.84% | 100% | 0.0000 | **sig** |
| `gmv_recovery_rate` | 48.23% | 63.64% | +31.96% | 14.52% to 16.27% | 100% | 0.0000 | **sig** |
| `total_cost_paise` | 63,104 INR | 978 INR | -98.45% | -63,163 INR to -61,131 INR | 0% | 0.0000 | **sig** |
| `nudges` | 4,399 | 596 | -86.46% | -3,844 to -3,764 | 0% | 0.0000 | **sig** |
| `wasted_retries` | 1,043 | 0 | -99.97% | -1,076 to -1,011 | 0% | 0.0000 | **sig** |
| `scheme_violations` | 1,822 | 0 | -100.00% | -1,859 to -1,786 | 0% | 0.0000 | **sig** |

### kintsugi vs rule_based

| Metric | Baseline | Challenger | Lift | 95% CI | Wins | p | |
|---|---:|---:|---:|---|---:|---:|---|
| `net_value_paise` | 10,988,324 INR | 11,965,846 INR | +8.90% | 857,718 INR to 1,089,843 INR | 100% | 0.0000 | **sig** |
| `recovery_rate` | 60.81% | 65.72% | +8.07% | 4.33% to 5.41% | 100% | 0.0000 | **sig** |
| `gmv_recovery_rate` | 58.43% | 63.64% | +8.92% | 4.56% to 5.83% | 100% | 0.0000 | **sig** |
| `total_cost_paise` | 1,313 INR | 978 INR | -25.50% | -348 INR to -322 INR | 0% | 0.0000 | **sig** |
| `nudges` | 1,663 | 596 | -64.18% | -1,099 to -1,036 | 0% | 0.0000 | **sig** |
| `wasted_retries` | 17 | 0 | -97.92% | -18 to -15 | 0% | 0.0000 | **sig** |
| `scheme_violations` | 0 | 0 | +0.00% | 0 to 0 | 0% | 1.0000 | — |

### rule_based vs fixed_retry

| Metric | Baseline | Challenger | Lift | 95% CI | Wins | p | |
|---|---:|---:|---:|---|---:|---:|---|
| `net_value_paise` | 9,012,087 INR | 10,988,324 INR | +21.93% | 1,871,413 INR to 2,072,633 INR | 100% | 0.0000 | **sig** |
| `recovery_rate` | 50.38% | 60.81% | +20.72% | 10.10% to 10.77% | 100% | 0.0000 | **sig** |
| `gmv_recovery_rate` | 48.23% | 58.43% | +21.16% | 9.60% to 10.82% | 100% | 0.0000 | **sig** |
| `total_cost_paise` | 63,104 INR | 1,313 INR | -97.92% | -62,828 INR to -60,798 INR | 0% | 0.0000 | **sig** |
| `nudges` | 4,399 | 1,663 | -62.20% | -2,764 to -2,710 | 0% | 0.0000 | **sig** |
| `wasted_retries` | 1,043 | 17 | -98.39% | -1,059 to -996 | 0% | 0.0000 | **sig** |
| `scheme_violations` | 1,822 | 0 | -100.00% | -1,859 to -1,786 | 0% | 0.0000 | **sig** |

## Where the lift comes from

Recovery rate by the cause of the original failure, single world.

| Cause | Disposition | Failed | fixed_retry recovery | rule_based recovery | kintsugi recovery | Kintsugi retries/recovery |
|---|---|---:|---:|---:|---:|---:|
| `INSUFFICIENT_FUNDS` | TIME_HEALS | 1,357 | 52.2% | 69.8% | 74.6% | 2.7 |
| `ISSUER_DOWN` | RAIL_SWITCH | 310 | 65.8% | 70.6% | 89.0% | 2.1 |
| `RISK_DECLINE` | RAIL_SWITCH | 244 | 81.1% | 82.8% | 97.1% | 1.3 |
| `MANDATE_REVOKED` | TERMINAL | 204 | 1.5% | 3.4% | 0.0% | — |
| `LIMIT_EXCEEDED` | TIME_HEALS | 191 | 77.0% | 82.7% | 84.8% | 2.2 |
| `AUTH_ABANDONED` | NEEDS_CUSTOMER | 164 | 12.8% | 18.9% | 16.5% | 22.3 |
| `PSP_TIMEOUT` | RAIL_SWITCH | 120 | 77.5% | 83.3% | 99.2% | 1.2 |
| `AUTH_TIMEOUT` | NEEDS_CUSTOMER | 89 | 12.4% | 22.5% | 18.0% | 17.1 |
| `ACCOUNT_CLOSED` | TERMINAL | 77 | 1.3% | 3.9% | 0.0% | — |
| `NETWORK_TIMEOUT` | RAIL_SWITCH | 49 | 51.0% | 61.2% | 98.0% | 1.3 |
| `CARD_BLOCKED` | TERMINAL | 47 | 2.1% | 4.3% | 0.0% | — |
| `USER_CANCELLED` | NEEDS_CUSTOMER | 32 | 21.9% | 25.0% | 21.9% | 15.0 |
| `INVALID_INSTRUMENT` | TERMINAL | 17 | 0.0% | 5.9% | 0.0% | — |

## Does the simulated world behave like the real one?

The world is calibrated to **first-attempt marginals only** — per-rail authorisation rates and the failure-cause mix. Nothing about recovery, retry timing, or the value of a schedule change enters that fit, so every quantity below is out-of-sample.

| Quantity | Published | Simulated | |
|---|---:|---:|---|
| hard declines as a share of failures | 10-15% | 12.5% | ok |
| fixed schedule + dunning recovery | 15-25% (basic retries) | 50.2% | **miss** |
| cause-aware rules recovery | 45-60% (best-in-class, all decline types) | 59.8% | ok |
| learned agent recovery | 55-80% (smart dunning) | 66.4% | ok |
| retry at +24h instead of +2h | +6.5% | +70.7% | dir |
| &nbsp;&nbsp;… same change, first retry inside a 3-retry schedule | +6.5% | +5.1% | ok |
| &nbsp;&nbsp;… same change, card payments only | +6.5% | +76.3% | dir |
| three extra retries inside the dunning window | +20.2% | +29.6% | ok |

> **On the timing result.** Measured in isolation the effect is ~11x the published figure. Two explanations were tested. Restricting to card payments made it *larger* (+76.3%), refuting the population-difference hypothesis. Making the same timing change to the first retry of a three-retry schedule -- which is what a dunning A/B actually varies, since later attempts recover most of what an early first attempt misses -- gives +5.1% against a published +6.5%.

The remaining miss is stated rather than explained away: the 15–25% band is measured on card subscription books where most failures sit on stale credentials, while this is a mixed checkout book whose failures are far more recoverable. Different populations, not a reconciled number.

## Scheme and regulator compliance

Retry behaviour is constrained by rules that are not economic trade-offs. NPCI caps a UPI Autopay mandate at one debit plus three retries and permits execution only in non-peak windows (before 10:00, 13:00–17:00, after 21:30). Visa caps card-not-present resubmissions at 15 per card per 30 days, and both major schemes prohibit reattempting a decline in the never-retry category.

| Policy | Violations | Fines (INR) |
|---|---:|---:|
| No recovery (floor) | 0 | 0 |
| Fixed retry + dunning (industry default) | 1,822 | 61,130 |
| Cause-aware rules (strong baseline) | 0 | 0 |
| **Kintsugi (this agent)** | 0 | 0 |

The compliance layer is shared by every serious policy rather than reserved for the agent — reserving mandatory rules for the learned policy would manufacture a lead that has nothing to do with decision quality. Only the naive fixed schedule breaches, and its headline recovery rate hides every one of those fines.

## Which idea earns the money?

Each variant removes exactly one idea and keeps the rest. `share of lift` is how much of the agent's advantage over the rules baseline disappears when that idea is taken away.

Values above 100% are not a bug: removing that idea does not merely erase the lift, it drives the agent *below* the baseline.

| Variant | Net lift vs rules | Recovery lift | Wins | Significant | Share of lift |
|---|---:|---:|---:|---|---:|
| `full` | +13.52% | +11.48% | 100% | yes | — |
| `no_wait_search` | -61.54% | -59.39% | 0% | yes | 555% |
| `no_payday` | +13.54% | +11.55% | 100% | yes | -0% |
| `no_monitor` | +13.57% | +11.50% | 100% | yes | -0% |
| `no_model` | -63.05% | -62.43% | 0% | yes | 566% |

**Two of the four ideas are worth nothing, and one of them is a component this project measured carefully.** The timing search and the learned model carry the entire result — remove either and the agent falls well below the rules baseline. But the explicit month-start candidate is redundant (the geometric offsets plus repeated re-evaluation already reach payday), and removing the issuer health detector *completely* — both its expected-value multiplier and the issuer-state features handed to the model — changes the result by less than a tenth of a percent.

The most likely explanation is that the failure taxonomy already carries the signal: an attempt that comes back `ISSUER_DOWN` has told the model the bank is unavailable, so a separate detector adds nothing to *this* decision. It may still earn its place for cross-issuer routing or operational alerting — neither of which this agent does. Reported rather than quietly dropped, because a component that measures well and contributes nothing is exactly the kind of thing an ablation exists to catch.

## Recovery against customer contact

An expected-value agent given only the *send* price of a message will message everyone forever: 20 paise against a payment worth hundreds of rupees clears almost any bar. Charging the agent for customer attention sweeps out this frontier.

| Policy | Recovery | Value recovered | Messages | Retries | Cost (INR) | Churned |
|---|---:|---:|---:|---:|---:|---:|
| fixed_retry | 50.51% | 47.51% | 2,208 | 3,660 | 991 | 3.6 |
| rule_based | 61.82% | 58.99% | 472 | 2,910 | 562 | 0.4 |
| kintsugi @ INR 0/contact | 68.75% | 67.13% | 2,402 | 2,762 | 1,253 | 6.0 |
| kintsugi @ INR 5/contact | 69.08% | 67.20% | 2,087 | 2,760 | 1,144 | 4.1 |
| kintsugi @ INR 15/contact | 68.95% | 67.23% | 1,843 | 2,764 | 1,060 | 3.5 |
| kintsugi @ INR 50/contact | 68.91% | 67.01% | 1,462 | 2,729 | 921 | 2.8 |
| kintsugi @ INR 150/contact | 68.54% | 66.34% | 1,090 | 2,636 | 777 | 1.9 |
| kintsugi @ INR 500/contact | 68.10% | 65.89% | 633 | 2,448 | 589 | 0.9 |

## Does the agent starve its own detector?

The health monitor scores differently depending on which policy is driving traffic, with identical detector code. Two candidate causes: traffic volume, and the agent routing away from issuers it suspects — which destroys the very evidence that would confirm them. Measuring at matched volume separates them.

| Payments | Policy driving traffic | Precision | Recall | Latency |
|---:|---|---:|---:|---:|
| 20,000 | open loop (rules) | 93.0% | 12.7% | 42 min |
| 20,000 | closed loop (agent) | 93.0% | 14.2% | 54 min |
| 20,000 | agent, monitor off | 95.0% | 14.2% | 53 min |
| 60,000 | open loop (rules) | 96.3% | 29.7% | 30 min |
| 60,000 | closed loop (agent) | 95.9% | 32.7% | 30 min |
| 60,000 | agent, monitor off | 96.6% | 32.2% | 30 min |

The gap between *closed loop* and *agent, monitor off* isolates the feedback effect: same agent, same traffic, differing only in whether it acts on the detector's output.

**The hypothesis was wrong.** Those two rows land within noise of each other, and of the open loop. Traffic volume explains the whole original discrepancy — recall roughly doubles from 20,000 to 60,000 payments, and the two numbers that prompted this investigation had been measured at different payment counts on different seeds. The starvation mechanism is real in principle, but it is not present here: the agent de-rates suspect issuers rather than blocking them, so it keeps observing. Reported because a plausible mechanism shown to be absent is worth more than one assumed to be there.

## Component measurements

### Issuer health detector

Thresholds swept on tuning seeds 11-13; reported on disjoint seeds [101, 102, 103], at 40,000 payments per world.

Detector recall is strongly traffic-dependent — a brief outage on a low-volume issuer generates almost no attempts to observe — so this figure is not comparable across volumes. See the open-loop/closed-loop study below, which measures the same detector at two volumes.

- precision **89.3%**, recall **25.7%**, median detection latency **29 min**

| Incident duration | Detected | Incidents | Recall |
|---|---:|---:|---:|
| 20-45min | 14 | 76 | 18.4% |
| 45-90min | 20 | 85 | 23.5% |
| 90min+ | 22 | 59 | 37.3% |

Tuned precision-heavy on purpose: a false alarm stops retries against a *healthy* issuer and costs revenue on every payment routed there, while a miss merely degrades the agent to baseline behaviour.

### Decline-string taxonomy

129 strings across 13 classes; 39 held out and never seen while authoring rules.

| Layer | Visible strings | Held-out strings |
|---|---:|---:|
| Rules | 100% (90) | 13% (39) |
| + language model | — | 76% (26/34) |

Rules are perfect on the strings they were written for and blind on strings they have never seen — and every miss returns `UNKNOWN` rather than a confident wrong class. That gap is the entire argument for having a model, and it is why the model sits here rather than in the decision loop.

### Predictors

| Model | Rows | Positive rate | AUC | Brier | Brier skill | Calibration error |
|---|---:|---:|---:|---:|---:|---:|
| retry | 237,609 | 16.65% | 0.9620 | 0.0579 | +0.5830 | 0.0029 |
| nudge | 154,867 | 14.73% | 0.8197 | 0.1025 | +0.1844 | 0.0046 |

Calibration error matters more than AUC here: the policy multiplies these probabilities by rupees, so a model that ranks well but reports 0.8 where the truth is 0.4 approves retries that lose money.

## Is the world calibrated?

Hazard scales are fitted by iterative proportional fitting to published marginals, not hand-tuned.

| Quantity | Target | Achieved | Source |
|---|---:|---:|---|
| Checkout authorisation | 0.9088 | 0.9068 | Razorpay PSR guide, band 85%-95% |
| Mandate authorisation | 0.4000 | 0.3982 | UPI Autopay, band 30%-50% |
| Technical decline share | 0.1830 | 0.1771 | NPCI (checkout-only, comparable) |

Worst per-cause relative error: **1.2%**.

> The published 81.7/18.3 business-technical split is measured across all digital transactions, which are overwhelmingly customer-initiated. The comparable figure here is therefore the checkout-only share. The blended number sits lower purely because this world carries a 30% mandate segment, and mandate failures are dominated by balance -- a business decline.

Of 31 calibration constants: **7 published**, 8 derived, 16 assumptions. The assumptions are exactly what the sensitivity sweep moves.

## Does the result survive its assumptions?

Every `ASSUMPTION` constant pushed well above and below default, including settings hostile to the agent. 6 seeds per setting.

- **15 of 15** perturbations keep the lift positive
- **15** remain significantly positive
- **0** significantly negative
- lift range **+9.78%** to **+17.83%**, median **+14.12%**

| Assumption moved | Group | Lift | Significant | Why it is hostile |
|---|---|---:|---|---|
| (unperturbed) | reference | +14.12% | yes | default assumptions |
| nudge_conversion 0.10 (half) | behavioural | +15.50% | yes | reminders much weaker than assumed |
| nudge_conversion 0.40 (double) | behavioural | +13.77% | yes | hostile: reminders very effective, so naive dunning wins |
| patience 1.2 (impatient) | behavioural | +12.20% | yes | customers tire of contact quickly |
| patience 6.0 (tolerant) | behavioural | +14.46% | yes | hostile: over-contacting is nearly free |
| churn_hazard 0.05 (mild) | behavioural | +14.23% | yes | hostile: little penalty for hounding customers |
| churn_hazard 0.45 (severe) | behavioural | +13.90% | yes | over-contact drives customers away hard |
| retry_cost 2p (near free) | behavioural | +14.12% | yes | hostile: brute-force retrying is nearly costless |
| retry_cost 100p (expensive) | behavioural | +14.13% | yes | each attempt materially costly |
| nudge_decay 0.85 (slow) | behavioural | +14.52% | yes | hostile: repeat reminders keep working |
| salary_window 2d (sharp) | behavioural | +9.78% | yes | balance recovers in a sharp spike |
| salary_window 20d (flat) | behavioural | +11.28% | yes | hostile: almost no payday signal to exploit |
| outage_rate 0.01 (rare) | structural | +13.29% | yes | hostile: little issuer downtime to detect |
| outage_rate 0.15 (frequent) | structural | +15.44% | yes | unstable issuers |
| recurring share 0.10 | structural | +17.83% | yes | hostile: little recurring volume, where the value is |
| recurring share 0.55 | structural | +12.88% | yes | subscription-heavy book |

No setting of any assumed constant reversed the result.
