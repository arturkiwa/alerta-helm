# Alerta Next – deployment guide

[Polska wersja](README.pl.md)

This guide takes you from zero to a working Alerta Next, without guessing. It has three parts:

1. [What Alerta Next is](#1-what-alerta-next-is) – what it does, what it collects and how.
2. Installation, two ways:
   - [Quick start with Docker Compose](#3-quick-start-docker-compose) – the whole stack with demo alerts on one
     machine, to see what it is (10 minutes).
   - [Kubernetes with plain manifests](#4-kubernetes-plain-manifests) – a simple, complete installation to try it
     in a cluster.
   - [Helm chart](#410-alternative-helm-chart) – the same, parametrised.
3. Reference: [secrets](#5-secrets), [database (bundled or external)](#6-database),
   [configuration](#7-configuration), [connecting senders](#8-connecting-alert-senders),
   [operations](#9-operations), [before production](#10-before-production).

Both installations are for **evaluation and demos**. Secrets are in plain files on purpose (simple to start);
for production take them from your secret store – section [5](#5-secrets) lists every one of them.

---

## 1. What Alerta Next is

Alerta Next is a **console for alerts**: one place where the on-call people see what is broken, who is on it, and
what happened. It does not measure anything itself – monitoring systems (Prometheus with Alertmanager, Zabbix,
scripts …) detect problems and **send** alerts to it.

### What it collects and how

| Source | How | What arrives |
|---|---|---|
| **Prometheus / Alertmanager** | Alertmanager's webhook calls `POST /api/v1/ingest/alertmanager` | every alert of the routes pointing to Alerta Next, and its resolution |
| **Any other sender** (Zabbix, scripts, cron) | `POST /api/v1/ingest/alerts` – the same alert format ([docs/ingest-api.md](../ingest-api.md)) | alerts and their resolution; optionally they expire when the sender goes quiet |
| **Heartbeats** ("is it still alive?") | a job calls `POST /api/v1/ingest/heartbeat` regularly | if the call stops coming, Alerta Next raises an alert itself |
| **Changes** (deployments from ArgoCD, CI) | the deployment tool calls `POST /api/v1/ingest/changes` | what was deployed, where and by whom – next to the environment's alerts, not as an alert |

Everything is **pushed** to Alerta Next – it never polls or connects to your systems. The only outgoing
connection is optional: to Alertmanager's API, so that silences can be created and removed from the console.

Every sender authenticates with an **API key** that may send alerts only for chosen **environments**.

### What it does with alerts
- **Environments**: each alert lands in an environment (PROD, TEST …) by **conditions on its labels**
  (e.g. `cluster = prod-1`). An alert that matches no environment goes to the **quarantine** – nothing is lost, an
  administrator sees it and fixes the conditions. The environment dialog shows before saving what the conditions
  would take from other environments; a mistake is fixed by *Environments → Reassign alerts…* (active alerts and –
  optionally – ended ones of the last 7/30/90 days go where the conditions say; ended ones never to the quarantine).
- **Deduplication**: one alert per fingerprint (Alertmanager's, or derived from the labels); repeats update it, a
  return after resolution is a new occurrence of the same alert. A short "resolution grace" (default 5 min) keeps
  alerts that resolve and come back every few minutes from filling the history.
- **Console**: live list (updates without reloading), filters, shared and personal views, details with the whole
  history, notes, acknowledge (with a timeout), close, bulk actions, CSV export.
- **Silences** in Alertmanager from the console; **maintenance windows** per environment.
- **Reports**: response times (MTTA/MTTR), most frequent and longest alerts, unstable (flapping) alerts.
- **Access**: users, groups, roles per environment; local accounts and/or single sign-on (OpenID Connect).
- **Audit log** of every change and every action on an alert.

### What it stores
Everything in **PostgreSQL**: alerts and their history (events, notes), users, groups, roles, API keys (only a hash),
sessions, the audit log. Alerts are kept per environment class (PROD 400 days, TEST 30 …, configurable); the audit
log is append-only.

### Architecture

```
 browser ──HTTPS──▶ [TLS: ingress / load balancer] ──▶ frontend (nginx, :8080)
                                                          │  UI + /api on one origin
 Alertmanager, scripts ──HTTPS── (same address) ──────────┤
                                                          ▼
                                                     backend (Spring Boot, :8080 API, :8081 health+metrics)
                                                          │                        │ (optional)
                                                          ▼                        ▼
                                                     PostgreSQL              Alertmanager API :9093 (silences)
```

| Component | Image | Port | Notes |
|---|---|---|---|
| frontend | `arturkiwa/alerta-next-frontend` | 8080 (HTTP) | the web UI; forwards `/api` to the backend |
| backend | `arturkiwa/alerta-next-backend` | 8080 API, 8081 health+metrics | stateless, run 2+ replicas; includes the `alerta-admin` CLI |
| database | `postgres` 18 | 5432 | tested with PostgreSQL 18 |

**Security in short:** the browser gets only a session cookie (`HttpOnly; Secure; SameSite=Strict`) – no tokens;
CSRF protection; strict Content Security Policy; passwords hashed with Argon2; login lockout; API keys stored as
hashes and limited to environments; every change audited. **The UI must be reached over HTTPS** (the session cookie
is `Secure`) – except in the quick start on `http://localhost`, which switches that off.

### Resources (starting point)

| | CPU request | Memory request / limit |
|---|---|---|
| backend (each replica) | 250m | 768 Mi / 1536 Mi |
| frontend (each replica) | 50m | 64 Mi / 256 Mi |
| PostgreSQL (bundled) | 100m | 256 Mi / 1 Gi, disk 10 Gi |

A load test with ~10× a busy outage (10 alerts/s, 50 open consoles) ran on 2 backends and one database; the database
is what needs CPU first (see `load/README.md`).

---

## 2. Concepts you need during setup

| Term | Meaning |
|---|---|
| **First administrator** | Alerta Next never creates an account by itself. The first one is created with the command-line tool `alerta-admin` inside the backend container; it prints a one-time password to change at the first login. |
| **Environment** | A group of alerts (e.g. PROD) with **conditions on labels** that decide which alerts belong to it. |
| **Quarantine** | Alerts that match no environment. Visible to access administrators (view "Quarantine"); resolved and closed ones go after 7 days. Junk from broken rules an access administrator can **delete** (selected, or all matching the filter) – each deletion audited with the alert's labels. Alerts of an environment cannot be deleted (they are the record of how they were handled). |
| **API key** | What a sender (Alertmanager, a script) uses to send alerts; limited to chosen environments; shown only once when created. |
| **Roles** (built in) | `VIEWER` – sees alerts; `OPERATOR` – also acknowledges, closes, notes, silences; `MAINTAINER` – also maintenance windows and heartbeats; `ACCESS_ADMIN` – users, groups, roles, environments, API keys, labels, views; `AUDITOR` – the audit log. A role is assigned **per environment** (or for all). |

The first administrator gets only `ACCESS_ADMIN` (managing access). **To see alerts, assign yourself a role such as
Operator** – the steps below do it.

Password rules: at least 12 characters (16 for accounts with administrative roles), must not contain the login or a
forbidden word (`alerta.passwords.forbidden-words` – add your organisation's and systems' names), must not be a known
common password. A one-time password (new account, reset) is valid for 72 hours.

---

## 3. Quick start (Docker Compose)

The whole stack on one machine: Alerta Next + PostgreSQL + (optional) Prometheus with demo alerts + Alertmanager.
Everything is in [`deploy/quickstart`](../../deploy/quickstart).

### 3.1 What you need
- Docker Engine with **Compose v2** (`docker compose version` works). On Linux, macOS or Windows (Docker Desktop).
- About 2 GB of free memory.
- Free ports on your machine: **8080** (the UI); 9090 and 9093 (Prometheus and Alertmanager, only on `127.0.0.1`).
- Internet access to Docker Hub (images `arturkiwa/alerta-next-*`, `postgres`, `prom/prometheus`,
  `prom/alertmanager`).

### 3.2 Get the files
Either clone the repository, or copy only the directory `deploy/quickstart` (with the hidden file `.env`):

```sh
git clone https://github.com/arturkiwa/alerta-next.git
cd alerta-next/deploy/quickstart
ls -a      # .env  alertmanager/  docker-compose.yml  prometheus/
```

### 3.3 Look at the settings (optional)
All settings are in **`.env`**:

| Variable | Default | Meaning |
|---|---|---|
| `BACKEND_IMAGE`, `FRONTEND_IMAGE` | `docker.io/arturkiwa/alerta-next-…:0.13.0` | images; keep both on the same version |
| `ALERTA_PORT` | `8080` | the UI at `http://localhost:8080` |
| `DB_URL`, `DB_USER` | the bundled database | change only for your own PostgreSQL ([3.12](#312-turning-parts-off)) |
| `DB_PASSWORD` | `quickstart-change-me` | password of the bundled database – change it **before the first start** |
| `COMPOSE_PROFILES` | `monitoring` | optional parts; empty = Alerta Next alone ([3.12](#312-turning-parts-off)) |
| `ALERTMANAGER_URL` | `http://alertmanager:9093` | Alertmanager API for silences; empty = no "Silence" button |

### 3.4 Start

```sh
docker compose up -d
docker compose ps          # db (healthy), backend, frontend, prometheus, alertmanager: running
```

The backend needs ~30–60 s at the first start (it creates the database schema). It is ready when this answers:

```sh
curl http://localhost:8080/api/v1/ping
# {"status":"ok"}
```

### 3.5 Create the first administrator

```sh
docker compose exec backend alerta-admin create-admin admin "Administrator"
```

The output ends with:

```
Created access administrator admin
One-time password: Xxxxxx-Xxxxxx-Xxxxxx-Xxxxxx
It must be changed at the first login.
```

Open **http://localhost:8080**, sign in as `admin` with that one-time password and set your own password
(≥ 16 characters, must not contain "admin").

> Lost it? `docker compose exec backend alerta-admin reset-password admin` prints a new one-time password.

### 3.6 Give yourself access to alerts
1. **Administration → Users** → click **admin**.
2. **Assign role** → Role **Operator** → switch on **All environments** → **Add**.
3. Reload the page (F5) – permissions apply at once; the menu now shows the alert pages.

### 3.7 Create the environments of the demo alerts
The demo alerts carry the label `cluster` = `demo-prod` or `demo-test`.

1. **Administration → Environments → New environment**: Code `PROD`, Name `Demo production`, Class `PROD` → **Save**.
2. In the list click **Edit** (pencil) at PROD → **Add condition**: Label `cluster`, Values `demo-prod` → **Save**.
3. The same for `TEST` (Class `TEST`) with `cluster` = `demo-test`.

Do this **before** step 3.9 – alerts that arrive earlier land in the quarantine (they move to the right environment
with their next repetition, see [3.10](#310-see-it-working)).

### 3.8 Create an API key for Alertmanager
**Administration → API keys → New key**: Name `Alertmanager`, switch on **All environments** → **Create**.
The key (`ank_…`) is shown **only once** – copy it.

### 3.9 Give the key to Alertmanager
Replace the content of `alertmanager/secrets/alerta-token` with the key (one line, nothing else) and restart
Alertmanager so it sends everything at once:

```sh
echo 'ank_your_key_here' > alertmanager/secrets/alerta-token
docker compose restart alertmanager
```

### 3.10 See it working
- **Alerts** (http://localhost:8080): within a minute four demo alerts – two in PROD, two in TEST.
- **Administration → System status**: "Watchdog" received recently = the whole path Prometheus → Alertmanager →
  Alerta Next works.
- Click an alert → **Silence in Alertmanager…** → the silence appears in Alertmanager (http://localhost:9093).
- Prometheus: http://localhost:9090 (tab *Alerts*).
- If some alerts sit in the quarantine: fix the environment conditions (3.7) – active alerts move at once.

### 3.11 Send your own alert (any sender)

```sh
curl -fsS -X POST http://localhost:8080/api/v1/ingest/alerts \
  -H "Authorization: Bearer ank_your_key_here" -H "Content-Type: application/json" \
  -d '{"source":"test","alerts":[{"labels":{"alertname":"MyFirstAlert","severity":"warning","cluster":"demo-test"},
       "annotations":{"summary":"Sent with curl"}}]}'
# {"created":1,...}   – resolve it: the same with "status":"resolved"
```

### 3.12 Turning parts off
| You want | Do |
|---|---|
| **Alerta Next alone** (no Prometheus / Alertmanager) | in `.env`: `COMPOSE_PROFILES=` (empty) and `ALERTMANAGER_URL=` (empty); then `docker compose up -d --remove-orphans`. If they already run: `docker compose rm -sf prometheus alertmanager`. |
| **Your own Alertmanager** instead of the demo one | as above, and `ALERTMANAGER_URL=http://<your-alertmanager>:9093` (must be reachable from the backend container); in your Alertmanager a receiver as in [8.1](#81-prometheus--alertmanager) with the URL `http://<this-machine>:8080/api/v1/ingest/alertmanager` |
| **Demo Alertmanager, but your Prometheus** | in your Prometheus `alerting.alertmanagers` → `<this-machine>:9093` (the port is bound to 127.0.0.1 – change `127.0.0.1:9093:9093` to `9093:9093` in `docker-compose.yml`); delete or empty `prometheus/rules.yml` |
| **No demo alerts** but keep Prometheus | empty `prometheus/rules.yml` (keep the Watchdog rule if you want the path check), `docker compose restart prometheus` |
| **Your own PostgreSQL** instead of the bundled one | in `.env`: `DB_URL=jdbc:postgresql://<host>:5432/<database>`, `DB_USER`, `DB_PASSWORD`; start without the bundled one: `docker compose up -d --no-deps frontend backend` (see [6.2](#62-external-or-central-postgresql) for what the database needs) |
| **No silences** from the console | `ALERTMANAGER_URL=` (empty), `docker compose up -d` |

### 3.13 Stop, start, remove

```sh
docker compose stop           # stop, keep everything
docker compose start          # start again
docker compose down           # remove containers, KEEP the data (volume)
docker compose down -v        # remove containers AND the data
```

### 3.14 If something does not work
| Symptom | Cause / fix |
|---|---|
| `docker compose` unknown | install Compose v2 (Docker Desktop has it; on Linux the package `docker-compose-plugin`) |
| backend restarts, log: "password authentication failed" | `DB_PASSWORD` changed after the database was created – `docker compose down -v` and start again (deletes data) |
| the UI opens, but the alert pages are missing | the account has no role with alerts yet (3.6) |
| no alerts arrive | `docker compose logs alertmanager` – `401`: wrong key in `alertmanager/secrets/alerta-token`; the key must be one line |
| alerts only in the quarantine | the environment conditions do not match the labels (3.7) |
| "Silence" button missing | `ALERTMANAGER_URL` empty, or the backend cannot reach it |

Logs: `docker compose logs -f backend` (one line per HTTP request, errors with a request id).

---

## 4. Kubernetes (plain manifests)

A simple, complete installation in plain YAML (no Helm, no kustomize) in
[`deploy/kubernetes`](../../deploy/kubernetes): Alerta Next with 2 replicas, PostgreSQL inside the cluster, an NGINX
Ingress, network policies. Secrets are in a plain file – for a test. For production see [section 5](#5-secrets) and
[10](#10-before-production).

### 4.1 What you need
- A Kubernetes cluster (1.27 or newer) and `kubectl` with rights to create a namespace and objects in it.
- An **ingress controller**. The manifest uses the class `nginx` (NGINX Ingress Controller); another controller: change
  `ingressClassName` and remove the `nginx.ingress.kubernetes.io/*` annotations (their meaning: body up to 5 MB,
  long-lived live-update connections without buffering – configure the same in your controller). **F5 NGINX Ingress
  Controller** (annotations `nginx.org/*`, class usually `nginx`): `nginx.org/client-max-body-size: "5m"`,
  `nginx.org/proxy-read-timeout: "3600s"`, `nginx.org/proxy-buffering: "False"`. Without them live updates drop or
  arrive late (the console shows "offline").
- A **default StorageClass** (the database asks for a 10 Gi volume), or set one explicitly (4.6).
- A DNS name for Alerta Next pointing to the ingress, and HTTPS: TLS on the ingress or on a load balancer in front of it.
- Access to Docker Hub (or copy the images to your registry, 4.6).

### 4.2 The files
Applied in this order (the file names sort that way):

| File | Contents | Change |
|---|---|---|
| `00-namespace.yaml` | namespace `alerta-next`, Pod Security `restricted` | – |
| `01-secrets.yaml` | **secrets in plain text**: database login, Alertmanager login | **yes**: the database password |
| `10-config.yaml` | the backend configuration (`application.yml` + your `environment.yml`) | optional: Alertmanager URL |
| `20-database.yaml` | PostgreSQL 18, 1 pod, 10 Gi | optional: storage class; skip the file for an external database ([6.2](#62-external-or-central-postgresql)) |
| `30-backend.yaml` | backend, 2 replicas, Service, disruption budget | optional: image/registry |
| `40-frontend.yaml` | frontend, 2 replicas, Service, disruption budget | optional: image/registry |
| `50-ingress.yaml` | the Ingress | **yes**: host |
| `60-network-policies.yaml` | default deny + the allowed paths | – |

### 4.3 Step by step

**1. Get the files**

```sh
git clone https://github.com/arturkiwa/alerta-next.git
cd alerta-next/deploy/kubernetes
```

**2. Set the database password** in `01-secrets.yaml` (Secret `alerta-next-db`, key `password`). A random one:

```sh
openssl rand -base64 24 | tr -d '/+='
```

The bundled PostgreSQL takes it **only when it creates its data** (first start). Changing it later means changing it
in PostgreSQL too (`ALTER ROLE`) – or deleting the volume and starting over.

**3. Set your host name** in `50-ingress.yaml` (`host: alerta.example.com`). TLS:
- terminated **on the ingress** – add under `spec:` (with a Secret `alerta-tls` holding your certificate, or one
  issued by cert-manager):
  ```yaml
    tls:
      - hosts: [alerta.example.com]
        secretName: alerta-tls
  ```
- terminated **on a load balancer in front** (it sends HTTP to the ingress) – leave the file as it is.

**4. (Optional) silences from the console:** in `10-config.yaml` → `environment.yml` set
`alerta.integrations.alertmanager.url` (e.g. `http://alertmanager.monitoring.svc:9093`); if Alertmanager requires a
login, fill `alerta-next-alertmanager` in `01-secrets.yaml` (`token`, or `username` + `password`).

**5. Apply**

```sh
kubectl apply -f .
kubectl -n alerta-next rollout status statefulset/alerta-next-db
kubectl -n alerta-next rollout status deploy/alerta-next-backend     # 1–2 min at the first start
kubectl -n alerta-next rollout status deploy/alerta-next-frontend
kubectl -n alerta-next get pods                                      # all Running, READY 1/1
```

**6. Check from outside**

```sh
curl https://alerta.example.com/api/v1/ping
# {"status":"ok"}
```

**7. First administrator**

```sh
kubectl -n alerta-next exec deploy/alerta-next-backend -- alerta-admin create-admin admin "Administrator"
```

It prints a one-time password (only in your terminal). Open `https://alerta.example.com`, sign in as `admin`, set
your password. Then the same as in the quick start:
[3.6 role for yourself](#36-give-yourself-access-to-alerts), [3.7 environments](#37-create-the-environments-of-the-demo-alerts)
(with conditions for **your** labels), [3.8 API key](#38-create-an-api-key-for-alertmanager).

**8. Point your Alertmanager to it** – receiver in [8.1](#81-prometheus--alertmanager) with the URL
`https://alerta.example.com/api/v1/ingest/alertmanager`.

### 4.4 HTTPS is required
The session cookie is `Secure`: browsers keep it only over HTTPS. Without HTTPS the sign-in "does nothing". For a
test over plain HTTP only: in `30-backend.yaml` set `SESSION_COOKIE_SECURE` to `"false"` and apply again.

### 4.4a Client addresses behind the ingress (`TRUSTED_PROXIES`)
Login limits per address and the audit need the real client address. The frontend believes `X-Forwarded-For` only
from the proxies listed in `TRUSTED_PROXIES` (env of the frontend container, comma-separated addresses / CIDRs): the
ingress controller pods and a load balancer in front of them, if it forwards the client address. Empty (default) =
only the direct connection counts – safe (no client can fake an address), but every client appears as the ingress.
Set it in `40-frontend.yaml` (Helm: `frontend.trustedProxies`), e.g. the pod network of the ingress controller:
`10.233.64.0/18`. Check: *Administration → Audit log* shows the addresses of the users, not of the ingress.

**An empty `TRUSTED_PROXIES` in production is a problem, not just audit cosmetics:** the per-address limit of failed
sign-ins (`alerta.login.ip-max-failures`, 20 in 15 min) becomes shared by everyone – a few mistakes by different people
block sign-in for the whole organisation for a quarter of an hour.

**A load balancer (e.g. F5) in front of the ingress** – the client address must pass the whole chain:
1. the load balancer adds `X-Forwarded-For` (HTTP profile),
2. the ingress controller **passes it on** instead of overwriting it – ingress-nginx (community), in its ConfigMap:
   `use-forwarded-headers: "true"`, `proxy-real-ip-cidr: <LB addresses>`; F5 NGINX Ingress Controller:
   `set-real-ip-from: <LB addresses>`, `real-ip-header: X-Forwarded-For`, `real-ip-recursive: "True"`,
3. `TRUSTED_PROXIES` = the pod network of the ingress controller **and** the load balancer addresses.

A load balancer that does not forward the client address: list only the pod network – the audit shows the load
balancer, and the per-address sign-in limit stays shared (locking an account after failed attempts works regardless).
To check the chain: sign in once with a wrong password – the audit entry has the address of your workstation.

### 4.5 Configuration changes
Edit `10-config.yaml` (your settings in `environment.yml`), then:

```sh
kubectl apply -f 10-config.yaml
kubectl -n alerta-next rollout restart deploy/alerta-next-backend
```

An invalid value stops the backend at start with the key named in the log (`kubectl -n alerta-next logs
deploy/alerta-next-backend`); the running replicas keep working until the new ones are ready.

### 4.6 Your registry, storage class
- **Images from your registry**: change `image:` in `30-backend.yaml`, `40-frontend.yaml`, `20-database.yaml`. A
  registry with a login needs a pull Secret and a reference in both Deployments:
  ```sh
  kubectl -n alerta-next create secret docker-registry registry-login \
    --docker-server=<registry> --docker-username=<user> --docker-password=<password>
  ```
  ```yaml
      # in 30-backend.yaml and 40-frontend.yaml, under spec.template.spec:
      imagePullSecrets:
        - name: registry-login
  ```
- **Storage class**: in `20-database.yaml` under `volumeClaimTemplates[0].spec` add `storageClassName: <name>`.

### 4.7 Network policies
`60-network-policies.yaml` denies everything and allows only: DNS (port 53), ingress → frontend (8080),
frontend → backend (8080), backend → database (5432), anyone → backend metrics (8081), backend → Alertmanager (9093).
If your cluster does not enforce NetworkPolicies they are ignored. External database: add an egress rule, see
[6.2](#62-external-or-central-postgresql).

### 4.8 Upgrade and removal
- **Upgrade**: change the image tags (backend and frontend to the same version) and `kubectl apply -f .`. Pods are
  replaced one by one without an outage; database migrations run at start and are backward compatible with the
  previous version. What is guaranteed between versions (configuration, API, metrics, logs, skipping versions,
  rollback): [compatibility policy](../compatibility-policy.md) (in Polish).
- **Removal**: `kubectl delete namespace alerta-next` (deletes everything, including the database volume).

### 4.9 If something does not work
| Symptom | Cause / fix |
|---|---|
| `ImagePullBackOff` | image name/registry or pull Secret (4.6) |
| database pod `Pending` | no default StorageClass – set one (4.6) |
| pods restart, log "UnknownHostException" / "host not found" | DNS blocked by network policies in your cluster – check `allow-dns` fits your cluster DNS |
| backend log "password authentication failed" | the password in `01-secrets.yaml` differs from the one the database was created with (4.3 step 2) |
| sign-in does not stick | no HTTPS (4.4) |
| Alertmanager log `401` | wrong API key in Alertmanager's `credentials_file` |
| alerts in the quarantine | environment conditions do not match the labels |

### 4.10 Alternative: Helm chart
The same installation as a parametrised chart in [`deploy/helm/alerta-next`](../../deploy/helm/alerta-next) (Helm 3).
Every parameter is described in its [`values.yaml`](../../deploy/helm/alerta-next/values.yaml); three ready examples
are in `examples/`. By default the chart creates the Secrets from your values file (plain text – fine for a demo);
for production use your own Secrets or HashiCorp Vault via the Secrets Store CSI Driver (`secrets.mode`,
[5.1](#51-helm-where-the-secrets-come-from-secretsmode)). NetworkPolicies are off by default
(`networkPolicy.enabled`).

**1. Your values file** (start from `examples/values-demo.yaml`):

```yaml
database:
  password: <long random password>     # openssl rand -base64 24 | tr -d '/+='
ingress:
  host: alerta.example.com
```

**2. Install**

```sh
helm install alerta-next deploy/helm/alerta-next -n alerta-next --create-namespace -f my-values.yaml
kubectl -n alerta-next rollout status deploy/alerta-next-backend
```

The chart refuses to render with a clear message when something required is missing (password, host …).

**3. First administrator and the rest** – exactly as in 4.3 from step 6 (the commands are also printed by
`helm install`).

**Your CA** (for Alertmanager, SSO and the database over TLS) – one of:

```sh
helm upgrade --install alerta-next deploy/helm/alerta-next -n alerta-next -f my-values.yaml \
  --set-file internalCA.certificate=./ca.crt                 # file next to you
```
- pasted into the values file as `internalCA.certificate: |` (a CA certificate is public; this is the way for GitOps),
- or a ConfigMap created beforehand (`kubectl -n alerta-next create configmap my-ca --from-file=ca.crt=./ca.crt`)
  and `internalCA.existingConfigMap: my-ca`.

The chart mounts it as `/etc/alerta/ca/ca.crt` and uses it for the Alertmanager API, SSO and – with
`database.external.sslMode: verify-full` – the database.

**All parameters** (details and examples in the comments of [`values.yaml`](../../deploy/helm/alerta-next/values.yaml))

| Parameter | Meaning |
|---|---|
| `fullnameOverride` | base name of all objects (e.g. `alerta` → `alerta-backend`, `alerta-db`); empty = the release name |
| `image.registry`, `.backend`, `.frontend` | registry and image names (your registry mirror, 4.6) |
| `image.tag`, `.pullPolicy`, `.pullSecrets` | version (empty = chart `appVersion`; backend and frontend always the same), pull policy, pull Secrets |
| `secrets.mode` (`values` / `existing` / `csi`) | where secrets come from ([5.1](#51-helm-where-the-secrets-come-from-secretsmode)) |
| `secrets.csi.vault.address`, `.authPath`, `.role`, `.namespace`, `.objects` | Vault through CSI: address, path of the Kubernetes auth method, role, Vault Enterprise namespace, where each secret lives ([5.2](#52-vault-with-the-secrets-store-csi-driver-step-by-step)) |
| `secrets.csi.secretProviderClass` | your own `SecretProviderClass` / another CSI provider instead of Vault (empty with Vault) |
| `database.username`, `.password` / `.existingSecret` | the application's database login (with the internal database also the superuser, set only at the first start) |
| `database.migrationUsername`, `.migrationPassword` | separate account for schema migrations (external database, [6.2](#62-external-or-central-postgresql)); both or none |
| `database.internal.enabled`, `.image`, `.storageClass`, `.size` | PostgreSQL in the cluster (one pod, no HA) and its volume |
| `database.internal.resources`, `.nodeSelector`, `.tolerations`, `.affinity` | resources and placement of the database pod |
| `database.internal.backup.enabled`, `.schedule`, `.keep`, `.storageClass`, `.size`, `.resources` | nightly dump of the internal database to a separate volume ([runbook](backup-runbook.md)); `schedule` in the cluster's time zone |
| `database.external.host`, `.port`, `.name`, `.sslMode` (or `.url`) | external database ([6.2](#62-external-or-central-postgresql)); `url` wins over the rest |
| `database.schema`, `database.migrate` | schema of Alerta Next; `false` = a DBA applies the migrations |
| `database.poolSize` | connections per backend replica (default 20); `max_connections` ≥ (replicas + 1) × `poolSize` |
| `internalCA.certificate` / `.existingConfigMap` | your CA (above) |
| `alertmanager.url`, `.token` / `.username`+`.password` / `.existingSecret` | Alertmanager `default` – silences from the console. Deprecated next to `alertmanagers[]`, works until 2.0 ([compatibility policy](../compatibility-policy.md)) |
| `alertmanagers[]` (`name`, `url`, login as above) | further Alertmanagers ([8.2](#82-several-alertmanagers)); Vault CSI: objects `ALERTMANAGER_<NAME>_TOKEN` etc. |
| `mail.smarthost`, `.from`, `.hello`, `.requireTls`, `.username`, `.password` / `.existingSecret` | outgoing mail (names as Alertmanager's `smtp_*`); Vault CSI: object `MAIL_PASSWORD` |
| `mail.consoleUrl`, `.timeZone`, **`.allowedDomains` (required)** | links in mails (empty = `https://<ingress.host>`), report time zone for users without one in their profile, the only domains mail may go to |
| `notifications.enabled`, `.batchWindow`, `.minInterval` | e-mail notifications by rules (needs `mail.smarthost`) |
| `oidc.enabled`, `.issuer`, `.clientId`, `.clientSecret` / `.existingSecret`, `.claims` | single sign-on |
| `oidc.label` | SSO sign-in button text; empty = default |
| `config` | any application setting ([section 7](#7-configuration)), wins over everything |
| `session.cookieSecure` | `false` only for a plain-HTTP test (4.4) |
| `logs.consoleFormat` (`text`/`ecs`), `logs.file.enabled`, `logs.serviceEnvironment` | log format for ELK; `serviceEnvironment` = the `service.environment` field in JSON |
| `backend.replicas`, `frontend.replicas` | number of replicas (default 2; 2+ = upgrades without downtime) |
| `backend.resources`, `frontend.resources` | requests / limits |
| `backend.*` and `frontend.*`: `nodeSelector`, `tolerations`, `affinity`, `priorityClassName`, `spreadAcrossNodes` | pod placement (`spreadAcrossNodes` – soft spread of the replicas over nodes, on by default) |
| `backend.*` and `frontend.*`: `pdb.enabled`, `pdb.minAvailable` | PodDisruptionBudget (on by default, at least 1 pod) |
| `backend.*` and `frontend.*`: `podAnnotations`, `podLabels` | your own pod annotations and labels (e.g. for Istio, a log agent) |
| `backend.extraEnv`, `.extraVolumes`, `.extraVolumeMounts`, `.extraContainers` | extra variables (e.g. `JAVA_TOOL_OPTIONS`), volumes and sidecars (e.g. a log agent reading `/var/log/alerta`, volume `logs`) |
| `frontend.trustedProxies` | proxies whose `X-Forwarded-For` is believed (4.4a) |
| `ingress.enabled`, `.className`, `.host` | access; `enabled: false` = your own Ingress / Route / Gateway |
| `ingress.annotations` | by default NGINX Ingress: request size 5m, `proxy-read-timeout` 3600 and no buffering (live updates, SSE). Another controller: replace with its equivalents (F5 NGINX: example in `values.yaml`) |
| `ingress.tls.enabled`, `.secretName` | TLS on the ingress; `false` = TLS ends on a load balancer in front of it |
| `metrics.podAnnotations`, `metrics.serviceMonitor.enabled`, `.interval`, `.labels` | Prometheus scraping (annotations or a Prometheus Operator ServiceMonitor) |
| `networkPolicy.enabled` | network policies (off by default, 4.7) |
| `networkPolicy.ingressFrom`, `.metricsFrom` | who may reach the frontend and who may scrape metrics on 8081 (`NetworkPolicyPeer` list; empty = anyone) |
| `networkPolicy.extraEgress` | backend egress besides DNS and the internal database: external database, Alertmanager, SSO, mail |

**Changes and upgrades**: edit the values file and `helm upgrade alerta-next deploy/helm/alerta-next -n alerta-next
-f my-values.yaml` – the backend restarts by itself when its configuration, Secrets or CA change. A new version:
`--set image.tag=<version>` (or a newer chart). **Removal**: `helm uninstall alerta-next -n alerta-next` keeps the
database volume (PVC `data-alerta-next-db-0`); `kubectl delete namespace alerta-next` removes everything.

---

## 5. Secrets

Every secret Alerta Next uses. In a demo they come from `01-secrets.yaml`; in production create **the same Secrets
(names and keys)** with your tooling – HashiCorp Vault (Vault Agent / Vault Secrets Operator), External Secrets
Operator, Sealed Secrets, your CI … The application reads them as environment variables; it never needs to know
where they come from.

| Secret | Key | Required | Used for | Environment variable |
|---|---|---|---|---|
| `alerta-next-db` | `username` | yes | database login of the application (bundled PostgreSQL: also its superuser) | `DB_USER` |
| `alerta-next-db` | `password` | yes | its password | `DB_PASSWORD` |
| `alerta-next-db` | `migration-username`, `migration-password` | no | separate account for schema migrations (external database, [6.2](#62-external-or-central-postgresql)) | `DB_MIGRATION_USER`, `DB_MIGRATION_PASSWORD` |
| `alerta-next-alertmanager` | `token` | no | Alertmanager API login (Bearer) – silences | `ALERTMANAGER_TOKEN` |
| `alerta-next-alertmanager` | `username`, `password` | no | Alertmanager API login (basic auth) – silences | `ALERTMANAGER_USERNAME`, `ALERTMANAGER_PASSWORD` |
| `alerta-next-oidc` | `client-secret` | only with SSO | OpenID Connect client secret ([7](#7-configuration)) | `OIDC_CLIENT_SECRET` |

Not secrets of the application, but secret material you will have:
- **API keys** (`ank_…`) – created in the UI, stored only as a hash; each sender keeps its own (e.g. Alertmanager's
  `credentials_file`).
- **One-time passwords** of `alerta-admin` – only in the terminal of whoever ran it.
- Your **TLS certificate** – on the ingress / load balancer.
- A **pull Secret** for a private registry (4.6).

Nothing secret is in the ConfigMap (`10-config.yaml`), the images or the logs (passwords never appear in logs).

### 5.1 Helm: where the secrets come from (`secrets.mode`)

| `secrets.mode` | Secrets come from | For |
|---|---|---|
| `values` (default) | plain text in your values file (`database.password`, `alertmanager.token`, `oidc.clientSecret`); the chart creates the Kubernetes Secrets | demos, tests |
| `existing` | Kubernetes Secrets you create (`database.existingSecret`, `alertmanager.existingSecret`, `oidc.existingSecret`) with the keys from the table above – by hand, Vault Secrets Operator, External Secrets … | production with a Secret operator |
| `csi` | **HashiCorp Vault via the Secrets Store CSI Driver** – mounted as files in the pods, never stored as Kubernetes Secrets | production with Vault + CSI |

### 5.2 Vault with the Secrets Store CSI Driver, step by step
Needed in the cluster: the [Secrets Store CSI Driver](https://secrets-store-csi-driver.sigs.k8s.io/) and the
[Vault CSI provider](https://developer.hashicorp.com/vault/docs/platform/k8s/csi) (usually already there when your
cluster uses them). Needed in Vault: the Kubernetes auth method configured for this cluster.

**1. Find the auth path** of this cluster's Kubernetes auth method:

```sh
vault auth list          # the row of type "kubernetes", e.g. "kubernetes/" or "k8s-sandbox/" – the name without "/"
```

**2. Store the secrets** (KV v2 at `secret/`; your mount and paths may differ):

```sh
vault kv put secret/alerta-next/db username=alerta password="$(openssl rand -base64 24 | tr -d '/+=')"
# optional: vault kv put secret/alerta-next/alertmanager token=<token>
# with SSO: vault kv put secret/alerta-next/oidc client-secret=<secret>
```

With the internal database, the password is used only when the data is created (first start); change it later only
together with `ALTER ROLE` in PostgreSQL.

**3. Policy and role** (replace `kubernetes` with your auth path; namespace and release name `alerta-next` if yours
differ):

```sh
vault policy write alerta-next - <<'POLICY'
path "secret/data/alerta-next/*" { capabilities = ["read"] }
POLICY
vault write auth/kubernetes/role/alerta-next \
  bound_service_account_names=alerta-next-backend,alerta-next-db \
  bound_service_account_namespaces=alerta-next \
  policies=alerta-next ttl=20m
```

The service accounts are `<release>-backend` and `<release>-db` (the latter only with the internal database); with
the release name `alerta-next` exactly as above. Note: a release name without "alerta-next" (e.g. `helm install alerta …`) gives
`alerta-alerta-next-backend` – if the Vault role has other names already, set them in values: `fullnameOverride: alerta`
→ `alerta-backend`, `alerta-db`. `helm install` prints them too.

**4. Values** (from `examples/values-vault-csi.yaml`):

```yaml
secrets:
  mode: csi
  csi:
    vault:
      address: https://vault.example.com:8200
      authPath: kubernetes          # from step 1
      role: alerta-next             # from step 3
      objects:                      # names on the left are fixed; path/key = where it is in Vault (KV v2: …/data/…)
        DB_USER: { path: secret/data/alerta-next/db, key: username }
        DB_PASSWORD: { path: secret/data/alerta-next/db, key: password }
        # ALERTMANAGER_TOKEN: { path: secret/data/alerta-next/alertmanager, key: token }
        # OIDC_CLIENT_SECRET: { path: secret/data/alerta-next/oidc, key: client-secret }
```

Possible names: `DB_USER`, `DB_PASSWORD` (required), `DB_MIGRATION_USER`, `DB_MIGRATION_PASSWORD`,
`ALERTMANAGER_TOKEN` or `ALERTMANAGER_USERNAME` + `ALERTMANAGER_PASSWORD`, `OIDC_CLIENT_SECRET` (required with SSO), `MAIL_PASSWORD`;
further Alertmanagers: `ALERTMANAGER_<NAME>_TOKEN` or `_USERNAME` + `_PASSWORD` (the name in capitals, "-" → "_").

**5. Install** – `helm install …` as in 4.10. The chart creates a `SecretProviderClass` for the backend (all objects)
and one for the internal database (only `DB_USER`, `DB_PASSWORD`); the values appear in the pods as files in
`/etc/alerta/secrets/`.

**Troubleshooting.** Pods stuck in `ContainerCreating`: `kubectl -n alerta-next describe pod <pod>` – the events show
Vault's answer: `permission denied` = policy or role (step 3: service account, namespace, policy path with `/data/`);
secret or key not found = `path` or `key` in `objects`; connection errors = `address`, or the Vault CA in the Vault
CSI provider's configuration (TLS to Vault is made by the provider, not by Alerta Next).

**Rotation.** The backend reads the secrets at start-up. After changing a value in Vault restart it:
`kubectl -n alerta-next rollout restart deploy/alerta-next-backend`.

**Another CSI provider** (AWS, Azure, GCP) or your own `SecretProviderClass`: set `secrets.csi.secretProviderClass`
to its name; it must deliver files named like the object names above.

---

## 6. Database

### 6.1 Bundled PostgreSQL (in the cluster / compose)
One PostgreSQL 18 with a 10 Gi volume, **no high availability**. Backups: with Helm a nightly dump to a separate volume
(`database.internal.backup.enabled: true`) – the whole backup and restore procedure: **[runbook](backup-runbook.md)**.
A manual dump:

```sh
kubectl -n alerta-next exec alerta-next-db-0 -- sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" -Fc alerta' > alerta-$(date +%F).dump
# compose: docker compose exec -T db pg_dump -U alerta -Fc alerta > alerta-$(date +%F).dump
```

Helm (the database login and password are files there, not variables; `<release>` – the installation name):

```sh
kubectl -n <ns> exec <release>-db-0 -- sh -c \
  'PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")" pg_dump -h 127.0.0.1 -U "$(cat "$POSTGRES_USER_FILE")" -Fc "$POSTGRES_DB"' \
  > alerta-$(date +%F).dump
```

Take a dump at least **before every upgrade** (a new version may bring schema migrations). Restore – step by step in the
[runbook](backup-runbook.md#3-restore) (keeping the current state, sessions, access undone by the restore).
A lost database means losing the configuration (environments, access, API keys, labels, views) and the history with
the audit – the alerts themselves Alertmanager sends again.

### 6.2 External or central PostgreSQL
Use this when your organisation runs PostgreSQL centrally (administration, backups, HA), or you want your own
outside the cluster.

**What the database must provide**
- PostgreSQL **18** (the version Alerta Next is tested with), UTF-8. No extensions needed.
- Connections: each backend replica opens up to **20** (`DB_POOL_SIZE`). `max_connections` ≥ (replicas + 1) × 20 +
  a few for `alerta-admin` – with 2 replicas: ≥ 70 for Alerta Next.
- The application never changes the schema at run time; **migrations** (Flyway, `backend/src/main/resources/db/migration`)
  run at start – with a separate account if you want (below) – or are applied by the DBA.
- Network access from the backend pods to the database port; TLS recommended.

**Variant A – one account (simplest).** For the DBA:

```sql
CREATE ROLE alerta LOGIN PASSWORD '<password>';
CREATE DATABASE alerta OWNER alerta ENCODING 'UTF8';
```

Alerta Next: `DB_URL=jdbc:postgresql://<host>:5432/alerta`, `DB_USER=alerta`, `DB_PASSWORD=<password>`.

**Variant B – schema in a shared database, separate migration account (least privilege).** For the DBA:

```sql
-- in the target database, e.g. "monitoring"
CREATE ROLE alerta_owner LOGIN PASSWORD '<owner password>';     -- runs migrations (DDL), owns the tables
CREATE ROLE alerta_app   LOGIN PASSWORD '<app password>';       -- the application at run time: data only
CREATE SCHEMA alerta_next AUTHORIZATION alerta_owner;
GRANT USAGE ON SCHEMA alerta_next TO alerta_app;
ALTER DEFAULT PRIVILEGES FOR ROLE alerta_owner IN SCHEMA alerta_next
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO alerta_app;
ALTER DEFAULT PRIVILEGES FOR ROLE alerta_owner IN SCHEMA alerta_next
  GRANT USAGE, SELECT ON SEQUENCES TO alerta_app;
```

Alerta Next:

| Variable | Value |
|---|---|
| `DB_URL` | `jdbc:postgresql://<host>:5432/monitoring` |
| `DB_SCHEMA` | `alerta_next` |
| `DB_USER` / `DB_PASSWORD` | `alerta_app` (Secret `alerta-next-db`: `username`, `password`) |
| `DB_MIGRATION_USER` / `DB_MIGRATION_PASSWORD` | `alerta_owner` (Secret `alerta-next-db`: `migration-username`, `migration-password`) |

**Variant C – the DBA applies migrations.** Set `DB_MIGRATE=false`; the DBA applies the files
`backend/src/main/resources/db/migration/V*.sql` in version order (`V1`, `V2`, … – numeric order) **before** each
upgrade of Alerta Next. The application checks at start that the schema matches and refuses to start otherwise.

**TLS to the database.** Add to `DB_URL`: `?sslmode=verify-full&sslrootcert=/etc/alerta/db-ca/ca.crt` and mount the CA
certificate there (see below). `sslmode=require` encrypts without checking the certificate (not recommended).

**In the Kubernetes manifests**
1. Do **not** apply `20-database.yaml` (delete it from the directory, or apply the other files one by one).
2. In `01-secrets.yaml` put the application account (and, for variant B, `migration-username` / `migration-password`).
3. In `30-backend.yaml`, in the `env:` of the container `backend`, change `DB_URL` and add what your variant needs:
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
   and for TLS the CA certificate (a ConfigMap `alerta-next-db-ca` with the key `ca.crt`):
   ```yaml
          # under the container "backend", next to the existing volumeMounts:
            - name: db-ca
              mountPath: /etc/alerta/db-ca
              readOnly: true
      # under spec.template.spec.volumes:
        - name: db-ca
          configMap: { name: alerta-next-db-ca }
   ```
   ```sh
   kubectl -n alerta-next create configmap alerta-next-db-ca --from-file=ca.crt=<your-ca.pem>
   ```
4. Allow the backend to reach the database – add to `60-network-policies.yaml`:
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
           - ipBlock: { cidr: 10.20.30.40/32 }    # your database address (or range)
         ports:
           - { protocol: TCP, port: 5432 }
   ```

**In the quick start**: `.env` → `DB_URL`, `DB_USER`, `DB_PASSWORD`; start with
`docker compose up -d --no-deps frontend backend` (the bundled database is not started).

### 6.3 Backups
Bundled database: the chart's nightly dump + a copy outside the cluster + a restore test every quarter –
[runbook](backup-runbook.md). With a central database, backups are the DBA's – Alerta Next needs nothing special: a
consistent dump or PITR of the database/schema is enough to restore it; after a restore, steps 3.4–3.6 of the runbook
apply.

---

## 7. Configuration

Two places:
- **Environment variables** (connection data and secrets) – in `30-backend.yaml` / `.env`.
- **`application.yml`** (behaviour) – in Kubernetes the ConfigMap in `10-config.yaml`: the file `application.yml`
  lists every setting with its default and a comment; put **your** changes into `environment.yml` in the same
  ConfigMap (it wins). The quick start uses the defaults built into the image.

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `DB_URL` | – | JDBC URL of PostgreSQL |
| `DB_USER`, `DB_PASSWORD` | – | application account (from a Secret) |
| `DB_SCHEMA` | `public` | schema of Alerta Next (must exist) |
| `DB_POOL_SIZE` | `20` | connections per backend replica |
| `DB_CONNECTION_TIMEOUT_MS` | `10000` | waiting for a free connection |
| `DB_MIGRATE` | `true` | `false` = migrations applied by the DBA |
| `DB_MIGRATION_USER`, `DB_MIGRATION_PASSWORD` | the application account | account for migrations |
| `SESSION_COOKIE_SECURE` | `true` | `false` only for plain HTTP tests |
| `ALERTMANAGER_URL` | empty | Alertmanager API for silences |
| `ALERTMANAGER_TOKEN` / `ALERTMANAGER_USERNAME` + `ALERTMANAGER_PASSWORD` | empty | its login |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | empty | single sign-on (with `alerta.auth.oidc.enabled: true`) |

### Frequently changed settings (`environment.yml`)

```yaml
alerta:
  auth:
    local:
      mode: ENABLED              # ENABLED | BREAK_GLASS_ONLY (only listed emergency accounts) | DISABLED
      break-glass-users: []
    oidc:                        # single sign-on with any OpenID Connect provider (Keycloak, Entra ID …)
      enabled: false
      issuer: https://sso.example.com/realms/example
      client-id: alerta-next     # secret: OIDC_CLIENT_SECRET
      # redirect-uri: https://alerta.example.com/api/v1/auth/oidc/callback
      #   default {baseUrl}/api/v1/auth/oidc/callback – from the request. When TLS ends before the ingress (F5) and the
      #   request arrives as http, SSO refuses the redirect_uri: set the full https address. The address to come back
      #   to after signing out is taken from it too (https://<host>/login?reason=LOGGED_OUT). In the Keycloak client:
      #   Valid redirect URIs = this address, Valid post logout redirect URIs = https://<host>/login*
      claims: { username: preferred_username, display-name: name, email: email, groups: groups }
  accounts:
    inactive-disable-after: 90d  # a local account unused this long (since sign-in, creation, password reset, enabling)
                                 # is disabled within the hour; empty = never, min. 30d. Never SSO, kiosk, break-glass
                                 # accounts or the last access administrator. Who would go: Access review
  integrations:
    alertmanager:
      url: http://alertmanager.monitoring.svc:9093
      ca-file: ""                # CA (PEM) for TLS to Alertmanager, if needed
  alerts:
    ack-timeout: 8h              # an acknowledgement lapses after this (per environment in the UI)
    resolve-grace: 5m            # "resolved" counts only if the alert stays quiet this long
    highlight-new: 10m           # the console highlights a new or returning alert this long; 0 = off
    watchdog-timeout: 5m         # a Watchdog (one per Prometheus and Alertmanager) missing this long: WatchdogMissing
  passwords:
    forbidden-words: [alerta, company-name, system-name]  # words a password may not contain (any case; replaces the default list)
    one-time-validity: 72h       # validity of a one-time password (new account, reset)
  session:
    idle-privileged: 30m         # idle limit for administrators
    idle-standard: 8h            # idle limit for operators
  environments:
    classes:                     # environment classes and default retention (days)
      - { code: PROD, retention-days: 400 }
      - { code: TEST, retention-days: 30 }
```

Labels with a meaning (shown first in the details, values on the alert list, quick filters, report grouping, marks on the list) and shared
views are **set in the UI** (Administration → Labels / Views), not in the configuration.

Severity: the common Critical / Error / Warning / Info scale – CRITICAL, ERROR, WARNING, INFORMATIONAL (plus NORMAL);
any label value is mapped by `alerta.alerts.severity-aliases` (built in: critical, error, err, warning, info,
informational, normal, ok; e.g. for Zabbix add disaster → CRITICAL, high → ERROR, average → WARNING, information →
INFORMATIONAL – the map is replaced as a whole). A value no alias knows makes the alert UNKNOWN – *System status → Unrecognised
severities* lists such values of the last 30 days, so the alias to add is obvious.

Single sign-on in detail: [deploy/k8s/README.md](../../deploy/k8s/README.md) (section "Logowanie przez SSO").

### Daily e-mail report

Every user with an e-mail address can switch on a daily summary in *Profile → E-mail report*: they choose the
environments (of those they may read – checked at every sending), severities and hour; "Send a test report" checks
right away that mail arrives. The server only needs an SMTP relay – names as in Alertmanager:

```yaml
alerta:
  mail:
    from: alerta@example.com              # smtp_from
    hello: alerta.example.com             # smtp_hello
    smarthost: 10.1.2.3:25                 # smtp_smarthost HOST:PORT (465 = TLS from the start)
    require-tls: false                     # smtp_require_tls – STARTTLS required (with the CA of internalCA / ca-file)
    username: ""                           # empty = relay without sign-in; with it the password from MAIL_PASSWORD
    console-url: https://alerta.example.com   # links in the mail (Helm: https://<ingress.host> by default)
    allowed-domains: [example.com]        # REQUIRED: the only domains mail may go to
```

In Helm: the `mail` section of values (password: `mail.password` / `mail.existingSecret` / Vault object `MAIL_PASSWORD`).
Without `smarthost` the report is not offered. Sent once per cluster (with several replicas).

**Allowed domains only.** With `smarthost` the list `allowed-domains` (Helm: `mail.allowedDomains`) is required – without
it the application does not start and Helm refuses to render. The domain must match exactly (any letter case);
subdomains only when listed. The address must be a plain address (no display name, quotes, second `@`, list). The
check sits in the one place every message passes – at sending, not only when settings are saved. A user with an
address outside the list sees in the profile that the report is not available.

**Audit of sending** (audit log and the log for the SIEM): `mail.sent` – every message sent (to whom, which report),
`mail.failed` – the relay refused it, `mail.blocked` (outcome DENIED) – an attempt to send to an address outside the
list (reason: `domain-not-allowed` / `not-an-address`); nothing goes out then. The entries stay even when the rest of
the operation rolls back.

### Links to tools (Grafana, Kibana …)

In *Administration → Labels → Links to tools* an access administrator defines buttons in the alert details: a name
and an address with the alert's labels, e.g. `https://grafana.example.com/d/abc?var-namespace={namespace}&var-pod={pod}`.
A button appears only for alerts that have every label it uses. The server builds the address: values are encoded
(they cannot add a parameter or a path), a value in the host name (`https://grafana-{cluster}.example.com/…`) may only
be one DNS label. https only, and only to the hosts in the configuration – without it no links can be defined. The
same list decides on the links of changes from ArgoCD / CI (8.6):

```yaml
alerta:
  links:
    allowed-hosts: [grafana.example.com, "*.kibana.example.com"]   # exact, or any host under the domain
```

### E-mail notifications (instead of receivers in Alertmanager)

Mails about alerts by rules set in the application (page *Notifications*, permission "Manage notifications" – the
Maintainer role has it in its environments). A rule: environments, severities, label conditions (`team=db, dba`,
`service!=web`), **recipient groups**, reminders (every 15 min … 24 h while nobody acknowledges, at most N times) and
the resolution (only to those who got a mail about the alert). No templates or files of your own – the content is
fixed, everything from senders escaped.

Switched on **only in the configuration** (never in the UI) and only with mail (section above):

```yaml
alerta:
  notifications:
    enabled: true
    batch-window: 2m      # what arrives for one person within this time goes out in one mail
    min-interval: 5m      # at most one mail per person this often (the rest waits for the next one)
```

Helm: `notifications.enabled: true` (needs `mail.smarthost`), `notifications.batchWindow`, `notifications.minInterval`.

Rules of sending: mail only to people who may read the alert's environment **at sending time**, and only at an allowed
domain; acknowledged, closed, silenced (also by a maintenance window) alerts do not notify; an alert coming back within
an hour of a mail about it (flapping) – one notice, then quiet, and "resolved" only once it stays away for an hour; alerts already firing when the rule was created (switched on) are not sent. Sent once per cluster (with several
replicas, each person by one of them, claimed right before their mail), retried when the relay fails, outside database transactions (a slow relay holds no connection). At least
once: if a replica dies after the relay accepted a mail but before the result was written, the mail goes again after
10 minutes – never lost. Every mail in the audit log (`mail.sent`), rule changes as
`notification-rule.*`; the queue and what was not sent on *System status*.

**Office hours:** an access administrator sets them on the group's page (days, from–to; zone `mail.time-zone`); anyone
can choose in the profile "as my groups", "always by e-mail" or their own hours – their choice wins. Within office hours
notifications stay in the console only (on *System status* as "office hours"); critical ones still go by mail unless the
person turns that off in the profile.

**Moving from Alertmanager:** environment by environment – first the rule in Alerta alongside Alertmanager's mails,
once checked switch the receiver off in Alertmanager. Failures of Alerta itself are still reported by Alertmanager
(rules `alerta-next.yml`, Watchdog).

---

## 8. Connecting alert senders

### 8.1 Prometheus / Alertmanager
In Alertmanager's configuration, a receiver with the API key **in a file** (not in the configuration itself), and
**one route to Alerta Next at the top of the tree** that takes everything:

```yaml
receivers:
  - name: alerta-next
    webhook_configs:
      - url: https://alerta.example.com/api/v1/ingest/alertmanager
        send_resolved: true               # required: resolutions must arrive
        http_config:
          authorization:
            type: Bearer
            credentials_file: /etc/alertmanager/secrets/alerta-next-token   # the ank_… key, one line
route:
  receiver: <your default receiver>
  routes:
    - receiver: alerta-next               # first, without matchers: every alert
      continue: true                      # keep your existing notifications working
      group_by: ['...']                   # one notification per alert – no grouping delay on the way to the console
      group_wait: 0s
      group_interval: 1m
      repeat_interval: 1m                 # also the Watchdog's pace – keep it below alerta.alerts.watchdog-timeout (5 m)
```

The route to Alerta Next does not need to distinguish anything: which environment an alert belongs to, who sees it
and what is silenced for a whole environment is decided in Alerta Next (environments with label conditions, roles,
blackouts). The rest of the routing tree stays only for notifications (mail, chat, pager).

Recommended in Prometheus:
- `for:` on threshold rules (and `keep_firing_for:` from Prometheus 2.42) – fewer alerts that come and go.
- An always-firing **Watchdog** rule (`expr: vector(1)`, `alertname: Watchdog`) in **every** Prometheus. Alerta Next
  keeps one Watchdog per Prometheus (told apart by its labels, e.g. `cluster`) and per Alertmanager: page *System
  status* lists them, and one that stops for longer than `alerta.alerts.watchdog-timeout` (5 m) opens
  **`WatchdogMissing`** – so a single cluster that went silent is noticed, not hidden by the others.
- Labels that decide the environment (e.g. `cluster`, `environment`) on every alert – via `external_labels` of each
  Prometheus.

`WatchdogMissing` carries the Watchdog's labels, so it lands in the environment they match. When a cluster holds
several environments told apart by `namespace` (DEV1, DEV2 … on one cluster `dev`), the Watchdog (no namespace) matches
none of them – it goes to the quarantine. Create a technical environment for the cluster itself, e.g. `DEV-CLUSTER`
with the only condition `cluster = dev`: the namespace-based environments stay more specific and keep their alerts.

### 8.2 Several Alertmanagers
Alerta Next works with one Alertmanager or several – e.g. one per cluster. API keys **name no** Alertmanager – Alerta
asks every configured one:
- a silence from the console goes to every Alertmanager that has the alert (none – refused, it would silence nothing);
- a blackout (maintenance window) is created in every Alertmanager (all or none);
- an alert is silenced when any Alertmanager silences it; one that is down never "unsilences" alerts, and an alert none
  has at the moment (resolved) keeps its last known state;
- page *Silences* shows all of them with the Alertmanager's name; *System status* shows each one's last sync.

Steps for another Alertmanager:
1. Add it to the configuration – Helm `alertmanagers:` in the values (secrets per mode, see `values.yaml`), or in
   `environment.yml`:
   ```yaml
   alerta:
     integrations:
       alertmanagers:
         - name: waw                                   # [a-z][a-z0-9-]*, unique
           url: https://alertmanager.waw.example.com
           bearer-token: ${ALERTMANAGER_WAW_TOKEN:}    # or username / password; also ca-file, timeout
   ```
   and restart the backend. A wrong name, a missing URL or a name used twice stops the start-up with the key in the log.
2. **Administration → API keys → New key** (simplest: all environments) and give the key to that Alertmanager (8.1).
   An existing key's environments are changed with "Environments" – no new key.

An older configuration with the single `alertmanager:` (named "default") still works; next to the `alertmanagers:` list
the application warns in its log – move it into the list with a name of its own.

**One path per alert.** The same alert (the same labels) delivered by two independent Alertmanagers is one alert in the
console, and "resolved" from one while the other still fires makes it flicker. Route every alert to Alerta Next through
one Alertmanager; the external labels of each Prometheus usually make alerts distinct anyway.

### 8.3 Thanos Ruler
Alerts evaluated by Thanos Ruler reach Alerta Next the same way (Ruler → Alertmanager → Alerta Next) – nothing to set up
in Alerta Next. Three rules for the teams writing such alert rules:
1. **Keep the labels that decide the environment.** The Ruler sees data of all clusters: an aggregation without
   `by (cluster)` drops `cluster` and the alert lands in the quarantine (nothing is lost, but fix the rule). Or set an
   explicit `environment` label in the rule.
2. **A rule lives in one place** – in the local Prometheus or in the Ruler. The same rule in both gives two alerts
   (different external labels).
3. **Failed queries resolve alerts.** When a query to Thanos fails (Store unavailable, partial response), the rule
   returns nothing and the alert goes away. The resolution grace (5 m) hides short gaps; for longer ones use
   `partial_response_strategy: abort` in alerting rule groups and alert on the Ruler's evaluation failures.

### 8.4 Other senders
The generic API, format, limits and errors: [docs/ingest-api.md](../ingest-api.md).

### 8.5 Heartbeats (is a job still alive?)

```sh
curl -fsS -X POST https://alerta.example.com/api/v1/ingest/heartbeat \
  -H "Authorization: Bearer $ALERTA_KEY" -H "Content-Type: application/json" \
  -d '{"name":"nightly-backup","environment":"PROD","timeoutSeconds":86400,"severity":"CRITICAL"}'
```

Created by the first call; if the next one does not come within `timeoutSeconds`, an alert `HeartbeatMissing` opens,
the next call resolves it. Page *Heartbeats* shows them all.

### 8.6 Changes (deployments from ArgoCD, CI)

A deployment tool can report what it changed and where – changes are not alerts (not on the list, in mails or
reports); they only tell "what changed" next to the alerts of the same environment.

```sh
curl -fsS -X POST https://alerta.example.com/api/v1/ingest/changes \
  -H "Authorization: Bearer $ALERTA_KEY" -H "Content-Type: application/json" \
  -d '{"id":"catalog-api:4f2c1e9","labels":{"cluster":"portal-prod","namespace":"catalog"},
       "application":"catalog-api","version":"4f2c1e9","author":"jan.kowalski",
       "description":"Sync succeeded","url":"https://argocd.example.com/applications/catalog-api"}'
# {"id":"…","environment":"PORTAL-PROD","duplicate":false}
```

- **Environment** – from `labels`, by the same conditions as an alert's; the API key must cover it
  (`403 ENVIRONMENT_NOT_ALLOWED`). A change matching no environment is refused (`422 NO_ENVIRONMENT` – there is no
  quarantine for changes).
- `application` (required, up to 128 characters), `version`, `author` (up to 128), `description` (up to 2000), `url`
  (http/https only, no credentials), `at` (when – default: when it arrives; at most 5 min ahead).
- `id` (optional, up to 256) – the sender's id, e.g. application + revision: a repeated delivery is stored once
  (`"duplicate":true`).
- **The console shows a change's link only for https to a host on `alerta.links.allowed-hosts`** (the same list as
  the links to tools – add the ArgoCD host there). Another address is stored, but the change is shown without a link;
  the response says so in `urlShown`. Checked when shown, so adding the host works for changes already stored.
- Kept as long as the environment's alerts (the same retention).

#### Example: ArgoCD (argocd-notifications)

ArgoCD's notifications controller (built in since 2.6) sends a change after a successful deployment – once per revision.

1. **An API key** in *Administration → API keys*, e.g. "ArgoCD", covering the environments ArgoCD deploys to.
2. **The secret** – the key in `argocd-notifications-secret` (best from Vault, like the other secrets):
   ```sh
   kubectl -n argocd patch secret argocd-notifications-secret --type merge \
     -p '{"stringData":{"alerta-next-token":"ank_…"}}'
   ```
3. **Service, template, trigger** in `argocd-notifications-cm`:
```yaml
# add to the existing argocd-notifications-cm (namespace argocd)
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
  # every application (or instead an annotation on chosen ones – below)
  subscriptions: |
    - recipients: [alerta-next]
      triggers: [on-deployed-alerta-next]
```
4. Instead of `subscriptions` for all – an annotation on chosen applications:
   `notifications.argoproj.io/subscribe.on-deployed-alerta-next.alerta-next: ""`.

Watch out:
- **`labels` must meet an environment's conditions** in Alerta. The example sends `cluster` = the destination
  cluster's name in ArgoCD, and `namespace`. If your environments are recognised by other labels, take them from the
  application's labels, e.g.
  `dict "cluster" .app.spec.destination.name "environment" (get (default (dict) .app.metadata.labels) "environment")`.
  A change matching no environment gets `422 NO_ENVIRONMENT` – visible in the `argocd-notifications-controller` log
  (check with *Administration → Label tester* too).
- `author` and `description` read the commit (`GetCommitMetadata`) – the controller needs access to the repository
  (it usually has it through ArgoCD's credentials). Without it, drop those two lines or use
  `.app.status.operationState.operation.initiatedBy.username`.
- `toJson` encodes the values (quotes, new lines in a commit message) – do not insert them without it.
- `id` = application + revision: a repeated delivery is stored once.
- Alerta's certificate must be trusted by the controller (the company CA in ArgoCD); do not turn TLS checks off.

---

## 9. Operations

**Command-line tool** (in the backend container; everything audited as `cli`):

```sh
kubectl -n alerta-next exec deploy/alerta-next-backend -- alerta-admin create-admin <login> "<Name Surname>"
kubectl -n alerta-next exec deploy/alerta-next-backend -- alerta-admin reset-password <login>
kubectl -n alerta-next exec deploy/alerta-next-backend -- alerta-admin unlock <login>
kubectl -n alerta-next exec deploy/alerta-next-backend -- alerta-admin list-admins
# compose: docker compose exec backend alerta-admin …
```

**Health and metrics** (port 8081 of the backend, never through the ingress):
- `/actuator/health/liveness`, `/actuator/health/readiness` – used by Kubernetes probes.
- `/actuator/prometheus` – JVM, HTTP, database pool, plus `alerta_*`: active alerts per environment and severity,
  ingested alerts, age of the Watchdog, delay of the alert path (`alerta_ingest_delay_seconds`), logins and lockouts, sessions, heartbeats. The pods carry
  `prometheus.io/scrape` annotations. Example alert rules for Alerta Next itself:
  [deploy/test-monitoring/11-rules.yaml](../../deploy/test-monitoring/11-rules.yaml) (group `alerta-next.yml`).
  A ready Grafana dashboard (11.0+): [deploy/grafana](../../deploy/grafana/README.md); a starting set of alert rules
  with tests: [deploy/prometheus](../../deploy/prometheus/README.md).

**Logs**: readable lines on stdout (`kubectl logs`); in Kubernetes additionally JSON (Elastic Common Schema) in
`/var/log/alerta/alerta-next.json` inside the pod for an ELK agent. One line per HTTP request with a request id; audit
events are logged too (for a SIEM, [9.1](#91-audit-events-for-a-siem)). Passwords and keys never appear in logs.

**System status** (Administration → System status): version, database size, background jobs, Alertmanager and
Watchdog, quarantine, expiring keys/accounts, the configuration in use (secrets only as "set / not set").

### 9.1 Audit events for a SIEM

Every audit event goes to the database (*Administration → Audit log*) and to the log at the same time (logger
`io.alertanext.audit`, level INFO – on by default). In the JSON (ECS) log it has the fields:

| Field | Value |
|---|---|
| `event.category` | always `audit` – this filter picks the audit out of the rest of the log |
| `event.action` | the action name (table below) |
| `event.outcome` | `success`, `failure` (e.g. a wrong password) or `denied` (no permission, mail blocked) |
| `actor.type`, `actor.name` | `USER` + login, `SYSTEM` + job name (`cli` = `alerta-admin`, `sso`, `login`, `ack-timeout`, `account-expiry`, `inactive-accounts`, `daily-report`, `notifications` …), `ANONYMOUS` (failed sign-in with an unknown login) |
| `target.type`, `target.id`, `target.name` | what it concerns (`USER`, `ALERT`, `API_KEY`, `ROLE`, `ENVIRONMENT`, `ENDPOINT` …) |
| `details` | details as JSON text (e.g. `reason` of a failed sign-in, `to` and `purpose` of a mail, changed fields) |

The action names are part of the contract ([compatibility policy](../compatibility-policy.md), 2.4): in 1.x new ones
may appear, existing ones keep their names and meaning.

| Area | Actions |
|---|---|
| Sign-in and sessions | `auth.login` (`success` / `failure` with `details.reason`), `auth.logout`, `auth.lockout` (lock after failed attempts), `auth.password.change`, `auth.session.end` (a user ends their other sessions) |
| Accounts | `user.create`, `user.update`, `user.delete`, `user.disable`, `user.enable`, `user.unlock`, `user.password.reset`, `user.kiosk`, `user.sessions.terminate` (an administrator ends someone's sessions), `user.expire` (temporary account expired), `user.inactive-disable` (disabled after inactivity), `user.directory_name_changed` (SSO renamed the account) |
| Access | `role.create`, `role.update`, `role.delete`, `assignment.create`, `assignment.delete` (role granted / taken away, also by `alerta-admin create-admin`), `group.create`, `group.update`, `group.delete`, `group.member.add`, `group.member.remove`, `group.directory_link` (link to an SSO group), `access.export` (access review CSV) |
| Refusals | `access.denied` (request without permission, `denied`), `security.csrf_rejected` (CSRF token rejected in a session, `denied`) |
| API keys | `apikey.create`, `apikey.environments`, `apikey.revoke` |
| Environments | `environment.create`, `environment.update`, `environment.delete`, `environment.matchers` (alert assignment conditions), `environment.reassign` (alerts moved between environments) |
| Alerts | `alert.ack`, `alert.unack`, `alert.close`, `alert.reopen`, `alert.ack_expired` (acknowledgement lapsed), `alert.note`, `alert.note.edit`, `alert.note.delete`, `alert.delete`, `alert.export` (CSV) |
| Silences | `silence.create`, `silence.expire`, `blackout.create`, `blackout.end` (maintenance windows) |
| Heartbeats | `heartbeat.update`, `heartbeat.delete` |
| Console settings | `label.create`, `label.update`, `label.delete`, `label.reorder`, `link.create`, `link.update`, `link.delete`, `view.shared.create`, `view.shared.update`, `view.shared.delete`, `view.shared.reorder` |
| Mail and reports | `mail.sent`, `mail.failed`, `mail.blocked` (address outside `allowedDomains`, `denied`) – `details.purpose`: `report.daily`, `report.test`, `notification`; `report.subscription`, `report.test`, `report.export` |
| Notifications | `notification-rule.create`, `notification-rule.update`, `notification-rule.delete`, `notification-preferences.update`, `group.office-hours` |
| Audit chain | `audit.verify` (`alerta-admin verify-audit`; `failure` when the result is not `OK` / `MATCHES`); `audit.anchor` – log only, hourly (fields `audit.chain.*`, [backup runbook](backup-runbook.md) 3.6) |

**Worth alerting on in the SIEM** (suggestion): `auth.lockout`; a series of `auth.login` with `failure`;
`access.denied` and `security.csrf_rejected`; `mail.blocked`; `audit.verify` with `failure`; no `audit.anchor` for
over 2 hours; `assignment.create` of the `ACCESS_ADMIN` role and `user.password.reset` / `assignment.create` done by
`cli` (emergency access from the cluster).

---

## 10. Before production

- Secrets from your secret store ([5](#5-secrets)), never `01-secrets.yaml`.
- HTTPS with a proper certificate; `SESSION_COOKIE_SECURE` stays `true`.
- A database with backups (and ideally HA) – usually the central one ([6.2](#62-external-or-central-postgresql));
  with the bundled one: nightly dump, a copy outside the cluster, a restore test ([runbook](backup-runbook.md)).
- Single sign-on and `alerta.auth.local.mode: BREAK_GLASS_ONLY` with named emergency accounts.
- Network policies enforced by the cluster; the metrics port reachable only by your Prometheus.
- Alerts on Alerta Next itself (Watchdog missing, backend down, database pool exhausted) – see 9.
- Resources sized to your load; the database first.
- `TRUSTED_PROXIES` set (4.4a); `alerta.passwords.forbidden-words` with the organisation's words.
- Security self-assessment (OWASP ASVS 5.0 L2) and what is left for the deployment: `docs/security/asvs-l2.md`.
- SBOM (CycloneDX) of each image for your scanner: backend `META-INF/sbom/application.cdx.json` in the jar
  (`/app/META-INF/sbom/…`), frontend `/usr/share/sbom/alerta-next-frontend.cdx.json`.
