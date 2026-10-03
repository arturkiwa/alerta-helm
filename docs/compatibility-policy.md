# Polityka kompatybilności (od 1.0)

Co Alerta Next gwarantuje w obrębie wersji **1.x** – żeby aktualizacja nie psuła konfiguracji, nadawców alertów,
dashboardów, reguł alertowania ani analiz logów. Obowiązuje od wydania 1.0.0. Do tego czasu (0.x) zasady są te same,
ale bez gwarancji.

## 1. Numer wersji

`MAJOR.MINOR.PATCH`:

| Część | Kiedy rośnie | Co wolno |
|---|---|---|
| **PATCH** (1.2.**3**) | poprawki błędów i bezpieczeństwa | nic nowego w kontrakcie |
| **MINOR** (1.**3**.0) | nowe funkcje | tylko **dodawanie** do kontraktu (nowe klucze, pola, metryki, uprawnienia) |
| **MAJOR** (**2**.0.0) | zmiana niezgodna | usuwanie i zmiana znaczenia elementów kontraktu |

Wyjątek: poprawka bezpieczeństwa, której nie da się zrobić zgodnie wstecz, może wejść w MINOR albo PATCH. Wtedy jest
oznaczona w „Co nowego” (`security`) i w GitHub Release, z opisem, co trzeba zmienić.

## 2. Co jest kontraktem

### 2.1 Konfiguracja

- **Klucze `alerta.*`** w konfiguracji backendu (`application.yml` obrazu, ConfigMapa, `config` w Helmie):
  `session`, `login`, `passwords`, `auth.local`, `auth.oidc`, `accounts`, `environments.classes`, `alerts`,
  `integrations.alertmanager`, `integrations.alertmanagers`, `mail`, `notifications`, `links` – z podkluczami, typami
  i znaczeniem wartości domyślnych.
