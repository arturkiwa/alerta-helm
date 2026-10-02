# Kopie zapasowe i odtworzenie bazy – runbook

*English: [backup-runbook.md](backup-runbook.md)*

Dotyczy **wbudowanego PostgreSQL** (Helm: `database.internal.enabled: true`, compose: usługa `db`). Przy bazie
zewnętrznej / centralnej kopie i odtworzenie należą do DBA – wystarczy spójny zrzut albo PITR bazy (schematu) Alerty;
kroki 3.4–3.6 (sesje, uprawnienia cofnięte przez odtworzenie, sprawdzenie) obowiązują tak samo.

## 1. Co chronimy i ile możemy stracić

W bazie jest **wszystko**: konfiguracja (środowiska i ich warunki, użytkownicy, grupy, role, klucze API, etykiety,
widoki, reguły powiadomień, heartbeaty, okna serwisowe), alerty z historią i notatkami, dziennik audytu, sesje.
Utrata bazy = utrata konfiguracji i historii obsługi; same **aktywne** alerty Alertmanager przyśle ponownie.

| | Wartość | Skąd |
|---|---|---|
| RPO (ile danych można stracić) | do 24 h | kopia nocna; przed każdą aktualizacją kopia ręczna (2.3) |
| RTO (czas odtworzenia) | kilkanaście minut | zrzut ma zwykle kilka–kilkadziesiąt MB; `pg_restore` trwa sekundy |

Potrzebujesz krótszego RPO – bazę zewnętrzną z PITR (ciągła archiwizacja WAL) po stronie DBA.

## 2. Kopie

### 2.1 Kopia nocna (Helm)

```yaml
database:
  internal:
    backup:
      enabled: true
      schedule: "30 2 * * *"   # cron, strefa klastra (zwykle UTC)
      keep: 14                 # tyle zrzutów zostaje na wolumenie
      storageClass: ""         # najlepiej INNY magazyn niż baza (np. ceph-block, gdy baza na CephFS)
      size: 20Gi
```

Chart zakłada CronJob `<release>-db-backup` i wolumen `<release>-db-backup` (zostaje po `helm uninstall`). Co noc:
`pg_dump -Fc` do pliku tymczasowego → sprawdzenie, że zrzut da się odczytać (`pg_restore --list`) → zmiana nazwy na
`alerta-RRRRMMDDTGGMMSSZ.dump` → usunięcie najstarszych ponad `keep`. Nieudany zrzut niczego nie usuwa. Zadanie
działa na koncie usługi bazy (ten sam dostęp do sekretów, także Vault CSI) i ma własną NetworkPolicy (tylko do bazy).

Sprawdzenie po włączeniu – uruchom zadanie od razu, nie czekając do nocy:

```sh
kubectl -n <ns> create job --from=cronjob/<release>-db-backup <release>-db-backup-test
kubectl -n <ns> logs -f job/<release>-db-backup-test
# backup done: alerta-20261001T083000Z.dump, 93303 bytes; kept: 1
```

### 2.2 Kopia poza klastrem – obowiązkowo

Wolumen z kopiami jest **w tym samym klastrze** (często na tym samym magazynie) – chroni przed błędem w bazie,
złą migracją, pomyłką człowieka, ale **nie** przed utratą klastra lub magazynu. Pliki z wolumenu
`<release>-db-backup` muszą regularnie trafiać poza klaster – systemem kopii organizacji (Velero / Kasten / agent
kopii plików / zadanie kopiujące do S3). Zrzuty zawierają dane osobowe (loginy, imiona, e-maile) i skróty haseł
kont lokalnych – przechowywać jak inne kopie systemów produkcyjnych (szyfrowane, z kontrolą dostępu).

### 2.3 Kopia przed aktualizacją

Przed każdą aktualizacją wersji (nowa wersja może mieć migracje schematu):

