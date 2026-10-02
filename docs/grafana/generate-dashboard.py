#!/usr/bin/env python3
"""Generates the Alerta Next Grafana dashboard in the "Export for sharing externally" shape (Grafana 11.0.0)."""
import json
import sys

DS = {"type": "prometheus", "uid": "${datasource}"}
NS = 'namespace="$namespace"'
POD = 'namespace="$namespace", pod=~"$pod"'

panels = []
_id = [0]
_y = [0]
_row = [None]  # current collapsed row (its panels go inside it)


def nid():
    _id[0] += 1
    return _id[0]


def target(expr, legend="__auto", ref="A", instant=False, fmt=None):
    t = {"datasource": DS, "editorMode": "code", "expr": expr, "legendFormat": legend, "range": not instant,
         "instant": instant, "refId": ref}
    if fmt:
        t["format"] = fmt
    return t


def place(panel, w, h, x):
    panel["gridPos"] = {"h": h, "w": w, "x": x, "y": _y[0]}
    (_row[0]["panels"] if _row[0] is not None else panels).append(panel)


class Line:
    """Places panels left to right; a new line when the row is full."""

    def __init__(self):
        self.x = 0
        self.h = 0

    def add(self, panel, w, h):
        if self.x + w > 24:
            self.end()
        place(panel, w, h, self.x)
        self.x += w
        self.h = max(self.h, h)

    def end(self):
        if self.x:
            _y[0] += self.h
        self.x = 0
        self.h = 0


line = Line()


def row(title, collapsed=False):
    line.end()
    r = {"collapsed": collapsed, "gridPos": {"h": 1, "w": 24, "x": 0, "y": _y[0]}, "id": nid(), "panels": [],
         "title": title, "type": "row"}
    panels.append(r)
    _y[0] += 1
    _row[0] = r if collapsed else None


def thresholds(*steps):
    out = [{"color": "green", "value": None}]
    for color, value in steps:
        out.append({"color": color, "value": value})
    return {"mode": "absolute", "steps": out}


def stat(title, expr, unit="short", desc="", th=None, mappings=None, w=4, h=4, color_mode="background", decimals=None,
         no_value=None):
    p = {
        "datasource": DS, "description": desc, "id": nid(), "title": title, "type": "stat",
        "fieldConfig": {"defaults": {"color": {"mode": "thresholds"}, "mappings": mappings or [],
                                     "thresholds": th or thresholds(), "unit": unit},
                        "overrides": []},
        "options": {"colorMode": color_mode, "graphMode": "none", "justifyMode": "auto", "orientation": "auto",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "showPercentChange": False, "textMode": "auto", "wideLayout": True},
        "pluginVersion": "11.0.0",
        "targets": [target(expr, legend="", instant=True)],
    }
    if decimals is not None:
        p["fieldConfig"]["defaults"]["decimals"] = decimals
    if no_value is not None:
        p["fieldConfig"]["defaults"]["noValue"] = no_value
    line.add(p, w, h)


def ts(title, targets, unit="short", desc="", w=12, h=8, stack=False, draw="line", th=None, min_zero=True,
       legend_calcs=("mean", "max", "lastNotNull"), max_value=None):
    custom = {
        "axisBorderShow": False, "axisCenteredZero": False, "axisColorMode": "text", "axisLabel": "",
        "axisPlacement": "auto", "barAlignment": 0, "drawStyle": draw, "fillOpacity": 25 if stack or draw == "bars" else 10,
        "gradientMode": "none", "hideFrom": {"legend": False, "tooltip": False, "viz": False},
        "insertNulls": False, "lineInterpolation": "linear", "lineWidth": 1, "pointSize": 4,
        "scaleDistribution": {"type": "linear"}, "showPoints": "never", "spanNulls": False,
        "stacking": {"group": "A", "mode": "normal" if stack else "none"},
        "thresholdsStyle": {"mode": "line" if th else "off"},
    }
    defaults = {"color": {"mode": "palette-classic"}, "custom": custom, "mappings": [],
                "thresholds": th or thresholds(), "unit": unit}
    if min_zero:
        defaults["min"] = 0
    if max_value is not None:
        defaults["max"] = max_value
    p = {
        "datasource": DS, "description": desc, "id": nid(), "title": title, "type": "timeseries",
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"legend": {"calcs": list(legend_calcs), "displayMode": "table", "placement": "bottom",
                               "showLegend": True},
                    "tooltip": {"maxHeight": 600, "mode": "multi", "sort": "desc"}},
        "targets": [target(e, l, chr(ord("A") + i)) for i, (e, l) in enumerate(targets)],
    }
    line.add(p, w, h)


