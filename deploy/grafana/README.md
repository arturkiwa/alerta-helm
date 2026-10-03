# Dashboard Grafany – Alerta Next

`alerta-next-dashboard.json` – pełny monitoring aplikacji dla **Grafany 11.0+** (format „Export for sharing externally”).

**Import:** *Dashboards → New → Import* → wgraj plik → wybierz źródło danych Prometheus (pole „Prometheus”) → *Import*.
Wybrane źródło staje się domyślną wartością zmiennej „Źródło danych”; panele korzystają ze zmiennej, więc źródło można
potem zmieniać z listy na górze dashboardu.

**Zmienne:** źródło danych, namespace, replika backendu, środowisko alertów, źródło alertów, Alertmanager, ścieżka API.

**Sekcje:** stan ogólny (kafelki) · alerty (aktywne, przyjmowanie, opóźnienie ścieżki, Watchdogi, synchronizacja
wyciszeń, heartbeaty, retencja) · bezpieczeństwo i dostęp (logowania, blokady, 401/403, sesje, łańcuch audytu, ingest) ·
HTTP / API · baza danych (pula połączeń) · JVM i proces · zadania w tle · Kubernetes (cAdvisor, kube-state-metrics;
wszystkie pody przestrzeni nazw). Adnotacja „Restart repliki” zaznacza restarty backendu.

**Wymagania:** Prometheus zbiera `/actuator/prometheus` z portu 8081 backendu i dodaje etykiety `namespace` i `pod`
(standardowo przy odkrywaniu podów lub ServiceMonitorze). Sekcja Kubernetes potrzebuje metryk cAdvisora
i kube-state-metrics – bez nich pokazuje „No data”, reszta działa.

**Zmiany:** dashboard generuje `generate-dashboard.py` (Python 3, bez zależności) –
`python3 generate-dashboard.py > alerta-next-dashboard.json`. Zmieniaj skrypt, nie JSON.
Reguły alertów do tych samych metryk: [../prometheus](../prometheus/README.md).