```sh
kubectl -n <ns> create job --from=cronjob/<release>-db-backup <release>-db-backup-pre-$(date +%Y%m%d%H%M)
kubectl -n <ns> wait --for=condition=complete job/<release>-db-backup-pre-... --timeout=10m
```

Bez włączonej kopii nocnej – zrzut ręczny do pliku na stacji administratora:

```sh
kubectl -n <ns> exec <release>-db-0 -- sh -c \
  'PGPASSWORD="${POSTGRES_PASSWORD:-$(cat "$POSTGRES_PASSWORD_FILE")}" pg_dump -h 127.0.0.1 \
   -U "${POSTGRES_USER:-$(cat "$POSTGRES_USER_FILE")}" -Fc alerta' > alerta-$(date +%F).dump
# compose: docker compose exec -T db pg_dump -U alerta -Fc alerta > alerta-$(date +%F).dump
```

### 2.4 Monitorowanie kopii

Reguła Prometheusa (kube-state-metrics) – brak udanej kopii od ponad 26 h albo zadanie zakończone błędem:

```yaml
- alert: AlertaNextBackupMissing
  expr: time() - kube_cronjob_status_last_successful_time{cronjob=~".*-db-backup"} > 26 * 3600
  for: 15m
  labels: { severity: critical }
  annotations:
    summary: Brak udanej kopii bazy Alerty Next od ponad doby
- alert: AlertaNextBackupFailed
  expr: kube_job_status_failed{job_name=~".*-db-backup-.*"} > 0
  labels: { severity: warning }
  annotations:
    summary: Zadanie kopii bazy Alerty Next zakończyło się błędem ({{ $labels.job_name }})
```

## 3. Odtworzenie

Odtworzenie cofa bazę **do chwili zrzutu**: wszystko później (alerty, notatki, zmiany konfiguracji **i wpisy
audytu**) znika. Dlatego krok 3.1 jest obowiązkowy, gdy uszkodzona baza jeszcze istnieje.

### 3.1 Zabezpiecz obecny stan (jeśli baza jeszcze działa)

Zrzut uszkodzonej bazy to **dowód** (dziennik audytu jest nieusuwalny – po odtworzeniu jego końcówka zniknie) i źródło
do kroku 3.5. Zrób go tak jak w 2.3 (ręcznie do pliku) i zachowaj razem z opisem zdarzenia.

### 3.2 Zatrzymaj backend

Backend nie może pisać do bazy w trakcie odtwarzania ani – przy pustej, nowej bazie – założyć na niej świeżego
schematu przed odtworzeniem.

- **Argo CD** (auto-sync / self-heal przywróci ręczne `kubectl scale`): ustaw w values `backend.replicas: 0`
  (commit, sync) **albo** wyłącz na czas odtwarzania auto-sync aplikacji w Argo i wtedy
  `kubectl -n <ns> scale deploy/<release>-backend --replicas=0`.
- Bez Argo: `kubectl -n <ns> scale deploy/<release>-backend --replicas=0`.
- compose: `docker compose stop backend`.

Sprawdź: `kubectl -n <ns> get pods` – żadnego poda `<release>-backend-…`.

### 3.3 Odtwórz zrzut

Baza musi działać (pod `<release>-db-0` gotowy). **Baza całkowicie utracona** (usunięty wolumen): StatefulSet sam
założy nową, pustą bazę `alerta` przy starcie poda – potem odtwarzasz jak niżej.

Pod pomocniczy z dostępem do wolumenu kopii i do bazy – etykiety takie jak zadanie kopii (NetworkPolicy go
przepuści), konto usługi bazy (sekrety, także Vault CSI). Zapisz jako `restore.yaml`, podmień `<release>`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: <release>-db-restore
  labels:
    app.kubernetes.io/name: <release>-db-backup
    app.kubernetes.io/instance: <nazwa-instalacji-helm>
