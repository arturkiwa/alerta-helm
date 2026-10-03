# Alerta Next

Konsola alertów dla środowiska korporacyjnego, zbudowana od zera jako następca Alerty (`alerta-webui` + `alerta-api`).

**Instalacja (dla wdrożeniowca):** [docs/deployment/README.pl.md](docs/deployment/README.pl.md) ·
[English](docs/deployment/README.md) – szybki start z Docker Compose (`deploy/quickstart`), Kubernetes z jawnymi
manifestami (`deploy/kubernetes`), sekrety, baza zewnętrzna.

| Katalog     | Zawartość                                                   |
|-------------|-------------------------------------------------------------|
| `backend/`  | Spring Boot 4.1, Java 25, PostgreSQL, Flyway, Gradle         |
| `frontend/` | Angular 22 (standalone, zoneless), Angular Material, Tailwind |
| `deploy/`   | docker-compose do lokalnych testów, `quickstart/` (pokaz), `kubernetes/` (jawne manifesty), `k8s/` (kustomize) |
| `docs/`     | Dokumentacja – spis: [docs/README.md](docs/README.md) (`docs/internal/` – robocze, nie do publikacji) |

## Uruchomienie lokalne (wymaga tylko Dockera)

```sh
cd deploy
docker-compose up --build
```

(Z Docker Compose v2 to samo: `docker compose up --build`. Stary `docker-compose` 1.29 przy ponownym tworzeniu kontenera potrafi rzucić `KeyError: 'ContainerConfig'`; wtedy najpierw `docker-compose rm -sf <usługa>`.)

UI: <http://127.0.0.1:8087>. Nagłówek pokazuje, czy UI dogaduje się z API przez proxy.

## Budowa obrazów i wysyłka do Artifactory

```sh
REGISTRY=artifactory.example/alerta-next   # podmień na właściwe repozytorium
VERSION=0.1.0

docker build -t $REGISTRY/backend:$VERSION backend
docker build -t $REGISTRY/frontend:$VERSION frontend
docker push $REGISTRY/backend:$VERSION
docker push $REGISTRY/frontend:$VERSION
```

Obrazy:
- **backend**: JRE 25 na Alpine, użytkownik bez uprawnień (UID 10001), port `8080` (API) i `8081` (health/metryki; nie wystawiać przez ingress).
- **frontend**: `nginx-unprivileged`, port `8080`, statyczne SPA + proxy `/api/` → `BACKEND_URL`.

## Testy

Backend (testy integracyjne uruchamiają PostgreSQL przez Testcontainers, więc potrzebny jest dostęp do Dockera):

```sh
docker run --rm --network host \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD/backend":/work -w /work \
  gradle:9.7.1-jdk25 ./gradlew test
```

Frontend:

```sh
docker run --rm -v "$PWD/frontend":/work -w /work node:24-alpine sh -c "npm ci && npx ng test --watch=false"
```

## Praca lokalna bez kontenerów

Backend (`./gradlew bootRun`, wymaga JDK 25 i PostgreSQL) oraz frontend (`npm start`, wymaga Node 24). Serwer deweloperski Angulara przekierowuje `/api` na `localhost:8080`.