def table(title, expr, columns, desc="", w=12, h=8, unit_overrides=None):
    overrides = []
    for name, unit in (unit_overrides or {}).items():
        overrides.append({"matcher": {"id": "byName", "options": name},
                          "properties": [{"id": "unit", "value": unit}]})
    p = {
        "datasource": DS, "description": desc, "id": nid(), "title": title, "type": "table",
        "fieldConfig": {"defaults": {"color": {"mode": "thresholds"},
                                     "custom": {"align": "auto", "cellOptions": {"type": "auto"}, "inspect": False},
                                     "mappings": [], "thresholds": thresholds()},
                        "overrides": overrides},
        "options": {"cellHeight": "sm", "footer": {"countRows": False, "fields": "", "reducer": ["sum"], "show": False},
                    "showHeader": True, "sortBy": [{"desc": True, "displayName": "Value"}]},
        "pluginVersion": "11.0.0",
        "targets": [target(expr, legend="", instant=True, fmt="table")],
        "transformations": [{"id": "organize", "options": {"excludeByName": {"Time": True}, "renameByName": columns}}],
    }
    line.add(p, w, h)


RATE = "$__rate_interval"
ACTIVE = f'max by (environment, severity) (alerta_alerts_active{{{NS}, environment=~"$environment"}})'

# ---------------------------------------------------------------------------------------------------------------------
row("Stan ogólny")
stat("Repliki backendu", f'sum(up{{{POD}}})', desc="Repliki backendu, które Prometheus odpytał z powodzeniem (metryka up).",
     th={"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "orange", "value": 1},
                                       {"color": "green", "value": 2}]}, w=3)
stat("Aktywne alerty", f"sum({ACTIVE})", desc="Otwarte i potwierdzone alerty w wybranych środowiskach.",
     color_mode="value", w=3)
stat("Krytyczne aktywne", f'sum(max by (environment) (alerta_alerts_active{{{NS}, environment=~"$environment", severity="CRITICAL"}})) or vector(0)',
     th=thresholds(("red", 1)), w=3)
stat("Kwarantanna", f'sum(max by (severity) (alerta_alerts_active{{{NS}, environment="(quarantine)"}})) or vector(0)',
     desc="Alerty bez środowiska – nikt ich nie widzi poza administratorami. Dopisz warunki środowiska.",
     th=thresholds(("orange", 1)), w=3)
stat("Wiek Watchdoga", f'max(alerta_watchdog_age_seconds{{{NS}}})', unit="s",
     desc="Ile sekund temu dotarł najstarszy Watchdog (zawsze aktywny alert Alertmanagera). Ponad 5 min = ścieżka alertów zerwana.",
     th=thresholds(("orange", 120), ("red", 300)), w=3)
stat("Łańcuch audytu", f'max(alerta_audit_chain_ok{{{NS}}})',
     desc="Wynik ostatniego nocnego sprawdzenia łańcucha skrótów dziennika audytu.",
     mappings=[{"options": {"-1": {"color": "text", "index": 0, "text": "nie sprawdzono"},
                            "0": {"color": "red", "index": 1, "text": "PRZERWANY / NIEPEŁNY"},
                            "1": {"color": "green", "index": 2, "text": "OK"}}, "type": "value"}],
     th=thresholds(), w=3)
stat("Audyt poza łańcuchem", f'max(alerta_audit_chain_orphaned{{{NS}}}) or vector(0)',
     desc="Starsze wpisy audytu poza łańcuchem przy ostatnim sprawdzeniu (powinno być 0).",
     th=thresholds(("red", 1)), w=3)
stat("Heartbeaty wygasłe", f'max(alerta_heartbeats_expired{{{NS}}})',
     desc="Źródła, które przestały się zgłaszać (strona Heartbeaty).", th=thresholds(("orange", 1)), w=3)
