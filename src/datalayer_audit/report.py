"""Raport audytu: jeden model danych (JSON) i dwa widoki (Markdown, HTML).

Zasada: liczby liczy wyłącznie AuditReport. Widoki je tylko formatują. Gdyby szablon
HTML sam sumował pushe, a Markdown robił to inaczej, dwa raporty z tego samego
przebiegu mogłyby pokazać różne wyniki - klasyczny rozjazd dashboardu z modelem.
"""

from collections.abc import Sequence
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment, select_autoescape
from pydantic import BaseModel, ValidationError, computed_field

from datalayer_audit.capture import CapturedPush
from datalayer_audit.contract import TRACKING_PLAN_EVENTS, push_kind, validate_push

# Etykiety dla czytelnika bez znajomości kodu. Kolejność = kolejność wierszy w raporcie.
EVENT_LABELS: dict[str, str] = {
    "cookie_consent_update": "Decyzja o zgodach (każda)",
    # „udzielona”, a nie „tylko”: zdarzenie leci przy każdej decyzji zawierającej tę zgodę.
    "cookie_consent_analytics": "Zgoda analityczna udzielona (w dowolnej decyzji)",
    "cookie_consent_marketing": "Zgoda marketingowa udzielona (w dowolnej decyzji)",
    "phone_reveal": "Odkrycie numeru telefonu",
    "phone_call": "Kliknięcie w numer telefonu",
    "linkedin_click": "Przejście na LinkedIn",
    "chat_open": "Otwarcie czatu z bliźniakiem AI",
    "mobile_menu_open": "Otwarcie menu mobilnego",
}
assert set(EVENT_LABELS) == TRACKING_PLAN_EVENTS, "etykiety rozjechały się z planem"


class PushRecord(BaseModel):
    index: int
    t_ms: float
    kind: str | None
    payload: Any
    contract_error: str | None

    @classmethod
    def from_captured(cls, push: CapturedPush) -> "PushRecord":
        try:
            validate_push(push.payload)
            error = None
        except ValidationError as exc:
            # Bez nagłówka i linków do dokumentacji - w raporcie liczy się sam powód.
            error = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return cls(
            index=push.index,
            t_ms=push.t_ms,
            kind=push_kind(push.payload),
            payload=push.payload,
            contract_error=error,
        )


class ScenarioResult(BaseModel):
    node_id: str
    title: str
    outcome: Literal["passed", "failed", "skipped"]
    failure: str | None = None
    duration_s: float
    pushes: list[PushRecord]
    blocked_requests: list[str]


class EventSummary(BaseModel):
    event: str
    label: str
    in_plan: bool
    fired: int
    valid: int
    scenarios: list[str]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> Literal["ok", "invalid", "missing", "unexpected"]:
        if not self.in_plan:
            return "unexpected"
        if self.fired == 0:
            return "missing"
        return "ok" if self.valid == self.fired else "invalid"


class Metric(BaseModel):
    key: str
    label: str
    hint: str
    numerator: int
    denominator: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def percent(self) -> float:
        # Pusty mianownik to brak danych, nie 100%: zero scenariuszy nie jest sukcesem.
        if self.denominator == 0:
            return 0.0
        return round(100 * self.numerator / self.denominator, 1)

    @property
    def percent_label(self) -> str:
        """Polski zapis dla czytelnika raportu: 87,5% zamiast 87.5%. Poza JSON-em -
        maszyna dostaje liczbę, człowiek tekst."""
        return f"{self.percent:g}".replace(".", ",") + "%"


