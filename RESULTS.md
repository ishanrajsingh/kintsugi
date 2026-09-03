# Kintsugi — Results

Generated from `data/results.json`. 20 independent worlds x 12,000 payments over 30 days (30% recurring).

> **Pairing verified.** 12,000 payments across 4 policies, 0 first-attempt mismatches. Every policy faced the identical world, payment by payment, so the intervals below are paired differences rather than two noisy samples.

## Headline

| Policy | Recovery rate | GMV recovered | Net value (INR) | Cost (INR) | Retries | Nudges | Wasted retries |
|---|---:|---:|---:|---:|---:|---:|---:|
| No recovery (floor) | 0.00% | 0.00% | 0 | 0 | 0 | 0 | 0 |
| Fixed retry + dunning (industry default) | 49.66% | 47.68% | 8,995,580 | 1,992 | 7,350 | 4,449 | 1,068 |
| Cause-aware rules (strong baseline) | 61.41% | 59.34% | 11,191,581 | 1,128 | 5,800 | 966 | 0 |
| **Kintsugi (this agent)** | 67.91% | 66.32% | 12,507,952 | 1,808 | 5,434 | 2,837 | 0 |

*Recovery rate is share of payments whose first attempt failed. Payments that authorised immediately were never the agent's to win, so they are excluded from the denominator.*

## Paired comparisons

Bootstrap over seeds, 20,000 resamples. `sig` means the 95% interval excludes zero.

### kintsugi vs fixed_retry

| Metric | Baseline | Challenger | Lift | 95% CI | Wins | p | |
|---|---:|---:|---:|---|---:|---:|---|
| `net_value_paise` | 8,995,580 INR | 12,507,952 INR | +39.05% | 3,384,119 INR to 3,642,850 INR | 100% | 0.0000 | **sig** |
| `recovery_rate` | 49.66% | 67.91% | +36.74% | 17.80% to 18.63% | 100% | 0.0000 | **sig** |
| `gmv_recovery_rate` | 47.68% | 66.32% | +39.08% | 17.97% to 19.32% | 100% | 0.0000 | **sig** |
| `total_cost_paise` | 1,992 INR | 1,808 INR | -9.24% | -204 INR to -165 INR | 0% | 0.0000 | **sig** |
| `nudges` | 4,449 | 2,837 | -36.22% | -1,655 to -1,569 | 0% | 0.0000 | **sig** |
| `wasted_retries` | 1,068 | 0 | -100.00% | -1,101 to -1,036 | 0% | 0.0000 | **sig** |

### kintsugi vs rule_based

| Metric | Baseline | Challenger | Lift | 95% CI | Wins | p | |
|---|---:|---:|---:|---|---:|---:|---|
| `net_value_paise` | 11,191,581 INR | 12,507,952 INR | +11.76% | 1,210,349 INR to 1,420,080 INR | 100% | 0.0000 | **sig** |
| `recovery_rate` | 61.41% | 67.91% | +10.58% | 6.03% to 6.89% | 100% | 0.0000 | **sig** |
| `gmv_recovery_rate` | 59.34% | 66.32% | +11.75% | 6.44% to 7.51% | 100% | 0.0000 | **sig** |
| `total_cost_paise` | 1,128 INR | 1,808 INR | +60.33% | 666 INR to 695 INR | 100% | 0.0000 | **sig** |
| `nudges` | 966 | 2,837 | +193.82% | 1,837 to 1,907 | 100% | 0.0000 | **sig** |
| `wasted_retries` | 0 | 0 | +0.00% | 0 to 0 | 0% | 1.0000 | — |

### rule_based vs fixed_retry

| Metric | Baseline | Challenger | Lift | 95% CI | Wins | p | |
|---|---:|---:|---:|---|---:|---:|---|
| `net_value_paise` | 8,995,580 INR | 11,191,581 INR | +24.41% | 2,087,306 INR to 2,301,921 INR | 100% | 0.0000 | **sig** |
| `recovery_rate` | 49.66% | 61.41% | +23.65% | 11.45% to 12.07% | 100% | 0.0000 | **sig** |
| `gmv_recovery_rate` | 47.68% | 59.34% | +24.45% | 11.05% to 12.28% | 100% | 0.0000 | **sig** |
| `total_cost_paise` | 1,992 INR | 1,128 INR | -43.39% | -878 INR to -851 INR | 0% | 0.0000 | **sig** |
| `nudges` | 4,449 | 966 | -78.29% | -3,521 to -3,446 | 0% | 0.0000 | **sig** |
| `wasted_retries` | 1,068 | 0 | -100.00% | -1,101 to -1,036 | 0% | 0.0000 | **sig** |

## Where the lift comes from

Recovery rate by the cause of the original failure, single world.