stat("Zalogowane sesje", f'max(alerta_sessions_active{{{NS}}})', color_mode="value", w=3)
stat("Konta tymczasowe", f'max(alerta_accounts_temporary{{{NS}}})', color_mode="value", w=3)
stat("Błędy 5xx (5 min)", f'sum(increase(http_server_requests_seconds_count{{{POD}, status=~"5.."}}[5m])) or vector(0)',
     th=thresholds(("orange", 1), ("red", 10)), decimals=0, w=3)
stat("Pula DB – oczekujący", f'max(hikaricp_connections_pending{{{POD}}})',
     desc="Wątki czekające na wolne połączenie z puli – stale > 0 oznacza wyczerpaną pulę.",
     th=thresholds(("orange", 1), ("red", 5)), w=3)
stat("Najmłodsza replika", f'min(process_uptime_seconds{{{POD}}})', unit="s",
     desc="Czas od startu najmłodszej repliki – krótki = niedawny restart.",
     th={"mode": "absolute", "steps": [{"color": "orange", "value": None}, {"color": "green", "value": 900}]}, w=3)
stat("Błędy w logach (1 h)", f'sum(increase(logback_events_total{{{POD}, level="error"}}[1h])) or vector(0)',
     th=thresholds(("orange", 1), ("red", 20)), decimals=0, w=3)
stat("Błędy sync wyciszeń (1 h)", f'sum(increase(alerta_alertmanager_sync_total{{{POD}, outcome="failure"}}[1h])) or vector(0)',
     desc="Nieudane synchronizacje wyciszeń z Alertmanagerami.", th=thresholds(("orange", 1), ("red", 10)), decimals=0, w=3)
stat("Opóźnienie alertów p50",
     f'histogram_quantile(0.5, sum by (le) (rate(alerta_ingest_delay_seconds_bucket{{{POD}}}[30m])))', unit="s",
     desc="Mediana z 30 min: od początku problemu (wg źródła) do dotarcia nowego wystąpienia do Alerta Next.",
     th=thresholds(("orange", 300), ("red", 900)), w=3, no_value="brak nowych")

# ---------------------------------------------------------------------------------------------------------------------
row("Alerty")
ts("Aktywne alerty wg ważności", [(f"sum by (severity) ({ACTIVE})", "{{severity}}")], stack=True,
   desc="Otwarte i potwierdzone alerty (wartość z bazy – każda replika raportuje to samo, stąd max).")
ts("Aktywne alerty wg środowiska", [(f"sum by (environment) ({ACTIVE})", "{{environment}}")], stack=True)
ts("Przyjmowanie alertów (na minutę)",
   [(f'sum by (source, outcome) (rate(alerta_alerts_ingested_total{{{POD}, source=~"$source"}}[{RATE}])) * 60',
     "{{source}} – {{outcome}}")],
   desc="Komunikaty od źródeł: created, updated, resolved, quarantined, rejected, stale…")
ts("Opóźnienie ścieżki alertów (okno 30 min)",
   [(f'histogram_quantile(0.5, sum by (le, source) (rate(alerta_ingest_delay_seconds_bucket{{{POD}, source=~"$source"}}[30m])))', "p50 {{source}}"),
    (f'histogram_quantile(0.9, sum by (le, source) (rate(alerta_ingest_delay_seconds_bucket{{{POD}, source=~"$source"}}[30m])))', "p90 {{source}}"),
    (f'max by (source) (alerta_ingest_delay_seconds_max{{{POD}, source=~"$source"}})', "max {{source}}")],
   unit="s", th=thresholds(("red", 900)),
   desc="Od startu problemu wg źródła do dotarcia nowego wystąpienia. Obejmuje for: reguł i grupowanie Alertmanagera; reguła AlertaNextAlertPathSlow reaguje na medianę > 15 min.")
ts("Wiek Watchdogów", [(f'max by (alertmanager, watchdog) (alerta_watchdog_age_seconds{{{NS}, alertmanager=~"$alertmanager"}})',
                        "{{alertmanager}} {{watchdog}}")],
   unit="s", th=thresholds(("red", 300)), desc="Każdy Watchdog powinien dochodzić co kilka minut; > 5 min = zerwana ścieżka Prometheus → Alertmanager → Alerta.")
ts("Synchronizacja wyciszeń z Alertmanagerami",
   [(f'sum by (alertmanager, outcome) (increase(alerta_alertmanager_sync_total{{{POD}, alertmanager=~"$alertmanager"}}[{RATE}]))',
     "{{alertmanager}} – {{outcome}}")], draw="bars", stack=True)
