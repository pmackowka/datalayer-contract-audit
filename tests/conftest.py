"""Fixture'y wspólne dla testów przeglądarkowych + spięcie scenariuszy z raportem.

Raport powstaje tylko, gdy ustawiona jest zmienna AUDIT_REPORT_DIR (robi to `make audit`).
Zwykłe `make check` i `make e2e` niczego nie zapisują.
"""

import os
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, Page

from datalayer_audit.capture import CapturedPush, DataLayerSpy
from datalayer_audit.guard import NetworkGuard
from datalayer_audit.report import AuditReport, ScenarioResult, push_records, write_report

# StashKey: typowany schowek pytest na dane przypięte do konkretnego testu (item).
# Fixture'y wkładają tu pushe i zablokowane żądania, hook - wynik testu.
PUSHES = pytest.StashKey[list[CapturedPush]]()
BLOCKED = pytest.StashKey[list[str]]()
REPORT = pytest.StashKey[pytest.TestReport]()


@pytest.fixture
def network_guard(
    request: pytest.FixtureRequest, context: BrowserContext
) -> Generator[NetworkGuard]:
    guard = NetworkGuard()
    guard.install(context)
    yield guard
    request.node.stash[BLOCKED] = guard.blocked


@pytest.fixture
def page(page: Page, network_guard: NetworkGuard) -> Page:
    """Nadpisanie `page` z pytest-playwright: każda strona startuje z osłoną sieci.

    Fixture o tej samej nazwie, który prosi o samego siebie, dostaje wersję z poziomu
    wyżej (pluginu). Tak blokada GTM jest domyślna i nie da się o niej zapomnieć
    w pojedynczym teście - twarda zasada 1 egzekwowana strukturą, nie dyscypliną.
    """
    return page


@pytest.fixture
def datalayer(request: pytest.FixtureRequest, page: Page) -> Generator[DataLayerSpy]:
    """Podsłuch dataLayer. Instalowany przed ciałem testu, czyli przed page.goto().

    Po teście (teardown) odczytuje pushe dla raportu - także gdy test padł, bo wtedy
    raport jest najbardziej potrzebny. Strona jeszcze żyje: `page` zamyka się po nas.
    """
    spy = DataLayerSpy(page)
    yield spy
    try:
        request.node.stash[PUSHES] = spy.pushes()
    except Exception:  # HookLostError i błędy Playwrighta - raport nie może wywrócić sesji
        # Strona po nawigacji, zamknięta albo bez podsłuchu - raport pokaże 0 pushy,
        # a przyczynę i tak niesie wynik samego testu.
        request.node.stash[PUSHES] = []


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    # Wrapper widzi raport każdej fazy (setup, call, teardown). Zapamiętujemy fazę call,
    # a setup tylko wtedy, gdy padł - wtedy call w ogóle się nie wykona.
    report = yield
    if report.when == "call" or (report.when == "setup" and not report.passed):
        item.stash[REPORT] = report
    return report


def _title(item: pytest.Item) -> str:
    func = getattr(item, "function", None)
    doc = (func.__doc__ or "").strip().splitlines() if func else []
    title = doc[0].rstrip(".") if doc else item.name
    callspec = getattr(item, "callspec", None)
    # Parametr przeglądarki ([chromium]) dokłada pytest-playwright - w raporcie to szum.
    # pytest zapisuje id jako ASCII z sekwencjami \uXXXX (Zaproś -> Zapro\u015b);
    # id jest więc czystym ASCII i unicode_escape bezpiecznie przywraca polskie znaki.
    raw_id = callspec.id.encode().decode("unicode_escape") if callspec else ""
    ids = [i for i in raw_id.split("-") if i and i != "chromium"]
    return f"{title} ({', '.join(ids)})" if ids else title


def _scenario(item: pytest.Item) -> ScenarioResult | None:
    report = item.stash.get(REPORT, None)
    if report is None:
        return None
    # Jawna adnotacja: StashKey jest inwariantny, a mypy bez niej wywnioskowałby typ
    # domyślnej wartości z oczekiwanego Sequence i odrzucił klucz z list.
    pushes: list[CapturedPush] = item.stash.get(PUSHES, [])
    failure = None
    if report.failed:
        crash = getattr(report.longrepr, "reprcrash", None)
        failure = crash.message if crash else str(report.longrepr)
    return ScenarioResult(
        node_id=item.nodeid,
        title=_title(item),
        outcome=report.outcome,
        failure=failure,
        duration_s=report.duration,
        pushes=push_records(pushes),
        blocked_requests=item.stash.get(BLOCKED, []),
    )


def pytest_sessionfinish(session: pytest.Session) -> None:
    out_dir = os.environ.get("AUDIT_REPORT_DIR")
    if not out_dir:
        return
    items = [i for i in session.items if i.get_closest_marker("e2e")]
    scenarios = [s for s in map(_scenario, items) if s is not None]
    if not scenarios:
        return
    report = AuditReport(
        generated_at=datetime.now(UTC),
        base_url=str(session.config.getini("base_url")),
        scenarios=scenarios,
    )
    paths = write_report(report, Path(out_dir))
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line("")
        for path in paths:
            reporter.write_line(f"raport: {path}")
