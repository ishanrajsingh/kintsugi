"""Build a self-contained HTML dashboard from the evaluation artefacts.

Data is inlined at build time, so the page has no network dependencies and can
be published or opened directly. As with the report, every number comes from
``data/results.json`` -- nothing is typed into the template.

Run: ``python -m scripts.build_dashboard``
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data" / "results.json"
SENSITIVITY = ROOT / "data" / "sensitivity.json"
ABLATION = ROOT / "data" / "ablation.json"
FRONTIER = ROOT / "data" / "contact_frontier.json"
DETECTOR = ROOT / "data" / "detector_study.json"
VALIDATION = ROOT / "data" / "external_validation.json"
OUT = ROOT / "dashboard.html"

TEMPLATE = """<title>Kintsugi</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap">
<style>
  /* Light palette on bare :root, so the un-stamped "system" state resolves. */
  :root {
    --ground: #faf8f5;      /* warm off-white, biased toward the accent */
    --panel:  #ffffff;
    --ink:    #17140f;
    --muted:  #6e6559;
    --line:   #e4ddd2;
    --seam:   #a8762c;      /* the gold in the repair -- the only accent */
    --seam-wash: #f3e8d4;
    --good:   #2e7d57;      /* semantic, deliberately not the accent */
    --bad:    #b0443b;
    --sans: "IBM Plex Sans", ui-sans-serif, system-ui, -apple-system, sans-serif;
    --mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --ground: #13110e; --panel: #1c1917; --ink: #f2ede6; --muted: #a79c8e;
      --line: #302a22; --seam: #d9a94f; --seam-wash: #33291a;
      --good: #5cb98a; --bad: #de7d72;
    }
  }
  :root[data-theme="dark"] {
    --ground: #13110e; --panel: #1c1917; --ink: #f2ede6; --muted: #a79c8e;
    --line: #302a22; --seam: #d9a94f; --seam-wash: #33291a;
    --good: #5cb98a; --bad: #de7d72;
  }

  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--ground); color: var(--ink);
    font-family: var(--sans); font-size: 16px; line-height: 1.6;
    -webkit-font-smoothing: antialiased;
  }
  .wrap {
    max-width: 1060px; margin: 0 auto; padding: 64px 24px 104px;
    display: flex; flex-direction: column; gap: 0;
  }

  header { display: flex; flex-direction: column; gap: 14px; }
  h1 {
    font-size: clamp(38px, 6.5vw, 58px); margin: 0; font-weight: 600;
    letter-spacing: -0.03em; line-height: 1.02; text-wrap: balance;
  }
  h1 .kanji { color: var(--seam); font-weight: 400; letter-spacing: 0; }
  .tag { color: var(--muted); font-size: 17px; max-width: 60ch; margin: 0; }
  .thesis {
    margin: 6px 0 0; padding: 16px 0 16px 20px; font-size: 17.5px;
    border-left: 2px solid var(--seam); line-height: 1.5; max-width: 62ch;
  }

  /* The seam: a hairline of gold running the width of the page, the way the
     lacquer runs along the break. Doubles as the section rule. */
  .seam {
    height: 1px; background: var(--line); margin: 56px 0 22px;
    position: relative;
  }
  .seam::after {
    content: ""; position: absolute; left: 0; top: 0; height: 1px;
    width: 68px; background: var(--seam);
  }
  h2 {
    font-family: var(--mono); font-size: 11.5px; text-transform: uppercase;
    letter-spacing: 0.14em; color: var(--muted); margin: 0 0 18px;
    font-weight: 500;
  }

  .cards {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(196px, 1fr));
    gap: 14px;
  }
  .card {
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 3px; padding: 20px; display: flex; flex-direction: column;
    gap: 5px;
  }
  .card .n {
    font-family: var(--mono); font-size: 29px; font-weight: 600;
    letter-spacing: -0.02em; font-variant-numeric: tabular-nums;
    line-height: 1.1;
  }
  .card .l { font-size: 12.5px; color: var(--muted); line-height: 1.45; }
  .up { color: var(--good); } .down { color: var(--bad); }

  .scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  table {
    width: 100%; border-collapse: collapse; font-size: 14.5px; min-width: 580px;
  }
  th, td {
    padding: 10px 14px; text-align: right; border-bottom: 1px solid var(--line);
    white-space: nowrap;
  }
  th:first-child, td:first-child { text-align: left; white-space: normal; }
  th {
    font-family: var(--mono); font-size: 10.5px; text-transform: uppercase;
    letter-spacing: 0.09em; color: var(--muted); font-weight: 500;
    border-bottom-color: var(--ink);
  }
  td.num, th.num {
    font-variant-numeric: tabular-nums; font-family: var(--mono);
    font-size: 13px; font-weight: 400;
  }
  tbody tr.hero td { background: var(--seam-wash); font-weight: 600; }
  tbody tr:last-child td { border-bottom: none; }

  .bar {
    height: 6px; background: var(--line); border-radius: 0; overflow: hidden;
    min-width: 96px;
  }
  .bar > i { display: block; height: 100%; background: var(--seam); }

  code {
    font-family: var(--mono); font-size: 12.5px; color: var(--ink);
    background: var(--seam-wash); padding: 1px 5px; border-radius: 2px;
  }
  .note {
    color: var(--muted); font-size: 14px; max-width: 74ch; margin: 16px 0 0;
    line-height: 1.6;
  }
  .pill {
    display: inline-block; font-family: var(--mono); font-size: 10.5px;
    padding: 2px 8px; border-radius: 2px; font-weight: 500;
    letter-spacing: 0.05em; text-transform: uppercase;
  }
  .pill.y { background: color-mix(in srgb, var(--good) 15%, transparent); color: var(--good); }
  .pill.n { background: color-mix(in srgb, var(--muted) 15%, transparent); color: var(--muted); }
  footer {
    margin-top: 68px; padding-top: 24px; border-top: 1px solid var(--line);
    color: var(--muted); font-size: 13.5px; line-height: 1.65; max-width: 78ch;
  }
  :focus-visible { outline: 2px solid var(--seam); outline-offset: 2px; }
  @media (prefers-reduced-motion: reduce) {
    * { animation: none !important; transition: none !important; }
  }
