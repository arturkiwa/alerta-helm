# Testowy Prometheus + Alertmanager (klaster testowy)

Najprostsze możliwe wdrożenie tylko do testów: **poza ArgoCD**, ręcznie przez `kubectl`. Namespace `monitoring`.

| Co | Adres | Uwagi |
|---|---|---|
| Prometheus v3.14.0 | https://prometheus.artbit.com.pl | basic auth, użytkownik `admin`, hasło w Secret `prometheus-basic-auth` (klucz `password`); retencja 7 dni, PVC 10 Gi |
| Alertmanager v0.34.1 | https://alertmanager.artbit.com.pl | **logowanie basic auth** (konta: `./alertmanager-auth.sh`); wszystkie alerty → webhook Alerta Next; PVC 1 Gi (wyciszenia przetrwają restart) |

LB: oba hosty → `<worker>:30090` (HTTP), health check `GET <worker>:30091/healthz/ready`.

```sh
kubectl apply -f 00-namespace.yaml
./create-secrets.sh [KLUCZ_API_ALERTY]    # hasło Prometheusa (wypisane raz) + klucz API dla Alertmanagera
kubectl apply -f .
```

Klucz API później (Alerta Next → Administracja → Klucze API):

```sh
kubectl -n monitoring create secret generic alertmanager-alerta-token --from-literal=token='ank_…' \
  --dry-run=client -o yaml | kubectl apply -f -
```
Alertmanager czyta plik przy każdej wysyłce, więc restart nie jest potrzebny.

Hasło: `kubectl -n monitoring get secret prometheus-basic-auth -o jsonpath='{.data.password}' | base64 -d`

## Logowanie do Alertmanagera

Alertmanager wymaga logowania na każdym adresie (API, UI, `/metrics`, `/-/healthy`). Konta to hashe bcrypt w Secret
`alertmanager-web-config`; Alertmanager czyta je przy każdym żądaniu (zmiana konta bez restartu). Bez tego Secretu
pod nie wystartuje – nigdy nie ruszy otwarty.

```sh
./alertmanager-auth.sh add alerta alerta-next/alerta-next-alertmanager               # Alerta Next (wyciszenia)
./alertmanager-auth.sh add prometheus-testcluster monitoring/prometheus-alertmanager-auth  # Prometheus tego klastra
./alertmanager-auth.sh add prometheus-<klaster>        # Prometheus z innego klastra – hasło wypisane raz
./alertmanager-auth.sh list | remove <konto>           # ostatniego konta skrypt nie usunie (lista pusta = brak logowania)
```

**Pierwsze włączenie bez przerwy w alertach** (odbiorcy najpierw dostają hasła – Alertmanager bez logowania je ignoruje):

1. Konta `alerta` i `prometheus-testcluster` (dwie pierwsze linie wyżej) – tworzą też Secret z kontami.
2. Prometheus: `kubectl apply -f 10-prometheus.yaml && kubectl -n monitoring rollout restart deploy/prometheus`.
3. Alerta Next: merge PR z `ALERTMANAGER_USERNAME/PASSWORD` + sync w ArgoCD (backend przeczyta Secret przy starcie;
   jeśli pody już działały – `kubectl -n alerta-next rollout restart deploy/alerta-next-backend`).
4. Dopiero teraz logowanie: `kubectl apply -f 20-alertmanager.yaml` (pod startuje z `--web.config.file`).
5. Sprawdzenie: `curl -s -o /dev/null -w '%{http_code}' https://alertmanager.artbit.com.pl/api/v2/status` → `401`;
   w Alerta Next strona Wyciszenia działa, „Stan systemu” → synchronizacja z Alertmanagerem OK; w Prometheusie
   `/targets` → job `alertmanager` UP.

**Prometheus w innym klastrze** (konto `prometheus-<klaster>`, hasło w Secret po tamtej stronie):

```yaml
global:
  external_labels:          # po nich Alerta Next przypisze alerty do środowiska (warunki środowiska)
    cluster: <klaster>
    environment: <Środowisko>
alerting:
  alertmanagers:
    - scheme: https
      basic_auth:
        username: prometheus-<klaster>
        password_file: /etc/prometheus/secrets/alertmanager-password
      static_configs:
        - targets: ["alertmanager.artbit.com.pl"]
```

Jeśli mimo to jest 403: to nie Alertmanager (on odpowiada 401). Sprawdź nagłówek `server:` odpowiedzi – odmawia load
balancer (lista adresów) albo proxy/egress po stronie tamtego klastra.

Zmiana reguł lub konfiguracji: edytuj pliki, `kubectl apply -f .`, potem
`kubectl -n monitoring rollout restart deploy/prometheus` (lub `deploy/alertmanager`).

**Źródła metryk:** Prometheus, Alertmanager, node-exporter (DaemonSet na wszystkich 6 węzłach, `40-exporters.yaml`),
kube-state-metrics, kubelet i cAdvisor (przez API server), API server, kube-scheduler i kube-controller-manager,
CoreDNS, ArgoCD (application-controller) oraz pody z adnotacją `prometheus.io/scrape: "true"` (Ceph, Istio,
nodelocaldns, cert-manager…). Etykiety zewnętrzne `cluster=testcluster`, `environment=Test` – takie warunki ustaw
środowisku w Alerta Next.

**Reguły** (`11-rules.yaml`, ~110, na podstawie awesome-prometheus-alerts, dostosowane do klastra): monitoring,
węzły, Kubernetes (węzły, obciążenia, wolumeny, control plane), DNS, Ceph, Istio, ArgoCD oraz sama Alerta Next
(backend nie odpowiada, brak Watchdoga > 5 min = zerwany łańcuch, błędy 5xx, synchronizacja wyciszeń, kwarantanna,
pula połączeń z bazą, sterta JVM). Watchdog ma w Alertmanagerze osobną trasę i dochodzi do Alerty co 1–2 min. Każda ma `severity`
(critical / warning / info), `service` (grupa w konsoli) i `notify`. Tylko reguły, dla których metryki istnieją
na tym klastrze; reguły dysków hosta obejmują dyski lokalne (sd/vd/nvme/dm), nie urządzenia RBD/NBD Cepha.
Etcd nie jest scrapowany bezpośrednio (metryki tylko na 127.0.0.1 masterów) – jego opóźnienia widać przez
`KubernetesApiServerLatencyHigh`.

Zmiana reguł bez restartu:
```sh
kubectl apply -f 11-rules.yaml
# ConfigMapa trafia do poda po ok. minucie, potem:
curl -u admin:<hasło> -X POST https://prometheus.artbit.com.pl/-/reload
```

Usunięcie wszystkiego: `kubectl delete -f .` (usuwa też ClusterRole i ClusterRoleBinding).
