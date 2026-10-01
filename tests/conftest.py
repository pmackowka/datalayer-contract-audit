"""Fixture'y wspólne dla testów przeglądarkowych."""

import pytest
from playwright.sync_api import BrowserContext, Page

from datalayer_audit.capture import DataLayerSpy
from datalayer_audit.guard import NetworkGuard


@pytest.fixture
def network_guard(context: BrowserContext) -> NetworkGuard:
    guard = NetworkGuard()
    guard.install(context)
    return guard


@pytest.fixture
def page(page: Page, network_guard: NetworkGuard) -> Page:
    """Nadpisanie `page` z pytest-playwright: każda strona startuje z osłoną sieci.

    Fixture o tej samej nazwie, który prosi o samego siebie, dostaje wersję z poziomu
    wyżej (pluginu). Tak blokada GTM jest domyślna i nie da się o niej zapomnieć
    w pojedynczym teście - twarda zasada 1 egzekwowana strukturą, nie dyscypliną.
    """
    return page


@pytest.fixture
def datalayer(page: Page) -> DataLayerSpy:
    """Podsłuch dataLayer. Instalowany przed ciałem testu, czyli przed page.goto()."""
    return DataLayerSpy(page)
