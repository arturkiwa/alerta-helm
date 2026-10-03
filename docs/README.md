# Dokumentacja Alerta Next

| Dokument | Dla kogo | Treść |
|---|---|---|
| [Instrukcja wdrożenia](deployment/README.pl.md) · [English](deployment/README.md) | wdrożeniowiec, administrator | instalacja (Docker Compose, Kubernetes, Helm), sekrety, baza, konfiguracja, nadawcy alertów, utrzymanie, audyt dla SIEM |
| [Runbook kopii zapasowych](deployment/backup-runbook.pl.md) · [English](deployment/backup-runbook.md) | administrator | kopie bazy, odtworzenie po awarii, próba utraty bazy z pomiarem RTO |
| [Polityka kompatybilności](compatibility-policy.md) | administrator, autorzy integracji | co jest stałe w wersjach 1.x, jak aktualizować i wycofywać |
| [API przyjmowania alertów](ingest-api.md) | autorzy integracji | wysyłanie alertów ze skryptów, Zabbixa i innych źródeł |
| [Samoocena OWASP ASVS L2](security/asvs-l2.md) | bezpieczeństwo, audyt | dokumentacja bezpieczeństwa, ocena wymagań, luki |
| [Alerta Next – konsola alertów dla zespołów IT](executive-overview.pl.md) | kadra kierownicza | czym jest aplikacja i co daje |

Dashboard Grafany: [`deploy/grafana`](../deploy/grafana/README.md) · reguły alertów dla samej Alerty Next:
[`deploy/prometheus`](../deploy/prometheus/README.md).
