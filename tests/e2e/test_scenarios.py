"""Scenariusze E2E na produkcyjnym https://pmdata.pl/ (GTM zablokowany przez osłonę).

Wzorzec każdego scenariusza:
1. wejście na stronę (podsłuch i osłona są już zainstalowane przez fixture'y),
2. zapamiętanie liczby pushy przed akcją,
3. kliknięcie,
4. asercja na pushach PO akcji (sekwencja etykiet) + walidacja wszystkich kontraktem.

Czekanie nie jest potrzebne: listenery strony są synchroniczne, a click() wraca po
dispatchu zdarzenia, więc push jest w logu, zanim click() zwróci sterowanie.
"""

from collections.abc import Callable

import pytest
from playwright.sync_api import Page, expect

from datalayer_audit.capture import DataLayerSpy
from datalayer_audit.checks import assert_contract, kinds
from datalayer_audit.guard import NetworkGuard

pytestmark = pytest.mark.e2e

BANNER = "[data-consent]"
# Dwa przyciski data-action="accept" (widok default i settings) - bez zakresu widoku
# Playwright rzuci strict mode violation. Ustalenie audytu, nie błąd strony.
ACCEPT = f"{BANNER} [data-view=default] [data-action=accept]"
REJECT = f"{BANNER} [data-view=default] [data-action=reject]"
CUSTOMIZE = f"{BANNER} [data-view=default] [data-action=customize]"
SAVE = f"{BANNER} [data-view=settings] [data-action=save]"
LINKEDIN_URL = "https://www.linkedin.com/in/pmackowka/"


def open_home(page: Page) -> None:
    # "load" czeka też na skrypty modułowe Astro, które podpinają listenery kliknięć.
    page.goto("/", wait_until="load")


# --- zgody --------------------------------------------------------------------


def test_consent_default_precedes_gtm_js(page: Page, datalayer: DataLayerSpy) -> None:
    """Wczytanie strony: consent default przed gtm.js."""
    open_home(page)
    pushes = datalayer.pushes()
    seq = kinds(pushes)
    assert seq.index("gtag:consent:default") < seq.index("gtm.js")
    assert seq == [
        "gtag:consent:default",
        "gtag:set:ads_data_redaction",
        "gtag:set:url_passthrough",
        "gtm.js",
    ]
    assert_contract(pushes)


@pytest.mark.parametrize(
    ("button", "expected", "analytics", "marketing"),
    [
        (
            ACCEPT,
            ["cookie_consent_update", "cookie_consent_analytics", "cookie_consent_marketing"],
            "granted",
            "granted",
        ),
        (REJECT, ["cookie_consent_update"], "denied", "denied"),
    ],
    ids=["akceptacja wszystkich", "odrzucenie wszystkich"],
)
def test_banner_decision(
    page: Page,
    datalayer: DataLayerSpy,
    button: str,
    expected: list[str],
    analytics: str,
    marketing: str,
) -> None:
    """Decyzja w banerze zgód."""
    open_home(page)
    expect(page.locator(BANNER)).to_be_visible()
    before = len(datalayer.pushes())

    page.click(button)

    pushes = datalayer.pushes()
    after = pushes[before:]
    assert kinds(after) == ["gtag:consent:update", *expected]
    params = after[0].payload[2]
    assert (params["analytics_storage"], params["ad_storage"]) == (analytics, marketing)
    expect(page.locator(BANNER)).to_be_hidden()
    assert_contract(pushes)


def test_custom_settings_analytics_only(page: Page, datalayer: DataLayerSpy) -> None:
    """Ustawienia własne: tylko analityka."""
    open_home(page)
    before = len(datalayer.pushes())

    page.click(CUSTOMIZE)
    page.click(f"{BANNER} .switch[data-toggle=analytics]")
    page.click(SAVE)

    pushes = datalayer.pushes()
    after = pushes[before:]
    assert kinds(after) == [
        "gtag:consent:update",
        "cookie_consent_update",
        "cookie_consent_analytics",
    ]
    params = after[0].payload[2]
    assert (params["analytics_storage"], params["ad_storage"]) == ("granted", "denied")
    assert_contract(pushes)


