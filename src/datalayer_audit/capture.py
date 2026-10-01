"""Przechwytywanie pushy dataLayer z przeglądarki sterowanej przez Playwright."""

from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from playwright.sync_api import Page

# Skrypt leży obok jako plik .js, a nie string w Pythonie: edytor podświetla składnię,
# a uv_build pakuje go razem z modułem.
INIT_SCRIPT = files("datalayer_audit").joinpath("capture.js").read_text(encoding="utf-8")


class HookLostError(RuntimeError):
    """Strona podmieniła window.dataLayer - pushe po podmianie nie zostały przechwycone."""


@dataclass(frozen=True)
class CapturedPush:
    """Jeden push w kolejności wysłania. `t_ms` liczone od startu dokumentu."""

    index: int
    t_ms: float
    payload: Any


class DataLayerSpy:
    """Podsłuch dataLayer jednej strony. Instaluj PRZED page.goto()."""

    def __init__(self, page: Page) -> None:
        self._page = page
        # add_init_script działa na każdy kolejny dokument tej strony, także po nawigacji.
        # Każda nawigacja zaczyna więc log od zera - to log jednego dokumentu.
        page.add_init_script(INIT_SCRIPT)

    def pushes(self) -> list[CapturedPush]:
        state = self._page.evaluate("window.__dataLayerAudit.read()")
        if not state["hooked"]:
            raise HookLostError(
                "window.dataLayer.push nie jest już podsłuchem - strona nadpisała dataLayer"
            )
        return [
            CapturedPush(index=i, t_ms=entry["t"], payload=entry["payload"])
            for i, entry in enumerate(state["log"])
        ]
