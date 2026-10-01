"""Pierwsze wejście na produkcyjne pmdata.pl: co strona pushuje przy samym wczytaniu."""

import pytest
from playwright.sync_api import Page

from datalayer_audit.capture import DataLayerSpy
from datalayer_audit.contract import validate_push
from datalayer_audit.guard import NetworkGuard

pytestmark = pytest.mark.e2e


def test_page_load_pushes_match_contract(
    page: Page, datalayer: DataLayerSpy, network_guard: NetworkGuard
) -> None:
    page.goto("/", wait_until="load")
    pushes = datalayer.pushes()

    for push in pushes:
        print(f"#{push.index} t={push.t_ms:7.1f}ms  {push.payload}")
        validate_push(push.payload)
    print("zablokowane:", network_guard.blocked)

    assert pushes, "strona nie wysłała żadnego pusha - podsłuch nie zadziałał?"
    assert any("/mackowka/" in url for url in network_guard.blocked), "GTM nie był zablokowany"