def test_returning_user_replays_consent_before_gtm(
    page: Page, datalayer: DataLayerSpy, returning_user: Callable[..., None]
) -> None:
    """Powracający użytkownik: zgody odtworzone przed GTM."""
    returning_user(analytics=True, marketing=False)
    open_home(page)

    pushes = datalayer.pushes()
    assert kinds(pushes) == [
        "gtag:consent:default",
        "gtag:set:ads_data_redaction",
        "gtag:set:url_passthrough",
        "gtag:consent:update",
        "cookie_consent_update",
        "cookie_consent_analytics",
        # Zapisane zgody muszą trafić do dataLayer PRZED GTM - inaczej pierwsze tagi
        # odpaliłyby w stanie domyślnym mimo wcześniejszej zgody użytkownika.
        "gtm.js",
    ]
    expect(page.locator(BANNER)).to_be_hidden()
    assert_contract(pushes)


# --- kontakt ------------------------------------------------------------------
# Poniższe scenariusze startują jako powracający użytkownik z odmową: baner jest
# modalem z backdropem i zasłoniłby przyciski, a odmowa to najbezpieczniejszy stan.


def test_phone_reveal_then_call(
    page: Page, datalayer: DataLayerSpy, returning_user: Callable[..., None]
) -> None:
    """Telefon: odkrycie numeru, potem kliknięcie."""
    returning_user(analytics=False, marketing=False)
    open_home(page)
    before = len(datalayer.pushes())

    page.click("[data-phone-trigger]")
    # Link tel: powstaje dopiero po odkryciu numeru (createElement w PhoneReveal.astro).
    page.click("[data-analytics=phone-call]")

    pushes = datalayer.pushes()
    assert kinds(pushes[before:]) == ["phone_reveal", "phone_call"]
    assert page.url.startswith("https://pmdata.pl/"), "kliknięcie tel: opuściło stronę"
    assert_contract(pushes)


@pytest.mark.parametrize("text", ["Zobacz profil na LinkedIn", "Zaproś na LinkedIn"])
def test_linkedin_click_params(
    page: Page,
    datalayer: DataLayerSpy,
    returning_user: Callable[..., None],
    text: str,
) -> None:
    """Przejście na LinkedIn."""
    returning_user(analytics=False, marketing=False)
    open_home(page)
    before = len(datalayer.pushes())

    page.get_by_role("link", name=text).click()

    pushes = datalayer.pushes()
    after = pushes[before:]
    assert [p.payload for p in after] == [
        {"event": "linkedin_click", "link_text": text, "link_url": LINKEDIN_URL}
    ]
    # target=_blank anulowany przez osłonę - żadna nowa karta nie powstała.
    assert len(page.context.pages) == 1
    assert_contract(pushes)


def test_chat_open_fires_on_every_open(
    page: Page,
    datalayer: DataLayerSpy,
    network_guard: NetworkGuard,
    returning_user: Callable[..., None],
) -> None:
    """Czat: otwarcie dwa razy w jednej wizycie."""
    returning_user(analytics=False, marketing=False)
    open_home(page)
    before = len(datalayer.pushes())

    page.click("[data-twin-toggle]")
    expect(page.locator("[data-twin-panel]")).to_be_visible()
    page.click("[data-twin-close]")
    page.click("[data-twin-toggle]")

    pushes = datalayer.pushes()
    # Zamknięcie nie wysyła nic; drugie otwarcie w tej samej wizycie - tak (EVENT_CATALOG).
    assert kinds(pushes[before:]) == ["chat_open", "chat_open"]
    # Twarda zasada 3: zero wiadomości do czatu.
    assert not [url for url in network_guard.blocked if "/api/twin" in url]
    assert_contract(pushes)


# --- nawigacja ----------------------------------------------------------------


def test_mobile_menu_open(
    page: Page, datalayer: DataLayerSpy, returning_user: Callable[..., None]
) -> None:
    """Menu mobilne (390×844)."""
    # Hamburger jest widoczny tylko poniżej 960 px (Header.astro).
    page.set_viewport_size({"width": 390, "height": 844})
    returning_user(analytics=False, marketing=False)
    open_home(page)
    before = len(datalayer.pushes())

    # Hamburger nie ma atrybutu data-*; rola + nazwa dostępna to najstabilniejszy lokator.
    page.get_by_role("button", name="Otwórz menu").click()

    pushes = datalayer.pushes()
    assert kinds(pushes[before:]) == ["mobile_menu_open"]
    assert_contract(pushes)