| Cause | Disposition | Failed | fixed_retry recovery | rule_based recovery | kintsugi recovery | Kintsugi retries/recovery |
|---|---|---:|---:|---:|---:|---:|
| `INSUFFICIENT_FUNDS` | TIME_HEALS | 1,347 | 51.4% | 72.1% | 77.2% | 2.8 |
| `ISSUER_DOWN` | RAIL_SWITCH | 310 | 66.8% | 72.3% | 91.3% | 2.1 |
| `RISK_DECLINE` | RAIL_SWITCH | 247 | 81.4% | 84.6% | 98.0% | 1.3 |
| `MANDATE_REVOKED` | TERMINAL | 204 | 0.0% | 0.0% | 0.0% | — |
| `LIMIT_EXCEEDED` | TIME_HEALS | 193 | 76.2% | 83.9% | 86.0% | 2.3 |
| `AUTH_ABANDONED` | NEEDS_CUSTOMER | 167 | 13.2% | 19.2% | 19.2% | 18.8 |
| `PSP_TIMEOUT` | RAIL_SWITCH | 120 | 77.5% | 83.3% | 99.2% | 1.2 |
| `AUTH_TIMEOUT` | NEEDS_CUSTOMER | 88 | 13.6% | 23.9% | 20.5% | 15.4 |
| `ACCOUNT_CLOSED` | TERMINAL | 77 | 0.0% | 0.0% | 0.0% | — |
| `NETWORK_TIMEOUT` | RAIL_SWITCH | 53 | 56.6% | 64.2% | 98.1% | 1.3 |
| `CARD_BLOCKED` | TERMINAL | 47 | 0.0% | 0.0% | 0.0% | — |
| `USER_CANCELLED` | NEEDS_CUSTOMER | 33 | 21.2% | 24.2% | 24.2% | 13.4 |
| `INVALID_INSTRUMENT` | TERMINAL | 17 | 0.0% | 0.0% | 0.0% | — |

## Which idea earns the money?

Each variant removes exactly one idea and keeps the rest. `share of lift` is how much of the agent's advantage over the rules baseline disappears when that idea is taken away.

| Variant | Net lift vs rules | Recovery lift | Wins | Significant | Share of lift |
|---|---:|---:|---:|---|---:|
| `full` | +13.52% | +11.48% | 100% | yes | — |
| `no_wait_search` | -61.54% | -59.39% | 0% | yes | 555% |
| `no_payday` | +13.54% | +11.55% | 100% | yes | -0% |
| `no_monitor` | +13.58% | +11.48% | 100% | yes | -0% |
| `no_model` | -63.05% | -62.43% | 0% | yes | 566% |

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

- precision **87.7%**, recall **26.7%**, median detection latency **35 min**

| Incident duration | Detected | Incidents | Recall |
|---|---:|---:|---:|
| 20-45min | 12 | 76 | 15.8% |
| 45-90min | 21 | 85 | 24.7% |
| 90min+ | 25 | 59 | 42.4% |

Tuned precision-heavy on purpose: a false alarm stops retries against a *healthy* issuer and costs revenue on every payment routed there, while a miss merely degrades the agent to baseline behaviour.

### Decline-string taxonomy

79 strings across 13 classes; 20 held out and never seen while authoring rules.

| Layer | Visible strings | Held-out strings |
|---|---:|---:|
| Rules | 100% (59) | 0% (20) |
| + language model | — | 95% (19/20) |

Rules are perfect on the strings they were written for and blind on strings they have never seen — and every miss returns `UNKNOWN` rather than a confident wrong class. That gap is the entire argument for having a model, and it is why the model sits here rather than in the decision loop.

### Predictors

| Model | Rows | Positive rate | AUC | Brier | Brier skill | Calibration error |
|---|---:|---:|---:|---:|---:|---:|
| retry | 240,820 | 15.56% | 0.9724 | 0.0489 | +0.6279 | 0.0023 |
| nudge | 157,148 | 12.98% | 0.8694 | 0.0865 | +0.2338 | 0.0034 |

Calibration error matters more than AUC here: the policy multiplies these probabilities by rupees, so a model that ranks well but reports 0.8 where the truth is 0.4 approves retries that lose money.

## Is the world calibrated?

Hazard scales are fitted by iterative proportional fitting to published marginals, not hand-tuned.

| Quantity | Target | Achieved | Source |
|---|---:|---:|---|
| Checkout authorisation | 0.9088 | 0.9068 | Razorpay PSR guide, band 85%-95% |
| Mandate authorisation | 0.4000 | 0.3979 | UPI Autopay, band 30%-50% |
| Technical decline share | 0.1830 | 0.1763 | NPCI (checkout-only, comparable) |

Worst per-cause relative error: **1.7%**.

> The published 81.7/18.3 business-technical split is measured across all digital transactions, which are overwhelmingly customer-initiated. The comparable figure here is therefore the checkout-only share. The blended number sits lower purely because this world carries a 30% mandate segment, and mandate failures are dominated by balance -- a business decline.

Of 29 calibration constants: **7 published**, 8 derived, 14 assumptions. The assumptions are exactly what the sensitivity sweep moves.

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
