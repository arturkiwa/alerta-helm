# Wdrożenie na Kubernetes

Kustomize: `base/` + `overlays/test/` (klaster testowy, `alerta.artbit.com.pl`). Namespace: `alerta-next`.

## Przepływ ruchu

```
klient ──HTTPS──► zewnętrzny LB (TLS, certyfikat) ──HTTP──► worker:30087 (NodePort)
   ──► Istio gateway (Gateway API, pod alerta-next-gateway-istio)
   ──► frontend (nginx: SPA + proxy /api) ──► backend (Spring Boot) ──► PostgreSQL (StatefulSet, ceph-block)
```

## Konfiguracja zewnętrznego LB

| Co | Wartość |
|---|---|
| Cel | workery `10.0.0.111`, `10.0.0.112`, `10.0.0.113` (każdy przyjmuje ruch, `externalTrafficPolicy: Cluster`) |
| Ruch aplikacji | **HTTP na port `30087`**, z zachowanym nagłówkiem `Host: alerta.artbit.com.pl` |
| Health check | **HTTP `GET /healthz/ready` na port `30088`** → `200` |
| Nagłówki od LB | `X-Forwarded-For` z adresem klienta (gateway ufa jednemu hopowi) |
| Zalecane na LB | HSTS (`Strict-Transport-Security: max-age=31536000`), przekierowanie 80→443, usunięcie nagłówka `server` |
| Timeouty | Bez krótkiego limitu odczytu: od fazy 2 UI używa SSE (długie połączenia). Proponowane ≥ 1 h lub wyłączony idle timeout dla tego hosta |

`X-Forwarded-Proto: https` ustawia HTTPRoute (TLS zawsze kończy się na LB).

## Pierwsze wdrożenie

```sh
cd deploy/k8s
# 1. Sekrety spoza gita (hasło bazy losowane w klastrze; pull secret do cr.artbit.com.pl)
REGISTRY_DOCKERCONFIG=/ścieżka/do/config.json ./create-secrets.sh
# 2. Manifesty
kubectl apply -k overlays/test
```

## Pierwszy administrator i odzyskiwanie dostępu

Aplikacja nie tworzy żadnego konta sama. Pierwszego administratora (i każde awaryjne odzyskanie dostępu) robi się
poleceniem `alerta-admin` w podzie backendu – hasło jednorazowe pojawia się tylko w terminalu wywołującego:

```sh
kubectl -n alerta-next exec deploy/alerta-next-backend -- alerta-admin create-admin <login> <Imię Nazwisko>
kubectl -n alerta-next exec deploy/alerta-next-backend -- alerta-admin reset-password <login>
kubectl -n alerta-next exec deploy/alerta-next-backend -- alerta-admin unlock <login>
kubectl -n alerta-next exec deploy/alerta-next-backend -- alerta-admin list-admins
```

Każde wywołanie jest w dzienniku audytu (aktor `SYSTEM/cli`). Polecenie uruchamia drugą, małą JVM obok serwera –
stąd limit pamięci backendu 1,5 GiB.

## Konfiguracja

Zachowanie backendu ustawia się w **`base/config/application.yml`**. Kustomize robi z niego ConfigMapę
`alerta-next-backend-config-<hash>`, zamontowaną jako `/etc/alerta/application.yml`. Zmiana treści zmienia nazwę
ConfigMapy, więc ArgoCD sam restartuje backend. Nadpisania dla jednego środowiska: `overlays/<env>/config/environment.yml`.
Błędna wartość zatrzymuje start z nazwą klucza w logu (np. `alerta.auth.local.mode`).

