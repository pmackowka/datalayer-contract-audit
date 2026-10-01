"""Testy dymne etapu 1: pakiet się importuje, a Chromium faktycznie wstaje.

Drugi test nie dotyka sieci - `set_content` wstrzykuje HTML bezpośrednio do strony.
Sprawdza instalację przeglądarki, nie pmdata.pl, więc wolno mu być w `make check`.
"""

from playwright.sync_api import Page

import datalayer_audit


def test_package_is_importable() -> None:
    # Wersja zamiast gołego importu: pusty katalog też by się zaimportował
    # jako pakiet namespace'owy i test przeszedłby fałszywie.
    assert datalayer_audit.__version__ == "0.1.0"


def test_chromium_runs_javascript(page: Page) -> None:
    # Ta sama mechanika, której użyjemy w etapie 3: strona woła dataLayer.push,
    # a my odczytujemy stan z Pythona przez page.evaluate.
    page.set_content("<script>window.dataLayer = [{event: 'smoke'}];</script>")
    assert page.evaluate("window.dataLayer") == [{"event": "smoke"}]
