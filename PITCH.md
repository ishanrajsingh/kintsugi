# Kintsugi — 5-minute pitch script

Timings are cues, not a straitjacket. Numbers marked `[read from RESULTS.md]`
must be read off the generated report at recording time, never from memory.

**What this is scored on**, and where each lands in the five minutes:

| Criterion | Where |
|---|---|
| Problem taste | 0:00–0:40 — UPI Autopay authorises 30–50%, the worst segment in Indian payments |
| AI judgment | 4:00–4:35 — what the model does, and the money decision it is deliberately kept out of |
| Failure recovery | 3:00–4:00 — the simulator that was wrong, and the baseline that beat my own agent |
| Build quality | 4:50–5:00 — 98 tests, every number generated, nothing typed by hand |

If you are short on time, cut the component detail — **never** cut the section
where things broke. It is a quarter of the score and almost nobody else will
have it.

---

## 0:00 — 0:40 · The problem nobody looks at

**On screen:** the UPI Autopay success-rate figure, large.

> India's checkout authorises about nine times out of ten. That number gets
> quoted a lot.
>
> Here's the number that doesn't. **UPI Autopay — the rail carrying every
> subscription renewal in the country — authorises between 30 and 50 percent.**
> More than half of all recurring collections fail on the first attempt.
>
> And what happens next is the same everywhere. Retry in an hour. Retry
> tomorrow. Retry in three days. Send two reminder texts. Give up.
>
> That loop never asks *why* the payment failed. So it retries closed accounts,
> which can never work. It texts people at three in the morning. It hammers an
> empty account on the 28th, and quits before payday on the 1st. And when a bank
> is down, it keeps firing straight into the outage.

**Beat.**

> A failed payment isn't a dead transaction. It's a decision problem. Almost
> everyone solves it with a `for` loop.

## 0:40 — 1:20 · The idea

**On screen:** the four EV equations, appearing one at a time.

> Kintsugi puts a price in rupees on every action available.
>
> Retrying is worth the probability it authorises, times the amount, minus what
> the attempt costs. Messaging someone is worth the probability money actually
> arrives, minus the send cost, minus the risk that one more message makes them
> abandon entirely. Stopping is worth zero — and sometimes zero is the best
> number on the board.

**Highlight the third line.**

> And then the one that matters most: **waiting is an action.** Not the gap
> between retries — an action, priced against specific future moments.
>
> A fixed schedule asks "has enough time passed?" Kintsugi asks "is there a
> better moment coming, and is it worth waiting for?" For a balance failure on
> the 26th, the answer is almost always yes. Payday beats any number of retries
> before it.

## 1:20 — 2:10 · Show it deciding

**On screen:** decision log for two payments, side by side.

> Here's the agent on a real decision. Same failure — insufficient funds — two
> different customers.

**Point at the first.**

> This one it holds for six days, and the log says why: acting now is worth
> forty rupees, waiting until the salary credit is worth three hundred and ten.

**Point at the second.**

> This one it abandons immediately. The card came back `41 — lost card`. That's
> terminal. No probability estimate is allowed to override it — the taxonomy
> settles it before the model is consulted, because a dead card is dead however
> confident a model feels.

> Every decision carries the alternatives that lost, with their prices. A
> recovery engine that can't explain why it didn't chase a large payment doesn't
> get deployed at a merchant.

## 2:10 — 3:00 · Results

**On screen:** the headline table.

> Against the industry default — fixed retries plus dunning — and against a
> genuinely strong baseline I wrote to beat myself: cause-aware rules that
> abandon terminal instruments, wait out outages, and time balance retries to
> the salary cycle. That baseline is not a strawman. It's what a good payments
> engineer ships.

> `[read from RESULTS.md at recording time — as of the last run: 65.72% of
> failed payments recovered against the rules baseline's 60.81%, +8.90% net
> value, 100% of 20 paired worlds, p < 0.0001]`

**Point at the wasted-retries column.**

> And this column is the one I'd look at first. Retries fired at instruments
> that were already dead. The fixed schedule burns **1,043** of them. Kintsugi burns
> zero — every one of those is gateway load, issuer trust, and a customer
> watching their payment fail again for nothing.

## 3:00 — 4:00 · Why you should believe any of it

**On screen:** the calibration table, then the CRN check, then the sweep.

> Now the part that should make you suspicious. There is no public dataset of
> payment failures — nobody publishes transaction-level declines. So I simulated
> the world. Which means I could have graded my own homework.
>
> Four things stop that.

> **One.** The hazard rates aren't hand-tuned, they're *fitted* — iterative
> proportional fitting against published NPCI and Razorpay marginals. Checkout
> lands at `0.9068` against a target of `0.9088`. Mandates at `0.3982` against
> `0.4000`. Worst per-cause error, 1.2 percent.

> **Two.** Every constant carries its provenance — published, derived, or
> assumption — and that table ships in the results. You can see exactly how much
> of this is evidence and how much is me.

> **Three.** Policies are compared under common random numbers — same world,
> payment by payment — and the pairing is *asserted*, not assumed. The harness
> checks every policy saw byte-identical first attempts and refuses to report if
> they didn't. That guarantee fails silently otherwise; the confidence intervals
> keep printing as though nothing's wrong.