</style>

<div class="wrap">
<header>
  <h1>Kintsugi <span class="kanji">\u91d1\u7d99\u304e</span></h1>
  <p class="tag">An expected-value agent for recovering failed payments. Every action priced in rupees; waiting treated as a first-class action.</p>
  <p class="thesis"><strong>A failed payment is not a dead transaction.</strong> It is a decision problem &mdash; and almost everyone solves it with a <code>for</code> loop.</p>
</header>
<div id="app"></div>
<footer>
  <strong>Honest by construction.</strong> No public dataset of payment failures exists, so the world is simulated &mdash; but its hazard rates are <em>fitted</em> to published NPCI and Razorpay marginals rather than hand-tuned, every constant carries its provenance, policies are compared under common random numbers with the pairing asserted, and the assumptions are swept to find where the result breaks.
</footer>
</div>

<script>
const DATA = __DATA__;

const fmt = {
  pct: (v, d = 1) => (v * 100).toFixed(d) + '%',
  signPct: (v, d = 1) => (v >= 0 ? '+' : '') + (v * 100).toFixed(d) + '%',
  inr: v => '\\u20b9' + Math.round(v / 100).toLocaleString('en-IN'),
  int: v => Math.round(v).toLocaleString('en-IN'),
};
const el = (tag, attrs = {}, kids = []) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k === 'html') n.innerHTML = v;
    else n.setAttribute(k, v);
  }
  for (const kid of [].concat(kids)) n.append(kid);
  return n;
};
const section = (title) => {
  const wrap = el('div');
  wrap.append(el('div', { class: 'seam' }));
  const h = el('h2'); h.textContent = title; wrap.append(h);
  return wrap;
};