spec:
  serviceAccountName: <release>-db
  automountServiceAccountToken: false
  restartPolicy: Never
  securityContext: { runAsNonRoot: true, runAsUser: 70, runAsGroup: 70, fsGroup: 70, seccompProfile: { type: RuntimeDefault } }
  containers:
    - name: restore
      image: docker.io/library/postgres:18-alpine
      command: [sleep, "3600"]
      env:
        - { name: PGHOST, value: <release>-db }
        - { name: PGDATABASE, value: alerta }
      securityContext: { allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: { drop: [ALL] } }
      volumeMounts:
        - { name: backup, mountPath: /backup }
        - { name: tmp, mountPath: /tmp }
        # secrets.mode = csi: odkomentuj też wolumen "secrets" niżej
        # - { name: secrets, mountPath: /etc/alerta/secrets, readOnly: true }
  volumes:
    - { name: backup, persistentVolumeClaim: { claimName: <release>-db-backup } }
    - { name: tmp, emptyDir: {} }
    # - name: secrets
    #   csi: { driver: secrets-store.csi.k8s.io, readOnly: true, volumeAttributes: { secretProviderClass: <release>-db-secrets } }
```

`app.kubernetes.io/instance` = nazwa instalacji Helm (`helm list`). Przy `secrets.mode` `values` / `existing`
dodaj do `env` `PGUSER` / `PGPASSWORD` z sekretu bazy (`<release>-db`, klucze `username` / `password`, albo Twój
`database.existingSecret`) – tak jak w CronJobie kopii (`kubectl get cronjob <release>-db-backup -o yaml`).

```sh
kubectl -n <ns> apply -f restore.yaml
kubectl -n <ns> wait --for=condition=ready pod/<release>-db-restore
kubectl -n <ns> exec <release>-db-restore -- ls -l /backup          # wybierz zrzut
# zrzut spoza klastra: kubectl -n <ns> cp alerta-….dump <release>-db-restore:/tmp/alerta.dump
kubectl -n <ns> exec <release>-db-restore -- sh -c '
  export PGUSER="${PGUSER:-$(cat /etc/alerta/secrets/DB_USER)}"
  export PGPASSWORD="${PGPASSWORD:-$(cat /etc/alerta/secrets/DB_PASSWORD)}"
  pg_restore --clean --if-exists --no-owner --exit-on-error --single-transaction -d alerta /backup/alerta-….dump'
```

`--single-transaction`: albo odtworzy się całość, albo nic (baza zostaje jak była). compose:

```sh
docker compose exec -T db pg_restore -U alerta --clean --if-exists --no-owner --exit-on-error --single-transaction \
  -d alerta < alerta-….dump
```

### 3.4 Unieważnij sesje

Zrzut zawiera sesje z chwili kopii – po odtworzeniu ożyłyby. Usuń je (wszyscy zalogują się ponownie):

```sh
kubectl -n <ns> exec <release>-db-restore -- sh -c '
  export PGUSER="${PGUSER:-$(cat /etc/alerta/secrets/DB_USER)}" PGPASSWORD="${PGPASSWORD:-$(cat /etc/alerta/secrets/DB_PASSWORD)}"
  psql -c "DELETE FROM spring_session"'
```

### 3.5 Przywróć odebrane uprawnienia – bezpieczeństwo

Odtworzenie cofa też **odebrane dostępy**: konto wyłączone, klucz API unieważniony, rola odebrana po chwili zrzutu
znów działa. W zrzucie z kroku 3.1 (albo w logu backendu / SIEM – zdarzenia audytu też tam trafiają) sprawdź, co
zmieniło się po chwili kopii, i powtórz odebrania w aplikacji:

```sql
-- na zrzucie uszkodzonej bazy (np. odtworzonym tymczasowo gdzie indziej) albo w SIEM:
SELECT occurred_at, actor_name, action, target_name FROM audit_log
 WHERE occurred_at > '<czas zrzutu>' AND action IN ('user.disable', 'user.expire', 'user.kiosk',
       'user.password.reset', 'user.sessions.terminate', 'apikey.revoke', 'apikey.environments', 'assignment.delete',
       'group.member.remove', 'role.update', 'role.delete', 'environment.matchers')
 ORDER BY occurred_at;