ts("Heartbeaty odebrane (na minutę)", [(f'sum(rate(alerta_heartbeats_received_total{{{POD}}}[{RATE}])) * 60', "odebrane")],
   w=8)
ts("Heartbeaty wygasłe", [(f'max(alerta_heartbeats_expired{{{NS}}})', "wygasłe")], w=8, th=thresholds(("orange", 1)))
ts("Retencja – usunięte alerty", [(f'sum(increase(alerta_retention_deleted_total{{{POD}}}[{RATE}]))', "usunięte")],
   draw="bars", w=8, desc="Nocne zadanie retencji usuwa rozwiązane i zamknięte alerty starsze niż retencja środowiska.")

# ---------------------------------------------------------------------------------------------------------------------
row("Bezpieczeństwo i dostęp")
ts("Logowania", [(f'sum by (outcome, reason) (increase(alerta_auth_logins_total{{{POD}}}[{RATE}]))', "{{outcome}} {{reason}}")],
   draw="bars", stack=True, w=8, desc="Udane i nieudane logowania (lokalne i SSO) z powodem odmowy.")
ts("Blokady kont i odmowy dostępu",
   [(f'sum(increase(alerta_auth_lockouts_total{{{POD}}}[{RATE}])) or vector(0)', "blokady kont"),
    (f'sum by (status) (increase(http_server_requests_seconds_count{{{POD}, status=~"401|403"}}[{RATE}]))', "HTTP {{status}}")],
   draw="bars", w=8, desc="Seria 401/403 lub blokad może oznaczać zgadywanie haseł albo źle skonfigurowany klucz API.")
ts("Sesje i konta tymczasowe",
   [(f'max(alerta_sessions_active{{{NS}}})', "zalogowane sesje"),
    (f'max(alerta_accounts_temporary{{{NS}}})', "konta tymczasowe")], w=8)
ts("Łańcuch dziennika audytu",
   [(f'max(alerta_audit_chain_ok{{{NS}}})', "wynik (1 = OK)"),
    (f'max(alerta_audit_chain_orphaned{{{NS}}})', "wpisy poza łańcuchem")], min_zero=False,
   desc="Nocne sprawdzenie: 1 = cały i kompletny, 0 = przerwany lub niekompletny, -1 = jeszcze nie sprawdzony.")
ts("Ingest – żądania wg wyniku",
   [(f'sum by (uri, status) (rate(http_server_requests_seconds_count{{{POD}, uri=~"/api/v1/ingest/.*"}}[{RATE}]))', "{{uri}} {{status}}")],
   unit="reqps", desc="Webhook Alertmanagera, API alertów, heartbeaty i zmiany (ArgoCD / CI). 401 = zły klucz API, 4xx = odrzucone dane.")

# ---------------------------------------------------------------------------------------------------------------------
row("HTTP / API")
URI = f'{POD}, uri=~"$uri"'
# the live console stream (SSE) stays open for hours – not a slow response
TIMED = f'{URI}, uri!="/api/v1/alerts/stream"'
ts("Żądania wg wyniku", [(f'sum by (outcome) (rate(http_server_requests_seconds_count{{{URI}}}[{RATE}]))', "{{outcome}}")],
   unit="reqps", stack=True, w=8)
ts("Odsetek błędów serwera (5xx)",
   [(f'(sum(rate(http_server_requests_seconds_count{{{URI}, status=~"5.."}}[{RATE}])) or vector(0)) / sum(rate(http_server_requests_seconds_count{{{URI}}}[{RATE}]))', "5xx")],
   unit="percentunit", w=8, th=thresholds(("red", 0.01)))
ts("Żądania w toku (także strumienie SSE konsol)",
   [(f'sum by (pod) (http_server_requests_active_seconds_count{{{POD}}})', "{{pod}}")], w=8,
   desc="Żądania trwające w chwili odczytu – w większości otwarte konsole (połączenie na żywo, SSE).")
ts("Średni czas odpowiedzi – 10 najwolniejszych (bez strumienia konsoli)",
   [(f'topk(10, sum by (uri) (rate(http_server_requests_seconds_sum{{{TIMED}}}[{RATE}])) / sum by (uri) (rate(http_server_requests_seconds_count{{{TIMED}}}[{RATE}])))', "{{uri}}")],
   unit="s")
