"""Osłona sieci: nic z testu nie może dotrzeć do GA4 ani opuścić pmdata.pl.

Route działa na poziomie kontekstu przeglądarki, więc obejmuje każdą stronę i każdy
popup (np. link LinkedIn z target=_blank). `abort` kończy żądanie błędem sieci, zanim
cokolwiek wyjdzie z maszyny - to nie jest filtr po fakcie.
"""

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Route

# Ścieżka first-party loadera GTM to konfiguracja, nie kod: repo jest publiczne,
# a opisana wprost ścieżka to gotowy wpis dla list blokujących (EasyPrivacy itp.).
# Lokalnie z .env, w CI z sekretu repo. Twarda zasada 1.
GTM_LOADER_ENV = "GTM_LOADER_GLOB"
# Endpoint czatu z bliźniakiem AI. Audyt mierzy wyłącznie otwarcie panelu, a rozmowy
# z testów zaśmiecałyby limit zapytań prawdziwych użytkowników. Blokada sprawia,
# że nawet przypadkowy submit nie wyjdzie z przeglądarki. Twarda zasada 2.
TWIN_API = "**/api/twin**"
# Host linkedin.com albo dowolna jego subdomena. Twarda zasada 3.
LINKEDIN = re.compile(r"^https?://([^/]+\.)?linkedin\.com(/|$)")

# Abort samego żądania nie wystarcza dla nawigacji w tej samej karcie: Chromium pokazuje
# wtedy chrome-error://, a dokument strony - razem z podsłuchem dataLayer - przestaje
# istnieć. `tel:` w ogóle nie przechodzi przez route (to nie jest żądanie HTTP).
# Dlatego anulujemy domyślną akcję kliknięcia. Listener na window w fazie bubbling
# wykonuje się PO listenerach strony na linku i na document, więc push strony zdąży.
NAV_GUARD_JS = """
window.addEventListener('click', (e) => {
  const a = e.target instanceof Element ? e.target.closest('a[href]') : null;
  if (!a) return;
  const href = a.href;
  if (href.startsWith('tel:') || /^https?:\\/\\/([^/]+\\.)?linkedin\\.com(\\/|$)/.test(href)) {
    e.preventDefault();
  }
});
"""


class MissingGtmLoaderError(RuntimeError):
    """Brak konfiguracji loadera GTM - test nie może ruszyć bez blokady GA4."""


def gtm_loader_glob() -> str:
    """Wzorzec ścieżki loadera GTM ze zmiennej środowiskowej.

    Brak wartości to błąd, nie pusty wzorzec: osłona bez blokady GTM wysyłałaby
    hity testów do GA4 - dokładnie to, przed czym ma chronić.
    """
    value = os.environ.get(GTM_LOADER_ENV, "").strip()
    if not value:
        raise MissingGtmLoaderError(
            f"ustaw {GTM_LOADER_ENV} (lokalnie w .env, w CI jako sekret repo), "
            "np. GTM_LOADER_GLOB='**/sciezka-loadera/**'"
        )
    return value


@dataclass(frozen=True)
class BlockedRequest:
    category: str
    url: str

    @property
    def label(self) -> str:
        """Wersja do raportu: kategoria i domena, bez ścieżki i parametrów."""
        return f"{self.category} ({urlsplit(self.url).hostname or '?'})"


@dataclass
class NetworkGuard:
    """Blokuje żądania i zapisuje, co zablokował - to też jest wynik audytu."""

    gtm_glob: str
    requests: list[BlockedRequest] = field(default_factory=list)

    @property
    def blocked(self) -> list[str]:
        """Pełne URL-e - tylko do asercji w testach, nigdy do raportu."""
        return [r.url for r in self.requests]

    @property
    def labels(self) -> list[str]:
        return [r.label for r in self.requests]

    def install(self, context: BrowserContext) -> None:
        context.add_init_script(NAV_GUARD_JS)
        context.route(self.gtm_glob, self._aborter("loader GTM"))
        context.route(LINKEDIN, self._aborter("LinkedIn"))
        context.route(TWIN_API, self._aborter("czat AI"))

    def _aborter(self, category: str) -> Callable[[Route], None]:
        def abort(route: Route) -> None:
            self.requests.append(BlockedRequest(category, route.request.url))
            route.abort("blockedbyclient")

        return abort
