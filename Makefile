# ============================================================================
# Makefile jest jedynym interfejsem do projektu - lokalnie i w CI te same cele.
# Komentarze stoją NAD celami: linia wcięta tabem idzie do shella i komentarz
# w środku bloku wypisywałby się przy każdym uruchomieniu.
# ============================================================================

.DEFAULT_GOAL := help
SHELL := /bin/bash
.PHONY: help setup lint format typecheck test check e2e e2e-headed audit audit-open open-report clean

help: ## Lista dostępnych komend
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --only-shell instaluje chromium-headless-shell zamiast pełnego Chromium:
# ok. 3x mniej na dysku i w cache CI. Wystarcza, bo audyt nie potrzebuje okna.
# Konsekwencja: `--headed` nie zadziała - do podglądu na żywo trzeba doinstalować
# pełne `playwright install chromium`.
setup: ## Python 3.12, .venv, zależności, chromium-headless-shell
	uv python install 3.12
	uv sync
	uv run playwright install --only-shell chromium

lint: ## ruff check + kontrola formatowania
	uv run ruff check .
	uv run ruff format --check .

format: ## ruff format + autofix
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## mypy strict
	uv run mypy

# -m "not e2e": bramka jakości nie dotyka produkcji. Scenariusze na pmdata.pl
# odpala się świadomie osobnym celem (etap 4).
test: ## pytest z pokryciem, bez scenariuszy E2E
	uv run pytest -m "not e2e" --cov --cov-report=term-missing

check: lint typecheck test ## Pełna bramka jakości, to samo co CI

# -s pokazuje print() z testów - w e2e to lista przechwyconych pushy.
# --tracing retain-on-failure: trace.zip tylko dla testów, które padły.
e2e: ## Scenariusze na produkcyjnym pmdata.pl (GTM zablokowany)
	uv run pytest -m e2e -s --tracing retain-on-failure

# Okno wymaga pełnego Chromium (setup instaluje tylko headless-shell). Instalacja
# jest idempotentna - przy kolejnym uruchomieniu kończy się w sekundę.
# --slowmo 500: pauza 500 ms przed każdą akcją, żeby oko nadążyło za kliknięciami.
e2e-headed: ## Scenariusze w widocznym oknie, z pauzą między kliknięciami
	uv run playwright install chromium
	uv run pytest -m e2e --headed --slowmo 500

# Te same scenariusze co `e2e` + raport. Zmienna AUDIT_REPORT_DIR włącza zapis
# w tests/conftest.py; bez niej żaden cel niczego nie zapisuje. Raport powstaje także
# wtedy, gdy scenariusze padną - wtedy jest najbardziej potrzebny.
audit: ## Audyt pmdata.pl + raport reports/audit-<data>.{json,md,html}
	AUDIT_REPORT_DIR=reports uv run pytest -m e2e --tracing retain-on-failure

# Najnowszy raport = ostatni alfabetycznie; nazwa zawiera datę i godzinę, więc
# kolejność alfabetyczna jest chronologiczna. Chrome, a gdy go nie ma - domyślna
# przeglądarka. `open` istnieje tylko na macOS, dlatego te cele nie są używane w CI.
LATEST_REPORT = $(lastword $(sort $(wildcard reports/audit-*.html)))

# `-` przed poleceniem: make nie przerywa, gdy audyt padnie - raport z porażką
# jest wtedy najważniejszy, więc i tak go otwieramy.
audit-open: ## Audyt + raport od razu w Chrome (macOS)
	-$(MAKE) audit
	@$(MAKE) open-report

open-report: ## Otwiera najnowszy raport z reports/ w Chrome (macOS)
	@test -n "$(LATEST_REPORT)" || { echo "Brak raportu w reports/ - uruchom make audit"; exit 1; }
	@echo "Otwieram $(LATEST_REPORT)"
	@open -a "Google Chrome" "$(LATEST_REPORT)" 2>/dev/null || open "$(LATEST_REPORT)"

clean: ## Usuwa cache narzędzi i artefakty lokalne
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml test-results
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