ts("Maksymalny czas odpowiedzi – 10 najwolniejszych (bez strumienia konsoli)",
   [(f'topk(10, max by (uri) (http_server_requests_seconds_max{{{TIMED}}}))', "{{uri}}")], unit="s")
ts("Błędy 5xx wg ścieżki",
   [(f'sum by (uri, status, exception) (rate(http_server_requests_seconds_count{{{URI}, status=~"5.."}}[{RATE}]))', "{{uri}} {{status}} {{exception}}")],
   unit="reqps", draw="bars")
table("Ścieżki API – ruch i czasy (wybrany zakres)",
      f'sum by (method, uri) (increase(http_server_requests_seconds_count{{{URI}}}[$__range]))',
      {"method": "Metoda", "uri": "Ścieżka", "Value": "Żądań w zakresie"},
      desc="Liczba żądań na ścieżkę w wybranym zakresie czasu.")

# ---------------------------------------------------------------------------------------------------------------------
row("Baza danych (pula połączeń)")
ts("Połączenia z bazą",
   [(f'sum by (pod) (hikaricp_connections_active{{{POD}}})', "aktywne {{pod}}"),
    (f'sum by (pod) (hikaricp_connections_idle{{{POD}}})', "wolne {{pod}}"),
    (f'max(hikaricp_connections_max{{{POD}}})', "maksimum puli")], w=8)
ts("Oczekujący na połączenie", [(f'sum by (pod) (hikaricp_connections_pending{{{POD}}})', "{{pod}}")], w=8,
   th=thresholds(("red", 1)))
ts("Czas pozyskania połączenia",
   [(f'sum by (pod) (rate(hikaricp_connections_acquire_seconds_sum{{{POD}}}[{RATE}])) / sum by (pod) (rate(hikaricp_connections_acquire_seconds_count{{{POD}}}[{RATE}]))', "średnio {{pod}}"),
    (f'max by (pod) (hikaricp_connections_acquire_seconds_max{{{POD}}})', "max {{pod}}"),
    (f'sum(increase(hikaricp_connections_timeout_total{{{POD}}}[{RATE}]))', "timeouty")], unit="s", w=8)
ts("Czas trzymania połączenia",
   [(f'sum by (pod) (rate(hikaricp_connections_usage_seconds_sum{{{POD}}}[{RATE}])) / sum by (pod) (rate(hikaricp_connections_usage_seconds_count{{{POD}}}[{RATE}]))', "średnio {{pod}}"),
    (f'max by (pod) (hikaricp_connections_usage_seconds_max{{{POD}}})', "max {{pod}}")], unit="s",
   desc="Długie trzymanie połączenia = długie transakcje (wolne zapytania, blokady).")
ts("Wywołania repozytoriów – średni czas",
   [(f'topk(10, sum by (repository, method) (rate(spring_data_repository_invocations_seconds_sum{{{POD}}}[{RATE}])) / sum by (repository, method) (rate(spring_data_repository_invocations_seconds_count{{{POD}}}[{RATE}])))', "{{repository}}.{{method}}")],
   unit="s")

# ---------------------------------------------------------------------------------------------------------------------
row("JVM i proces")
ts("Pamięć sterty (heap)",
   [(f'sum by (pod) (jvm_memory_used_bytes{{{POD}, area="heap"}})', "użyta {{pod}}"),
    (f'sum by (pod) (jvm_memory_max_bytes{{{POD}, area="heap"}} > 0)', "maks. {{pod}}")], unit="bytes", w=8)
ts("Sterta po GC (%)", [(f'max by (pod) (jvm_memory_usage_after_gc{{{POD}, area="heap", pool="long-lived"}})', "{{pod}}")],
   unit="percentunit", w=8, th=thresholds(("orange", 0.8), ("red", 0.9)),
   desc="Zajętość starej generacji po odśmiecaniu – stale rosnąca sugeruje wyciek pamięci.")
ts("Pamięć poza stertą", [(f'sum by (pod) (jvm_memory_used_bytes{{{POD}, area="nonheap"}})', "{{pod}}")], unit="bytes", w=8)
ts("CPU", [(f'max by (pod) (process_cpu_usage{{{POD}}})', "proces {{pod}}"),
           (f'max by (pod) (system_cpu_usage{{{POD}}})', "system {{pod}}")], unit="percentunit", w=8)