- **Zmienne środowiskowe** sekretów: `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `ALERTMANAGER_URL`,
  `ALERTMANAGER_TOKEN`, `ALERTMANAGER_USERNAME`, `ALERTMANAGER_PASSWORD`, `MAIL_PASSWORD`, nazwy obiektów w Vault CSI
  (np. `ALERTMANAGER_<NAZWA>_TOKEN`).
- **Values Helma** – klucze najwyższego poziomu i ich podklucze: `image`, `secrets`, `database`, `internalCA`,
  `alertmanager`, `alertmanagers`, `mail`, `notifications`, `oidc`, `config`, `session`, `logs`, `backend`,
  `frontend`, `ingress`, `metrics`, `networkPolicy`, `fullnameOverride`. Nazwy obiektów Kubernetes tworzonych przez
  chart (`<release>-backend`, `<release>-db`, `<release>-db-backup` …).
- **Porty i ścieżki**: 8080 – aplikacja, 8081 – sondy i metryki (`/actuator/health/liveness`,
  `/actuator/health/readiness`, `/actuator/prometheus`), nigdy przez ingress.

### 2.2 API dla nadawców

Udokumentowane w `docs/ingest-api.md` i w instrukcji wdrożenia (8.6):

| Endpoint | Nadawca |
|---|---|
| `POST /api/v1/ingest/alertmanager` | webhook Alertmanagera (format `version: "4"`) |
| `POST /api/v1/ingest/alerts` | skrypty, Zabbix, inne źródła |
| `POST /api/v1/ingest/heartbeat` | heartbeaty |
| `POST /api/v1/ingest/changes` | zmiany z ArgoCD / CI |

Gwarantowane: ścieżki, uwierzytelnienie kluczem API (`Authorization: Bearer ank_…`), pola żądania, kody HTTP, pola
odpowiedzi i kody błędów (`code`, np. `NO_ENVIRONMENT`, `CHANGE_IN_FUTURE`). W 1.x pola i kody błędów mogą dochodzić,
nie znikają i nie zmieniają znaczenia. **Nadawca musi ignorować nieznane pola odpowiedzi.**

### 2.3 Metryki

Nazwy, etykiety i jednostki serii z `/actuator/prometheus`, na których opierają się dashboard
(`deploy/grafana/`) i reguły (`deploy/prometheus/`):

| Metryka | Etykiety |
|---|---|
| `alerta_alerts_active` | `environment`, `severity` |
| `alerta_alerts_ingested_total` | `source`, `outcome` |
| `alerta_ingest_delay_seconds` (histogram) | `source` |
| `alerta_watchdog_age_seconds` | `source`, `alertmanager`, `watchdog` |
| `alerta_heartbeats_expired`, `alerta_heartbeats_received_total` | – |
| `alerta_alertmanager_sync_total` | `alertmanager`, `outcome` |
| `alerta_auth_logins_total` | `outcome`, `reason` |
| `alerta_auth_lockouts_total` | – |
| `alerta_sessions_active`, `alerta_accounts_temporary` | – |
| `alerta_audit_chain_ok`, `alerta_audit_chain_orphaned` | – |
| `alerta_retention_deleted_total` | – |

Dochodzić mogą **nowe metryki** i nowe **wartości** etykiet (np. nowy `outcome`). Do istniejącej metryki **nie
dochodzą nowe etykiety** – psułoby to agregacje w regułach i dashboardach (`sum by (…)`) – potrzebny podział = nowa
metryka. Metryki Spring Boot / JVM / Hikari (`http_server_requests_seconds`, `jvm_*`, `hikaricp_*`) należą do
bibliotek; zmieniamy je tylko razem z dashboardem i regułami i opisujemy w „Co nowego”.

### 2.4 Logi

- Format: zwykły tekst na konsolę albo **ECS JSON** (`logs.consoleFormat: ecs`, plik `logs.file`).
- Pola ECS, na których opierają się SIEM i ELK: zdarzenia audytu (`event.category: audit`, `event.action`,
  `event.outcome`, `actor.type`, `actor.name`, `target.type` …), kotwica łańcucha audytu (`event.action:
  audit.anchor`, `audit.chain.seq`, `audit.chain.hash`, `audit.chain.audit_id`), linia żądania HTTP
  (`http.request.method`, `url.path`, `http.response.status_code`, `event.duration_ms`, `client.ip`).
- **Nazwy akcji audytu** (pełna lista: instrukcja wdrożenia, 9.1) – nowe mogą dochodzić, istniejące nie zmieniają
  nazw ani znaczenia.

Treść komunikatów tekstowych (`message`) **nie** jest kontraktem – nie budujcie na niej reguł, poza wymienionymi
w runbooku backupów (WARN `linked late`).

### 2.5 Uprawnienia i role

Uprawnienia `alerts:read`, `alerts:act`, `alerts:delete`, `blackouts:manage`, `heartbeats:manage`,
`notifications:manage`, `access:read`, `access:manage`, `audit:read` i role wbudowane (`VIEWER`, `OPERATOR`,
`MAINTAINER`, `ACCESS_ADMIN`, `AUDITOR`). Nowe uprawnienie w MINOR **nie jest** automatycznie dodawane do istniejących
ról bez wyraźnej informacji: jeśli trafia do roli wbudowanej (jak `notifications:manage` do `MAINTAINER` w 0.31),
opis wydania to mówi. Role własne administratora nigdy nie dostają uprawnień same.

### 2.6 Narzędzie `alerta-admin`

Polecenia `create-admin`, `reset-password`, `unlock`, `list-admins`, `verify-audit` – argumenty i wyniki
(`OK`, `MATCHES`, `TRUNCATED`, `DIFFERENT`, `BROKEN`, `INCOMPLETE`), na których opiera się runbook.

## 3. Co **nie** jest kontraktem

- **API konsoli** (`/api/v1/…` poza ingestem): służy przeglądarce i zmienia się razem z nią. Skrypty powinny
  korzystać tylko z API dla nadawców.
- **Schemat bazy** – tabele, kolumny, indeksy. Dostęp tylko przez aplikację (wyjątki: kroki runbooka backupów).
  Kolumna może zostać nieużywana (np. `label_definitions.required` po 0.56.1).
- **Wygląd i teksty UI**, kolejność kolumn listy, adresy stron konsoli (poza linkami w mailach, które działają dalej).
- **Kolumny CSV** raportów i eksportu – dokładamy na końcu, nie usuwamy bez potrzeby, ale bez gwarancji.
- Wewnętrzne mechanizmy zgodności z poprzednią wersją (opisane w kodzie jako „previous version”).

## 4. Zmiany w 1.x – jak

| Zmiana | Jak |
|---|---|
| Nowy klucz konfiguracji / value Helma | z wartością domyślną zachowującą dotychczasowe działanie |
| Zmiana nazwy klucza | stary klucz działa do 2.0, przy starcie WARN „deprecated – użyj …” |
| Usunięcie klucza / pola API / metryki | tylko w 2.0; w 1.x najpierw oznaczenie jako przestarzałe |
| Nowe pole w API / nowy kod błędu | w MINOR; nadawcy ignorują nieznane pola |
| Migracja bazy | tylko dodawanie; usunięcie / zmiana nazwy kolumny w dwóch wydaniach (zasada replik) |

Obecnie przestarzałe (działa do 2.0): pojedynczy `alerta.integrations.alertmanager` (`alertmanager:` w Helmie) obok
listy `alertmanagers` – przy obu jednocześnie WARN; docelowo każdy Alertmanager w liście z własną nazwą.

## 5. Aktualizacja i wycofanie

- **Rolling update** (repliki 2+) jest gwarantowany z **poprzedniego wydania** (np. 1.3.x → 1.4.0): stara i nowa
  wersja działają razem na tym samym schemacie.
- **Przeskok o kilka wydań** (np. 1.1 → 1.4): migracje przechodzą po kolei, ale stare pody mogą nie działać na nowym
  schemacie – zrób to z krótką przerwą (backend do 0 replik, potem nowa wersja) albo przejdź po kolei.
- **Wycofanie** o jedno wydanie (obraz poprzedniej wersji) działa bez odtwarzania bazy – migracje tylko dodają.
  Dalej wstecz – tylko z kopią sprzed aktualizacji (runbook backupów, 2.3).
- Kopia przed każdą aktualizacją – runbook backupów, 2.3.

## 6. Wsparcie

Wspierana jest **najnowsza wersja 1.x**. Poprawki trafiają do kolejnego wydania, nie są przenoszone do starszych.
Aktualizujcie regularnie; każde wydanie ma w „Co nowego” (strona *O aplikacji* i GitHub Release) sekcję zmian
dla administratorów (`admin: true`), także wymaganych działań.

## 7. Przegląd kontraktu przed 1.0

Wynik przeglądu (2026-10-02, zamknięty 2026-10-03):

- [x] Pojedynczy `alertmanager:` zostaje jako przestarzały do 2.0 (rozdział 4).
- [x] Każdy klucz `values.yaml` Helma opisany w instrukcji wdrożenia (4.10, PL/EN).
- [x] Lista akcji audytu dla SIEM w instrukcji wdrożenia (9.1).
- [x] Metryki, dashboard i reguły spójne (PR #101, promtool).
- [x] API ingestu udokumentowane (`docs/ingest-api.md`, instrukcja 8.6).
