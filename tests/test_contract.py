"""Testy kontraktu bez przeglądarki: test pozytywny i negatywny na każdą regułę.

Payloady pozytywne są przepisane 1:1 z BaseLayout.astro i komponentów strony. Jeśli
kontrakt odrzuci któryś z nich, to kontrakt rozjechał się z implementacją.
Negatywne sprawdzają `type` błędu pydantic, a nie treść komunikatu - typ jest stabilny,
tekst bywa zmieniany między wersjami biblioteki.
"""

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from datalayer_audit.contract import (
    TRACKING_PLAN_EVENTS,
    ConsentDefaultParams,
    ConsentUpdateParams,
    GtmJs,
    LinkedinClick,
    validate_push,
)

# Dokładnie to, co pushuje gtag('consent', 'default', ...) w BaseLayout.astro.
CONSENT_DEFAULT: dict[str, Any] = {
    "ad_storage": "denied",
    "ad_user_data": "denied",
    "ad_personalization": "denied",
    "analytics_storage": "denied",
    "functionality_storage": "denied",
    "personalization_storage": "denied",
    "security_storage": "granted",
    "wait_for_update": 2000,
}


def consent_update(*, analytics: bool, marketing: bool) -> dict[str, str]:
    """Odtworzenie window.applyConsent(prefs) z BaseLayout.astro."""
    a = "granted" if analytics else "denied"
    m = "granted" if marketing else "denied"
    return {
        "analytics_storage": a,
        "ad_storage": m,
        "ad_user_data": m,
        "ad_personalization": m,
        "functionality_storage": "granted",
        "personalization_storage": "granted",
        "security_storage": "granted",
    }


LINKEDIN: dict[str, str] = {
    "event": "linkedin_click",
    "link_text": "Napisz na LinkedIn",
    "link_url": "https://www.linkedin.com/in/piotrmackowka/",
}


def error_types(raw: object) -> list[str]:
    """Typy wszystkich błędów walidacji - asercje nie zależą od treści komunikatu."""
    with pytest.raises(ValidationError) as exc:
        validate_push(raw)
    return [e["type"] for e in exc.value.errors()]


# --- spójność kontraktu z tracking planem -----------------------------------


@pytest.mark.parametrize("name", sorted(TRACKING_PLAN_EVENTS))
def test_every_tracking_plan_event_has_a_variant(name: str) -> None:
    # Zdarzenie z planu bez wariantu w unii dałoby union_tag_invalid na poprawnym pushu.
    payload = LINKEDIN if name == "linkedin_click" else {"event": name}
    result = validate_push(payload)
    assert isinstance(result, BaseModel)
    assert result.model_dump()["event"] == name


# --- rozpoznanie kształtu (dyskryminator) -----------------------------------


def test_unknown_event_is_rejected() -> None:
    # Literówka w nazwie zdarzenia to najczęstszy błąd trackingu.
    assert error_types({"event": "phone_revealed"}) == ["union_tag_invalid"]


@pytest.mark.parametrize(
    "raw",
    [
        {"link_text": "x"},  # obiekt bez pola event
        {"event": 42},  # event nie jest stringiem
        ["consent"],  # komenda gtag za krótka, by ją rozpoznać
        [1, "default"],  # komenda gtag z nie-stringiem na pozycji 0
        "phone_reveal",  # goły string zamiast obiektu
    ],
)
def test_unrecognised_shape_is_rejected(raw: object) -> None:
    assert error_types(raw) == ["union_tag_not_found"]


# --- zdarzenia bez parametrów -----------------------------------------------


def test_extra_param_on_simple_event_is_rejected() -> None:
    # extra="forbid": parametr spoza planu wyłapany, zamiast cicho trafić do GA4.
    assert error_types({"event": "chat_open", "source": "fab"}) == ["extra_forbidden"]


# --- gtm.js -----------------------------------------------------------------


def test_gtm_js_push_is_valid() -> None:
    result = validate_push({"gtm.start": 1_759_312_345_678, "event": "gtm.js"})
    assert isinstance(result, GtmJs)
    assert result.gtm_start == 1_759_312_345_678


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"event": "gtm.js"}, "missing"),
        ({"event": "gtm.js", "gtm.start": 0}, "greater_than"),
        ({"event": "gtm.js", "gtm.start": "1759312345678"}, "int_type"),  # strict
    ],
)
def test_invalid_gtm_js_is_rejected(raw: object, expected: str) -> None:
    assert error_types(raw) == [expected]


# --- linkedin_click ---------------------------------------------------------


