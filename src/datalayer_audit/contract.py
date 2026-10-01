"""Kontrakt dataLayer pmdata.pl: wykonywalna wersja tracking planu z `src/data/events.ts`.

dataLayer dostaje dwa kształty pushy i kontrakt musi je rozróżnić, zanim cokolwiek zwaliduje:

1. Obiekty ze zdarzeniem - `dataLayer.push({event: 'phone_reveal'})`. Typ rozpoznajemy
   po wartości pola `event`.
2. Komendy gtag - `gtag('consent', 'default', {...})` pushuje obiekt `arguments`, który
   po normalizacji (etap 3) jest tablicą `['consent', 'default', {...}]`. Tu nie ma pola
   `event`; typ wyznaczają dwa pierwsze elementy tablicy.

Dlatego dyskryminator jest funkcją (`Discriminator(callable)`), a nie nazwą pola: zwykły
`Field(discriminator='event')` działa tylko dla modeli z tym polem, a tablica go nie ma.
Funkcja zwraca etykietę (`Tag`), a pydantic waliduje push wyłącznie względem wariantu
z tą etykietą. Zysk: przy błędzie dostajesz jeden konkretny komunikat zamiast listy
porażek ze wszystkich 13 wariantów unii.
"""

from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    StrictBool,
    Tag,
    TypeAdapter,
    field_validator,
    model_validator,
)

# Stan zgody w Consent Mode v2 - Google akceptuje dokładnie te dwie wartości.
ConsentState = Literal["granted", "denied"]