ts("Odśmiecanie (GC) – czas przerw",
   [(f'sum by (pod) (rate(jvm_gc_pause_seconds_sum{{{POD}}}[{RATE}]))', "{{pod}}")], unit="percentunit", w=8,
   desc="Ułamek czasu w przerwach GC.")
ts("Wątki", [(f'sum by (pod) (jvm_threads_live_threads{{{POD}}})', "żywe {{pod}}"),
             (f'sum by (state) (jvm_threads_states_threads{{{POD}, state=~"blocked|waiting|timed-waiting"}})', "{{state}}")], w=8)
ts("Zdarzenia w logach", [(f'sum by (level) (increase(logback_events_total{{{POD}, level=~"error|warn"}}[{RATE}]))', "{{level}}")],
   draw="bars", stack=True, w=8)
ts("Otwarte pliki", [(f'max by (pod) (process_files_open_files{{{POD}}} / process_files_max_files{{{POD}}})', "{{pod}}")],
   unit="percentunit", w=8)
ts("Czas działania", [(f'max by (pod) (process_uptime_seconds{{{POD}}})', "{{pod}}")], unit="s", w=8)

# ---------------------------------------------------------------------------------------------------------------------
row("Zadania w tle", collapsed=True)
ts("Uruchomienia zadań (na minutę)",
   [(f'sum by (code_namespace, code_function) (rate(tasks_scheduled_execution_seconds_count{{{POD}}}[{RATE}])) * 60',
     "{{code_namespace}}.{{code_function}}")],
   desc="Zadania cykliczne: synchronizacja wyciszeń, powiadomienia, łańcuch audytu, retencja, porządki…")
ts("Zadania zakończone błędem",
   [(f'sum by (code_namespace, code_function, exception) (increase(tasks_scheduled_execution_seconds_count{{{POD}, outcome!="SUCCESS"}}[{RATE}]))',
     "{{code_namespace}}.{{code_function}} {{exception}}")], draw="bars")
ts("Średni czas zadania",
   [(f'sum by (code_namespace, code_function) (rate(tasks_scheduled_execution_seconds_sum{{{POD}}}[{RATE}])) / sum by (code_namespace, code_function) (rate(tasks_scheduled_execution_seconds_count{{{POD}}}[{RATE}]))',
     "{{code_namespace}}.{{code_function}}")], unit="s")
ts("Maksymalny czas zadania",
   [(f'max by (code_namespace, code_function) (tasks_scheduled_execution_seconds_max{{{POD}}})',
     "{{code_namespace}}.{{code_function}}")], unit="s")

# ---------------------------------------------------------------------------------------------------------------------
row("Kubernetes – wszystkie pody przestrzeni nazw (cAdvisor, kube-state-metrics)", collapsed=True)
ts("CPU kontenerów",
   [(f'sum by (pod) (rate(container_cpu_usage_seconds_total{{{NS}, container!="", container!="POD"}}[{RATE}]))', "{{pod}}")],
   unit="short", w=8, desc="Rdzenie CPU – backend, frontend i baza (jeśli w tej przestrzeni nazw).")
ts("Pamięć kontenerów (working set)",
   [(f'sum by (pod) (container_memory_working_set_bytes{{{NS}, container!="", container!="POD"}})', "{{pod}}")],
   unit="bytes", w=8)
ts("Restarty kontenerów",
   [(f'sum by (pod, container) (increase(kube_pod_container_status_restarts_total{{{NS}}}[{RATE}]))', "{{pod}} {{container}}")],
   draw="bars", w=8)
ts("Pody niegotowe", [(f'sum by (pod) (kube_pod_status_ready{{{NS}, condition="false"}})', "{{pod}}")], w=12,
   th=thresholds(("red", 1)))
ts("Ograniczanie CPU (throttling)",
   [(f'sum by (pod) (rate(container_cpu_cfs_throttled_periods_total{{{NS}, container!=""}}[{RATE}])) / sum by (pod) (rate(container_cpu_cfs_periods_total{{{NS}, container!=""}}[{RATE}]))', "{{pod}}")],
   unit="percentunit", w=12)
line.end()


