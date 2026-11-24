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


def test_no_gtm_before_consent(page: Page, datalayer: DataLayerSpy) -> None:
    """Wczytanie strony bez decyzji: consent default, GTM nie startuje."""
    open_home(page)
    pushes = datalayer.pushes()
    # Loader GTM zapisuje dane w localStorage, a to wymaga zgody (art. 399 PKE) - przed
    # decyzją w dataLayer nie może być gtm.js.
    assert kinds(pushes) == ["gtag:consent:default", "gtag:set:ads_data_redaction"]
    assert_contract(pushes)


@pytest.mark.parametrize(
    ("button", "expected", "analytics"),
    [
        (ACCEPT, ["cookie_consent_update", "cookie_consent_analytics", "gtm.js"], "granted"),
        (REJECT, ["cookie_consent_update"], "denied"),
    ],
    ids=["akceptacja wszystkich", "odrzucenie wszystkich"],
)
def test_banner_decision(
    page: Page,
    datalayer: DataLayerSpy,
    button: str,
    expected: list[str],
    analytics: str,
) -> None:
    """Decyzja w banerze zgód."""
    open_home(page)
    expect(page.locator(BANNER)).to_be_visible()
    before = len(datalayer.pushes())

    page.click(button)

    pushes = datalayer.pushes()
    after = pushes[before:]
    # gtm.js PO zdarzeniach zgody: GTM odtwarza kolejkę, więc tagi widzą zgodę od startu.
    assert kinds(after) == ["gtag:consent:update", *expected]
    assert after[0].payload[2]["analytics_storage"] == analytics
    expect(page.locator(BANNER)).to_be_hidden()
    assert_contract(pushes)


def test_custom_settings_analytics_only(page: Page, datalayer: DataLayerSpy) -> None:
    """Ustawienia własne: włączona analityka."""
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
        "gtm.js",
    ]
    assert after[0].payload[2]["analytics_storage"] == "granted"
    assert_contract(pushes)


def test_returning_user_replays_consent_before_gtm(
    page: Page, datalayer: DataLayerSpy, returning_user: Callable[..., None]
) -> None:
    """Powracający użytkownik: zgody odtworzone przed GTM."""
    returning_user(analytics=True)
    open_home(page)

    pushes = datalayer.pushes()
    assert kinds(pushes) == [
        "gtag:consent:default",
        "gtag:set:ads_data_redaction",
        "gtag:consent:update",
        "cookie_consent_update",
        "cookie_consent_analytics",
        # Zapisane zgody muszą trafić do dataLayer PRZED GTM - inaczej pierwsze tagi
        # odpaliłyby w stanie domyślnym mimo wcześniejszej zgody użytkownika.
        "gtm.js",
    ]
    expect(page.locator(BANNER)).to_be_hidden()
    assert_contract(pushes)


def test_no_events_without_analytics_consent(
    page: Page, datalayer: DataLayerSpy, returning_user: Callable[..., None]
) -> None:
    """Odmowa zgody: kliknięcia nie trafiają do dataLayer."""
    returning_user(analytics=False)
    open_home(page)
    before = len(datalayer.pushes())

    page.click("[data-email-trigger]")

    # pushEvent czeka na zgodę: zdarzenie sprzed zgody GTM odtworzyłby z kolejki po
    # późniejszej akceptacji i wysłał do GA4.
    assert datalayer.pushes()[before:] == []


# --- kontakt ------------------------------------------------------------------
# Poniższe scenariusze startują jako powracający użytkownik ze zgodą analityczną: baner
# jest modalem z backdropem i zasłoniłby przyciski, a bez zgody strona nie pushuje zdarzeń.
# Zgoda wstrzykuje loader GTM, ale osłona i tak go blokuje - do GA4 nic nie trafia.