| Klucz | Domyślnie | Znaczenie |
|---|---|---|
| `alerta.auth.local.mode` | `ENABLED` | `ENABLED` / `BREAK_GLASS_ONLY` (tylko konta z `break-glass-users`) / `DISABLED`. **Celowo tylko tutaj, nie w UI.** |
| `alerta.auth.local.break-glass-users` | `[]` | Konta lokalne dozwolone w trybie `BREAK_GLASS_ONLY` |
| `alerta.session.idle-privileged` / `idle-standard` / `absolute` | `15m` / `8h` / `12h` | Limity sesji |
| `alerta.login.*` | 5 prób, 15 min ×2, maks. 1 h; 20 prób / 15 min z IP | Blokady logowania |
| `alerta.passwords.*` | 12 / 16 / 128 | Długość haseł kont lokalnych (zwykłe / administracyjne / maks.) |
| `alerta.accounts.temporary-max-validity` | `180d` | Najdłuższa ważność konta tymczasowego |
| `alerta.links.allowed-hosts` | `[]` (brak linków) | Hosty, do których mogą prowadzić linki z alertów do narzędzi (Grafana, Kibana; *Etykiety → Linki do narzędzi*) i linki zmian z ArgoCD / CI: dokładne nazwy albo `*.example.com`, tylko https |
| `alerta.accounts.inactive-disable-after` | puste (wyłączone) | Np. `90d` (min. `30d`): konto lokalne nieużywane tak długo jest wyłączane (bez SSO, kiosku, kont awaryjnych i ostatniego administratora dostępu) |
| `alerta.environments.classes` | PROD 400, PREPROD 90, UAT 30, TEST 30, DEV 14 | Klasy środowisk i domyślna retencja alertów (dni) |
| `logging.structured.format.console` | `ecs` | Logi JSON (Elastic Common Schema) dla ELK |
| `logging.level.io.alertanext.http` | `INFO` | Linia na każde żądanie HTTP; `WARN` wyłącza |
| `logging.level.io.alertanext.audit` | `INFO` | Zdarzenia audytu w logu (dla SIEM) |

Parametry bazy to zmienne środowiskowe w `base/backend.yaml`: `DB_URL`, `DB_USER`, `DB_PASSWORD` (Secret), `DB_SCHEMA`,
`DB_POOL_SIZE`, `DB_CONNECTION_TIMEOUT_MS`, `DB_MIGRATE`, `DB_MIGRATION_USER`, `DB_MIGRATION_PASSWORD`.

## Logi

Backend pisze JSON (ECS) na stdout – do zebrania przez ELK. Każde żądanie: metoda, ścieżka, status, czas, `user.name`,
`client.ip`, `request.id`. Ten sam `request.id` (nadawany przez nginx) jest w logach nginx, w logu backendu i w dzienniku
audytu – jedno żądanie da się prześledzić od przeglądarki do bazy. Zdarzenia audytu są też w logu (`event.category: audit`).
Nigdy nie są logowane treści żądań, cookie, nagłówki autoryzacji ani hasła (sprawdza to test). Błąd nieoczekiwany:
pełny ślad w logu, użytkownik dostaje tylko `requestId` do zgłoszenia.

## Metryki

Backend wystawia `/actuator/prometheus` na porcie `8081` (nigdy przez gateway). Poza metrykami JVM/HTTP/puli połączeń:
`alerta_auth_logins_total{outcome,reason}`, `alerta_auth_lockouts_total`, `alerta_sessions_active`,
`alerta_accounts_temporary`, `alerta_alerts_active{environment,severity}`, `alerta_alerts_ingested_total{source,outcome}`,
`alerta_watchdog_age_seconds{source}`, `alerta_audit_chain_ok` (ostatnie sprawdzenie łańcucha skrótów audytu: 1 / 0 / -1 = jeszcze nie),
`alerta_ingest_delay_seconds{source}` (histogram: od startu podanego przez
źródło do dotarcia nowego wystąpienia), `alerta_alertmanager_sync_total{outcome}`, `alerta_retention_deleted_total`
(bez nazw użytkowników ani pojedynczych alertów w etykietach). Żeby Prometheus spoza namespace'u mógł je zbierać,
dołącz komponent **`components/prometheus-scrape`** (adnotacje `prometheus.io/*` na podzie backendu – job
`kubernetes-pods` – i na Service metryk, NetworkPolicy z namespace'u
Prometheusa – ustaw etykietę w `network-policy.yaml`, wyjątek mTLS i reguła AuthorizationPolicy tylko dla portu 8081; opcjonalnie `servicemonitor.yaml`
dla Prometheus Operatora):

```yaml
# overlays/<env>/kustomization.yaml
components:
  - ../../components/prometheus-scrape
```

