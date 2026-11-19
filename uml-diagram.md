# Diagram sekwencji UML: jeden przebieg audytu

Kto wywołuje kogo w jednym scenariuszu tor A (audyt). Tor B (drift) i proces w GitHub Actions: [README](README.md).

```mermaid
sequenceDiagram
    autonumber
    participant GH as GitHub Actions (job audit)
    participant PW as pytest + Playwright (Chromium)
    participant G as guard.py
    participant S as pmdata.pl (produkcja)
    participant SPY as capture.js
    participant C as contract.py
    participant R as report.py

    GH->>PW: make audit (cron 03:48 albo Run workflow)
    PW->>G: osłona w fixture page
    PW->>SPY: wstrzyknięcie przed kodem strony (owija dataLayer.push)
    PW->>S: otwarcie strony w świeżej przeglądarce
    S->>G: żądanie loadera GTM
    G-->>S: abort — zero ruchu do GA4
    PW->>S: scenariusz: baner zgód, e-mail, LinkedIn, czat, menu
    Note over PW,S: nawigacje wychodzące (linkedin.com, mailto:) przechwycone i anulowane
    S->>SPY: dataLayer.push / gtag
    SPY->>PW: kopia pusha z chwili wysłania
    PW->>C: validate_push
    C-->>PW: zgodny albo lista błędów
    PW->>R: wyniki scenariuszy
    R->>GH: reports/audit-RRRR-MM-DD.json, .md, .html → podsumowanie joba i artefakt
```

| Krok | Kto | Po co |
|---|---|---|
| 1 | GitHub Actions | audyt codziennie, bez ręcznego klikania w GTM Preview |
| 2, 5–6 | osłona | test na produkcji nie zanieczyszcza danych GA4 |
| 3, 8–9 | podsłuch | kopia pusha z chwili wysłania, zanim strona go zmieni |
| 10–11 | kontrakt pydantic | typy, wymagane parametry i reguły biznesowe w jednym miejscu |
| 12–13 | raport | wynik czytelny bez uruchamiania testów |
