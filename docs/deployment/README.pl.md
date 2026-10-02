# Alerta Next – instrukcja wdrożenia

[English version](README.md)

Ta instrukcja prowadzi od zera do działającej Alerty Next, bez zgadywania. Ma trzy części:

1. [Czym jest Alerta Next](#1-czym-jest-alerta-next) – co robi, co zbiera i jak.
2. Instalacja na dwa sposoby:
   - [Szybki start z Docker Compose](#3-szybki-start-docker-compose) – cały stos z przykładowymi alertami na jednej
     maszynie, żeby zobaczyć, co to jest (10 minut).
   - [Kubernetes z jawnymi manifestami](#4-kubernetes-jawne-manifesty) – prosta, kompletna instalacja do
     wypróbowania w klastrze.
   - [Helm chart](#410-alternatywa-helm-chart) – to samo, sparametryzowane.
3. Informacje referencyjne: [sekrety](#5-sekrety), [baza danych (w klastrze lub zewnętrzna)](#6-baza-danych),
   [konfiguracja](#7-konfiguracja), [podłączenie nadawców alertów](#8-podłączenie-nadawców-alertów),
   [utrzymanie](#9-utrzymanie), [przed produkcją](#10-przed-produkcją).

Obie instalacje służą do **oceny i pokazów**. Sekrety są celowo w jawnych plikach (łatwo zacząć); na produkcji
bierze się je z własnego magazynu sekretów – sekcja [5](#5-sekrety) wymienia każdy z nich.

---

## 1. Czym jest Alerta Next

Alerta Next to **konsola alertów**: jedno miejsce, w którym dyżurni widzą, co jest zepsute, kto się tym zajmuje i co
się działo. Sama niczego nie mierzy – systemy monitoringu (Prometheus z Alertmanagerem, Zabbix, skrypty …) wykrywają
problemy i **wysyłają** do niej alerty.

### Co zbiera i jak

| Źródło | Jak | Co przychodzi |
|---|---|---|
| **Prometheus / Alertmanager** | webhook Alertmanagera wywołuje `POST /api/v1/ingest/alertmanager` | każdy alert z tras skierowanych do Alerty Next i jego rozwiązanie |
| **Dowolny inny nadawca** (Zabbix, skrypty, cron) | `POST /api/v1/ingest/alerts` – ten sam format alertu ([docs/ingest-api.md](../ingest-api.md)) | alerty i ich rozwiązanie; opcjonalnie wygasają, gdy nadawca zamilknie |
| **Heartbeaty** („czy to jeszcze żyje?”) | zadanie regularnie wywołuje `POST /api/v1/ingest/heartbeat` | jeśli wywołania ustaną, Alerta Next sama zgłasza alert |
| **Zmiany** (wdrożenia z ArgoCD, CI) | narzędzie wdrożeniowe wywołuje `POST /api/v1/ingest/changes` | co, gdzie i kto wdrożył – obok alertów środowiska, nie jako alert |

Wszystko jest **wysyłane** do Alerty Next – ona nigdy nie odpytuje Waszych systemów ani się z nimi nie łączy.
Jedyne połączenie wychodzące jest opcjonalne: do API Alertmanagera, żeby z konsoli zakładać i zdejmować wyciszenia.

Każdy nadawca uwierzytelnia się **kluczem API**, który może wysyłać alerty tylko dla wybranych **środowisk**.

### Co robi z alertami
- **Środowiska**: każdy alert trafia do środowiska (PROD, TEST …) według **warunków na jego etykietach**
  (np. `cluster = prod-1`). Alert niepasujący do żadnego środowiska trafia do **kwarantanny** – nic nie ginie,
  administrator go widzi i poprawia warunki. Okno środowiska pokazuje przed zapisem, co warunki zabiorą innym
  środowiskom; pomyłkę naprawia *Środowiska → Przelicz przypisania…* (aktywne alerty i – do wyboru – zakończone
  z ostatnich 7/30/90 dni wracają tam, gdzie wskazują warunki; zakończone nigdy do kwarantanny).
- **Deduplikacja**: jeden alert na fingerprint (z Alertmanagera albo wyliczony z etykiet); powtórzenia go
  aktualizują, powrót po rozwiązaniu to nowe wystąpienie tego samego alertu. Krótkie „okno uspokojenia” (domyślnie
  5 min) nie pozwala, by alerty gasnące i wracające co kilka minut zaśmiecały historię.
- **Konsola**: lista na żywo (odświeża się sama), filtry, widoki wspólne i osobiste, szczegóły z całą historią,
  notatki, potwierdzanie (z timeoutem), zamykanie, akcje grupowe, eksport CSV.
- **Wyciszenia** w Alertmanagerze z konsoli; **okna serwisowe** per środowisko.
- **Raporty**: czasy reakcji (MTTA/MTTR), najczęstsze i najdłuższe alerty, alerty niestabilne (flapping).
- **Dostęp**: użytkownicy, grupy, role per środowisko; konta lokalne i/lub logowanie jednokrotne (OpenID Connect).
- **Dziennik audytu** każdej zmiany i każdej akcji na alercie.

### Co przechowuje
Wszystko w **PostgreSQL**: alerty i ich historię (zdarzenia, notatki), użytkowników, grupy, role, klucze API (tylko
skrót), sesje, dziennik audytu. Alerty są przechowywane według klasy środowiska (PROD 400 dni, TEST 30 …,
konfigurowalne); dziennik audytu jest tylko do dopisywania.

### Architektura

```
 przeglądarka ──HTTPS──▶ [TLS: ingress / load balancer] ──▶ frontend (nginx, :8080)
                                                               │  UI i /api pod jednym adresem
 Alertmanager, skrypty ──HTTPS── (ten sam adres) ──────────────┤
                                                               ▼
                                                          backend (Spring Boot, :8080 API, :8081 health+metryki)
                                                               │                        │ (opcjonalnie)
                                                               ▼                        ▼
                                                          PostgreSQL              API Alertmanagera :9093 (wyciszenia)
```

| Składnik | Obraz | Port | Uwagi |
|---|---|---|---|
| frontend | `arturkiwa/alerta-next-frontend` | 8080 (HTTP) | interfejs WWW; przekazuje `/api` do backendu |
| backend | `arturkiwa/alerta-next-backend` | 8080 API, 8081 health+metryki | bezstanowy, 2+ repliki; zawiera narzędzie `alerta-admin` |
| baza | `postgres` 18 | 5432 | testowane z PostgreSQL 18 |

**Bezpieczeństwo w skrócie:** przeglądarka dostaje tylko cookie sesji (`HttpOnly; Secure; SameSite=Strict`) –
żadnych tokenów; ochrona CSRF; ścisła polityka CSP; hasła haszowane Argon2; blokada po nieudanych logowaniach; klucze
API przechowywane jako skróty i ograniczone do środowisk; każda zmiana w audycie. **Interfejs musi być dostępny przez
HTTPS** (cookie sesji jest `Secure`) – poza szybkim startem na `http://localhost`, który to wyłącza.

### Zasoby (punkt wyjścia)

| | CPU (request) | Pamięć request / limit |
|---|---|---|
| backend (każda replika) | 250m | 768 Mi / 1536 Mi |
| frontend (każda replika) | 50m | 64 Mi / 256 Mi |
| PostgreSQL (wbudowany) | 100m | 256 Mi / 1 Gi, dysk 10 Gi |

Test obciążeniowy ~10× intensywnej awarii (10 alertów/s, 50 otwartych konsol) działał na 2 backendach i jednej
bazie; najpierw CPU potrzebuje baza (zob. `load/README.md`).

---

## 2. Pojęcia potrzebne przy instalacji

| Pojęcie | Znaczenie |
|---|---|
| **Pierwszy administrator** | Alerta Next nigdy sama nie zakłada konta. Pierwsze zakłada się narzędziem `alerta-admin` w kontenerze backendu; wypisuje ono hasło jednorazowe do zmiany przy pierwszym logowaniu. |
| **Środowisko** | Grupa alertów (np. PROD) z **warunkami na etykietach**, które decydują, które alerty do niej należą. |
| **Kwarantanna** | Alerty niepasujące do żadnego środowiska. Widoczne dla administratorów dostępu (widok „Kwarantanna”); rozwiązane i zamknięte znikają po 7 dniach. Śmieci z błędnych reguł administrator dostępu może **usunąć** (zaznaczone albo wszystkie pasujące do filtru) – każde usunięcie w audycie z etykietami alertu. Alerty środowisk nie dają się usunąć (to zapis obsługi). |
| **Klucz API** | Tym nadawca (Alertmanager, skrypt) wysyła alerty; ograniczony do wybranych środowisk; pokazywany tylko raz przy utworzeniu. |
| **Role** (wbudowane) | `VIEWER` (Obserwator) – widzi alerty; `OPERATOR` – dodatkowo potwierdza, zamyka, dodaje notatki, wycisza; `MAINTAINER` (Opiekun) – dodatkowo okna serwisowe i heartbeaty; `ACCESS_ADMIN` (Administrator dostępu) – użytkownicy, grupy, role, środowiska, klucze API, etykiety, widoki; `AUDITOR` (Audytor) – dziennik audytu. Rolę przypisuje się **per środowisko** (albo na wszystkie). |

Pierwszy administrator dostaje tylko `ACCESS_ADMIN` (zarządzanie dostępem). **Żeby widzieć alerty, przypisz sobie
rolę, np. Operator** – robią to kroki poniżej.

Zasady haseł: co najmniej 12 znaków (16 dla kont z rolami administracyjnymi), hasło nie może zawierać loginu ani słowa
zakazanego (`alerta.passwords.forbidden-words` – dopisz nazwy firmy i systemów) ani być znanym, popularnym hasłem.
Hasło jednorazowe (nowe konto, reset) jest ważne 72 godziny.

---

## 3. Szybki start (Docker Compose)

Cały stos na jednej maszynie: Alerta Next + PostgreSQL + (opcjonalnie) Prometheus z przykładowymi alertami +
Alertmanager. Wszystko jest w [`deploy/quickstart`](../../deploy/quickstart).

### 3.1 Czego potrzebujesz
- Docker Engine z **Compose v2** (działa `docker compose version`). Linux, macOS albo Windows (Docker Desktop).
- Około 2 GB wolnej pamięci.
- Wolne porty na maszynie: **8080** (interfejs); 9090 i 9093 (Prometheus i Alertmanager, tylko na `127.0.0.1`).
- Dostęp do Docker Hub (obrazy `arturkiwa/alerta-next-*`, `postgres`, `prom/prometheus`, `prom/alertmanager`).

### 3.2 Pobierz pliki
Sklonuj repozytorium albo skopiuj sam katalog `deploy/quickstart` (razem z ukrytym plikiem `.env`):

```sh
git clone https://github.com/arturkiwa/alerta-next.git
cd alerta-next/deploy/quickstart
ls -a      # .env  alertmanager/  docker-compose.yml  prometheus/
```

### 3.3 Przejrzyj ustawienia (opcjonalnie)
Wszystkie ustawienia są w **`.env`**:

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `BACKEND_IMAGE`, `FRONTEND_IMAGE` | `docker.io/arturkiwa/alerta-next-…:0.13.0` | obrazy; oba w tej samej wersji |
| `ALERTA_PORT` | `8080` | interfejs pod `http://localhost:8080` |
| `DB_URL`, `DB_USER` | wbudowana baza | zmieniasz tylko dla własnego PostgreSQL ([3.12](#312-wyłączanie-części-stosu)) |
| `DB_PASSWORD` | `quickstart-change-me` | hasło wbudowanej bazy – zmień **przed pierwszym uruchomieniem** |
| `COMPOSE_PROFILES` | `monitoring` | części opcjonalne; puste = sama Alerta Next ([3.12](#312-wyłączanie-części-stosu)) |
| `ALERTMANAGER_URL` | `http://alertmanager:9093` | API Alertmanagera do wyciszeń; puste = brak przycisku „Wycisz” |

### 3.4 Uruchom

```sh
docker compose up -d
docker compose ps          # db (healthy), backend, frontend, prometheus, alertmanager: running
```

Przy pierwszym starcie backend potrzebuje ~30–60 s (zakłada schemat bazy). Jest gotowy, gdy odpowiada:

```sh
curl http://localhost:8080/api/v1/ping
# {"status":"ok"}
```

### 3.5 Załóż pierwszego administratora

```sh
docker compose exec backend alerta-admin create-admin admin "Administrator"
```

Wynik kończy się tak:

```
Created access administrator admin
One-time password: Xxxxxx-Xxxxxx-Xxxxxx-Xxxxxx
It must be changed at the first login.
```

Otwórz **http://localhost:8080**, zaloguj się jako `admin` tym hasłem jednorazowym i ustaw własne hasło
(≥ 16 znaków, nie może zawierać „admin”).

> Zgubione? `docker compose exec backend alerta-admin reset-password admin` wypisze nowe hasło jednorazowe.

### 3.6 Nadaj sobie dostęp do alertów
1. **Administracja → Użytkownicy** → kliknij **admin**.
2. **Przypisz rolę** → Rola **Operator** → włącz **Wszystkie środowiska** → **Dodaj**.
3. Odśwież stronę (F5) – uprawnienia działają od razu; w menu pojawiają się strony alertów.

### 3.7 Załóż środowiska przykładowych alertów
Przykładowe alerty mają etykietę `cluster` = `demo-prod` albo `demo-test`.

1. **Administracja → Środowiska → Nowe środowisko**: Kod `PROD`, Nazwa `Demo produkcja`, Klasa `PROD` → **Zapisz**.
2. Na liście kliknij **Edytuj** (ołówek) przy PROD → **Dodaj warunek**: Etykieta `cluster`, Wartości `demo-prod` →
   **Zapisz**.
3. To samo dla `TEST` (Klasa `TEST`) z `cluster` = `demo-test`.

Zrób to **przed** krokiem 3.9 – alerty, które dotrą wcześniej, trafią do kwarantanny (do właściwego środowiska
przejdą przy następnym powtórzeniu, zob. [3.10](#310-zobacz-jak-działa)).

### 3.8 Utwórz klucz API dla Alertmanagera
**Administracja → Klucze API → Nowy klucz**: Nazwa `Alertmanager`, włącz **Wszystkie środowiska** → **Utwórz**.
Klucz (`ank_…`) jest pokazywany **tylko raz** – skopiuj go.

### 3.9 Przekaż klucz Alertmanagerowi
Zastąp zawartość pliku `alertmanager/secrets/alerta-token` kluczem (jedna linia, nic więcej) i zrestartuj
Alertmanagera, żeby od razu wysłał wszystko:

```sh
echo 'ank_twoj_klucz' > alertmanager/secrets/alerta-token
docker compose restart alertmanager
```

### 3.10 Zobacz, jak działa
- **Alerty** (http://localhost:8080): w ciągu minuty cztery przykładowe alerty – dwa w PROD, dwa w TEST.
- **Administracja → Stan systemu**: „Watchdog” odebrany przed chwilą = cała ścieżka Prometheus → Alertmanager →
  Alerta Next działa.
- Kliknij alert → **Wycisz w Alertmanagerze…** → wyciszenie pojawi się w Alertmanagerze (http://localhost:9093).
- Prometheus: http://localhost:9090 (zakładka *Alerts*).
- Jeśli część alertów jest w kwarantannie: popraw warunki środowisk (3.7) – aktywne alerty przejdą od razu.

### 3.11 Wyślij własny alert (dowolny nadawca)

```sh
curl -fsS -X POST http://localhost:8080/api/v1/ingest/alerts \
  -H "Authorization: Bearer ank_twoj_klucz" -H "Content-Type: application/json" \
  -d '{"source":"test","alerts":[{"labels":{"alertname":"MojPierwszyAlert","severity":"warning","cluster":"demo-test"},
       "annotations":{"summary":"Wysłany curlem"}}]}'
# {"created":1,...}   – rozwiązanie: to samo z "status":"resolved"
```

### 3.12 Wyłączanie części stosu
| Chcesz | Zrób |
|---|---|
| **Samą Alertę Next** (bez Prometheusa i Alertmanagera) | w `.env`: `COMPOSE_PROFILES=` (puste) i `ALERTMANAGER_URL=` (puste); potem `docker compose up -d --remove-orphans`. Jeśli już działają: `docker compose rm -sf prometheus alertmanager`. |
| **Własny Alertmanager** zamiast przykładowego | jak wyżej oraz `ALERTMANAGER_URL=http://<twoj-alertmanager>:9093` (musi być osiągalny z kontenera backendu); w swoim Alertmanagerze odbiorca jak w [8.1](#81-prometheus--alertmanager) z adresem `http://<ta-maszyna>:8080/api/v1/ingest/alertmanager` |
| **Przykładowy Alertmanager, ale własny Prometheus** | w swoim Prometheusie `alerting.alertmanagers` → `<ta-maszyna>:9093` (port jest przypięty do 127.0.0.1 – w `docker-compose.yml` zmień `127.0.0.1:9093:9093` na `9093:9093`); usuń albo opróżnij `prometheus/rules.yml` |
| **Bez przykładowych alertów**, ale z Prometheusem | opróżnij `prometheus/rules.yml` (zostaw regułę Watchdog, jeśli chcesz sprawdzania ścieżki), `docker compose restart prometheus` |
| **Własny PostgreSQL** zamiast wbudowanego | w `.env`: `DB_URL=jdbc:postgresql://<host>:5432/<baza>`, `DB_USER`, `DB_PASSWORD`; uruchom bez wbudowanej bazy: `docker compose up -d --no-deps frontend backend` (czego wymaga baza – [6.2](#62-zewnętrzny-lub-centralny-postgresql)) |
| **Bez wyciszeń** z konsoli | `ALERTMANAGER_URL=` (puste), `docker compose up -d` |

### 3.13 Zatrzymanie, uruchomienie, usunięcie

```sh
docker compose stop           # zatrzymaj, zostaw wszystko
docker compose start          # uruchom ponownie
docker compose down           # usuń kontenery, ZOSTAW dane (wolumen)
docker compose down -v        # usuń kontenery I dane
```

### 3.14 Gdy coś nie działa
| Objaw | Przyczyna / rozwiązanie |
|---|---|
| nieznane polecenie `docker compose` | zainstaluj Compose v2 (Docker Desktop go ma; na Linuksie pakiet `docker-compose-plugin`) |
| backend się restartuje, w logu „password authentication failed” | `DB_PASSWORD` zmienione po utworzeniu bazy – `docker compose down -v` i start od nowa (kasuje dane) |
| interfejs działa, ale brak stron z alertami | konto nie ma jeszcze roli z alertami (3.6) |
| alerty nie przychodzą | `docker compose logs alertmanager` – `401`: zły klucz w `alertmanager/secrets/alerta-token`; klucz musi być w jednej linii |
| alerty tylko w kwarantannie | warunki środowisk nie pasują do etykiet (3.7) |
| brak przycisku „Wycisz” | `ALERTMANAGER_URL` puste albo backend nie może się z nim połączyć |

Logi: `docker compose logs -f backend` (linia na każde żądanie HTTP, błędy z identyfikatorem żądania).

---

## 4. Kubernetes (jawne manifesty)

Prosta, kompletna instalacja w zwykłym YAML-u (bez Helma, bez kustomize) w
[`deploy/kubernetes`](../../deploy/kubernetes): Alerta Next w 2 replikach, PostgreSQL w klastrze, Ingress NGINX,
polityki sieciowe. Sekrety są w jawnym pliku – do testu. Na produkcję zob. [sekcję 5](#5-sekrety) i
[10](#10-przed-produkcją).

### 4.1 Czego potrzebujesz
- Klaster Kubernetes (1.27 lub nowszy) i `kubectl` z prawem do utworzenia namespace i obiektów w nim.
- **Kontroler ingress**. Manifest używa klasy `nginx` (NGINX Ingress Controller); inny kontroler: zmień
  `ingressClassName` i usuń adnotacje `nginx.ingress.kubernetes.io/*` (ich znaczenie: treść do 5 MB, długie
  połączenia aktualizacji na żywo bez buforowania – ustaw to samo w swoim kontrolerze). **F5 NGINX Ingress
  Controller** (adnotacje `nginx.org/*`, klasa zwykle `nginx`): `nginx.org/client-max-body-size: "5m"`,
  `nginx.org/proxy-read-timeout: "3600s"`, `nginx.org/proxy-buffering: "False"`. Bez tych ustawień aktualizacje
  na żywo urywają się albo przychodzą z opóźnieniem (konsola pokazuje „offline”).
- **Domyślną StorageClass** (baza prosi o wolumen 10 Gi) albo podaj ją jawnie (4.6).
- Nazwę DNS dla Alerty Next wskazującą na ingress oraz HTTPS: TLS na ingressie albo na load balancerze przed nim.
- Dostęp do Docker Hub (albo skopiuj obrazy do swojego rejestru, 4.6).

### 4.2 Pliki
Stosowane w tej kolejności (nazwy plików tak się sortują):

| Plik | Zawartość | Do zmiany |
|---|---|---|
| `00-namespace.yaml` | namespace `alerta-next`, Pod Security `restricted` | – |
| `01-secrets.yaml` | **sekrety jawnym tekstem**: login do bazy, login do Alertmanagera | **tak**: hasło bazy |
| `10-config.yaml` | konfiguracja backendu (`application.yml` + Twój `environment.yml`) | opcjonalnie: adres Alertmanagera |
| `20-database.yaml` | PostgreSQL 18, 1 pod, 10 Gi | opcjonalnie: klasa dysków; pomiń plik przy bazie zewnętrznej ([6.2](#62-zewnętrzny-lub-centralny-postgresql)) |
| `30-backend.yaml` | backend, 2 repliki, Service, budżet zakłóceń | opcjonalnie: obraz/rejestr |
| `40-frontend.yaml` | frontend, 2 repliki, Service, budżet zakłóceń | opcjonalnie: obraz/rejestr |
| `50-ingress.yaml` | Ingress | **tak**: host |
| `60-network-policies.yaml` | domyślnie wszystko zamknięte + dozwolone ścieżki | – |

### 4.3 Krok po kroku

**1. Pobierz pliki**

```sh
git clone https://github.com/arturkiwa/alerta-next.git
cd alerta-next/deploy/kubernetes
```

**2. Ustaw hasło bazy** w `01-secrets.yaml` (Secret `alerta-next-db`, klucz `password`). Losowe:

```sh
openssl rand -base64 24 | tr -d '/+='
```

Wbudowany PostgreSQL przyjmuje je **tylko przy zakładaniu danych** (pierwszy start). Późniejsza zmiana wymaga zmiany
także w PostgreSQL (`ALTER ROLE`) – albo usunięcia wolumenu i startu od nowa.

**3. Ustaw nazwę hosta** w `50-ingress.yaml` (`host: alerta.example.com`). TLS:
- kończony **na ingressie** – dodaj pod `spec:` (z Secretem `alerta-tls` zawierającym Twój certyfikat albo
  wystawionym przez cert-managera):
  ```yaml
    tls:
      - hosts: [alerta.example.com]
        secretName: alerta-tls
  ```
- kończony **na load balancerze przed nim** (wysyła HTTP do ingressu) – zostaw plik bez zmian.

**4. (Opcjonalnie) wyciszenia z konsoli:** w `10-config.yaml` → `environment.yml` ustaw
`alerta.integrations.alertmanager.url` (np. `http://alertmanager.monitoring.svc:9093`); jeśli Alertmanager wymaga
logowania, uzupełnij `alerta-next-alertmanager` w `01-secrets.yaml` (`token` albo `username` + `password`).

**5. Zastosuj**

```sh
kubectl apply -f .
kubectl -n alerta-next rollout status statefulset/alerta-next-db
kubectl -n alerta-next rollout status deploy/alerta-next-backend     # 1–2 min przy pierwszym starcie
kubectl -n alerta-next rollout status deploy/alerta-next-frontend
kubectl -n alerta-next get pods                                      # wszystkie Running, READY 1/1
```

**6. Sprawdź z zewnątrz**

```sh
curl https://alerta.example.com/api/v1/ping
# {"status":"ok"}
```

**7. Pierwszy administrator**

```sh
kubectl -n alerta-next exec deploy/alerta-next-backend -- alerta-admin create-admin admin "Administrator"
```

Wypisze hasło jednorazowe (tylko w Twoim terminalu). Otwórz `https://alerta.example.com`, zaloguj się jako `admin`,
ustaw hasło. Dalej tak samo jak w szybkim starcie:
[3.6 rola dla siebie](#36-nadaj-sobie-dostęp-do-alertów), [3.7 środowiska](#37-załóż-środowiska-przykładowych-alertów)
(z warunkami dla **Twoich** etykiet), [3.8 klucz API](#38-utwórz-klucz-api-dla-alertmanagera).

**8. Skieruj do niej swojego Alertmanagera** – odbiorca z [8.1](#81-prometheus--alertmanager) z adresem
`https://alerta.example.com/api/v1/ingest/alertmanager`.

### 4.4 HTTPS jest wymagany
Cookie sesji jest `Secure`: przeglądarki trzymają je tylko przez HTTPS. Bez HTTPS logowanie „nic nie robi”. Wyłącznie
do testu przez zwykłe HTTP: w `30-backend.yaml` ustaw `SESSION_COOKIE_SECURE` na `"false"` i zastosuj ponownie.

### 4.4a Adresy klientów za ingressem (`TRUSTED_PROXIES`)
Limity logowania na adres i audyt potrzebują prawdziwego adresu klienta. Frontend wierzy nagłówkowi `X-Forwarded-For`
tylko od pośredników wymienionych w `TRUSTED_PROXIES` (zmienna kontenera frontendu, adresy / CIDR-y po przecinku): pody
kontrolera ingress i load balancer przed nimi, jeśli przekazuje adres klienta. Puste (domyślnie) = liczy się tylko
bezpośrednie połączenie – bezpiecznie (nikt nie podrobi adresu), ale każdy klient wygląda jak ingress. Ustaw w
`40-frontend.yaml` (Helm: `frontend.trustedProxies`), np. sieć podów kontrolera ingress: `10.233.64.0/18`. Sprawdzenie:
*Administracja → Dziennik audytu* pokazuje adresy użytkowników, a nie ingressu.

**Puste `TRUSTED_PROXIES` na produkcji to problem, nie tylko kosmetyka audytu:** limit nieudanych logowań na adres
(`alerta.login.ip-max-failures`, 20 w 15 min) staje się wspólny dla wszystkich – kilka pomyłek różnych osób blokuje
logowanie całej organizacji na kwadrans.

**Load balancer (np. F5) przed ingressem** – adres klienta musi przejść przez cały łańcuch:
1. load balancer dopisuje `X-Forwarded-For` (profil HTTP),
2. kontroler ingress go **przekazuje** zamiast nadpisać – ingress-nginx (społecznościowy), w jego ConfigMapie:
   `use-forwarded-headers: "true"`, `proxy-real-ip-cidr: <adresy LB>`; F5 NGINX Ingress Controller:
   `set-real-ip-from: <adresy LB>`, `real-ip-header: X-Forwarded-For`, `real-ip-recursive: "True"`,
3. `TRUSTED_PROXIES` = sieć podów kontrolera ingress **i** adresy load balancera.

Load balancer, który nie przekazuje adresu klienta: wpisz tylko sieć podów – audyt pokaże adres load balancera,
a limit logowań na adres pozostanie wspólny (blokada konta po nieudanych próbach działa niezależnie od adresu).
Sprawdzenie łańcucha: zaloguj się raz błędnym hasłem – wpis w dzienniku audytu ma adres Twojej stacji.

### 4.5 Zmiany konfiguracji
Edytuj `10-config.yaml` (swoje ustawienia w `environment.yml`), potem:

```sh
kubectl apply -f 10-config.yaml
kubectl -n alerta-next rollout restart deploy/alerta-next-backend
```

Błędna wartość zatrzymuje backend przy starcie z nazwą klucza w logu (`kubectl -n alerta-next logs
deploy/alerta-next-backend`); działające repliki pracują dalej, dopóki nowe nie będą gotowe.

### 4.6 Własny rejestr, klasa dysków
- **Obrazy z własnego rejestru**: zmień `image:` w `30-backend.yaml`, `40-frontend.yaml`, `20-database.yaml`.
  Rejestr z logowaniem wymaga Secretu do pobierania obrazów i odwołania w obu Deploymentach:
  ```sh
  kubectl -n alerta-next create secret docker-registry registry-login \
    --docker-server=<rejestr> --docker-username=<login> --docker-password=<hasło>
  ```
  ```yaml
      # w 30-backend.yaml i 40-frontend.yaml, pod spec.template.spec:
      imagePullSecrets:
        - name: registry-login
  ```
- **Klasa dysków**: w `20-database.yaml` pod `volumeClaimTemplates[0].spec` dodaj `storageClassName: <nazwa>`.

### 4.7 Polityki sieciowe
`60-network-policies.yaml` zamyka wszystko i pozwala tylko na: DNS (port 53), ingress → frontend (8080),
frontend → backend (8080), backend → baza (5432), dowolne źródło → metryki backendu (8081), backend → Alertmanager
(9093). Jeśli klaster nie egzekwuje NetworkPolicy, są po prostu ignorowane. Baza zewnętrzna: dodaj regułę wyjścia,
zob. [6.2](#62-zewnętrzny-lub-centralny-postgresql).

### 4.8 Aktualizacja i usunięcie
- **Aktualizacja**: zmień tagi obrazów (backend i frontend na tę samą wersję) i `kubectl apply -f .`. Pody są
  wymieniane po jednym, bez przerwy; migracje bazy uruchamiają się przy starcie i są zgodne wstecz z poprzednią wersją.
- **Usunięcie**: `kubectl delete namespace alerta-next` (usuwa wszystko, łącznie z wolumenem bazy).

### 4.9 Gdy coś nie działa
| Objaw | Przyczyna / rozwiązanie |
|---|---|
| `ImagePullBackOff` | nazwa obrazu/rejestr albo Secret do pobierania (4.6) |
| pod bazy w `Pending` | brak domyślnej StorageClass – ustaw ją (4.6) |
| pody się restartują, w logu „UnknownHostException” / „host not found” | DNS zablokowany przez polityki sieciowe w Twoim klastrze – sprawdź, czy `allow-dns` pasuje do Twojego DNS |
| w logu backendu „password authentication failed” | hasło w `01-secrets.yaml` różni się od tego, z którym założono bazę (4.3 krok 2) |
| logowanie „nie trzyma” | brak HTTPS (4.4) |
| w logu Alertmanagera `401` | zły klucz API w `credentials_file` Alertmanagera |
| alerty w kwarantannie | warunki środowisk nie pasują do etykiet |

### 4.10 Alternatywa: Helm chart
Ta sama instalacja jako sparametryzowany chart w [`deploy/helm/alerta-next`](../../deploy/helm/alerta-next)
(Helm 3). Każdy parametr jest opisany w jego [`values.yaml`](../../deploy/helm/alerta-next/values.yaml); trzy gotowe
przykłady są w `examples/`. Domyślnie chart tworzy Secrety z Twojego pliku values (jawnym tekstem – dobre na pokaz);
na produkcji własne Secrety albo HashiCorp Vault przez Secrets Store CSI Driver (`secrets.mode`,
[5.1](#51-helm-skąd-biorą-się-sekrety-secretsmode)). Polityki sieciowe są domyślnie
wyłączone (`networkPolicy.enabled`).

**1. Twój plik values** (zacznij od `examples/values-demo.yaml`):

```yaml
database:
  password: <długie losowe hasło>      # openssl rand -base64 24 | tr -d '/+='
ingress:
  host: alerta.example.com
```

**2. Instalacja**

```sh
helm install alerta-next deploy/helm/alerta-next -n alerta-next --create-namespace -f my-values.yaml
kubectl -n alerta-next rollout status deploy/alerta-next-backend
```

Jeśli brakuje czegoś wymaganego (hasło, host …), chart odmawia z czytelnym komunikatem.

**3. Pierwszy administrator i dalej** – dokładnie jak w 4.3 od kroku 6 (polecenia wypisuje też `helm install`).

**Własne CA** (dla Alertmanagera, SSO i bazy przez TLS) – jeden ze sposobów:

```sh
helm upgrade --install alerta-next deploy/helm/alerta-next -n alerta-next -f my-values.yaml \
  --set-file internalCA.certificate=./ca.crt                 # plik obok Ciebie
```
- wklejony w plik values jako `internalCA.certificate: |` (certyfikat CA jest publiczny; to droga dla GitOps),
- albo ConfigMapa założona wcześniej (`kubectl -n alerta-next create configmap my-ca --from-file=ca.crt=./ca.crt`)
  i `internalCA.existingConfigMap: my-ca`.

Chart montuje go jako `/etc/alerta/ca/ca.crt` i używa dla API Alertmanagera, SSO oraz – przy
`database.external.sslMode: verify-full` – bazy.

**Najczęściej używane parametry**

| Parametr | Znaczenie |
|---|---|
| `image.registry`, `image.tag`, `image.pullSecrets` | własny rejestr, wersja (puste = `appVersion` charta), Secret do pobierania |
| `secrets.mode` (`values` / `existing` / `csi`) | skąd biorą się sekrety ([5.1](#51-helm-skąd-biorą-się-sekrety-secretsmode)) |
| `database.password` / `database.existingSecret` / `secrets.csi.vault.*` | login do bazy |
| `database.internal.enabled`, `.storageClass`, `.size` | PostgreSQL w klastrze i jego wolumen |
| `database.internal.backup.enabled`, `.schedule`, `.keep`, `.storageClass`, `.size` | nocny zrzut bazy wbudowanej na osobny wolumen ([runbook](backup-runbook.pl.md)) |
| `database.external.host`, `.port`, `.name`, `.sslMode` (albo `.url`), `database.schema`, `database.migrate` | baza zewnętrzna ([6.2](#62-zewnętrzny-lub-centralny-postgresql)) |
| `internalCA.*` | własne CA (wyżej) |
| `alertmanager.url`, `.token` / `.username`+`.password` / `.existingSecret` | wyciszenia z konsoli |
| `alertmanagers[]` (`name`, `url`, logowanie jak wyżej) | kolejne Alertmanagery ([8.2](#82-kilka-alertmanagerów)) |
| `oidc.enabled`, `.issuer`, `.clientId`, `.clientSecret` / `.existingSecret`, `.claims` | logowanie jednokrotne |
| `config` | dowolne ustawienie aplikacji ([sekcja 7](#7-konfiguracja)), wygrywa ze wszystkim |
| `mail.*` | raport dzienny e-mail: `smarthost`, `from`, `hello`, `requireTls`, `username` + hasło, `consoleUrl`, **`allowedDomains` (wymagane)** |
| `notifications.*` | powiadomienia e-mail według reguł: `enabled` (wymaga `mail.smarthost`), `batchWindow`, `minInterval` |
| `fullnameOverride` | nazwa bazowa obiektów (np. `alerta` → `alerta-backend`, `alerta-db`); pusta = nazwa instalacji |
| `ingress.host`, `.className`, `.annotations`, `.tls.*` | dostęp |
| `session.cookieSecure` | `false` tylko do testu przez zwykłe HTTP (4.4) |
| `frontend.trustedProxies` | pośrednicy, którym wierzymy w `X-Forwarded-For` (4.4a) |
| `backend.*`, `frontend.*` | repliki, zasoby, nodeSelector, tolerations, affinity, dodatkowe zmienne/wolumeny/sidecary |
| `logs.consoleFormat` (`text`/`ecs`), `logs.file.enabled` | format logów dla ELK |
| `metrics.podAnnotations`, `metrics.serviceMonitor.*` | zbieranie metryk przez Prometheusa |
| `networkPolicy.*` | domyślnie wyłączone |

**Zmiany i aktualizacje**: edytuj plik values i `helm upgrade alerta-next deploy/helm/alerta-next -n alerta-next
-f my-values.yaml` – backend sam się restartuje, gdy zmienia się jego konfiguracja, Secrety albo CA. Nowa wersja:
`--set image.tag=<wersja>` (albo nowszy chart). **Usunięcie**: `helm uninstall alerta-next -n alerta-next` zostawia
wolumen bazy (PVC `data-alerta-next-db-0`); `kubectl delete namespace alerta-next` usuwa wszystko.

---

## 5. Sekrety

Wszystkie sekrety, których używa Alerta Next. W pokazie pochodzą z `01-secrets.yaml`; na produkcji utwórz **te same
Secrety (nazwy i klucze)** swoimi narzędziami – HashiCorp Vault (Vault Agent / Vault Secrets Operator), External
Secrets Operator, Sealed Secrets, CI … Aplikacja czyta je jako zmienne środowiskowe; nie musi wiedzieć, skąd pochodzą.

| Secret | Klucz | Wymagany | Do czego | Zmienna środowiskowa |
|---|---|---|---|---|
| `alerta-next-db` | `username` | tak | login aplikacji do bazy (wbudowany PostgreSQL: także jego superużytkownik) | `DB_USER` |
| `alerta-next-db` | `password` | tak | jego hasło | `DB_PASSWORD` |
| `alerta-next-db` | `migration-username`, `migration-password` | nie | osobne konto do migracji schematu (baza zewnętrzna, [6.2](#62-zewnętrzny-lub-centralny-postgresql)) | `DB_MIGRATION_USER`, `DB_MIGRATION_PASSWORD` |
| `alerta-next-alertmanager` | `token` | nie | logowanie do API Alertmanagera (Bearer) – wyciszenia | `ALERTMANAGER_TOKEN` |
| `alerta-next-alertmanager` | `username`, `password` | nie | logowanie do API Alertmanagera (basic auth) – wyciszenia | `ALERTMANAGER_USERNAME`, `ALERTMANAGER_PASSWORD` |
| `alerta-next-oidc` | `client-secret` | tylko z SSO | sekret klienta OpenID Connect ([7](#7-konfiguracja)) | `OIDC_CLIENT_SECRET` |

Nie są sekretami aplikacji, ale będziesz mieć do czynienia z poufnym materiałem:
- **Klucze API** (`ank_…`) – tworzone w interfejsie, przechowywane tylko jako skrót; każdy nadawca trzyma swój (np.
  `credentials_file` Alertmanagera).
- **Hasła jednorazowe** z `alerta-admin` – tylko w terminalu osoby, która je wywołała.
- Twój **certyfikat TLS** – na ingressie / load balancerze.
- **Secret do pobierania obrazów** z prywatnego rejestru (4.6).

W ConfigMapie (`10-config.yaml`), obrazach ani logach nie ma nic poufnego (hasła nigdy nie trafiają do logów).

### 5.1 Helm: skąd biorą się sekrety (`secrets.mode`)

| `secrets.mode` | Sekrety pochodzą z | Do czego |
|---|---|---|
| `values` (domyślnie) | jawny tekst w Twoim pliku values (`database.password`, `alertmanager.token`, `oidc.clientSecret`); chart zakłada Secrety Kubernetes | pokazy, testy |
| `existing` | Secrety Kubernetes, które zakładasz sam (`database.existingSecret`, `alertmanager.existingSecret`, `oidc.existingSecret`), z kluczami z tabeli wyżej – ręcznie, Vault Secrets Operator, External Secrets … | produkcja z operatorem sekretów |
| `csi` | **HashiCorp Vault przez Secrets Store CSI Driver** – montowane jako pliki w podach, nigdy nie zapisywane jako Secrety Kubernetes | produkcja z Vault + CSI |

### 5.2 Vault z Secrets Store CSI Driver krok po kroku
W klastrze potrzebne są: [Secrets Store CSI Driver](https://secrets-store-csi-driver.sigs.k8s.io/) i
[provider Vault CSI](https://developer.hashicorp.com/vault/docs/platform/k8s/csi) (zwykle już są, jeśli klaster z nich
korzysta). W Vault: metoda logowania Kubernetes skonfigurowana dla tego klastra.

**1. Sprawdź ścieżkę logowania** metody Kubernetes tego klastra:

```sh
vault auth list          # wiersz z typem "kubernetes", np. "kubernetes/" albo "k8s-sandbox/" – nazwa bez "/"
```

**2. Zapisz sekrety** (KV v2 pod `secret/`; Twój mount i ścieżki mogą być inne):

```sh
vault kv put secret/alerta-next/db username=alerta password="$(openssl rand -base64 24 | tr -d '/+=')"
# opcjonalnie: vault kv put secret/alerta-next/alertmanager token=<token>
# z SSO: vault kv put secret/alerta-next/oidc client-secret=<sekret>
```

Przy bazie w klastrze hasło jest używane tylko przy zakładaniu danych (pierwszy start); późniejsza zmiana tylko razem
z `ALTER ROLE` w PostgreSQL.

**3. Polityka i rola** (zamień `kubernetes` na swoją ścieżkę; namespace i nazwę instalacji `alerta-next`, jeśli
masz inne):

```sh
vault policy write alerta-next - <<'POLICY'
path "secret/data/alerta-next/*" { capabilities = ["read"] }
POLICY
vault write auth/kubernetes/role/alerta-next \
  bound_service_account_names=alerta-next-backend,alerta-next-db \
  bound_service_account_namespaces=alerta-next \
  policies=alerta-next ttl=20m
```

ServiceAccounty to `<release>-backend` i `<release>-db` (ten drugi tylko z bazą w klastrze); przy nazwie instalacji
`alerta-next` dokładnie jak wyżej. Uwaga: nazwa instalacji bez „alerta-next” (np. `helm install alerta …`) daje
`alerta-alerta-next-backend` – jeśli rola w Vault ma już inne nazwy, ustaw je w values: `fullnameOverride: alerta`
→ `alerta-backend`, `alerta-db`. `helm install` też je wypisuje.

**4. Values** (z `examples/values-vault-csi.yaml`):

```yaml
secrets:
  mode: csi
  csi:
    vault:
      address: https://vault.example.com:8200
      authPath: kubernetes          # z kroku 1
      role: alerta-next             # z kroku 3
      objects:                      # nazwy po lewej są stałe; path/key = gdzie to jest w Vault (KV v2: …/data/…)
        DB_USER: { path: secret/data/alerta-next/db, key: username }
        DB_PASSWORD: { path: secret/data/alerta-next/db, key: password }
        # ALERTMANAGER_TOKEN: { path: secret/data/alerta-next/alertmanager, key: token }
        # OIDC_CLIENT_SECRET: { path: secret/data/alerta-next/oidc, key: client-secret }
```

Możliwe nazwy: `DB_USER`, `DB_PASSWORD` (wymagane), `DB_MIGRATION_USER`, `DB_MIGRATION_PASSWORD`,
`ALERTMANAGER_TOKEN` albo `ALERTMANAGER_USERNAME` + `ALERTMANAGER_PASSWORD`, `OIDC_CLIENT_SECRET` (wymagane z SSO).

**5. Instalacja** – `helm install …` jak w 4.10. Chart zakłada `SecretProviderClass` dla backendu (wszystkie obiekty)
i osobną dla bazy w klastrze (tylko `DB_USER`, `DB_PASSWORD`); wartości pojawiają się w podach jako pliki w
`/etc/alerta/secrets/`.

**Gdy coś nie działa.** Pody wiszą w `ContainerCreating`: `kubectl -n alerta-next describe pod <pod>` – zdarzenia
pokazują odpowiedź Vaulta: `permission denied` = polityka albo rola (krok 3: ServiceAccount, namespace, ścieżka
polityki z `/data/`); nie znaleziono sekretu lub klucza = `path` albo `key` w `objects`; błędy połączenia = `address`
albo CA Vaulta w konfiguracji providera Vault CSI (TLS do Vaulta robi provider, nie Alerta Next).

**Rotacja.** Backend czyta sekrety przy starcie. Po zmianie wartości w Vault zrestartuj go:
`kubectl -n alerta-next rollout restart deploy/alerta-next-backend`.

**Inny provider CSI** (AWS, Azure, GCP) albo własna `SecretProviderClass`: ustaw `secrets.csi.secretProviderClass`
na jej nazwę; musi dostarczać pliki nazwane jak obiekty wyżej.

---

## 6. Baza danych

### 6.1 Wbudowany PostgreSQL (w klastrze / compose)
Jeden PostgreSQL 18 z wolumenem 10 Gi, **bez wysokiej dostępności**. Kopie: w Helmie nocny zrzut na osobny wolumen
(`database.internal.backup.enabled: true`) – pełna procedura kopii i odtworzenia:
**[runbook](backup-runbook.pl.md)**. Ręczny zrzut:

```sh
kubectl -n alerta-next exec alerta-next-db-0 -- sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" -Fc alerta' > alerta-$(date +%F).dump
# compose: docker compose exec -T db pg_dump -U alerta -Fc alerta > alerta-$(date +%F).dump
```

Helm (login i hasło bazy są tam w plikach, nie w zmiennych; `<release>` – nazwa instalacji):

```sh
kubectl -n <ns> exec <release>-db-0 -- sh -c \
  'PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")" pg_dump -h 127.0.0.1 -U "$(cat "$POSTGRES_USER_FILE")" -Fc "$POSTGRES_DB"' \
  > alerta-$(date +%F).dump
```

Zrzut rób co najmniej **przed każdą aktualizacją** (nowa wersja może mieć migracje schematu). Odtworzenie – krok po
kroku w [runbooku](backup-runbook.pl.md#3-odtworzenie) (zabezpieczenie obecnego stanu, sesje, cofnięte uprawnienia).
Utracona baza oznacza utratę konfiguracji (środowiska, dostęp, klucze API, etykiety, widoki) i historii z audytem –
same alerty Alertmanager przyśle ponownie.

### 6.2 Zewnętrzny lub centralny PostgreSQL
Gdy organizacja utrzymuje PostgreSQL centralnie (administracja, kopie, HA) albo chcesz własny poza klastrem.

**Czego potrzeba od bazy**
- PostgreSQL **18** (wersja, z którą Alerta Next jest testowana), UTF-8. Żadne rozszerzenia nie są potrzebne.
- Połączenia: każda replika backendu otwiera do **20** (`DB_POOL_SIZE`). `max_connections` ≥ (repliki + 1) × 20 +
  kilka dla `alerta-admin` – przy 2 replikach: ≥ 70 dla Alerty Next.
- Aplikacja w trakcie działania nigdy nie zmienia schematu; **migracje** (Flyway,
  `backend/src/main/resources/db/migration`) uruchamiają się przy starcie – jeśli chcesz, osobnym kontem (niżej) –
  albo stosuje je DBA.
- Dostęp sieciowy z podów backendu do portu bazy; zalecany TLS.

**Wariant A – jedno konto (najprościej).** Dla DBA:

```sql
CREATE ROLE alerta LOGIN PASSWORD '<hasło>';
CREATE DATABASE alerta OWNER alerta ENCODING 'UTF8';
```

Alerta Next: `DB_URL=jdbc:postgresql://<host>:5432/alerta`, `DB_USER=alerta`, `DB_PASSWORD=<hasło>`.

**Wariant B – schemat we wspólnej bazie, osobne konto do migracji (najmniejsze uprawnienia).** Dla DBA:

```sql
-- w docelowej bazie, np. "monitoring"
CREATE ROLE alerta_owner LOGIN PASSWORD '<hasło właściciela>';   -- migracje (DDL), właściciel tabel
CREATE ROLE alerta_app   LOGIN PASSWORD '<hasło aplikacji>';     -- aplikacja w trakcie działania: tylko dane
CREATE SCHEMA alerta_next AUTHORIZATION alerta_owner;
GRANT USAGE ON SCHEMA alerta_next TO alerta_app;
ALTER DEFAULT PRIVILEGES FOR ROLE alerta_owner IN SCHEMA alerta_next
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO alerta_app;
ALTER DEFAULT PRIVILEGES FOR ROLE alerta_owner IN SCHEMA alerta_next
  GRANT USAGE, SELECT ON SEQUENCES TO alerta_app;
```

Alerta Next:

| Zmienna | Wartość |
|---|---|
| `DB_URL` | `jdbc:postgresql://<host>:5432/monitoring` |
| `DB_SCHEMA` | `alerta_next` |
| `DB_USER` / `DB_PASSWORD` | `alerta_app` (Secret `alerta-next-db`: `username`, `password`) |
| `DB_MIGRATION_USER` / `DB_MIGRATION_PASSWORD` | `alerta_owner` (Secret `alerta-next-db`: `migration-username`, `migration-password`) |

**Wariant C – migracje stosuje DBA.** Ustaw `DB_MIGRATE=false`; DBA stosuje pliki
`backend/src/main/resources/db/migration/V*.sql` w kolejności wersji (`V1`, `V2`, … – liczbowo) **przed** każdą
aktualizacją Alerty Next. Aplikacja przy starcie sprawdza, czy schemat się zgadza, i w przeciwnym razie nie startuje.

**TLS do bazy.** Dopisz do `DB_URL`: `?sslmode=verify-full&sslrootcert=/etc/alerta/db-ca/ca.crt` i podmontuj tam
certyfikat CA (niżej). `sslmode=require` szyfruje bez sprawdzania certyfikatu (niezalecane).

**W manifestach Kubernetes**
1. **Nie** stosuj `20-database.yaml` (usuń go z katalogu albo stosuj pozostałe pliki po kolei).
2. W `01-secrets.yaml` wpisz konto aplikacji (a dla wariantu B także `migration-username` / `migration-password`).
3. W `30-backend.yaml`, w `env:` kontenera `backend`, zmień `DB_URL` i dodaj to, czego wymaga Twój wariant:
   ```yaml
            - name: DB_URL
              value: jdbc:postgresql://db.example.internal:5432/monitoring?sslmode=verify-full&sslrootcert=/etc/alerta/db-ca/ca.crt
            - name: DB_SCHEMA
              value: alerta_next
            - name: DB_MIGRATION_USER
              valueFrom: { secretKeyRef: { name: alerta-next-db, key: migration-username } }
            - name: DB_MIGRATION_PASSWORD
              valueFrom: { secretKeyRef: { name: alerta-next-db, key: migration-password } }
   ```
   a dla TLS certyfikat CA (ConfigMap `alerta-next-db-ca` z kluczem `ca.crt`):
   ```yaml
          # w kontenerze "backend", obok istniejących volumeMounts:
            - name: db-ca
              mountPath: /etc/alerta/db-ca
              readOnly: true
      # pod spec.template.spec.volumes:
        - name: db-ca
          configMap: { name: alerta-next-db-ca }
   ```
   ```sh
   kubectl -n alerta-next create configmap alerta-next-db-ca --from-file=ca.crt=<twoj-ca.pem>
   ```
4. Pozwól backendowi połączyć się z bazą – dopisz do `60-network-policies.yaml`:
   ```yaml
   ---
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: backend-to-external-db
     namespace: alerta-next
   spec:
     podSelector:
       matchLabels:
         app.kubernetes.io/name: alerta-next-backend
     policyTypes: [Egress]
     egress:
       - to:
           - ipBlock: { cidr: 10.20.30.40/32 }    # adres Twojej bazy (albo zakres)
         ports:
           - { protocol: TCP, port: 5432 }
   ```

**W szybkim starcie**: `.env` → `DB_URL`, `DB_USER`, `DB_PASSWORD`; uruchom
`docker compose up -d --no-deps frontend backend` (wbudowana baza nie wystartuje).

### 6.3 Kopie zapasowe
Wbudowana baza: nocny zrzut z chartu + kopia poza klaster + kwartalna próba odtworzenia –
[runbook](backup-runbook.pl.md). Przy bazie centralnej kopie należą do DBA – Alerta Next nie wymaga niczego
szczególnego: spójny zrzut albo PITR bazy/schematu wystarczy do odtworzenia; po odtworzeniu obowiązują kroki 3.4–3.6
runbooka.

---

## 7. Konfiguracja

Dwa miejsca:
- **Zmienne środowiskowe** (dane połączeń i sekrety) – w `30-backend.yaml` / `.env`.
- **`application.yml`** (zachowanie) – w Kubernetes ConfigMapa w `10-config.yaml`: plik `application.yml` zawiera
  każde ustawienie z wartością domyślną i komentarzem; **swoje** zmiany wpisuj do `environment.yml` w tej samej
  ConfigMapie (wygrywa). Szybki start używa wartości domyślnych wbudowanych w obraz.

### Zmienne środowiskowe

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `DB_URL` | – | adres JDBC PostgreSQL |
| `DB_USER`, `DB_PASSWORD` | – | konto aplikacji (z Secretu) |
| `DB_SCHEMA` | `public` | schemat Alerty Next (musi istnieć) |
| `DB_POOL_SIZE` | `20` | połączenia na replikę backendu |
| `DB_CONNECTION_TIMEOUT_MS` | `10000` | czekanie na wolne połączenie |
| `DB_MIGRATE` | `true` | `false` = migracje stosuje DBA |
| `DB_MIGRATION_USER`, `DB_MIGRATION_PASSWORD` | konto aplikacji | konto do migracji |
| `SESSION_COOKIE_SECURE` | `true` | `false` tylko do testów przez zwykłe HTTP |
| `ALERTMANAGER_URL` | puste | API Alertmanagera do wyciszeń |
| `ALERTMANAGER_TOKEN` / `ALERTMANAGER_USERNAME` + `ALERTMANAGER_PASSWORD` | puste | logowanie do niego |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | puste | logowanie jednokrotne (z `alerta.auth.oidc.enabled: true`) |

### Najczęściej zmieniane ustawienia (`environment.yml`)

```yaml
alerta:
  auth:
    local:
      mode: ENABLED              # ENABLED | BREAK_GLASS_ONLY (tylko wymienione konta awaryjne) | DISABLED
      break-glass-users: []
    oidc:                        # logowanie jednokrotne z dowolnym dostawcą OpenID Connect (Keycloak, Entra ID …)
      enabled: false
      issuer: https://sso.example.com/realms/example
      client-id: alerta-next     # sekret: OIDC_CLIENT_SECRET
      claims: { username: preferred_username, display-name: name, email: email, groups: groups }
      # redirect-uri: https://alerta.example.com/api/v1/auth/oidc/callback
      #   domyślnie {baseUrl}/api/v1/auth/oidc/callback – adres z żądania. Gdy TLS kończy się przed ingressem (F5)
      #   i żądanie dociera jako http, SSO odrzuca redirect_uri: wpisz pełny adres https. Z niego bierze się też
      #   powrót po wylogowaniu (https://<adres>/login?reason=LOGGED_OUT). W kliencie Keycloak: Valid redirect URIs
      #   = ten adres, Valid post logout redirect URIs = https://<adres>/login*
  accounts:
    inactive-disable-after: 90d  # konto lokalne nieużywane tyle (od logowania, założenia, resetu hasła, włączenia)
                                 # jest wyłączane co godzinę; puste = nigdy, min. 30d. Bez kont SSO, kiosku,
                                 # awaryjnych i ostatniego administratora dostępu. Kto wypadnie: Przegląd dostępu
  integrations:
    alertmanager:
      url: http://alertmanager.monitoring.svc:9093
      ca-file: ""                # CA (PEM) dla TLS do Alertmanagera, jeśli potrzebne
  alerts:
    ack-timeout: 8h              # potwierdzenie wygasa po tym czasie (per środowisko w UI)
    resolve-grace: 5m            # „rozwiązany” liczy się, gdy alert tyle nie wróci
    highlight-new: 10m           # konsola wyróżnia nowy lub powracający alert przez ten czas; 0 = wyłączone
    watchdog-timeout: 5m         # brak Watchdoga (osobno dla Prometheusa i Alertmanagera) tak długo: WatchdogMissing
  passwords:
    forbidden-words: [alerta, nazwa-firmy, nazwa-systemu]  # słowa zakazane w hasłach (bez wielkości liter; lista zastępuje domyślną)
    one-time-validity: 72h       # ważność hasła jednorazowego (nowe konto, reset)
  session:
    idle-privileged: 30m         # limit bezczynności administratorów
    idle-standard: 8h            # limit bezczynności operatorów
  environments:
    classes:                     # klasy środowisk i domyślna retencja (dni)
      - { code: PROD, retention-days: 400 }
      - { code: TEST, retention-days: 30 }
```

Etykiety z znaczeniem (na górze szczegółów, wartości na liście alertów, szybkie filtry, grupowanie raportów, znaczniki na liście) i widoki
wspólne **ustawia się w interfejsie** (Administracja → Etykiety / Widoki), nie w konfiguracji.

Ważność: powszechna skala Critical / Error / Warning / Info – CRITICAL, ERROR, WARNING, INFORMATIONAL (plus NORMAL);
dowolne wartości etykiety mapuje `alerta.alerts.severity-aliases` (wbudowane: critical, error, err, warning, info,
informational, normal, ok; np. dla Zabbixa dopisz disaster → CRITICAL, high → ERROR, average → WARNING, information →
INFORMATIONAL – mapa podmienia się w całości). Wartość, której nie zna żaden alias, daje ważność UNKNOWN – *Stan
systemu → Nierozpoznane ważności* pokazuje takie wartości z ostatnich 30 dni, więc od razu widać, jaki alias dopisać.

Logowanie jednokrotne szczegółowo: [deploy/k8s/README.md](../../deploy/k8s/README.md) (sekcja „Logowanie przez SSO”).

### Raport dzienny e-mail

Każdy użytkownik z adresem e-mail może w *Profilu → Raport e-mail* włączyć codzienne podsumowanie: sam wybiera
środowiska (spośród tych, do których ma dostęp – sprawdzane przy każdej wysyłce), ważności i godzinę; „Wyślij próbny
raport” sprawdza od razu, czy poczta dochodzi. Serwer potrzebuje tylko przekaźnika SMTP – nazwy jak w Alertmanagerze:

```yaml
alerta:
  mail:
    from: alerta@example.com              # smtp_from
    hello: alerta.example.com             # smtp_hello
    smarthost: 10.1.2.3:25                 # smtp_smarthost HOST:PORT (465 = TLS od początku)
    require-tls: false                     # smtp_require_tls – STARTTLS wymagany (z CA z internalCA / ca-file)
    username: ""                           # pusto = przekaźnik bez logowania; z loginem hasło z MAIL_PASSWORD
    console-url: https://alerta.example.com   # linki w mailu (Helm: domyślnie https://<ingress.host>)
    allowed-domains: [example.com]        # WYMAGANE: jedyne domeny, na które może wyjść poczta
```

W Helmie sekcja `mail` w values (hasło: `mail.password` / `mail.existingSecret` / obiekt Vault `MAIL_PASSWORD`).
Bez `smarthost` raport nie jest oferowany. Wysyłka raz na klaster (przy wielu replikach).

**Tylko dozwolone domeny.** Z `smarthost` lista `allowed-domains` (Helm: `mail.allowedDomains`) jest obowiązkowa –
bez niej aplikacja nie wystartuje, a Helm odmówi renderowania. Domena musi się zgadzać dokładnie (wielkość liter bez
znaczenia); poddomeny tylko wpisane jawnie. Adres musi być zwykłym adresem (bez nazwy, cudzysłowów, drugiego `@`,
listy). Sprawdzenie jest w jednym miejscu, przez które przechodzi każda wiadomość – przy wysyłce, nie tylko przy
zapisie ustawień. Użytkownik z adresem spoza listy widzi w profilu, że raport jest niedostępny.

**Audyt wysyłki** (dziennik audytu i log dla SIEM): `mail.sent` – każda wysłana wiadomość (do kogo, jaki raport),
`mail.failed` – przekaźnik odrzucił, `mail.blocked` (wynik DENIED) – próba wysyłki na adres spoza listy
(powód: `domain-not-allowed` / `not-an-address`); nic wtedy nie wychodzi. Wpisy zostają, nawet gdy reszta operacji się
wycofa.

### Linki do narzędzi (Grafana, Kibana …)

W *Administracja → Etykiety → Linki do narzędzi* administrator dostępu definiuje przyciski w szczegółach alertu:
nazwa i adres z etykietami alertu, np. `https://grafana.example.com/d/abc?var-namespace={namespace}&var-pod={pod}`.
Przycisk pojawia się tylko przy alertach, które mają wszystkie użyte etykiety. Adres składa serwer: wartości są
kodowane (nie dodadzą parametru ani ścieżki), wartość w nazwie hosta (`https://grafana-{cluster}.example.com/…`) może
być tylko jednym członem nazwy DNS. Wyłącznie https i tylko do hostów z konfiguracji – bez niej linków nie da się
zdefiniować. Ta sama lista decyduje o linkach zmian z ArgoCD / CI (8.6):

```yaml
alerta:
  links:
    allowed-hosts: [grafana.example.com, "*.kibana.example.com"]   # dokładnie albo każdy host pod domeną
```

### Powiadomienia e-mail (zamiast odbiorców w Alertmanagerze)

Maile o alertach według reguł ustawianych w aplikacji (strona *Powiadomienia*, uprawnienie „Zarządzanie
powiadomieniami” – ma je rola Opiekun w swoich środowiskach). Reguła: środowiska, ważności, warunki na etykietach
(`team=db, dba`, `service!=web`), **grupy odbiorców**, przypomnienia (co 15 min … 24 h, dopóki nikt nie potwierdzi,
najwyżej N razy) i informacja o rozwiązaniu (tylko do tych, którzy dostali mail o alercie). Bez własnych szablonów
i plików – treść jest stała, wszystko od nadawców escapowane.

Włączenie **tylko w konfiguracji** (nigdy w UI) i tylko z pocztą (sekcja wyżej):

```yaml
alerta:
  notifications:
    enabled: true
    batch-window: 2m      # co przyjdzie dla jednej osoby w tym czasie, idzie jednym mailem
    min-interval: 5m      # najwyżej jeden mail na osobę tak często (reszta czeka na następny)
```

Helm: `notifications.enabled: true` (wymaga `mail.smarthost`), `notifications.batchWindow`, `notifications.minInterval`.

Zasady wysyłki: mail tylko do osoby, która **w chwili wysyłki** może czytać środowisko alertu, i tylko na dozwoloną
domenę; potwierdzony, zamknięty, wyciszony (także oknem serwisowym) alert nie powiadamia; alert wracający w ciągu
godziny po mailu o nim (niestabilny) – jedna informacja, potem cisza, a „Rozwiązany” dopiero gdy przez godzinę nie wróci; alerty, które już trwały przy tworzeniu (włączaniu) reguły, nie są wysyłane. Wysyłka raz na
klaster (przy wielu replikach każda osoba przez jedną z nich, rezerwowana tuż przed swoim mailem), ponawiana przy błędzie przekaźnika, poza transakcjami bazy (wolny przekaźnik nie trzyma
połączeń). Model „co najmniej raz”: jeśli replika padnie po przyjęciu maila przez przekaźnik, a przed zapisem wyniku,
mail pójdzie po 10 minutach drugi raz – nigdy nie ginie. Każdy mail w dzienniku audytu (`mail.sent`),
zmiany reguł jako `notification-rule.*`; kolejka i niewysłane w *Stanie systemu*.

**Godziny biurowe:** administrator dostępu ustawia je na stronie grupy (dni, od–do; strefa `mail.time-zone`), każdy
może w profilu wybrać „jak w moich grupach”, „zawsze mailem” albo własne godziny – jego wybór wygrywa. W godzinach
biurowych powiadomienia zostają tylko w konsoli (w *Stanie systemu* jako „godziny biurowe”); krytyczne i tak idą mailem,
chyba że ktoś wyłączy to w profilu.

**Przejście z Alertmanagera:** włączać środowisko po środowisku – najpierw reguła w Alercie równolegle z mailami
z Alertmanagera, po sprawdzeniu wyłączyć odbiorcę w Alertmanagerze. Awarie samej Alerty dalej zgłasza Alertmanager
(reguły `alerta-next.yml`, Watchdog).

---

## 8. Podłączenie nadawców alertów

### 8.1 Prometheus / Alertmanager
W konfiguracji Alertmanagera odbiorca z kluczem API **w pliku** (nie w samej konfiguracji) i **jedna trasa do Alerty
Next na początku drzewa**, która bierze wszystko:

```yaml
receivers:
  - name: alerta-next
    webhook_configs:
      - url: https://alerta.example.com/api/v1/ingest/alertmanager
        send_resolved: true               # wymagane: rozwiązania muszą docierać
        http_config:
          authorization:
            type: Bearer
            credentials_file: /etc/alertmanager/secrets/alerta-next-token   # klucz ank_…, jedna linia
route:
  receiver: <twój domyślny odbiorca>
  routes:
    - receiver: alerta-next               # pierwsza, bez warunków: każdy alert
      continue: true                      # dotychczasowe powiadomienia działają dalej
      group_by: ['...']                   # jedno powiadomienie na alert – bez opóźnienia grupowania w drodze do konsoli
      group_wait: 0s
      group_interval: 1m
      repeat_interval: 1m                 # to także tempo Watchdoga – poniżej alerta.alerts.watchdog-timeout (5 min)
```

Trasa do Alerty Next niczego nie musi rozróżniać: do którego środowiska należy alert, kto go widzi i co jest wyciszone
dla całego środowiska, rozstrzyga Alerta Next (środowiska z warunkami na etykietach, role, okna serwisowe). Reszta
drzewa tras zostaje tylko dla powiadomień (mail, czat, pager).

Zalecane w Prometheusie:
- `for:` w regułach progowych (i `keep_firing_for:` od Prometheusa 2.42) – mniej alertów, które zapalają się i gasną.
- Zawsze aktywna reguła **Watchdog** (`expr: vector(1)`, `alertname: Watchdog`) w **każdym** Prometheusie. Alerta Next
  trzyma osobnego Watchdoga dla każdego Prometheusa (rozróżnia je etykietami, np. `cluster`) i każdego Alertmanagera:
  strona *Stan systemu* pokazuje je wszystkie, a Watchdog, który milczy dłużej niż `alerta.alerts.watchdog-timeout`
  (5 min), otwiera alert **`WatchdogMissing`** – pojedynczy klaster, który zamilkł, nie ukryje się za pozostałymi.
- Etykiety decydujące o środowisku (np. `cluster`, `environment`) na każdym alercie – przez `external_labels`
  każdego Prometheusa.

`WatchdogMissing` niesie etykiety Watchdoga, więc trafia do środowiska, do którego one pasują. Gdy na jednym klastrze
jest kilka środowisk rozróżnianych po `namespace` (DEV1, DEV2 … na klastrze `dev`), Watchdog (bez namespace) nie
pasuje do żadnego z nich – trafi do kwarantanny. Załóż środowisko techniczne samego klastra, np. `DEV-KLASTER`
z jedynym warunkiem `cluster = dev`: środowiska z warunkiem na namespace są bardziej szczegółowe i zachowują swoje alerty.

### 8.2 Kilka Alertmanagerów
Alerta Next działa z jednym Alertmanagerem albo z kilkoma – np. po jednym na klaster. Klucze API **nie wskazują**
Alertmanagera – Alerta sama pyta każdy skonfigurowany:
- wyciszenie z konsoli trafia do każdego Alertmanagera, który ma alert (żaden – odmowa, bo nic by nie wyciszyło);
- okno serwisowe powstaje w każdym Alertmanagerze (wszystkie albo żaden);
- alert jest wyciszony, gdy wycisza go którykolwiek Alertmanager; niedziałający nie „odcisza” alertów, a alert, którego
  chwilowo nie ma żaden (rozwiązany), zachowuje ostatni znany stan;
- strona *Wyciszenia* pokazuje wszystkie z nazwą Alertmanagera; *Stan systemu* – ostatnią synchronizację każdego.

Kolejny Alertmanager krok po kroku:
1. Dopisz go do konfiguracji – w Helmie `alertmanagers:` w values (sekrety wg trybu, zob. `values.yaml`), albo
   w `environment.yml`:
   ```yaml
   alerta:
     integrations:
       alertmanagers:
         - name: waw                                   # [a-z][a-z0-9-]*, unikalna
           url: https://alertmanager.waw.example.com
           bearer-token: ${ALERTMANAGER_WAW_TOKEN:}    # albo username / password; także ca-file, timeout
   ```
   i zrestartuj backend. Błędna nazwa, brak adresu albo nazwa użyta dwa razy zatrzymują start z nazwą klucza w logu.
2. **Administracja → Klucze API → Nowy klucz** (najprościej: wszystkie środowiska) i przekaż klucz temu
   Alertmanagerowi (8.1). Środowiska istniejącego klucza zmienisz przyciskiem „Środowiska” – bez nowego klucza.

Starsza konfiguracja z pojedynczym `alertmanager:` (nazywanym „default”) nadal działa; obok listy `alertmanagers:`
aplikacja ostrzega w logu – przy okazji przenieś go na listę z własną nazwą.

**Jedna droga dla alertu.** Ten sam alert (te same etykiety) dostarczony przez dwa niezależne Alertmanagery to w konsoli
jeden alert, a „rozwiązany” z jednego przy „aktywnym” z drugiego sprawia, że mruga. Kieruj każdy alert do Alerty Next
przez jeden Alertmanager; etykiety zewnętrzne każdego Prometheusa zwykle i tak rozróżniają alerty.

### 8.3 Thanos Ruler
Alerty liczone przez Thanos Ruler docierają do Alerty Next tak samo (Ruler → Alertmanager → Alerta Next) – w Alercie
Next nic nie trzeba ustawiać. Trzy zasady dla zespołów piszących takie reguły:
1. **Zachowaj etykiety, po których rozpoznajemy środowisko.** Ruler widzi dane wszystkich klastrów: agregacja bez
   `by (cluster)` gubi `cluster` i alert trafia do kwarantanny (nic nie ginie, ale popraw regułę). Albo ustaw jawną
   etykietę `environment` w regule.
2. **Reguła żyje w jednym miejscu** – w lokalnym Prometheusie albo w Rulerze. Ta sama reguła w obu da dwa alerty
   (różne etykiety zewnętrzne).
3. **Nieudane zapytania rozwiązują alerty.** Gdy zapytanie do Thanosa się nie powiedzie (niedostępny Store, częściowa
   odpowiedź), reguła nic nie zwraca i alert gaśnie. Okno uspokojenia (5 min) ukrywa krótkie przerwy; na dłuższe
   ustaw `partial_response_strategy: abort` w grupach reguł alertowych i alert na błędy ewaluacji Rulera.

### 8.4 Inni nadawcy
Ogólne API, format, limity i błędy: [docs/ingest-api.md](../ingest-api.md).

### 8.5 Heartbeaty (czy zadanie jeszcze żyje?)

```sh
curl -fsS -X POST https://alerta.example.com/api/v1/ingest/heartbeat \
  -H "Authorization: Bearer $ALERTA_KEY" -H "Content-Type: application/json" \
  -d '{"name":"nocny-backup","environment":"PROD","timeoutSeconds":86400,"severity":"CRITICAL"}'
```

Heartbeat powstaje przy pierwszym wywołaniu; jeśli kolejne nie przyjdzie w `timeoutSeconds`, otwiera się alert
`HeartbeatMissing`, a następne wywołanie go rozwiązuje. Strona *Heartbeaty* pokazuje wszystkie.

### 8.6 Zmiany (wdrożenia z ArgoCD, CI)

Narzędzie wdrożeniowe może zgłaszać, co i gdzie zmieniło – zmiany nie są alertami (nie ma ich na liście, w mailach ani
raportach), tylko podpowiadają „co się zmieniło” obok alertów tego samego środowiska.

```sh
curl -fsS -X POST https://alerta.example.com/api/v1/ingest/changes \
  -H "Authorization: Bearer $ALERTA_KEY" -H "Content-Type: application/json" \
  -d '{"id":"catalog-api:4f2c1e9","labels":{"cluster":"portal-prod","namespace":"catalog"},
       "application":"catalog-api","version":"4f2c1e9","author":"jan.kowalski",
       "description":"Sync succeeded","url":"https://argocd.example.com/applications/catalog-api"}'
# {"id":"…","environment":"PORTAL-PROD","duplicate":false}
```

- **Środowisko** – z `labels`, według tych samych warunków co alert; klucz API musi je obejmować
  (`403 ENVIRONMENT_NOT_ALLOWED`). Zmiana, która nie pasuje do żadnego środowiska, jest odrzucana
  (`422 NO_ENVIRONMENT` – kwarantanny dla zmian nie ma).
- `application` (wymagane, do 128 znaków), `version`, `author` (do 128), `description` (do 2000), `url` (tylko
  http/https, bez danych logowania), `at` (kiedy – domyślnie chwila przyjęcia; najwyżej 5 min w przyszłości).
- `id` (opcjonalnie, do 256) – identyfikator nadawcy, np. aplikacja + rewizja: ponowione doręczenie zapisuje się raz
  (`"duplicate":true`).
- **Link zmiany konsola pokazuje tylko dla https i hosta z `alerta.links.allowed-hosts`** (ta sama lista co linki do
  narzędzi – dopisz tam host ArgoCD). Inny adres jest zapisany, ale zmiana wyświetla się bez linku; odpowiedź mówi to
  polem `urlShown`. Sprawdzane przy wyświetlaniu, więc dopisanie hosta działa też dla zmian już zapisanych.
- Przechowywane tak długo jak alerty środowiska (ta sama retencja).

#### Przykład: ArgoCD (argocd-notifications)

Kontroler powiadomień ArgoCD (wbudowany od 2.6) wysyła zmianę po udanym wdrożeniu – raz na rewizję.

1. **Klucz API** w *Administracja → Klucze API*, np. „ArgoCD”, obejmujący środowiska, do których ArgoCD wdraża.
2. **Sekret** – klucz w `argocd-notifications-secret` (najlepiej z Vaulta, jak inne sekrety):
   ```sh
   kubectl -n argocd patch secret argocd-notifications-secret --type merge \
     -p '{"stringData":{"alerta-next-token":"ank_…"}}'
   ```
3. **Usługa, szablon, wyzwalacz** w `argocd-notifications-cm`:
```yaml
# dopisz do istniejącego argocd-notifications-cm (namespace argocd)
data:
  service.webhook.alerta-next: |
    url: https://alerta.example.com/api/v1/ingest/changes
    headers:
      - name: Authorization
        value: Bearer $alerta-next-token
      - name: Content-Type
        value: application/json
  template.alerta-next-change: |
    webhook:
      alerta-next:
        method: POST
        body: |
          {
            "id": {{ printf "%s:%s" .app.metadata.name .app.status.operationState.syncResult.revision | toJson }},
            "labels": {{ dict "cluster" .app.spec.destination.name "namespace" .app.spec.destination.namespace | toJson }},
            "application": {{ .app.metadata.name | toJson }},
            "version": {{ .app.status.operationState.syncResult.revision | trunc 12 | toJson }},
            "author": {{ (call .repo.GetCommitMetadata .app.status.operationState.syncResult.revision).Author | trunc 128 | toJson }},
            "description": {{ (call .repo.GetCommitMetadata .app.status.operationState.syncResult.revision).Message | trunc 1900 | toJson }},
            "url": {{ printf "%s/applications/%s/%s" .context.argocdUrl .app.metadata.namespace .app.metadata.name | toJson }},
            "at": {{ .app.status.operationState.finishedAt | toJson }}
          }
  trigger.on-deployed-alerta-next: |
    - description: Synced and healthy – once per revision
      oncePer: app.status.operationState?.syncResult?.revision
      send: [alerta-next-change]
      when: app.status.operationState != nil and app.status.operationState.phase in ['Succeeded'] and app.status.health.status == 'Healthy'
  # wszystkie aplikacje (albo zamiast tego adnotacja na wybranych – niżej)
  subscriptions: |
    - recipients: [alerta-next]
      triggers: [on-deployed-alerta-next]
```
4. Zamiast `subscriptions` dla wszystkich – adnotacja na wybranych aplikacjach:
   `notifications.argoproj.io/subscribe.on-deployed-alerta-next.alerta-next: ""`.

Na co uważać:
- **`labels` muszą spełniać warunki środowiska** w Alercie. Przykład wysyła `cluster` = nazwa klastra docelowego
  w ArgoCD i `namespace`. Gdy środowiska rozpoznajecie po innych etykietach, weź je z etykiet aplikacji, np.
  `dict "cluster" .app.spec.destination.name "environment" (get (default (dict) .app.metadata.labels) "environment")`.
  Zmiana, która nie pasuje do żadnego środowiska, dostaje `422 NO_ENVIRONMENT` – widać to w logu
  `argocd-notifications-controller` (sprawdź też *Administracja → Tester etykiet*).
- `author` i `description` czytają commit (`GetCommitMetadata`) – kontroler musi mieć dostęp do repozytorium
  (zwykle ma, przez poświadczenia ArgoCD). Bez tego usuń te dwie linie albo użyj
  `.app.status.operationState.operation.initiatedBy.username`.
- `toJson` koduje wartości (cudzysłowy, nowe linie w opisie commita) – nie wstawiaj ich bez niego.
- `id` = aplikacja + rewizja: ponowione doręczenie zapisuje się raz.
- Certyfikat Alerty musi być zaufany dla kontrolera (firmowe CA w ArgoCD); nie wyłączaj sprawdzania TLS.

---

## 9. Utrzymanie

**Narzędzie wiersza poleceń** (w kontenerze backendu; wszystko w audycie jako `cli`):

```sh
kubectl -n alerta-next exec deploy/alerta-next-backend -- alerta-admin create-admin <login> "<Imię Nazwisko>"
kubectl -n alerta-next exec deploy/alerta-next-backend -- alerta-admin reset-password <login>
kubectl -n alerta-next exec deploy/alerta-next-backend -- alerta-admin unlock <login>
kubectl -n alerta-next exec deploy/alerta-next-backend -- alerta-admin list-admins
# compose: docker compose exec backend alerta-admin …
```

**Zdrowie i metryki** (port 8081 backendu, nigdy przez ingress):
- `/actuator/health/liveness`, `/actuator/health/readiness` – używane przez próby Kubernetes.
- `/actuator/prometheus` – JVM, HTTP, pula połączeń bazy oraz `alerta_*`: aktywne alerty per środowisko i ważność,
  przyjęte alerty, wiek Watchdoga, opóźnienie ścieżki alertów (`alerta_ingest_delay_seconds`), logowania i blokady, sesje, heartbeaty. Pody mają adnotacje
  `prometheus.io/scrape`. Przykładowe reguły alertów dla samej Alerty Next:
  [deploy/test-monitoring/11-rules.yaml](../../deploy/test-monitoring/11-rules.yaml) (grupa `alerta-next.yml`).

**Logi**: czytelne linie na stdout (`kubectl logs`); w Kubernetes dodatkowo JSON (Elastic Common Schema) w pliku
`/var/log/alerta/alerta-next.json` w podzie, dla agenta ELK. Linia na każde żądanie HTTP z identyfikatorem żądania;
zdarzenia audytu też trafiają do logu (dla SIEM). Hasła i klucze nigdy nie pojawiają się w logach.

**Stan systemu** (Administracja → Stan systemu): wersja, rozmiar bazy, zadania w tle, Alertmanager i Watchdog,
kwarantanna, wygasające klucze/konta, konfiguracja w użyciu (sekrety tylko jako „ustawiony / brak”).

---

## 10. Przed produkcją

- Sekrety z magazynu sekretów ([5](#5-sekrety)), nigdy `01-secrets.yaml`.
- HTTPS z właściwym certyfikatem; `SESSION_COOKIE_SECURE` zostaje `true`.
- Baza z kopiami zapasowymi (najlepiej z HA) – zwykle centralna ([6.2](#62-zewnętrzny-lub-centralny-postgresql));
  przy wbudowanej: nocny zrzut, kopia poza klaster, próba odtworzenia ([runbook](backup-runbook.pl.md)).
- Logowanie jednokrotne i `alerta.auth.local.mode: BREAK_GLASS_ONLY` z nazwanymi kontami awaryjnymi.
- Polityki sieciowe egzekwowane przez klaster; port metryk dostępny tylko dla Waszego Prometheusa.
- Alerty na samą Alertę Next (brak Watchdoga, backend niedostępny, wyczerpana pula połączeń bazy) – zob. 9.
- Zasoby dobrane do obciążenia; najpierw baza.
- Ustawione `TRUSTED_PROXIES` (4.4a); `alerta.passwords.forbidden-words` ze słowami organizacji.
- Samoocena bezpieczeństwa (OWASP ASVS 5.0 L2) i to, co zostaje po stronie wdrożenia: `docs/security/asvs-l2.md`.
- SBOM (CycloneDX) każdego obrazu dla skanera: backend `META-INF/sbom/application.cdx.json` w jarze
  (`/app/META-INF/sbom/…`), frontend `/usr/share/sbom/alerta-next-frontend.cdx.json`.