def test_linkedin_click_is_valid() -> None:
    result = validate_push(LINKEDIN)
    assert isinstance(result, LinkedinClick)
    assert result.link_text == "Napisz na LinkedIn"


@pytest.mark.parametrize("missing", ["link_text", "link_url"])
def test_linkedin_click_requires_params(missing: str) -> None:
    raw = {k: v for k, v in LINKEDIN.items() if k != missing}
    assert error_types(raw) == ["missing"]


def test_linkedin_click_rejects_empty_text() -> None:
    # Link-ikona bez tekstu: GA4 nie odróżniłby, które CTA zadziałało.
    assert error_types({**LINKEDIN, "link_text": ""}) == ["string_too_short"]


@pytest.mark.parametrize(
    "url",
    [
        "https://linkedin.com.evil.example/in/x",  # linkedin.com jako subdomena obcej
        "https://evil-linkedin.com/in/x",  # podobna nazwa, inna domena
        "http://www.linkedin.com/in/x",  # bez TLS
        "/kontakt",  # ścieżka względna
    ],
)
def test_linkedin_click_rejects_foreign_url(url: str) -> None:
    assert error_types({**LINKEDIN, "link_url": url}) == ["value_error"]


@pytest.mark.parametrize("url", ["https://linkedin.com/in/x", "https://pl.linkedin.com/in/x"])
def test_linkedin_click_accepts_linkedin_hosts(url: str) -> None:
    assert isinstance(validate_push({**LINKEDIN, "link_url": url}), LinkedinClick)


# --- gtag('consent', 'default') ---------------------------------------------


def test_consent_default_from_site_is_valid() -> None:
    result = validate_push(["consent", "default", CONSENT_DEFAULT])
    assert isinstance(result, tuple)
    assert result[:2] == ("consent", "default")
    assert isinstance(result[2], ConsentDefaultParams)
    assert result[2].wait_for_update == 2000


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"analytics_storage": "granted"}, "literal_error"),  # zgoda przed decyzją = RODO
        ({"security_storage": "denied"}, "literal_error"),
        ({"wait_for_update": 0}, "greater_than"),
        ({"region": ["PL"]}, "extra_forbidden"),
    ],
)
def test_invalid_consent_default_is_rejected(override: dict[str, Any], expected: str) -> None:
    assert error_types(["consent", "default", {**CONSENT_DEFAULT, **override}]) == [expected]


def test_consent_default_requires_params() -> None:
    # Krotka ma stałą długość: brak trzeciego elementu to błąd, nie pusty słownik.
    assert error_types(["consent", "default"]) == ["missing"]


# --- gtag('consent', 'update') ----------------------------------------------


@pytest.mark.parametrize(
    ("analytics", "marketing"),
    [(True, True), (False, False), (True, False), (False, True)],
    ids=["accept_all", "reject_all", "analytics_only", "marketing_only"],
)
def test_consent_update_from_apply_consent_is_valid(analytics: bool, marketing: bool) -> None:
    params = consent_update(analytics=analytics, marketing=marketing)
    result = validate_push(["consent", "update", params])
    assert isinstance(result, tuple)
    assert isinstance(result[2], ConsentUpdateParams)


def test_consent_update_rejects_split_marketing_signals() -> None:
    # Jeden przełącznik w banerze, trzy sygnały ad_* - rozjazd = błąd mapowania.
    params = {**consent_update(analytics=True, marketing=True), "ad_user_data": "denied"}
    assert error_types(["consent", "update", params]) == ["value_error"]


def test_consent_update_rejects_unknown_state() -> None:
    params = {**consent_update(analytics=True, marketing=False), "analytics_storage": "yes"}
    assert error_types(["consent", "update", params]) == ["literal_error"]


# --- gtag('set', ...) -------------------------------------------------------


@pytest.mark.parametrize("key", ["ads_data_redaction", "url_passthrough"])
def test_set_command_from_site_is_valid(key: str) -> None:
    assert validate_push(["set", key, True]) == ("set", key, True)


def test_set_command_rejects_string_bool() -> None:
    # strict: "true" jako string to błąd implementacji, nie wartość do koercji.
    assert error_types(["set", "url_passthrough", "true"]) == ["bool_type"]


def test_set_command_rejects_unknown_key() -> None:
    assert error_types(["set", "send_page_view", False]) == ["union_tag_invalid"]


def test_set_command_rejects_extra_argument() -> None:
    assert error_types(["set", "url_passthrough", True, {}]) == ["too_long"]
