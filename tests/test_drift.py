"""Drift kontraktu względem events.ts: parser na atrapach + jeden test na prawdziwym pliku."""

import os
from pathlib import Path

import pytest

from datalayer_audit.drift import (
    TrackingPlan,
    TrackingPlanParseError,
    drift_problems,
    load_tracking_plan,
    parse_tracking_plan,
)

# Domyślnie repo strony leży obok tego repo; CI podaje ścieżkę do własnego checkoutu.
PLAN_PATH = Path(
    os.environ.get("TRACKING_PLAN_PATH", "../personal-page/src/data/events.ts")
).resolve()

# Wycinek o układzie identycznym z events.ts: komentarze sekcji, opis z cudzysłowami
# i dwukropkami, params na głębszym wcięciu.
SAMPLE = """
export const EVENTS = {
  // --- kontakt ---
  phoneReveal: 'phone_reveal',
  linkedinClick: 'linkedin_click',
} as const;

export const EVENT_CATALOG: Record<EventName, EventSpec> = {
  phone_reveal: {
    category: 'kontakt',
    trigger: 'Kliknięcie „Pokaż numer": odkrycie.',
  },
  linkedin_click: {
    category: 'kontakt',
    params: {
      link_text: 'Tekst CTA (np. „Napisz"): rozróżnia przyciski.',
      link_url: 'Docelowy URL.',
    },
  },
};
"""


def test_parser_reads_events_and_params() -> None:
    plan = parse_tracking_plan(SAMPLE)
    assert plan.events == {"phone_reveal", "linkedin_click"}
    assert plan.params == {
        "phone_reveal": frozenset(),
        "linkedin_click": frozenset({"link_text", "link_url"}),
    }


@pytest.mark.parametrize(
    "source",
    [
        "export const OTHER = {};",  # brak bloków
        SAMPLE.replace("phoneReveal: 'phone_reveal',", ""),  # EVENTS bez wpisu z katalogu
        SAMPLE.replace("linkedinClick: 'linkedin_click'", "linkedinClick: 'phone_reveal'"),
    ],
    ids=["no_blocks", "catalog_mismatch", "duplicate_name"],
)
def test_parser_fails_loudly_on_unknown_layout(source: str) -> None:
    with pytest.raises(TrackingPlanParseError):
        parse_tracking_plan(source)


def test_drift_lists_every_difference() -> None:
    plan = TrackingPlan(
        events=frozenset({"phone_reveal", "linkedin_click", "form_submit"}),
        params={
            "phone_reveal": frozenset(),
            "linkedin_click": frozenset({"link_url"}),
            "form_submit": frozenset(),
        },
    )
    problems = drift_problems(plan)
    assert any("'form_submit' jest w planie" in p for p in problems)
    assert any("'chat_open' jest w kontrakcie" in p for p in problems)
    assert any(p.startswith("parametry 'linkedin_click'") for p in problems)


def test_contract_matches_site_tracking_plan() -> None:
    """Nowe zdarzenie na stronie bez modelu w kontrakcie = czerwony build."""
    if not PLAN_PATH.exists():
        # Lokalnie bez repo strony test nie ma czego porównać. W CI brak pliku to błąd
        # konfiguracji (checkout, token) - pominięcie dałoby fałszywie zielony build.
        if os.environ.get("CI"):
            pytest.fail(f"CI bez tracking planu: {PLAN_PATH} nie istnieje")
        pytest.skip(f"brak {PLAN_PATH} - ustaw TRACKING_PLAN_PATH")
    problems = drift_problems(load_tracking_plan(PLAN_PATH))
    assert not problems, "drift kontraktu względem events.ts:\n- " + "\n- ".join(problems)