```

Nie ma zrzutu ani SIEM – przejrzyj z administratorami dostępu zmiany z ostatniej doby.

### 3.6 Uruchom i sprawdź

1. Backend z powrotem: `backend.replicas` na poprzednią wartość (commit / włącz auto-sync w Argo) albo
   `kubectl scale … --replicas=2`; compose: `docker compose start backend`.
2. Usuń pod pomocniczy: `kubectl -n <ns> delete pod <release>-db-restore`.
3. Log backendu: `Successfully validated N migrations` i `Schema "public" is up to date` (albo migracja, jeśli
   odtworzony zrzut jest ze starszej wersji – to normalne). Wersja obrazu **taka sama albo nowsza** niż ta, która
   robiła zrzut.
4. Logowanie (SSO i konto awaryjne), *Stan systemu* bez błędów, lista środowisk i użytkowników, alerty z ostatnich
   godzin przed zrzutem, *Dziennik audytu* – ostatni wpis sprzed zrzutu, po nim wpisy z bieżących logowań.
5. Alertmanager dośle aktywne alerty przy najbliższym powtórzeniu (`repeat_interval`), heartbeaty przy najbliższym
   sygnale; alerty rozwiązane między zrzutem a awarią nie wrócą.
6. **Dziennik audytu – co utracono** (łańcuch skrótów, od 0.47.0): w ELK znajdź ostatnią kotwicę sprzed awarii
   (`event.action: audit.anchor`, pola `audit.chain.seq` i `audit.chain.hash`, co godzinę) i sprawdź ją razem
   z kilkoma wcześniejszymi:
   ```sh
   kubectl -n <ns> exec deploy/<release>-backend -- alerta-admin verify-audit <seq>:<hash> <seq>:<hash>
   ```
   Łańcuch odtworzonej bazy jest cały (`Audit chain: OK`), kotwice sprzed zrzutu dają `MATCHES`, nowsze – `TRUNCATED`:
   ich numery pokazują, ile wpisów audytu przepadło (były w bazie po zrzucie). `DIFFERENT` albo `BROKEN` = coś
   innego niż odtworzenie (zmienione wpisy) – zgłoś jako incydent bezpieczeństwa. `INCOMPLETE` = starsze wpisy
   audytu poza łańcuchem (polecenie najpierw je dołącza, więc zwykle tylko gdy zadanie łańcucha trzymało blokadę) –
   powtórz za minutę; jeśli zostaje, sprawdź log (`linked late`) i zgłoś.
7. Zapisz w rejestrze zdarzeń: czas awarii, użyty zrzut, czas przerwy, co utracono (także zakres utraconych wpisów
   audytu z punktu 6).

## 4. Próba odtworzenia

Kopia, której nie odtworzono, nie jest kopią. **Raz na kwartał** i po każdej zmianie sposobu kopii: odtwórz
najnowszy zrzut do **osobnej** bazy (inna instalacja testowa albo `createdb alerta_proba` na tym samym serwerze
i `pg_restore -d alerta_proba`), porównaj liczby wierszy (`users`, `environments`, `alerts`, `audit_log`,
`flyway_schema_history`) z produkcją z chwili zrzutu, uruchom na niej backend testowy, zapisz wynik i czas.

Pierwsza próba (2026-09-30, lokalny stack, wersja 0.39): zrzut skryptem z chartu (sprawdzenie i rotacja działają),
usunięcie wolumenu bazy, odtworzenie do nowej pustej bazy – liczby wierszy identyczne, Flyway: 33 migracje bez
zmian, logowanie działa, audyt pisze dalej od kolejnego numeru; odtworzenie na istniejącą, uszkodzoną bazę
(`--clean --single-transaction`) – także poprawne, wyzwalacze (na żywo, audyt tylko do dopisywania) wracają.
Czas samego `pg_restore`: ~4 s.