class AuditReport(BaseModel):
    """Wynik jednego przebiegu. computed_field trafia do JSON-a, więc konsument
    (CI, przyszły dashboard) nie musi powtarzać logiki liczenia."""

    generated_at: datetime
    base_url: str
    scenarios: list[ScenarioResult]

    def _all_pushes(self) -> list[tuple[ScenarioResult, PushRecord]]:
        return [(s, p) for s in self.scenarios for p in s.pushes]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def events(self) -> list[EventSummary]:
        rows: dict[str, EventSummary] = {
            name: EventSummary(
                event=name, label=label, in_plan=True, fired=0, valid=0, scenarios=[]
            )
            for name, label in EVENT_LABELS.items()
        }
        for scenario, push in self._all_pushes():
            name = push.kind or "(nierozpoznany kształt)"
            # Komendy gtag i gtm.js są infrastrukturą, nie zdarzeniami planu - liczymy
            # je w zgodności z kontraktem, ale nie w tabeli zdarzeń.
            if name.startswith("gtag:") or name == "gtm.js":
                continue
            row = rows.setdefault(
                name,
                EventSummary(
                    event=name, label="Spoza planu", in_plan=False, fired=0, valid=0, scenarios=[]
                ),
            )
            row.fired += 1
            row.valid += push.contract_error is None
            if scenario.title not in row.scenarios:
                row.scenarios.append(scenario.title)
        return list(rows.values())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def metrics(self) -> list[Metric]:
        plan_rows = [e for e in self.events if e.in_plan]
        pushes = [p for _, p in self._all_pushes()]
        return [
            Metric(
                key="plan_coverage",
                label="Pokrycie planu",
                hint="zdarzenia z planu odpalone poprawnie co najmniej raz",
                numerator=sum(e.status == "ok" for e in plan_rows),
                denominator=len(plan_rows),
            ),
            Metric(
                key="contract",
                label="Zgodność z kontraktem",
                hint="pushe przechodzące walidację, łącznie z komendami gtag",
                numerator=sum(p.contract_error is None for p in pushes),
                denominator=len(pushes),
            ),
            Metric(
                key="scenarios",
                label="Scenariusze zielone",
                hint="scenariusze, w których kolejność i parametry są zgodne z planem",
                numerator=sum(s.outcome == "passed" for s in self.scenarios),
                denominator=len(self.scenarios),
            ),
        ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        return all(m.denominator > 0 and m.numerator == m.denominator for m in self.metrics)


def push_records(pushes: Sequence[CapturedPush]) -> list[PushRecord]:
    return [PushRecord.from_captured(p) for p in pushes]


# Wszystkie teksty widoczne dla czytelnika w JEDNYM miejscu. Oba szablony (HTML i MD)
# czytają ten słownik, więc nie mogą się rozjechać w nazwach sekcji ani kolumn.
TEXT: dict[str, str] = {
    "title": "Audyt dataLayer",
    "verdict_ok": "Zgodny z planem",
    "verdict_bad": "Niezgodny z planem",
    "metrics": "Wskaźniki",
    "events": "Zdarzenia z planu",
    "scenarios": "Scenariusze",
    "col_event": "Zdarzenie",
    "col_label": "Opis",
    "col_fired": "Odpalone",
    "col_valid": "Zgodne",
    "col_status": "Status",
    "col_seen_in": "Wystąpiło w scenariuszach",
    "pushes": "pushy",
    "blocked": "Zablokowane żądania (GTM nie załadowany, więc nic nie trafia do GA4)",
}

# autoescape: payload pochodzi ze strony. `link_text` z <script> w środku bez escapowania
# wykonałby się w przeglądarce czytającej raport. Jinja escapuje każde {{ }} domyślnie.
_ENV = Environment(autoescape=select_autoescape(default=True), trim_blocks=True, lstrip_blocks=True)
_HTML = _ENV.from_string(
    files("datalayer_audit").joinpath("report.html.j2").read_text(encoding="utf-8")
)
# Markdown bez autoescape: encje HTML (&lt;) w blokach kodu wyświetliłyby się dosłownie.
# Bezpieczeństwo zapewnia renderer - GitHub sanityzuje HTML w Markdownie.
_MD = Environment(autoescape=False, trim_blocks=True, lstrip_blocks=True).from_string(
    files("datalayer_audit").joinpath("report.md.j2").read_text(encoding="utf-8")
)

STATUS_LABELS = {
    "ok": "zgodne",
    "invalid": "błąd kontraktu",
    "missing": "nie odpalone",
    "unexpected": "spoza planu",
}
OUTCOME_LABELS = {"passed": "zielony", "failed": "czerwony", "skipped": "pominięty"}


def _context(report: AuditReport) -> dict[str, Any]:
    return {
        "r": report,
        "t": TEXT,
        "status_labels": STATUS_LABELS,
        "outcome_labels": OUTCOME_LABELS,
    }


def render_html(report: AuditReport) -> str:
    return _HTML.render(_context(report))


def render_markdown(report: AuditReport) -> str:
    """Ta sama treść i kolejność sekcji co HTML. Istnieje, bo podsumowanie joba w GitHub
    Actions przyjmuje wyłącznie Markdown, a MD da się wkleić do issue albo notatki."""
    return _MD.render(_context(report)).rstrip() + "\n"


def write_report(report: AuditReport, out_dir: Path) -> list[Path]:
    """Zapisuje JSON (źródło) i oba widoki. Zwraca ścieżki w kolejności: json, md, html."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Data z godziną: dwa przebiegi tego samego dnia nie nadpisują się nawzajem.
    stem = f"audit-{report.generated_at:%Y-%m-%d-%H%M%S}"
    paths = [out_dir / f"{stem}.{ext}" for ext in ("json", "md", "html")]
    paths[0].write_text(report.model_dump_json(indent=2), encoding="utf-8")
    paths[1].write_text(render_markdown(report), encoding="utf-8")
    paths[2].write_text(render_html(report), encoding="utf-8")
    return paths