function table(headers, rows, opts = {}) {
  const t = el('table');
  const thead = el('thead');
  const tr = el('tr');
  headers.forEach((h, i) => {
    const th = el('th', i > 0 ? { class: 'num' } : {});
    th.textContent = h; tr.append(th);
  });
  thead.append(tr); t.append(thead);
  const tb = el('tbody');
  rows.forEach(r => {
    const row = el('tr', r.hero ? { class: 'hero' } : {});
    r.cells.forEach((c, i) => {
      const td = el('td', i > 0 ? { class: 'num' } : {});
      if (c && c.html !== undefined) td.innerHTML = c.html;
      else td.textContent = c;
      row.append(td);
    });
    tb.append(row);
  });
  t.append(tb);
  return el('div', { class: 'scroll' }, t);
}

function cards(items) {
  return el('div', { class: 'cards' }, items.map(i =>
    el('div', { class: 'card' }, [
      el('div', { class: 'n ' + (i.tone || ''), html: i.value }),
      el('div', { class: 'l', html: i.label }),
    ])));
}

function render() {
  const app = document.getElementById('app');
  const T = DATA.summary_table, cfg = DATA.config;
  const cmp = m => DATA.comparisons.find(c =>
    c.baseline === 'rule_based' && c.challenger === 'kintsugi' && c.metric === m);

  const rec = cmp('recovery_rate'), gmv = cmp('gmv_recovery_rate'), net = cmp('net_value_paise');
  const k = T.kintsugi, rb = T.rule_based, fr = T.fixed_retry;

  // -- headline ------------------------------------------------------
  app.append(section('Against a strong baseline'));
  app.append(cards([
    { value: fmt.pct(k.recovery_rate, 1), label: `of failed payments recovered<br>rules baseline ${fmt.pct(rb.recovery_rate, 1)}` },
    { value: fmt.signPct(gmv.relative_lift), tone: gmv.relative_lift > 0 ? 'up' : 'down',
      label: `more value recovered<br>${gmv.significant ? '95% CI excludes zero' : 'not significant'}` },
    { value: fmt.pct(rec.win_rate, 0), label: `of ${cfg.seeds} paired worlds won<br>p = ${rec.p_value.toFixed(4)}` },
    { value: fmt.int(k.wasted_retries), label: 'retries against dead instruments<br>fixed-retry: ' + fmt.int(fr.wasted_retries) },
  ]));

  app.append(section('All policies'));
  const labels = {
    no_recovery: ['No recovery (floor)', false],
    fixed_retry: ['Fixed retry + dunning (industry default)', false],
    rule_based: ['Cause-aware rules (strong baseline)', false],
    kintsugi: ['Kintsugi', true],
  };
  const maxGmv = Math.max(...Object.values(T).map(r => r.gmv_recovery_rate));
  app.append(table(
    ['Policy', 'Recovery', 'Value recovered', '', 'Cost', 'Retries', 'Nudges', 'Wasted'],
    Object.entries(labels).filter(([n]) => T[n]).map(([n, [label, hero]]) => {
      const r = T[n];
      return { hero, cells: [
        label, fmt.pct(r.recovery_rate, 1), fmt.pct(r.gmv_recovery_rate, 1),
        { html: `<div class="bar"><i style="width:${maxGmv ? (r.gmv_recovery_rate / maxGmv * 100) : 0}%"></i></div>` },
        fmt.inr(r.total_cost_paise), fmt.int(r.retries), fmt.int(r.nudges), fmt.int(r.wasted_retries),
      ] };
    })));
  app.append(el('p', { class: 'note', html:
    'Denominator is payments whose <em>first attempt failed</em>. Payments that authorised immediately were never the agent&rsquo;s to win.' }));

  // -- per cause -----------------------------------------------------
  const bc = DATA.by_failure_class;
  if (bc && bc.kintsugi) {
    app.append(section('Where the lift comes from'));
    const causes = Object.keys(bc.kintsugi).sort((a, b) => bc.kintsugi[b].failed - bc.kintsugi[a].failed);
    app.append(table(
      ['Failure cause', 'Disposition', 'Failed', 'Fixed retry', 'Rules', 'Kintsugi'],
      causes.map(c => {
        const row = bc.kintsugi[c];
        const g = (p) => bc[p] && bc[p][c] ? fmt.pct(bc[p][c].recovery_rate, 1) : '\\u2014';
        return { cells: [
          { html: `<code>${c}</code>` }, row.disposition, fmt.int(row.failed),
          g('fixed_retry'), g('rule_based'), { html: `<strong>${g('kintsugi')}</strong>` },
        ] };
      })));
    app.append(el('p', { class: 'note', html:
      '<code>TERMINAL</code> causes should read 0% for every policy &mdash; a dead instrument cannot be revived. The difference is what each policy <em>spends</em> discovering that.' }));
  }

  // -- components ----------------------------------------------------
  const d = DATA.detector, tax = DATA.taxonomy;
  app.append(section('Components, measured separately'));
  app.append(cards([
    { value: fmt.pct(d.precision, 0), label: `issuer-outage detection precision<br>recall ${fmt.pct(d.recall, 0)}, ${Math.round(d.median_detection_latency_min)} min latency` },
    { value: fmt.pct(d.recall_by_incident_duration['90min+'].recall, 0), label: 'recall on 90-minute-plus outages<br>the ones that actually cost money' },
    { value: fmt.pct(tax.rules.visible_accuracy, 0), label: 'rule accuracy on known decline strings<br>free, instant, deterministic' },
    { value: tax.llm_on_holdout.accuracy != null ? fmt.pct(tax.llm_on_holdout.accuracy, 0) : '\\u2014',
      label: `model accuracy on <em>unseen</em> strings<br>where rules score ${fmt.pct(tax.rules.holdout_accuracy, 0)}` },
  ]));
  app.append(el('p', { class: 'note', html:
    'The taxonomy gap is the entire argument for using a language model &mdash; and the reason it sits there rather than in the decision loop. Rules never guess wrong; they return <code>UNKNOWN</code>. New bank templates are the tail the model handles.' }));

  const models = DATA.models && DATA.models.models;
  if (models) {
    app.append(section('Predictors'));
    app.append(table(['Model', 'Rows', 'Base rate', 'AUC', 'Brier skill', 'Calibration error'],
      Object.entries(models).map(([n, m]) => ({ cells: [
        n, fmt.int(m.n_train), fmt.pct(m.positive_rate, 1), m.auc.toFixed(3),
        (m.brier_skill_score >= 0 ? '+' : '') + m.brier_skill_score.toFixed(3),
        m.expected_calibration_error.toFixed(4),
      ] }))));
    app.append(el('p', { class: 'note', html:
      'Calibration error matters more than AUC: the policy multiplies these probabilities by rupees, so a model that ranks well but is over-confident approves retries that lose money.' }));
  }

  // -- calibration ---------------------------------------------------
  const wc = DATA.world_calibration, prov = DATA.calibration_provenance && DATA.calibration_provenance.summary;
  if (wc && wc.checkout_success) {
    app.append(section('Is the world calibrated?'));
    app.append(table(['Quantity', 'Target', 'Achieved', 'Source'], [
      { cells: ['Checkout authorisation', wc.checkout_success.target.toFixed(4), wc.checkout_success.achieved.toFixed(4), 'Razorpay PSR guide'] },
      { cells: ['Mandate authorisation', wc.mandate_success.target.toFixed(4), wc.mandate_success.achieved.toFixed(4), 'UPI Autopay 30\\u201350%'] },
      { cells: ['Technical decline share', wc.technical_decline_share.target.toFixed(4), wc.technical_decline_share.achieved_checkout_only.toFixed(4), 'NPCI (checkout-only)'] },
    ]));
    if (prov) {
      app.append(el('p', { class: 'note', html:
        `Hazard rates are <em>fitted</em> to these marginals by iterative proportional fitting, not hand-tuned; worst per-cause error <strong>${fmt.pct(wc.max_rel_error, 1)}</strong>. Of ${prov.published + prov.derived + prov.assumption} calibration constants, <strong>${prov.published} are published</strong>, ${prov.derived} derived, ${prov.assumption} assumptions &mdash; and the assumptions are exactly what the sweep below moves.` }));
    }
  }

  // -- external validation -------------------------------------------
  if (DATA.validation) {
    const V = DATA.validation;
    app.append(section('Does the simulated world behave like the real one'));
    const mark = (ok) => ({ html: `<span class="pill ${ok ? 'y' : 'n'}">${ok ? 'match' : 'miss'}</span>` });
    const rows = V.bands.map(r => ({ cells: [
      r.metric, r.published, fmt.pct(r.simulated, 1), mark(r.within_band)] }));
    V.experiments.forEach(r => {
      const near = v => v >= 0.5 * r.published_value && v <= 2 * r.published_value;
      rows.push({ cells: [r.metric, r.published, fmt.signPct(r.simulated), mark(near(r.simulated))] });
      if (r.in_sequence_lift !== undefined) {
        rows.push({ hero: true, cells: [
          '\u2026 same change, first retry inside a 3-retry schedule',
          r.published, fmt.signPct(r.in_sequence_lift), mark(near(r.in_sequence_lift))] });
      }
      if (r.card_only_lift !== undefined) {
        rows.push({ cells: [
          '\u2026 same change, card payments only',
          r.published, fmt.signPct(r.card_only_lift), mark(near(r.card_only_lift))] });
      }
    });
    app.append(table(['Quantity', 'Published', 'Simulated', ''], rows));
    app.append(el('p', { class: 'note', html:
      'The world is calibrated to <strong>first-attempt marginals only</strong>, so every row here is out-of-sample. The timing result took two refuted hypotheses to resolve: measured in isolation it was eleven times the published figure, restricting to cards made it <em>worse</em>, and only measuring it the way a real dunning A/B does &mdash; moving the first retry inside an existing schedule &mdash; reproduced it. The remaining miss is a genuine population difference, stated rather than reconciled.' }));
  }

  // -- compliance ----------------------------------------------------
  if (T.kintsugi && T.kintsugi.scheme_violations !== undefined) {
    app.append(section('Scheme and regulator compliance'));
    app.append(table(['Policy', 'Violations', 'Fines'],
      Object.entries(labels).filter(([n]) => T[n] && n !== 'no_recovery').map(([n, [label, hero]]) => ({
        hero, cells: [label, fmt.int(T[n].scheme_violations || 0), fmt.inr(T[n].fines_paise || 0)] }))));
    app.append(el('p', { class: 'note', html:
      'NPCI caps a UPI Autopay mandate at one debit plus three retries and permits execution only in non-peak windows; Visa caps card-not-present resubmissions at 15 per card per 30 days; both schemes prohibit reattempting a never-retry decline. These are not costs to weigh, so they filter the action set before anything is priced. The layer is shared by every serious policy &mdash; reserving mandatory rules for the learned agent would manufacture a lead unrelated to decision quality.' }));
  }

  // -- ablation ------------------------------------------------------
  if (DATA.ablation) {
    app.append(section('Which idea earns the money'));
    app.append(table(['Variant removed', 'Net lift vs rules', 'Recovery lift', 'Wins', 'Share of the lift'],
      DATA.ablation.rows.map(r => ({
        hero: r.variant === 'full',
        cells: [
          r.variant === 'full' ? 'nothing (full agent)' : r.variant.replace(/^no_/, 'without ').replace(/_/g, ' '),
          fmt.signPct(r.net_lift_vs_rules), fmt.signPct(r.recovery_lift_vs_rules),
          fmt.pct(r.win_rate, 0),
          r.share_of_lift == null ? '\u2014' : fmt.pct(r.share_of_lift, 0),
        ]}))));
    app.append(el('p', { class: 'note', html:
      '<em>Share of the lift</em> is how much of the agent&rsquo;s advantage disappears when that one idea is removed. A single headline number says the agent is better without saying <em>why</em>, and why is the part that transfers.' }));
  }

  // -- contact frontier ----------------------------------------------
  if (DATA.contact_frontier) {
    const rows = DATA.contact_frontier.rows;
    app.append(section('Recovery against customer contact'));
    const maxN = Math.max(...rows.map(r => r.nudges)) || 1;
    app.append(table(['Policy', 'Recovery', 'Value recovered', 'Messages', '', 'Cost'],
      rows.map(r => ({
        cells: [
          r.label, fmt.pct(r.recovery_rate, 2), fmt.pct(r.gmv_recovery_rate, 2),
          fmt.int(r.nudges),
          { html: `<div class="bar"><i style="width:${r.nudges / maxN * 100}%"></i></div>` },
          fmt.inr(r.total_cost_paise),
        ]}))));
    app.append(el('p', { class: 'note', html:
      'An expected-value agent given only the <em>send</em> price of a message will message everyone forever &mdash; 20 paise against a payment worth hundreds of rupees clears almost any bar. What that misses is that attention is not free to the business either, and none of it appears on the telecom invoice.' }));
  }

  // -- detector study ------------------------------------------------
  if (DATA.detector_study) {
    app.append(section('Does the agent starve its own detector'));
    app.append(table(['Payments', 'Policy driving traffic', 'Precision', 'Recall', 'Latency'],
      DATA.detector_study.rows.map(r => ({ cells: [
        fmt.int(r.payments), r.policy, fmt.pct(r.precision, 1),
        fmt.pct(r.recall, 1), Math.round(r.median_latency_min) + ' min',
      ]}))));
    app.append(el('p', { class: 'note', html:
      'A hypothesis that did not survive testing. The agent routes away from issuers it suspects, which should destroy the evidence that would confirm them &mdash; but at matched volume the closed loop, the open loop, and the agent with its monitor disabled all land within noise. Traffic volume explains the original discrepancy entirely. Kept because a plausible mechanism shown to be absent is worth more than one assumed to be present.' }));
  }

  // -- sensitivity ---------------------------------------------------
  if (DATA.sensitivity) {
    const s = DATA.sensitivity.summary, rows = DATA.sensitivity.results;
    app.append(section('Does the result survive its assumptions?'));
    app.append(cards([
      { value: `${s.positive}/${s.n_perturbations}`, label: 'perturbations keep the lift positive' },
      { value: `${s.significant_positive}`, label: 'remain significantly positive' },
      { value: `${s.significant_negative}`, tone: s.significant_negative > 0 ? 'down' : '', label: 'significantly negative (reported either way)' },
      { value: fmt.signPct(s.median_lift), label: `median lift<br>range ${fmt.signPct(s.min_lift)} to ${fmt.signPct(s.max_lift)}` },
    ]));
    app.append(table(['Assumption moved', 'Group', 'Lift', 'Significant', 'Why this setting'],
      rows.map(r => ({ cells: [
        r.label, r.group, fmt.signPct(r.lift_relative),
        { html: `<span class="pill ${r.significant ? 'y' : 'n'}">${r.significant ? 'yes' : 'no'}</span>` },
        r.note,
      ] }))));
    app.append(el('p', { class: 'note', html:
      'Every constant here carries <code>ASSUMPTION</code> provenance &mdash; no published source. Several settings are deliberately hostile: retries nearly free, reminders highly effective, customers infinitely patient, almost no payday signal.' }));
  }
}
render();
</script>
"""


def main() -> None:
    if not RESULTS.exists():
        raise SystemExit("Run scripts.run_evaluation first.")
    data = json.loads(RESULTS.read_text())
    for key, path in (("sensitivity", SENSITIVITY), ("ablation", ABLATION),
                      ("contact_frontier", FRONTIER),
                      ("detector_study", DETECTOR),
                      ("validation", VALIDATION)):
        if path.exists():
            data[key] = json.loads(path.read_text())

    # Drop the bulky provenance table; the dashboard only shows the summary.
    data.get("calibration_provenance", {}).pop("table", None)

    html = TEMPLATE.replace("__DATA__", json.dumps(data, default=str))
    OUT.write_text(html)
    print(f"Wrote {OUT}  ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
