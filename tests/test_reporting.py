"""The report and dashboard must survive a change to what the evaluation emits.

These are the only two places where a rename in `run_evaluation` breaks
something silently. The report keeps rendering with a section quietly missing;
the dashboard throws inside the browser and shows a blank page, which nobody
sees until a reviewer opens the link.

That happened once: `llm_on_holdout` was renamed to `end_to_end_on_holdout` to
fix a denominator disagreement, and the dashboard kept reading the old key.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def _artefact(name: str):
    path = DATA / name
    if not path.exists():
        pytest.skip(f"{name} not generated yet")
    return json.loads(path.read_text())


def test_the_report_renders_from_the_committed_artefacts(tmp_path, monkeypatch):
    from scripts import render_report

    _artefact("results.json")
    out = tmp_path / "RESULTS.md"
    monkeypatch.setattr(render_report, "OUT", out)
    render_report.main()

    text = out.read_text()
    assert len(text) > 2_000, "report suspiciously short"
    assert "## Headline" in text
    # A section that renders its header but no rows is the silent failure.
    for heading in ("## Headline", "## Paired comparisons"):
        body = text.split(heading, 1)[1][:1200]
        assert "|---" in body, f"{heading} rendered without a table"


def test_the_dashboard_consumes_every_key_the_evaluation_emits():
    """Guards renames between the evaluation and the page that reads it."""
    from scripts import build_dashboard

    results = _artefact("results.json")
    script = re.search(r"<script>(.*)</script>", build_dashboard.TEMPLATE, re.S)
    assert script, "dashboard template has no script block"
    js = script.group(1)

    taxonomy = results.get("taxonomy", {})
    accuracy_keys = [k for k in ("end_to_end_on_holdout", "llm_on_holdout")
                     if k in taxonomy]
    assert accuracy_keys, "evaluation emits no held-out accuracy key"
    assert any(k in js for k in accuracy_keys), (
        f"dashboard reads none of {accuracy_keys}; a rename has broken it")

    for key in ("summary_table", "comparisons", "detector", "taxonomy"):
        assert key in results, f"evaluation stopped emitting {key}"
        assert key in js, f"dashboard stopped reading {key}"


def test_the_dashboard_is_self_contained_and_themed():
    """No external fetches, and no colour defined only in a dark block.

    A token defined only inside a media or [data-theme] block is the classic
    unreadable-artifact bug: the default "system" state stamps nothing, so the
    page renders one theme's text on the other theme's background.
    """
    page = ROOT / "dashboard.html"
    if not page.exists():
        pytest.skip("dashboard not built yet")
    html = page.read_text()

    for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "<script src="):
        assert forbidden not in html, f"dashboard reaches the network: {forbidden}"

    css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    light = set(re.findall(r"(--[a-z-]+)\s*:", css[:css.index("@media")]))
    dark = set(re.findall(r"(--[a-z-]+)\s*:", css[css.index("@media"):]))
    assert not (dark - light), (
        f"tokens defined only in a dark block: {sorted(dark - light)}")
    assert "background: var(--ground)" in css, "body has no explicit background"