> **Four.** Every assumption gets swept, including to settings hostile to my own
> agent — retries nearly free, reminders highly effective, customers infinitely
> patient, almost no payday signal to exploit. `[read from RESULTS.md — as of
> the last run: 15 of 15 keep the lift significantly positive, range +5.6% to
> +13.3%, no regressions. If a later run finds one, say it out loud.]`

**Beat.**

> And I'll tell you where it broke — twice.

**On screen:** the per-cause table, `AUTH_ABANDONED` row highlighted.

> The first simulator re-rolled every retry. Which meant blind retrying beat the
> smart policy, 98.9 to 96.8. That's not a tuning problem, that's the whole
> experiment being meaningless: if retries are free dice rolls, whoever rolls
> most wins.

> Then, later, this. My rules baseline was recovering five percent of abandoned
> authentications where everything else got ninety-nine. It was refusing to
> retry when the customer hadn't authenticated — which sounds right, and is
> wrong on UPI, because there a retry *is* a fresh prompt in the payer's app.

> So I fixed my own baseline. And it beat my agent. Seventy-eight to
> seventy-six.

**Beat.**

> That reversal is the most useful thing that happened in this project. Chasing
> it down found three real bugs in the agent — the worst being that it treated
> waiting and acting as mutually exclusive, when in fact if you retry now and it
> fails, the better moment is *still there*. It was waiting itself past the
> payment's expiry date for no reason.

## 4:00 — 4:35 · Where the model is, and isn't

**On screen:** the taxonomy table — 100% / 12.8% / 79.5%.

> There's a language model here, doing three jobs.
>
> It normalises decline strings. There's no shared vocabulary in Indian
> payments — the same cause shows up as ISO `51`, as NPCI `Z9`, as Razorpay's
> `insufficient_funds`, as "A/c balance low" — and banks ship new templates
> without telling anyone. The catalogue uses Razorpay's own published error
> vocabulary, not strings I made up.
>
> On the thirty-nine I held out while writing the rules: rules score a hundred
> percent on what they were written for and **thirteen** on what they've never
> seen — and critically, they never guess *wrong*, they return unknown. The
> model gets eighty percent of the rest. That gap is the whole reason it's here.
>
> It also writes the customer copy, per cause — because someone who's short on
> money and someone who closed the app before entering their PIN need completely
> different messages.
>
> And it answers the merchant when they ask why. But the numbers in that answer
> are retrieved from the ledger and summed in Python *before* the model is
> called — and then the answer is checked, so any figure that isn't in the
> ledger gets the whole answer thrown away. A grounded generator nobody audits
> is just a fluent one.

**Beat.**

> What it does *not* do is choose actions. Deciding which payment to chase is a
> calibrated-probability problem against a cost model. Ask a language model and
> you get fluent, confident, unpriced guesses — and a fluent wrong answer looks
> exactly like a right one, so you'd misprice retries and never notice.
>
> Keeping it out of the decision loop is a design decision, not a gap.

## 4:35 — 4:50 · Where this fits at Razorpay

**On screen:** the four-row table — Optimizer, Doppler, Vulcan, Kintsugi.

> Let me be straight about something. Razorpay already ships AI for payment
> success. Optimizer routes each transaction across gateways. Doppler detects
> failures in seconds and reroutes. Vulcan is a payments foundation model.
>
> This is none of those, and it isn't competing with them. All three act on the
> *spatial* axis — which endpoint, right now, at authorisation. This one acts on
> the temporal axis: given that authorisation already failed everywhere
> available, is this payment worth chasing, how, and *when*.
>
> And there's one honest overlap I'll point at rather than hide. Doppler detects
> issuer failures; I built an issuer health detector too. My own ablation says
> mine contributes nothing — the failure taxonomy already carries that signal.
> So the overlap resolves the right way: failure detection belongs in the
> routing layer, where Razorpay already has it, not duplicated inside a recovery
> agent. I found that from the ablation before I knew Doppler existed.

## 4:50 — 5:00 · Close

**On screen:** repo, then the kintsugi bowl.

> Everything runs on a laptop, on CPU, with no paid services. Eighty
> tests. Every number in the report generated from the artefacts, none typed by
> hand.
>
> And it respects the rules that actually bind: NPCI caps an Autopay mandate at
> three retries in defined windows, Visa caps card resubmissions, both schemes
> forbid retrying a dead card. The naive schedule breaks those eight hundred
> times in a month and its recovery rate never shows it.

**Beat.**

> Kintsugi is the Japanese craft of repairing broken pottery with gold. The
> break doesn't get hidden — it becomes the most valuable part of the object.
>
> That's the right way to think about a failed payment.

---

## Recording notes

- **Do not read the numbers from this file.** Regenerate `RESULTS.md` and read
  them off it, so the video and the repo can never disagree.
- Show the CRN assertion actually running. It is the most unusual thing here and
  it takes four seconds.
- If the sweep found a regression, **say it in the video.** A pitch that reports
  its own failure mode is more credible than one that doesn't, and a judge who
  finds it in the repo after you hid it has learned something worse.
- Keep the "first simulator was broken" story. It is the strongest evidence that
  the evaluation is real, and it is the part most submissions cannot say.
