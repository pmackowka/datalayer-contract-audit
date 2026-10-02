"""Konfiguracja ścieżki loadera GTM: brak wartości to błąd, a nie cicha zgoda na hity."""

import pytest

from datalayer_audit.guard import (
    GTM_LOADER_ENV,
    BlockedRequest,
    MissingGtmLoaderError,
    gtm_loader_glob,
)


def test_glob_comes_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GTM_LOADER_ENV, "  **/loader/**  ")
    assert gtm_loader_glob() == "**/loader/**"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_glob_fails_loudly(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv(GTM_LOADER_ENV, raising=False)
    else:
        monkeypatch.setenv(GTM_LOADER_ENV, value)
    with pytest.raises(MissingGtmLoaderError, match=GTM_LOADER_ENV):
        gtm_loader_glob()


def test_label_hides_path_and_query() -> None:
    blocked = BlockedRequest("loader GTM", "https://example.test/secret-path/x.js?id=abc")
    assert blocked.label == "loader GTM (example.test)"
