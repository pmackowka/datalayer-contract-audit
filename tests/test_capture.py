"""Mechanika podsłuchu na stronie-atrapie - bez sieci, więc wchodzi do `make check`.

Atrapa jest serwowana przez page.route().fulfill(): Playwright odpowiada na żądanie
sam, zanim cokolwiek wyjdzie do sieci. Domena `.test` jest zarezerwowana (RFC 2606),
więc nawet przy błędzie routingu nie trafimy w cudzy serwer.
"""

import pytest
from playwright.sync_api import Page, Route

from datalayer_audit.capture import DataLayerSpy, HookLostError
from datalayer_audit.contract import validate_push
from datalayer_audit.guard import NetworkGuard

URL = "https://capture.test/"

# Wierne odwzorowanie <head> z BaseLayout.astro: gtag pushuje `arguments`,
# snippet GTM pushuje gtm.js i doczepia loader z /mackowka/.
HEAD = """
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag() { dataLayer.push(arguments); }
  gtag('consent', 'default', {ad_storage: 'denied', ad_user_data: 'denied',
    ad_personalization: 'denied', analytics_storage: 'denied',
    functionality_storage: 'denied', personalization_storage: 'denied',
    security_storage: 'granted', wait_for_update: 2000});
  gtag('set', 'url_passthrough', true);
  dataLayer.push({'gtm.start': new Date().getTime(), event: 'gtm.js'});
</script>
<script async src="https://capture.test/mackowka/loader.js"></script>
"""


def serve(page: Page, body: str = "") -> None:
    def handler(route: Route) -> None:
        route.fulfill(content_type="text/html", body=f"<html><head>{HEAD}</head>{body}</html>")

    page.route(URL, handler)
    page.goto(URL)


def test_gtag_arguments_are_normalised_to_arrays(page: Page, datalayer: DataLayerSpy) -> None:
    serve(page)
    payloads = [p.payload for p in datalayer.pushes()]
    # Bez Array.from pierwszy push byłby {"0": "consent", "1": "default", ...}.
    assert payloads[0][:2] == ["consent", "default"]
    assert payloads[1] == ["set", "url_passthrough", True]
    for payload in payloads:
        validate_push(payload)


def test_pushes_keep_order_and_timestamps(page: Page, datalayer: DataLayerSpy) -> None:
    serve(page, "<script>dataLayer.push({event: 'phone_reveal'}, {event: 'phone_call'});</script>")
    pushes = datalayer.pushes()
    # Jeden push z dwoma argumentami = dwa wpisy, w kolejności argumentów.
    assert [p.payload.get("event") for p in pushes[-2:]] == ["phone_reveal", "phone_call"]
    assert [p.index for p in pushes] == list(range(len(pushes)))
    assert [p.t_ms for p in pushes] == sorted(p.t_ms for p in pushes)


def test_gtm_start_survives_as_int(page: Page, datalayer: DataLayerSpy) -> None:
    # Kontrakt ma strict int; Date.getTime() to number w JS - sprawdzamy, co dociera.
    serve(page)
    pushes = datalayer.pushes()
    gtm_js = next(p.payload for p in pushes if isinstance(p.payload, dict))
    assert type(gtm_js["gtm.start"]) is int


def test_snapshot_is_taken_at_push_time(page: Page, datalayer: DataLayerSpy) -> None:
    serve(page, "<script>const e = {event: 'chat_open'}; dataLayer.push(e); e.extra = 1;</script>")
    assert datalayer.pushes()[-1].payload == {"event": "chat_open"}


def test_functions_are_visible_to_the_contract(page: Page, datalayer: DataLayerSpy) -> None:
    # eventCallback to typowy dodatek GTM; JSON by go zgubił, a kontrakt ma go zobaczyć.
    serve(page, "<script>dataLayer.push({event: 'chat_open', eventCallback() {}});</script>")
    payload = datalayer.pushes()[-1].payload
    assert payload == {"event": "chat_open", "eventCallback": "[function]"}
    with pytest.raises(ValueError, match=r"extra_forbidden|Extra inputs"):
        validate_push(payload)


def test_overwritten_datalayer_is_detected(page: Page, datalayer: DataLayerSpy) -> None:
    serve(page, "<script>window.dataLayer = [];</script>")
    with pytest.raises(HookLostError):
        datalayer.pushes()


def test_gtm_loader_is_blocked(page: Page, network_guard: NetworkGuard) -> None:
    serve(page)
    assert network_guard.blocked == ["https://capture.test/mackowka/loader.js"]


LINKS = """
<a id="same-tab" href="https://www.linkedin.com/in/x">LinkedIn</a>
<a id="new-tab" href="https://www.linkedin.com/in/x" target="_blank">LinkedIn</a>
<a id="tel" href="tel:+48000000000">tel</a>
<script>
  document.addEventListener('click', (e) => {
    if (e.target.closest('a')) dataLayer.push({event: 'chat_open'});
  });
</script>
"""


@pytest.mark.parametrize("link", ["same-tab", "tel"])
def test_outbound_click_keeps_page_and_push(page: Page, datalayer: DataLayerSpy, link: str) -> None:
    # Listener strony na document odpala push, a nasz na window (później w fazie
    # bubbling) anuluje nawigację. Strona zostaje, podsłuch żyje, push jest w logu.
    serve(page, LINKS)
    page.click(f"#{link}")
    assert page.url == URL
    assert datalayer.pushes()[-1].payload == {"event": "chat_open"}


def test_new_tab_linkedin_is_aborted(page: Page, network_guard: NetworkGuard) -> None:
    # Druga linia obrony: target=_blank. preventDefault też to łapie, ale gdyby link
    # otworzono inaczej (window.open), route na kontekście aborta żądanie popupu.
    serve(page, LINKS)
    with page.context.expect_page() as popup_info:
        page.evaluate("window.open('https://www.linkedin.com/in/x')")
    popup_info.value.wait_for_load_state()
    assert network_guard.blocked[-1] == "https://www.linkedin.com/in/x"
