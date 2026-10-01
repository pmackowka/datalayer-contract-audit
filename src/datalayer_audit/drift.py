"""Drift: porównanie kontraktu z tracking planem strony (`src/data/events.ts`).

events.ts to TypeScript, a nie JSON, więc czytamy go regexami. To kruche z założenia -
dlatego parser sprawdza sam siebie: nazwy z EVENTS muszą się zgadzać z kluczami
EVENT_CATALOG. Gdy ktoś zmieni układ pliku, parser rzuci TrackingPlanParseError zamiast
po cichu zwrócić pusty plan, który dałby fałszywie zielony test.

Alternatywa - uruchomienie Node i import modułu - dałaby pewny wynik, ale dokłada
drugi runtime do CI tylko po to, żeby przeczytać osiem stringów.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from datalayer_audit.contract import TRACKING_PLAN_EVENTS, event_params

_EVENTS_BLOCK = re.compile(r"export const EVENTS = \{(?P<body>.*?)\} as const;", re.DOTALL)
# camelCaseKey: 'snake_case_name' - komentarze `// ---` w bloku nie pasują do wzorca.
_EVENT_ENTRY = re.compile(r"^\s*\w+:\s*'(?P<name>[a-z0-9_]+)',?\s*$", re.MULTILINE)
_CATALOG_BLOCK = re.compile(r"export const EVENT_CATALOG[^=]*=\s*\{(?P<body>.*?)\n\};", re.DOTALL)
# Wpis katalogu zaczyna się od nazwy zdarzenia na wcięciu 2 spacji: `  phone_reveal: {`.
_CATALOG_ENTRY = re.compile(r"^  (?P<name>[a-z0-9_]+): \{$", re.MULTILINE)
_PARAMS_BLOCK = re.compile(r"^\s*params: \{(?P<body>.*?)^\s*\},?$", re.DOTALL | re.MULTILINE)
_PARAM_KEY = re.compile(r"^\s*(?P<key>[a-z0-9_]+):", re.MULTILINE)


class TrackingPlanParseError(ValueError):
    """Układ events.ts zmienił się tak, że parser nie umie go już wiarygodnie przeczytać."""


@dataclass(frozen=True)
class TrackingPlan:
    events: frozenset[str]
    params: dict[str, frozenset[str]]


def parse_tracking_plan(source: str) -> TrackingPlan:
    events_match = _EVENTS_BLOCK.search(source)
    catalog_match = _CATALOG_BLOCK.search(source)
    if not events_match or not catalog_match:
        raise TrackingPlanParseError("nie znaleziono bloku EVENTS albo EVENT_CATALOG")

    events = [m["name"] for m in _EVENT_ENTRY.finditer(events_match["body"])]
    if not events or len(events) != len(set(events)):
        raise TrackingPlanParseError(f"EVENTS puste albo z duplikatami: {events}")

    body = catalog_match["body"]
    starts = list(_CATALOG_ENTRY.finditer(body))
    params: dict[str, frozenset[str]] = {}
    for i, entry in enumerate(starts):
        # Wpis kończy się tam, gdzie zaczyna się następny - prościej niż liczyć klamry.
        end = starts[i + 1].start() if i + 1 < len(starts) else len(body)
        params_match = _PARAMS_BLOCK.search(body, entry.end(), end)
        keys = (
            frozenset(m["key"] for m in _PARAM_KEY.finditer(params_match["body"]))
            if params_match
            else frozenset()
        )
        params[entry["name"]] = keys

    if set(params) != set(events):
        raise TrackingPlanParseError(
            f"EVENTS i EVENT_CATALOG się rozjechały: EVENTS={sorted(events)}, "
            f"EVENT_CATALOG={sorted(params)}"
        )
    return TrackingPlan(events=frozenset(events), params=params)


def drift_problems(plan: TrackingPlan) -> list[str]:
    """Różnice plan ↔ kontrakt jako zdania do komunikatu testu. Pusta lista = brak driftu."""
    problems = [
        f"zdarzenie '{name}' jest w planie strony, a kontrakt go nie zna - dodaj model"
        for name in sorted(plan.events - TRACKING_PLAN_EVENTS)
    ]
    problems += [
        f"zdarzenie '{name}' jest w kontrakcie, a strona go już nie ma - usuń model"
        for name in sorted(TRACKING_PLAN_EVENTS - plan.events)
    ]
    for name in sorted(plan.events & TRACKING_PLAN_EVENTS):
        expected, actual = plan.params[name], event_params(name)
        if expected != actual:
            problems.append(
                f"parametry '{name}': plan {sorted(expected)}, kontrakt {sorted(actual)}"
            )
    return problems


def load_tracking_plan(path: Path) -> TrackingPlan:
    return parse_tracking_plan(path.read_text(encoding="utf-8"))