# ---------------------------------------------------------------------------------------------------------------------
def query_var(name, label, query, multi=True, include_all=True, regex="", desc=""):
    v = {"current": {}, "datasource": DS, "definition": query, "description": desc, "hide": 0,
         "includeAll": include_all, "label": label, "multi": multi, "name": name, "options": [],
         "query": {"qryType": 1, "query": query, "refId": "PrometheusVariableQueryEditor-VariableQuery"},
         "refresh": 2, "regex": regex, "skipUrlSync": False, "sort": 1, "type": "query"}
    if include_all:
        v["allValue"] = ".*"
    return v


dashboard = {
    # as Grafana's "Export for sharing externally": the import asks for a Prometheus data source – here it becomes the
    # default of the "datasource" variable, so the panels still follow the variable (they use ${datasource})
    "__inputs": [{"name": "DS_PROMETHEUS", "label": "Prometheus", "description": "Prometheus z metrykami Alerta Next",
                  "type": "datasource", "pluginId": "prometheus", "pluginName": "Prometheus"}],
    "__elements": {},
    "__requires": [
        {"type": "grafana", "id": "grafana", "name": "Grafana", "version": "11.0.0"},
        {"type": "datasource", "id": "prometheus", "name": "Prometheus", "version": "1.0.0"},
        {"type": "panel", "id": "stat", "name": "Stat", "version": ""},
        {"type": "panel", "id": "table", "name": "Table", "version": ""},
        {"type": "panel", "id": "timeseries", "name": "Time series", "version": ""},
    ],
    "annotations": {"list": [
        {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True, "hide": True,
         "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts", "type": "dashboard"},
        {"datasource": DS, "enable": True, "expr": f'changes(process_start_time_seconds{{{POD}}}[2m]) > 0',
         "iconColor": "orange", "name": "Restart repliki", "step": "60s", "titleFormat": "Restart {{pod}}",
         "textFormat": "Replika backendu wystartowała ponownie"},
    ]},
    "description": "Alerta Next – pełny monitoring aplikacji: ścieżka alertów, audyt, bezpieczeństwo, API, baza, JVM, zadania w tle, Kubernetes.",
    "editable": True,
    "fiscalYearStartMonth": 0,
    "graphTooltip": 1,
    "id": None,
    "links": [],
    "panels": panels,
    "refresh": "1m",
    "schemaVersion": 39,
    "tags": ["alerta-next", "alerting", "spring-boot"],
    "templating": {"list": [
        {"current": {"selected": False, "text": "${DS_PROMETHEUS}", "value": "${DS_PROMETHEUS}"},
         "description": "Źródło danych Prometheus z metrykami Alerta Next.", "hide": 0,
         "includeAll": False, "label": "Źródło danych", "multi": False, "name": "datasource", "options": [],
         "query": "prometheus", "queryValue": "", "refresh": 1, "regex": "", "skipUrlSync": False,
         "type": "datasource"},
        query_var("namespace", "Namespace", "label_values(alerta_sessions_active, namespace)", multi=False,
                  include_all=False, desc="Przestrzeń nazw, w której działa Alerta Next."),
        query_var("pod", "Replika backendu", 'label_values(alerta_sessions_active{namespace="$namespace"}, pod)',
                  desc="Repliki backendu (metryki liczone przez repliki: HTTP, baza, JVM, zadania)."),
        query_var("environment", "Środowisko alertów",
                  'label_values(alerta_alerts_active{namespace="$namespace"}, environment)',
                  desc="Środowiska alertów (panele z aktywnymi alertami)."),
        query_var("source", "Źródło alertów",
                  'label_values(alerta_alerts_ingested_total{namespace="$namespace"}, source)',
                  desc="Źródło przyjmowanych alertów (alertmanager, api, …)."),
        query_var("alertmanager", "Alertmanager",
                  'label_values(alerta_watchdog_age_seconds{namespace="$namespace"}, alertmanager)',
                  desc="Alertmanagery skonfigurowane w Alerta Next."),
        query_var("uri", "Ścieżka API",
                  'label_values(http_server_requests_seconds_count{namespace="$namespace"}, uri)',
                  desc="Filtr paneli HTTP / API."),
    ]},
    "time": {"from": "now-6h", "to": "now"},
    "timeRangeUpdatedDuringEditOrView": False,
    "timepicker": {},
    "timezone": "browser",
    "title": "Alerta Next – monitoring aplikacji",
    "uid": "alerta-next-app",
    "version": 1,
    "weekStart": "",
}

json.dump(dashboard, sys.stdout, ensure_ascii=False, indent=2)
print()