def test_email_reveal_then_click(
    page: Page, datalayer: DataLayerSpy, returning_user: Callable[..., None]
) -> None:
    """E-mail: odkrycie adresu, potem kliknięcie."""
    returning_user(analytics=True)
    open_home(page)
    before = len(datalayer.pushes())

    page.click("[data-email-trigger]")
    # Link mailto: powstaje dopiero po odkryciu adresu (createElement w EmailReveal.astro).
    page.click("[data-analytics=email-click]")

    pushes = datalayer.pushes()
    assert kinds(pushes[before:]) == ["email_reveal", "email_click"]
    assert page.url.startswith("https://pmdata.pl/"), "kliknięcie mailto: opuściło stronę"
    # target=_blank anulowany przez osłonę - żadna nowa karta nie powstała.
    assert len(page.context.pages) == 1
    assert_contract(pushes)


@pytest.mark.parametrize("text", ["Zobacz profil na LinkedIn", "Zaproś na LinkedIn"])
def test_linkedin_click_params(
    page: Page,
    datalayer: DataLayerSpy,
    returning_user: Callable[..., None],
    text: str,
) -> None:
    """Przejście na LinkedIn."""
    returning_user(analytics=True)
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
    returning_user(analytics=True)
    open_home(page)
    before = len(datalayer.pushes())

    page.click("[data-twin-toggle]")
    expect(page.locator("[data-twin-panel]")).to_be_visible()
    page.click("[data-twin-close]")
    page.click("[data-twin-toggle]")

    pushes = datalayer.pushes()
    # Zamknięcie nie wysyła nic; drugie otwarcie w tej samej wizycie - tak (EVENT_CATALOG).
    assert kinds(pushes[before:]) == ["chat_open", "chat_open"]
    # Twarda zasada 2: zero wiadomości do czatu.
    assert not [url for url in network_guard.blocked if "/api/twin" in url]
    assert_contract(pushes)


# --- artykuł -----------------------------------------------------------------

# Odnośniki do wpisów na liście /artykuly/. Tagi (/artykuly/tag/...) to listy, nie wpisy.
ARTICLE_LINKS = """[...new Set([...document.querySelectorAll('main a[href^="/artykuly/"]')]
  .map((a) => a.getAttribute('href'))
  .filter((h) => h !== '/artykuly/' && !h.startsWith('/artykuly/tag/')))]"""


def test_article_footer_cta(
    page: Page, datalayer: DataLayerSpy, returning_user: Callable[..., None]
) -> None:
    """Artykuł: e-mail i LinkedIn w stopce wpisu."""
    returning_user(analytics=True)
    # Najnowszy wpis z listy zamiast zaszytego adresu: usunięcie albo zmiana nazwy
    # konkretnego artykułu nie wywróci scenariusza.
    page.goto("/artykuly/", wait_until="load")
    articles = page.evaluate(ARTICLE_LINKS)
    assert articles, "lista /artykuly/ nie zawiera żadnego wpisu"
    page.goto(articles[0], wait_until="load")
    before = len(datalayer.pushes())

    # Stopka wpisu (PostLayout.astro) ma własne kopie komponentów ze strony głównej -
    # ten sam kod zdarzeń, ale inny kontekst, który może się rozjechać niezależnie.
    page.click(".post-foot [data-email-trigger]")
    page.click(".post-foot-cta")

    pushes = datalayer.pushes()
    after = pushes[before:]
    assert kinds(after) == ["email_reveal", "linkedin_click"]
    assert after[1].payload == {
        "event": "linkedin_click",
        "link_text": "Zaproś na LinkedIn",
        "link_url": LINKEDIN_URL,
    }
    assert len(page.context.pages) == 1
    assert_contract(pushes)


# --- nawigacja ----------------------------------------------------------------


def test_mobile_menu_open(
    page: Page, datalayer: DataLayerSpy, returning_user: Callable[..., None]
) -> None:
    """Menu mobilne (390×844)."""
    # Hamburger jest widoczny tylko poniżej 960 px (Header.astro).
    page.set_viewport_size({"width": 390, "height": 844})
    returning_user(analytics=True)
    open_home(page)
    before = len(datalayer.pushes())

    # Hamburger nie ma atrybutu data-*; rola + nazwa dostępna to najstabilniejszy lokator.
    page.get_by_role("button", name="Otwórz menu").click()

    pushes = datalayer.pushes()
    assert kinds(pushes[before:]) == ["mobile_menu_open"]
    assert_contract(pushes)
