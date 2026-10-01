# CLAUDE.md

## Czym jest ten projekt

Automatyczny audyt zdarzeń dataLayer pod GA4 na produkcyjnej stronie https://pmdata.pl/.
Playwright przechodzi ścieżki użytkownika, pydantic waliduje każdy push względem kontraktu.
Projekt edukacyjny i portfolio: kontrakt → przechwycenie → walidacja → raport → cykliczne
uruchamianie. Mechanizmy mają być wyjaśnione, nie tylko użyte.

## Strona docelowa (osobne repo, tylko do odczytu)

`/Users/p/Documents/dev/personal-page` (GitHub: pmackowka/personal-page). NIE edytuj.
- `src/data/events.ts` — EVENTS + EVENT_CATALOG, jedyne źródło prawdy taksonomii (8 zdarzeń).
- `src/layouts/BaseLayout.astro` — Consent Mode v2 (`gtag('consent','default')`,
  `gtag('set', …)`, `window.applyConsent`), loader GTM ze ścieżki `/mackowka/` (Stape),
  delegowany listener `linkedin_click`.
- Komponenty: `ConsentBanner`, `PhoneReveal`, `ChatWidget`, `Header` (hamburger < 960 px).
  Selektory z kodu albo z żywego DOM — nigdy zgadywane.

## Twarde zasady (strona jest produkcyjna)

1. Zero zanieczyszczenia GA4: każdy test domyślnie blokuje `**/mackowka/**` (abort).
2. Testy warstwy sieciowej przechwytują żądania GA4/sGTM, zapisują i ABORTUJĄ.
3. Czat: wyłącznie otwarcie panelu (`chat_open`). NIGDY nie wysyłaj wiadomości.
4. Nawigacje wychodzące (linkedin.com, `tel:`) przechwytuj i abortuj.
5. Sekwencyjnie, bez równoległych workerów i pętli obciążających stronę.

## Komendy

```bash
make setup      # Python 3.12, .venv, zależności, chromium-headless-shell
make check      # ruff + mypy strict + pytest (bez E2E) - ta sama bramka co CI
make e2e        # scenariusze na produkcji, bez raportu
make audit      # scenariusze + reports/audit-<data>.{json,md,html}
make audit-open # audyt + najnowszy raport w Chrome (macOS)
make help       # pełna lista celów
```

Pojedynczy test: `uv run pytest tests/test_smoke.py::test_package_is_importable -x`.

## Stan i decyzje

- Etapy 1–5 i 7 gotowe, 6 opcjonalny; plan etapów w README. Praca etapami, kolejny dopiero po „ok” właściciela.
- Kontrakt: `contract.py` (`validate_push`); podsłuch: `capture.js` + `capture.py`; osłona: `guard.py`.
- Fixture `page` w `tests/conftest.py` zawsze instaluje osłonę; `datalayer` daje `DataLayerSpy`.
- Nawigacje wychodzące anulowane przez `preventDefault` na window — sam abort route niszczy dokument.
- Jeden pakiet zamiast workspace uv, bo kontrakt jest jeden.
- Raport: `report.py` (AuditReport liczy wszystko, widoki tylko formatują) + `report.html.j2` (Jinja autoescape). Spięcie z pytest w `tests/conftest.py` przez StashKey + `pytest_sessionfinish`, włączane zmienną `AUDIT_REPORT_DIR` (`make audit`). pytest-html świadomie pominięty.
- Etap 6: Consent Mode advanced wysyła pingi `gcs=G100` mimo odmowy — asercja musi to uwzględniać.
- Drift: `drift.py` parsuje events.ts regexami i sprawdza sam siebie (EVENTS == klucze EVENT_CATALOG). Ścieżka z `TRACKING_PLAN_PATH`; w CI checkout personal-page fine-grained PAT (`PERSONAL_PAGE_TOKEN`), brak pliku przy `CI` = fail.
- CI: `.github/workflows/ci.yml` — `quality` (push/PR/cron), `audit` (cron 06:00 UTC = 8:00 PL latem, + dispatch, concurrency bez równoległości).

## Konwencje

- Python 3.12, uv, pydantic v2, pytest + pytest-playwright, ruff, mypy --strict.
- Kod i nazwy po angielsku, komentarze i docstringi po polsku.
- Scenariusze na żywej stronie oznaczone markerem `e2e`, poza `make check`.
- Rozbieżność żywej strony z repo (selektor, nazwa, kolejność) = ustalenie audytu, zgłaszaj.
- Bez commitów i pushy bez zgody właściciela.
