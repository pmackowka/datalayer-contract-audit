# datalayer-contract-audit

Automatyczny audyt zdarzeń dataLayer pod GA4 na https://pmdata.pl/. Playwright sam przechodzi
ścieżki użytkownika z zablokowanym GTM, a pydantic waliduje każdy push względem kontraktu.

> **Status:** etapy 1–2 z 7 gotowe (szkielet, kontrakt). Komendy oznaczone *(plan)* jeszcze nie działają.

## Uruchomienie

```bash
make setup          # Python 3.12, .venv, zależności, chromium-headless-shell
make check          # ruff + mypy strict + testy kontraktu (bez wchodzenia na stronę)
make audit          # (plan) scenariusze na pmdata.pl + raport reports/audit-<data>.{json,md,html}
make audit-headed   # (plan) to samo w widocznym oknie, z pauzą między kliknięciami
make help           # pełna lista
```

Klika test, nie człowiek. Każdy scenariusz dostaje świeżą przeglądarkę (pusty `localStorage`),
podsłuchuje `dataLayer.push`, klika według scenariusza i waliduje zebrane pushe.

Podgląd porażki po fakcie: `uv run playwright show-trace test-results/<test>/trace.zip`.
Krok po kroku: `PWDEBUG=1 uv run pytest -m e2e -k <scenariusz>`.

## Bezpieczeństwo produkcji

GTM (`/mackowka/`) jest blokowany w każdym teście, więc nic nie trafia do GA4. Nawigacje do
LinkedIn i `tel:` są abortowane. Czat jest tylko otwierany, nigdy nie wysyła wiadomości.
Scenariusze uruchamiają się sekwencyjnie.

## Etapy

1. ✅ Szkielet: uv, Makefile, ruff, mypy, pytest, Chromium.
2. ✅ Kontrakt: unia pydantic z dyskryminatorem-funkcją (zdarzenia + komendy gtag).
3. Przechwytywanie: init script owijający `dataLayer.push`.
4. Scenariusze E2E: zgody, telefon, LinkedIn, czat, menu mobilne.
5. Raport: JSON → Markdown + HTML (pokrycie planu, zgodność, reguły).
6. (opcja) Warstwa sieciowa: hity GA4/sGTM przechwycone i abortowane.
7. Drift z `events.ts` + GitHub Actions (cron dzienny).
