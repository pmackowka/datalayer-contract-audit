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
make help       # pełna lista celów
```

Pojedynczy test: `uv run pytest tests/test_smoke.py::test_package_is_importable -x`.

## Stan i decyzje

- Etapy 1–3 z 7 gotowe; plan etapów w README. Praca etapami, kolejny dopiero po „ok” właściciela.
- Kontrakt: `contract.py` (`validate_push`); podsłuch: `capture.js` + `capture.py`; osłona: `guard.py`.
- Fixture `page` w `tests/conftest.py` zawsze instaluje osłonę; `datalayer` daje `DataLayerSpy`.
- Nawigacje wychodzące anulowane przez `preventDefault` na window — sam abort route niszczy dokument.
- Jeden pakiet zamiast workspace uv, bo kontrakt jest jeden.
- Raport (etap 5): JSON jako źródło, MD i HTML jako widoki; trzy osobne wskaźniki zamiast jednego %.
- Etap 6: Consent Mode advanced wysyła pingi `gcs=G100` mimo odmowy — asercja musi to uwzględniać.
- Etap 7: drift w CI wymaga checkoutu repo strony — decyzja jeszcze nie zapadła.

## Konwencje

- Python 3.12, uv, pydantic v2, pytest + pytest-playwright, ruff, mypy --strict.
- Kod i nazwy po angielsku, komentarze i docstringi po polsku.
- Scenariusze na żywej stronie oznaczone markerem `e2e`, poza `make check`.
- Rozbieżność żywej strony z repo (selektor, nazwa, kolejność) = ustalenie audytu, zgłaszaj.
- Bez commitów i pushy bez zgody właściciela.