Metryki samej bramy Istio (port 15020, pod ma już adnotacje) – komponent **`components/gateway-metrics`**
(NetworkPolicy z namespace'u Prometheusa; brama jest poza mesh, więc bez wyjątków mTLS).

## Baza zewnętrzna

Komponent **`components/external-database`** usuwa lokalny StatefulSet PostgreSQL i ustawia połączenie do bazy
zewnętrznej: TLS z weryfikacją certyfikatu i nazwy hosta (`sslmode=verify-full`, CA z Secret `alerta-next-db-ca`),
schemat zamiast osobnej bazy (`DB_SCHEMA`, musi istnieć), osobne konto z prawami DDL do migracji (klucze
`migration-username` / `migration-password` w Secret `alerta-next-db`) oraz egress do adresów bazy. Jeśli migracje ma
wykonywać DBA: `DB_MIGRATE=false` i kolejne pliki `backend/src/main/resources/db/migration/V*.sql` (zwykły SQL);
backend przy starcie tylko sprawdza, czy schemat zgadza się z kodem.

## Alertmanager (centralny)

**1. W Alerta Next:** załóż środowiska i ustaw im warunki (Środowiska → edycja → „Które alerty należą do środowiska”,
np. `cluster = portal-prod`, `environment = Production, PROD`). Alert niepasujący do żadnego środowiska trafia do
kwarantanny (widok „Kwarantanna” dla administratorów dostępu); po dopisaniu warunków przechodzi na miejsce sam.
Następnie Klucze API → nowy klucz dla Alertmanagera (wszystkie środowiska albo wybrane).

**2. W Alertmanagerze** (dodatkowy receiver; `continue: true` zostawia dotychczasowe powiadomienia bez zmian):

```yaml
route:
  routes:
    - receiver: alerta-next
      continue: true
      group_wait: 10s
      group_interval: 1m
    - receiver: alerta-next          # Watchdog jako „tętno” całej ścieżki alertów
      matchers: [alertname="Watchdog"]
      repeat_interval: 1m
      continue: true
receivers:
  - name: alerta-next
    webhook_configs:
      - url: https://alerta.artbit.com.pl/api/v1/ingest/alertmanager
        send_resolved: true
        http_config:
          authorization:
            type: Bearer
            credentials_file: /etc/alertmanager/secrets/alerta-next-token   # klucz ank_… z Alerta Next
```

Klucz może wysyłać alerty tylko dla swoich środowisk (inne są odrzucane i liczone w metryce). `Watchdog` nie trafia na
listę alertów – zapisywany jest tylko czas jego nadejścia (`alerta_watchdog_age_seconds`).

**3. Wyciszenia z konsoli** (opcjonalnie): w `overlays/<env>/config/environment.yml`

```yaml
alerta:
  integrations:
    alertmanager:
      url: https://alertmanager.monitoring.svc:9093
      # ca-file: /etc/alerta/ca/internal-ca.crt     # komponent internal-ca; albo insecure-skip-verify: true (tylko świadomie)
```

plus logowanie (jeśli Alertmanager go wymaga) w Secret `alerta-next-alertmanager`: klucz `token` (Bearer) albo
`username` + `password` (basic auth; na teście tworzy go `deploy/test-monitoring/alertmanager-auth.sh`) i komponent
**`components/alertmanager`** (NetworkPolicy do Alertmanagera – ustaw namespace/adres). Każde wyciszenie tworzone
z konsoli zawiera etykiety środowiska alertu (nie wyciszy nic w innych środowiskach); zdjąć można tylko wyciszenie
obejmujące wyłącznie środowiska, na których użytkownik obsługuje alerty. Stan wyciszeń jest odczytywany z Alertmanagera
co 30 s (także wyciszenia założone bezpośrednio w Alertmanagerze).

**4. Reguły alertów dla Prometheusa** (monitoring samej aplikacji):

```yaml
# Metryki liczone z bazy (alerta_watchdog_age_seconds, alerta_alerts_active, alerta_heartbeats_expired …) zgłasza każda
# replika – w regułach bierz jedną wartość: max without (pod, instance) (…), inaczej każdy pod podnosi osobny alert.
- alert: AlertaNextWatchdogMissing       # zepsuta ścieżka Prometheus → Alertmanager → Alerta Next
  expr: max without (pod, instance) (alerta_watchdog_age_seconds) > 600 or absent(alerta_watchdog_age_seconds)
  for: 5m
- alert: AlertaNextDown                  # żadna replika (przy 2+ replikach jedna niedziałająca to ostrzeżenie)
  expr: (sum(up{job=~".*alerta-next.*"}) or vector(0)) < 1
  for: 5m
- alert: AlertaNextAlertPathSlow         # ścieżka działa, ale wolno (kolejka AM, ewaluacja reguł); liczone per replika –
  expr: |                                # tu sumujemy; opóźnienie obejmuje `for:` reguł, stąd próg 15 min
    histogram_quantile(0.5, sum by (le, source) (rate(alerta_ingest_delay_seconds_bucket[30m]))) > 900
    and sum by (source) (increase(alerta_ingest_delay_seconds_count[30m])) >= 5
  for: 15m
- alert: AlertaNextAuditChainBroken      # nocne sprawdzenie łańcucha skrótów audytu (alerta-admin verify-audit)
  expr: max without (pod, instance) (alerta_audit_chain_ok) == 0
- alert: AlertaNextAlertmanagerSyncFailing
  expr: increase(alerta_alertmanager_sync_total{outcome="failure"}[15m]) > 5
```

## Logowanie przez SSO (OpenID Connect)

Standardowe OIDC – działa z każdym dostawcą (Keycloak, Entra ID, ADFS); wszystko, co zależy od wdrożenia, jest w
konfiguracji. Adresy endpointów i klucze aplikacja pobiera sama z `<issuer>/.well-known/openid-configuration` (przy
pierwszym logowaniu – niedostępny dostawca nie blokuje startu). Komponent **`components/sso`** (NetworkPolicy do
dostawcy + sekret klienta z Secretu `alerta-next-oidc`, klucz `client-secret`; ustaw adres w `network-policy.yaml`),
a w `config/environment.yml`:

```yaml
alerta:
  auth:
    oidc:
      enabled: true
      issuer: https://sso.example.com/realms/example
      client-id: alerta-next
      claims:                      # nazwy pól w tokenie (domyślne jak w Keycloaku)
        username: preferred_username
        display-name: name
        email: email
        groups: groups             # lista grup – w Keycloaku mapper „Group Membership” (bez pełnej ścieżki)
      required-acr: []             # np. poziom z MFA – logowanie bez niego odrzucane
      label: "Zaloguj przez SSO"
      ca-file: /etc/alerta/ca/internal-ca.crt   # z components/internal-ca, gdy certyfikat dostawcy jest z firmowego CA
    local:
      mode: BREAK_GLASS_ONLY       # konta lokalne tylko awaryjnie
      break-glass-users: [admin.awaryjny]
```

U dostawcy: klient poufny (confidential) `alerta-next` z przepływem Authorization Code, adres powrotu
`https://<host>/api/v1/auth/oidc/callback`, adres po wylogowaniu `https://<host>/login*`, pole `groups` w tokenie ID.

Działanie: konto zakładane przy pierwszym logowaniu (bez dostępu), wiązane z `sub` dostawcy; login zajęty przez konto
lokalne = odmowa (nigdy scalanie). Grupa w Alercie z ustawioną „Grupą w domenie” ma członków tylko z tokenu – liczone
przy każdym logowaniu (zdjęcie z grupy AD = utrata dostępu od następnego logowania). Wylogowanie kończy też sesję SSO.
Wszystko w audycie (`auth.login` z `method: sso` i listą grup z tokenu – pomaga ustawić nazwy grup).

## Firmowe CA (TLS do integracji)

Obrazy nie zawierają firmowego CA. Komponent **`components/internal-ca`** montuje ConfigMapę `alerta-next-ca` w
`/etc/alerta/ca` (certyfikat CA jest publiczny – Secret nie jest potrzebny). W overlayu:

```yaml
components:
  - ../../components/internal-ca
configMapGenerator:
  - name: alerta-next-ca
    files:
      - internal-ca.crt        # PEM, może zawierać kilka certyfikatów (główny + pośrednie)
```

i w `config/environment.yml` dla każdej integracji (nazwa hosta dalej sprawdzana; zaufane są też domyślne CA JVM):

```yaml
alerta:
  integrations:
    alertmanager:
      ca-file: /etc/alerta/ca/internal-ca.crt
```

Ten sam plik weryfikuje bazę: `DB_URL=…?sslmode=verify-full&sslrootcert=/etc/alerta/ca/internal-ca.crt`. ConfigMapa ma
stałą nazwę (bez hasha) – po podmianie certyfikatu zrestartuj backend (np. nowym wdrożeniem). Bez `configMapGenerator`
w overlayu `kustomize build` kończy się błędem. Awaryjnie, gdy CA jeszcze nie ma: `insecure-skip-verify: true` przy
integracji (szyfrowanie bez weryfikacji – ostrzeżenie w logu i na stronie „Stan systemu”; przechwycone mogą być dane
logowania do integracji) – tylko tymczasowo.

## Retencja alertów

Codziennie o 02:30 (`alerta.retention-cron`) usuwane są zamknięte i rozwiązane alerty starsze niż retencja środowiska
(wartość w UI albo domyślna dla klasy z `alerta.environments.classes`); kwarantanna – 7 dni. Porcjami po 1000 wierszy,
na jednej replice (blokada w PostgreSQL). Aktywne alerty nie są usuwane nigdy.

## Nowa wersja aplikacji

Dwie gałęzie: `main` = wydania (linia 1.0.x), `dev` = rozwój następnej wersji. **Klaster testowy śledzi `dev`**
(aplikacja ArgoCD `alerta-next`, `targetRevision: dev`).

- **Merge do `dev`** (funkcja): po zielonym CI `.github/workflows/dev-images.yml` buduje i skanuje oba obrazy, wypycha
  je na Docker Hub jako `<następna wersja>-dev.<commit>` i `dev`, wpisuje tag i digest do
  `overlays/test/kustomization.yaml` na `dev` (commit „Dev images …”) – ArgoCD wdraża.
- **Merge do `main` z nową wersją = wydanie** (`.github/workflows/release.yml`): obrazy `X.Y.Z` na Docker Hub, commit
  „Release X.Y.Z”, tag `vX.Y.Z`, GitHub Release. Overlayu testowego nie zmienia. Merge bez nowej wersji niczego nie
  wydaje. Nic nie uruchamia się ręcznie.

Obrazy są przypięte **po digeście**: w klastrze działa dokładnie to, co zostało zbudowane i przetestowane.
Tagów wersji nie nadpisujemy (każda zmiana to nowa wersja); tylko `dev` wskazuje zawsze najnowszy obraz rozwojowy.

## ArgoCD

- Ścieżka aplikacji: `deploy/k8s/overlays/test`.
- Sekrety `alerta-next-db` i `alerta-next-registry` **nie są w gicie**: utwórz je `create-secrets.sh` przed pierwszą synchronizacją.
  Docelowo Sealed Secrets / External Secrets.
- Włącz **Server-Side Diff** (`argocd.argoproj.io/compare-options: ServerSideDiff=true`). Kubernetes dopisuje
  `status` do `volumeClaimTemplates` StatefulSetu, a klasyczny diff pokazuje to jako wieczne OutOfSync.
- Nie włączaj `prune` dla sekretów tworzonych ręcznie (nie są w manifestach, więc ArgoCD ich nie usunie).

## Zabezpieczenia

- **Pod Security `restricted`** na namespace: wszystkie pody nie-root, `readOnlyRootFilesystem`, `drop ALL`,
  `seccomp RuntimeDefault`, bez tokenów ServiceAccount. Gatewayowi Istio brakuje seccompu w szablonie, więc uzupełnia
  go ConfigMap `alerta-next-gateway-options` (`infrastructure.parametersRef`).
- **NetworkPolicy (Cilium, egzekwowane)**: domyślnie deny w obie strony, dozwolone tylko
  LB → gateway → frontend → backend → baza, DNS i gateway → istiod. Blokowany jest też dostęp do metadanych
  chmury (`169.254.169.254`). DNS przez nodelocaldns wymaga `CiliumNetworkPolicy` (`toEntities: host`), bo zwykła
  NetworkPolicy nie opisze tożsamości `host`.
- **Istio ambient**: `PeerAuthentication STRICT` i `AuthorizationPolicy` po tożsamości ServiceAccount
  (gateway → frontend → backend → baza) – egzekwowane i sprawdzone.
- Port zarządzania backendu (`8081`: health, metryki) nie jest w Service i nie da się go wystawić przez gateway.
- Inne nazwy hosta niż `alerta.artbit.com.pl` → 404 na gatewayu.

## Znane problemy klastra testowego

1. **Istio ambient a Cilium – naprawione 2026-09-23.** `istio-cni-node` był 0/6, bo Cilium z `cni-exclusive=true`
   usuwał wtyczkę istio-cni z konfiguracji CNI. Zmienione w ConfigMapie `kube-system/cilium-config`
   (`cni-exclusive: "false"`) + restart DaemonSetu `cilium`. **Trwała poprawka musi trafić do kubespraya**
   (zmienna `cilium_cni_exclusive: false`) – inaczej następny przebieg kubespraya przywróci `true`. Uwaga: wartości
   Helm release'u `cilium` nadal mówią `cni.exclusive: true` – `helm upgrade --reuse-values` też by to cofnęło.
   Zweryfikowane: wszystkie pody `alerta-next` i `chc` w meshu; mTLS z tożsamościami SPIFFE
   (gateway → frontend → backend → baza); pod z obcą tożsamością odrzucony przez AuthorizationPolicy mimo
   przepuszczenia przez NetworkPolicy.
2. Dwie StorageClass oznaczone jako domyślne (`ceph-block` i `local-path`). Manifesty podają `ceph-block` jawnie.
3. Backend przy pierwszym starcie restartuje się, dopóki baza się nie zainicjalizuje (~1 min). Później stabilnie.
4. Na klastrze testowym działa testowy Prometheus (`deploy/test-monitoring`, poza Argo). W `overlays/test` włączone są
   `alertmanager`, `gateway-metrics` i `prometheus-scrape`.
