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
OUT = ROOT / "dashboard.html"

TEMPLATE = """<title>Kintsugi</title>
<style>
  :root {
    --bg: #fbfaf8; --panel: #ffffff; --ink: #1a1714; --muted: #6b6259;
    --line: #e6e0d8; --gold: #b08442; --gold-soft: #f0e4cd;
    --good: #2f7d55; --bad: #b4453a; --dim: #9a9088;
    --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #16130f; --panel: #1e1a15; --ink: #f0ebe4; --muted: #a89e93;
      --line: #332c24; --gold: #d4a45c; --gold-soft: #3a2f1d;
      --good: #62b98a; --bad: #e0796c; --dim: #7d7469;
    }
  }
  :root[data-theme="dark"] {
    --bg: #16130f; --panel: #1e1a15; --ink: #f0ebe4; --muted: #a89e93;
    --line: #332c24; --gold: #d4a45c; --gold-soft: #3a2f1d;
    --good: #62b98a; --bad: #e0796c; --dim: #7d7469;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font: 16px/1.65 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 1080px; margin: 0 auto; padding: 56px 24px 96px; }
  header { border-bottom: 2px solid var(--gold); padding-bottom: 28px; margin-bottom: 44px; }
  h1 { font-size: clamp(34px, 6vw, 52px); margin: 0 0 6px; letter-spacing: -0.025em; font-weight: 640; }
  .kanji { color: var(--gold); font-weight: 400; }
  .tag { color: var(--muted); font-size: 17px; max-width: 62ch; margin: 0; }
  .thesis {
    margin: 30px 0 0; padding: 18px 22px; background: var(--gold-soft);
    border-left: 3px solid var(--gold); border-radius: 0 8px 8px 0;
    font-size: 17px; line-height: 1.55;
  }
  h2 {
    font-size: 13px; text-transform: uppercase; letter-spacing: 0.13em;
    color: var(--muted); margin: 52px 0 18px; font-weight: 660;
  }
  h2:first-of-type { margin-top: 40px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 14px; }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 18px 20px; }
  .card .n { font-size: 30px; font-weight: 660; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
  .card .l { font-size: 12.5px; color: var(--muted); margin-top: 3px; line-height: 1.4; }
  .up { color: var(--good); } .down { color: var(--bad); }
  .scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  table { width: 100%; border-collapse: collapse; font-size: 14.5px; min-width: 560px; }
  th, td { padding: 10px 12px; text-align: right; border-bottom: 1px solid var(--line); white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; white-space: normal; }
  th { font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); font-weight: 640; }
  tbody tr.hero { background: var(--gold-soft); }
  tbody tr.hero td { font-weight: 640; }
  td.num, th.num { font-variant-numeric: tabular-nums; font-family: var(--mono); font-size: 13.5px; }
  .bar { height: 7px; background: var(--line); border-radius: 4px; overflow: hidden; min-width: 90px; }
  .bar > i { display: block; height: 100%; background: var(--gold); }
  code { font-family: var(--mono); font-size: 12.5px; background: var(--gold-soft); padding: 1px 5px; border-radius: 4px; }
  .note { color: var(--muted); font-size: 14px; max-width: 74ch; }
  .pill { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 99px; font-weight: 640; letter-spacing: 0.03em; }
  .pill.y { background: color-mix(in srgb, var(--good) 16%, transparent); color: var(--good); }
  .pill.n { background: color-mix(in srgb, var(--dim) 20%, transparent); color: var(--muted); }
  footer { margin-top: 64px; padding-top: 22px; border-top: 1px solid var(--line); color: var(--muted); font-size: 13.5px; }
</style>

<div class="wrap">
<header>
  <h1>Kintsugi <span class="kanji">金継ぎ</span></h1>
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
const section = (title) => { const h = el('h2'); h.textContent = title; return h; };

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
      'Identical detector code, different measurements. The agent routes away from issuers it suspects &mdash; which destroys the evidence that would have confirmed them. A real production effect: any system that avoids a suspected-bad endpoint stops learning about it.' }));
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
                      ("detector_study", DETECTOR)):
        if path.exists():
            data[key] = json.loads(path.read_text())

    # Drop the bulky provenance table; the dashboard only shows the summary.
    data.get("calibration_provenance", {}).pop("table", None)

    html = TEMPLATE.replace("__DATA__", json.dumps(data, default=str))
    OUT.write_text(html)
    print(f"Wrote {OUT}  ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
