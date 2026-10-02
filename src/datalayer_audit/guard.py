"""Osłona sieci: nic z testu nie może dotrzeć do GA4 ani opuścić pmdata.pl.

Route działa na poziomie kontekstu przeglądarki, więc obejmuje każdą stronę i każdy
popup (np. link LinkedIn z target=_blank). `abort` kończy żądanie błędem sieci, zanim
cokolwiek wyjdzie z maszyny - to nie jest filtr po fakcie.
"""

import re
from dataclasses import dataclass, field

from playwright.sync_api import BrowserContext, Route

# Loader GTM (Stape) leży pod tą ścieżką. Twarda zasada 1.
GTM_PATH = "**/mackowka/**"
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


@dataclass
class NetworkGuard:
    """Blokuje żądania i zapisuje, co zablokował - to też jest wynik audytu."""

    blocked: list[str] = field(default_factory=list)

    def install(self, context: BrowserContext) -> None:
        context.add_init_script(NAV_GUARD_JS)
        context.route(GTM_PATH, self._abort)
        context.route(LINKEDIN, self._abort)
        context.route(TWIN_API, self._abort)

    def _abort(self, route: Route) -> None:
        self.blocked.append(route.request.url)
        route.abort("blockedbyclient")
