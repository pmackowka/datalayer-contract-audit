"""Raport bez przeglądarki: liczenie wskaźników, statusy zdarzeń i bezpieczeństwo HTML."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from datalayer_audit.capture import CapturedPush
from datalayer_audit.report import (
    TEXT,
    AuditReport,
    Metric,
    ScenarioResult,
    push_records,
    render_html,
    render_markdown,
    write_report,
)

WHEN = datetime(2026, 10, 1, 12, 30, 5, tzinfo=UTC)


def scenario(title: str, payloads: list[Any], outcome: str = "passed") -> ScenarioResult:
    pushes = [CapturedPush(index=i, t_ms=float(i), payload=p) for i, p in enumerate(payloads)]
    return ScenarioResult(
        node_id=f"tests/e2e/test_x.py::{title}",
        title=title,
        outcome=outcome,  # type: ignore[arg-type]
        failure="AssertionError: boom" if outcome == "failed" else None,
        duration_s=1.0,
        pushes=push_records(pushes),
        blocked_requests=["loader GTM (pmdata.pl)"],
    )


def report(*scenarios: ScenarioResult) -> AuditReport:
    return AuditReport(generated_at=WHEN, base_url="https://pmdata.pl", scenarios=list(scenarios))


def metric(r: AuditReport, key: str) -> Metric:
    return next(m for m in r.metrics if m.key == key)


def test_partial_run_reports_each_dimension_separately() -> None:
    r = report(
        scenario("telefon", [{"event": "phone_reveal"}, {"event": "phone_call"}]),
        scenario("czat", [{"event": "chat_open", "extra": 1}], outcome="failed"),
        scenario("komenda", [["set", "url_passthrough", True]]),
    )
    # 2 z 8 zdarzeń planu odpalone poprawnie; chat_open odpalony, ale z błędem.
    assert (metric(r, "plan_coverage").numerator, metric(r, "plan_coverage").denominator) == (2, 8)
    assert metric(r, "plan_coverage").percent == 25.0
    assert metric(r, "contract").percent_label == "75%"
    assert metric(r, "scenarios").percent_label == "66,7%"
    # Komenda gtag liczy się do zgodności, choć nie ma jej w tabeli zdarzeń.
    assert (metric(r, "contract").numerator, metric(r, "contract").denominator) == (3, 4)
    assert (metric(r, "scenarios").numerator, metric(r, "scenarios").denominator) == (2, 3)
    assert r.passed is False

    status = {e.event: e.status for e in r.events}
    assert status["phone_reveal"] == "ok"
    assert status["chat_open"] == "invalid"
    assert status["mobile_menu_open"] == "missing"


def test_unknown_event_gets_its_own_row() -> None:
    r = report(scenario("literówka", [{"event": "phone_revealed"}, "goły string"]))
    rows = {e.event: e for e in r.events}
    assert rows["phone_revealed"].status == "unexpected"
    assert rows["(nierozpoznany kształt)"].fired == 1


def test_time_label_shows_polish_time_and_utc() -> None:
    # WHEN = 12:30 UTC 1 października, czyli czas letni (UTC+2) -> 14:30 w Polsce.
    label = report().generated_at_label
    assert label == "2026-10-01 14:30 czasu polskiego (12:30 UTC)"
    assert label in render_markdown(report())


def test_empty_run_is_not_a_success() -> None:
    r = report()
    assert metric(r, "scenarios").percent == 0.0
    assert r.passed is False


def test_full_run_passes() -> None:
    linkedin = {
        "event": "linkedin_click",
        "link_text": "LinkedIn",
        "link_url": "https://www.linkedin.com/in/x/",
    }
    plan = [
        {"event": name}
        for name in (
            "cookie_consent_update",
            "cookie_consent_analytics",
            "cookie_consent_marketing",
            "phone_reveal",
            "phone_call",
            "chat_open",
            "mobile_menu_open",
        )
    ]
    r = report(scenario("wszystko", [*plan, linkedin]))
    assert r.passed is True
    assert "✅ Zgodny z planem" in render_markdown(r)


def test_html_escapes_payload_from_the_page() -> None:
    # link_text pochodzi z textContent strony - może zawierać dowolny tekst, także HTML.
    evil = {"event": "linkedin_click", "link_text": "<script>alert(1)</script>", "link_url": "x"}
    html = render_html(report(scenario("xss", [evil])))
    assert "<script>alert(1)</script>" not in html
    assert "\\u003cscript\\u003e" in html  # tojson zamienia < i > na sekwencje unicode


def test_failed_scenario_is_expanded_in_both_views() -> None:
    r = report(scenario("czat", [{"event": "chat_open", "x": 1}], "failed"))
    for view in (render_markdown(r), render_html(r)):
        assert "<details open>" in view
        assert "AssertionError: boom" in view
        assert "Extra inputs are not permitted" in view


def test_views_share_every_label() -> None:
    # Symetria widoków: każdy tekst ze słownika TEXT występuje i w HTML, i w MD.
    # Gdyby ktoś dopisał sekcję tylko do jednego szablonu, ten test to wyłapie.
    r = report(scenario("telefon", [{"event": "phone_reveal"}]))
    html, md = render_html(r), render_markdown(r)
    for key, text in TEXT.items():
        if key == "verdict_ok":  # przebieg niepełny - widać werdykt negatywny
            continue
        assert text in html, f"HTML bez tekstu {key!r}"
        assert text in md, f"Markdown bez tekstu {key!r}"


def test_write_report_creates_json_source_and_two_views(tmp_path: Path) -> None:
    paths = write_report(report(scenario("czat", [{"event": "chat_open"}])), tmp_path)
    assert [p.name for p in paths] == [
        "audit-2026-10-01-123005.json",
        "audit-2026-10-01-123005.md",
        "audit-2026-10-01-123005.html",
    ]
    data = json.loads(paths[0].read_text())
    # computed_field ląduje w JSON-ie: konsument nie musi liczyć wskaźników sam.
    assert {m["key"] for m in data["metrics"]} == {"plan_coverage", "contract", "scenarios"}


def test_green_scenario_with_invalid_push_is_still_a_problem() -> None:
    # Scenariusz może przejść (sekwencja się zgadza), a push i tak łamać kontrakt -
    # raport ma to pokazać, mimo że test jest zielony.
    s = scenario("czat", [{"event": "chat_open"}, {"event": "chat_open", "x": 1}])
    r = report(s)
    row = next(e for e in r.events if e.event == "chat_open")
    assert (row.fired, row.valid, row.scenarios) == (2, 1, ["czat"])
    md = render_markdown(r)
    assert md.count("Extra inputs are not permitted") == 1
