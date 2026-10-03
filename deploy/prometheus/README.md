# Reguły alertów Prometheusa – Alerta Next

`alerta-next-rules.yaml` – zestaw startowy reguł do monitorowania samej Alerta Next: progi, `for:` i ważności dobrane
na początek, do dostrojenia. Etykiety kierujące (zespół, `notify` …) dopisz w `labels:` każdej reguły.

| Grupa | Reguła | Ważność | Kiedy |
|---|---|---|---|
| availability | `AlertaNextDown` | critical | żadna replika nie wystawia metryk od 2 min |
| | `AlertaNextReplicaDown` | warning | replika nie odpowiada od 5 min |
| | `AlertaNextSingleReplica` | info | jedna replika przez 30 min (brak zapasu) |
| | `AlertaNextReplicaRestarting` | warning | ponad 2 restarty w 30 min |
| alert-path | `AlertaNextWatchdogMissing` | critical | Watchdog z Alertmanagera nie dociera od 5 min (+2 min) |
| | `AlertaNextAlertPathSlow` | warning | mediana opóźnienia ścieżki > 15 min przez 15 min |
| | `AlertaNextAlertsInQuarantine` | warning | alerty bez środowiska przez 30 min |
| | `AlertaNextIngestRejected` | warning | klucz API nie obejmuje środowiska alertów |
| | `AlertaNextIngestUnauthorized` | warning | nadawca z nieważnym kluczem API przez 10 min |
| | `AlertaNextSilenceSyncFailing` | warning | synchronizacja wyciszeń z Alertmanagerem zawodzi przez 10 min |
| security | `AlertaNextAuditChainBroken` | critical | nocne sprawdzenie: łańcuch audytu przerwany lub niekompletny |
| | `AlertaNextAuditChainNotChecked` | warning | łańcuch niesprawdzony od ponad doby |
| | `AlertaNextLoginFailuresHigh` | warning | > 20 nieudanych logowań w 15 min |
| | `AlertaNextAccountLocked` | info | blokada konta po nieudanych logowaniach |
| runtime | `AlertaNextServerErrors` | warning | > 2% odpowiedzi 5xx (min. 5 błędów) przez 10 min |
| | `AlertaNextSlowResponses` | warning | średni czas odpowiedzi > 1 s przez 15 min |
| | `AlertaNextDatabasePoolExhausted` | warning | wątki czekają na połączenie z bazą przez 5 min |
| | `AlertaNextDatabaseConnectionTimeouts` | critical | połączenie z bazą nieprzydzielone w czasie |
| | `AlertaNextJvmHeapHigh` | warning | sterta po GC > 90% przez 15 min |
| | `AlertaNextGcPressure` | warning | > 10% czasu w GC przez 15 min |
| | `AlertaNextScheduledTaskFailing` | warning | zadanie cykliczne zakończone wyjątkiem |
| | `AlertaNextErrorLogs` | info | > 10 błędów w logach w 15 min |
| | `AlertaNextFileDescriptorsHigh` | warning | > 80% deskryptorów plików przez 15 min |

**Zakres bez edycji selektorów:** reguły na metrykach Alerta Next (`alerta_*`) dotyczą tylko jej; reguły na metrykach
ogólnych (`up`, `http_*`, `jvm_*`, `hikaricp_*`) biorą tylko pody, które wystawiają `alerta_sessions_active`
(`and on (namespace, pod) …`). Plik działa w dowolnym namespace i przy kilku instalacjach. Wymaga etykiet `namespace`
i `pod` na zbieranych seriach (odkrywanie podów albo ServiceMonitor).

**Watchdog:** `AlertaNextWatchdogMissing` zakłada, że Alertmanager powtarza zawsze aktywny alert `Watchdog` co 1–2 min
(osobna trasa z `repeat_interval: 1m`) – inaczej podnieś próg 300 s.

**Wdrożenie:** `rule_files:` w `prometheus.yml`, albo PrometheusRule (Prometheus Operator) – `spec.groups` przyjmuje
`groups` z pliku bez zmian.

**Sprawdzenie** (także po każdej zmianie progów):

```sh
promtool check rules alerta-next-rules.yaml
promtool test rules alerta-next-rules.test.yaml   # testy: zakres tylko na Alerta Next, Watchdog, audyt, 5xx, SSE
```

Dashboard Grafany do tych samych metryk: [../grafana](../grafana/README.md).
