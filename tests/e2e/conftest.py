"""Pomocniki scenariuszy na produkcyjnym pmdata.pl."""

import json
from collections.abc import Callable

import pytest
from playwright.sync_api import Page

# Klucz i kształt jak w ConsentBanner.astro: {...prefs, ts, v: 1}.
CONSENT_KEY = "consent"


@pytest.fixture
def returning_user(page: Page) -> Callable[..., None]:
    """Symuluje powracającego użytkownika: zapisane zgody w localStorage przed wejściem.

    Init script, a nie page.evaluate po wejściu: BaseLayout czyta zgody synchronicznie
    w <head>, więc wpis musi istnieć, zanim wykona się pierwszy skrypt strony.
    """

    def apply(*, analytics: bool, marketing: bool) -> None:
        prefs = {
            "analytics": analytics,
            "marketing": marketing,
            "ts": "2026-01-01T00:00:00Z",
            "v": 1,
        }
        page.add_init_script(
            f"localStorage.setItem({json.dumps(CONSENT_KEY)}, {json.dumps(json.dumps(prefs))});"
        )

    return apply