class _Strict(BaseModel):
    """Wspólna konfiguracja wszystkich modeli kontraktu.

    strict=True: bez cichej koercji typów. Bez tego `"true"` przeszłoby jako bool,
    a `"1"` jako int - czyli kontrakt przepuściłby dokładnie te błędy implementacji,
    które ma łapać. extra="forbid": parametr spoza planu to błąd, nie ciekawostka.
    frozen=True: zwalidowany push jest faktem z przeszłości, nikt go nie poprawia.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


# ============================================================================
# Zdarzenia (obiekty z polem `event`)
# ============================================================================


class GtmJs(_Strict):
    """Push snippetu GTM: `{'gtm.start': <ms epoki>, event: 'gtm.js'}`.

    Nie należy do tracking planu, ale strona go wysyła, więc kontrakt musi go znać.
    Kropka w nazwie wyklucza zwykłe pole Pythona - stąd alias.
    """

    event: Literal["gtm.js"]
    gtm_start: int = Field(alias="gtm.start", gt=0)


class CookieConsentUpdate(_Strict):
    event: Literal["cookie_consent_update"]


class CookieConsentAnalytics(_Strict):
    event: Literal["cookie_consent_analytics"]


class CookieConsentMarketing(_Strict):
    event: Literal["cookie_consent_marketing"]


class PhoneReveal(_Strict):
    event: Literal["phone_reveal"]


class PhoneCall(_Strict):
    event: Literal["phone_call"]


class ChatOpen(_Strict):
    event: Literal["chat_open"]


class MobileMenuOpen(_Strict):
    event: Literal["mobile_menu_open"]


class LinkedinClick(_Strict):
    """Jedyne zdarzenie z parametrami. Oba wymagane - bez nich GA4 nie odróżni CTA."""

    event: Literal["linkedin_click"]
    # Strona liczy link_text z textContent().trim(); link-ikona bez tekstu dałaby "".
    link_text: str = Field(min_length=1)
    link_url: str

    @field_validator("link_url")
    @classmethod
    def _must_point_to_linkedin(cls, value: str) -> str:
        # Sprawdzamy sparsowany host, nie podciąg: `"linkedin.com" in url` przepuściłoby
        # https://linkedin.com.evil.example i https://evil-linkedin.com.
        parts = urlsplit(value)
        host = parts.hostname or ""
        if parts.scheme != "https":
            raise ValueError(f"link_url musi używać https, jest {parts.scheme!r}")
        if host != "linkedin.com" and not host.endswith(".linkedin.com"):
            raise ValueError(f"link_url musi wskazywać linkedin.com, wskazuje {host!r}")
        return value


# ============================================================================
# Komendy gtag (tablice po normalizacji `arguments`)
# ============================================================================


class ConsentDefaultParams(_Strict):
    """Stan zgód przed decyzją użytkownika.

    Reguła RODO zapisana w typach: wszystko poza security_storage startuje jako
    `denied`. Literal["denied"] zamiast ConsentState sprawia, że regresja typu
    `analytics_storage: 'granted'` w defaultzie wywali walidację.
    """

    ad_storage: Literal["denied"]
    ad_user_data: Literal["denied"]
    ad_personalization: Literal["denied"]
    analytics_storage: Literal["denied"]
    functionality_storage: Literal["denied"]
    personalization_storage: Literal["denied"]
    security_storage: Literal["granted"]
    # Ile ms tagi czekają na `consent update`, zanim odpalą się w stanie domyślnym.
    wait_for_update: int = Field(gt=0)


class ConsentUpdateParams(_Strict):
    """Stan zgód po decyzji - wysyłany przez window.applyConsent."""

    ad_storage: ConsentState
    ad_user_data: ConsentState
    ad_personalization: ConsentState
    analytics_storage: ConsentState
    functionality_storage: ConsentState
    personalization_storage: ConsentState
    security_storage: Literal["granted"]

    @model_validator(mode="after")
    def _marketing_signals_move_together(self) -> "ConsentUpdateParams":
        # Baner ma jeden przełącznik „Marketingowe”, a applyConsent mapuje go na trzy
        # sygnały ad_*. Rozjazd oznacza błąd w mapowaniu, a nie świadomy wybór usera.
        # To reguła między polami, więc model_validator, a nie field_validator.
        ads = {self.ad_storage, self.ad_user_data, self.ad_personalization}
        if len(ads) != 1:
            raise ValueError(
                "ad_storage, ad_user_data i ad_personalization muszą mieć ten sam stan "
                f"(jeden przełącznik marketingowy), są: {sorted(ads)}"
            )
        return self


# Komendy jako krotki: pydantic sprawdza długość i typ każdej pozycji osobno, więc
# `['consent', 'default']` bez trzeciego elementu albo z czwartym nie przejdzie.
ConsentDefault = tuple[Literal["consent"], Literal["default"], ConsentDefaultParams]
ConsentUpdate = tuple[Literal["consent"], Literal["update"], ConsentUpdateParams]
SetAdsDataRedaction = tuple[Literal["set"], Literal["ads_data_redaction"], StrictBool]
SetUrlPassthrough = tuple[Literal["set"], Literal["url_passthrough"], StrictBool]


# ============================================================================
# Unia wszystkich pushy
# ============================================================================


def push_kind(value: Any) -> str | None:
    """Wyznacza etykietę wariantu unii z surowego pusha.

    Publiczna, bo scenariusze E2E porównują sekwencje etykiet, np.
    ["gtag:consent:update", "cookie_consent_update"] - ta sama funkcja co w kontrakcie,
    więc test i walidacja nie mogą inaczej rozumieć, czym jest dany push.

    Zwrócenie None mówi pydantic „nie rozpoznaję kształtu” - wtedy błąd ma typ
    `union_tag_not_found` zamiast próbować każdego wariantu po kolei.
    """
    if isinstance(value, dict):
        event = value.get("event")
        return event if isinstance(event, str) else None
    if isinstance(value, list | tuple) and len(value) >= 2:
        command, action = value[0], value[1]
        if isinstance(command, str) and isinstance(action, str):
            return f"gtag:{command}:{action}"
    return None


DataLayerPush = Annotated[
    Annotated[GtmJs, Tag("gtm.js")]
    | Annotated[CookieConsentUpdate, Tag("cookie_consent_update")]
    | Annotated[CookieConsentAnalytics, Tag("cookie_consent_analytics")]
    | Annotated[CookieConsentMarketing, Tag("cookie_consent_marketing")]
    | Annotated[PhoneReveal, Tag("phone_reveal")]
    | Annotated[PhoneCall, Tag("phone_call")]
    | Annotated[LinkedinClick, Tag("linkedin_click")]
    | Annotated[ChatOpen, Tag("chat_open")]
    | Annotated[MobileMenuOpen, Tag("mobile_menu_open")]
    | Annotated[ConsentDefault, Tag("gtag:consent:default")]
    | Annotated[ConsentUpdate, Tag("gtag:consent:update")]
    | Annotated[SetAdsDataRedaction, Tag("gtag:set:ads_data_redaction")]
    | Annotated[SetUrlPassthrough, Tag("gtag:set:url_passthrough")],
    Discriminator(push_kind),
]

# TypeAdapter waliduje typ, który nie jest modelem (tu: unię). Budowa schematu jest
# kosztowna, więc tworzymy go raz na moduł, a nie przy każdym pushu. Tytuł trafia do
# nagłówka ValidationError - bez niego nagłówkiem jest pełna sygnatura 13-elementowej unii.
PUSH_ADAPTER: TypeAdapter[DataLayerPush] = TypeAdapter(
    DataLayerPush, config=ConfigDict(title="DataLayerPush")
)

# Zdarzenia tracking planu -> model kontraktu. Test driftu (etap 7) porównuje z events.ts
# zarówno nazwy (klucze), jak i parametry (pola modelu poza `event`).
EVENT_MODELS: dict[str, type[BaseModel]] = {
    "cookie_consent_update": CookieConsentUpdate,
    "cookie_consent_analytics": CookieConsentAnalytics,
    "cookie_consent_marketing": CookieConsentMarketing,
    "phone_reveal": PhoneReveal,
    "phone_call": PhoneCall,
    "linkedin_click": LinkedinClick,
    "chat_open": ChatOpen,
    "mobile_menu_open": MobileMenuOpen,
}
TRACKING_PLAN_EVENTS: frozenset[str] = frozenset(EVENT_MODELS)


def event_params(name: str) -> frozenset[str]:
    """Parametry zdarzenia wg kontraktu - nazwy pól modelu bez dyskryminatora `event`."""
    return frozenset(EVENT_MODELS[name].model_fields) - {"event"}


def validate_push(raw: object) -> DataLayerPush:
    """Waliduje jeden push. Rzuca pydantic.ValidationError z powodem odrzucenia."""
    return PUSH_ADAPTER.validate_python(raw)
