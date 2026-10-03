# Instalacja na piaskownicy (czysty Kubernetes)

Wariant bez Istio, bez Cilium i bez SSO: TLS kończy się na F5, a F5 wysyła zwykły HTTP na port 80 workerów, gdzie
jest **NGINX Ingress** (`ingress.yaml`, host `alerta.example.com`, klasa `nginx`).

## 0. Czego potrzeba
- `kubectl` z prawami do utworzenia namespace `alerta-next` (lub zmień nazwę – niżej) i obiektów w nim.
- Klaster z **domyślną klasą dysków** (baza dostaje wolumin 10 GiB) – albo wpisz klasę w `kustomization.yaml`.
- Namespace ma profil Pod Security `restricted` – obrazy są pod to przygotowane (bez roota, read-only root FS).
- Obrazy w rejestrze firmowym (punkt 1) i dostęp do `postgres:18-alpine` (Docker Hub albo lustro).

## 1. Obrazy
Wersja **0.10.0**. Przenieś do rejestru firmowego, np. z Docker Hub:

```sh
for app in backend frontend; do
  docker pull arturkiwa/alerta-next-$app:0.10.0
  docker tag  arturkiwa/alerta-next-$app:0.10.0 <rejestr>/alerta-next/alerta-next-$app:0.10.0
  docker push <rejestr>/alerta-next/alerta-next-$app:0.10.0
done
```

## 2. Wartości do uzupełnienia (linie oznaczone `←`)
- `kustomization.yaml` → `images`: adres rejestru (`newName`), ewentualnie lustro dla `postgres`.
- `ingress.yaml` → `ingressClassName`, jeśli kontroler ma inną klasę niż `nginx`.
- `config/environment.yml` → adres Alertmanagera do wyciszeń (opcjonalnie, punkt 7).

Sprawdzenie bez instalowania: `kubectl kustomize deploy/k8s/overlays/sandbox | less`

## 3. Sekrety (poza gitem)

```sh
kubectl create namespace alerta-next   # albo pozwól zrobić to punktowi 4 i utwórz sekrety zaraz po nim
# hasło bazy – losowe, nigdzie nie zapisywane poza Secretem
kubectl -n alerta-next create secret generic alerta-next-db \
  --from-literal=username=alerta --from-literal=password="$(head -c 24 /dev/urandom | base64 | tr -d '/+=')"
# dostęp do rejestru, jeśli wymaga logowania (nazwa musi być taka)
kubectl -n alerta-next create secret docker-registry alerta-next-registry \
  --docker-server=<rejestr> --docker-username=<login> --docker-password=<hasło-lub-token>
```

Rejestr bez logowania: sekretu `alerta-next-registry` nie trzeba (kubelet tylko ostrzeże, że go brak).

## 4. Instalacja

```sh
kubectl apply -k deploy/k8s/overlays/sandbox
kubectl -n alerta-next rollout status statefulset/alerta-next-db
kubectl -n alerta-next rollout status deploy/alerta-next-backend    # ~1–2 min (migracje bazy przy pierwszym starcie)
kubectl -n alerta-next rollout status deploy/alerta-next-frontend
curl -H "Host: alerta.example.com" http://<worker>/api/v1/ping   # {"status":"ok"} – to samo, co widzi F5
```

## 5. Pierwszy administrator

```sh
kubectl -n alerta-next exec deploy/alerta-next-backend -- alerta-admin create-admin <login> "<Imię Nazwisko>"
```

Hasło jednorazowe pojawi się tylko w terminalu – przy pierwszym logowaniu trzeba je zmienić. To konto zarządza
dostępem (użytkownicy, grupy, role, klucze API); do pracy z alertami nadaj sobie rolę w UI.

## 6. Dwa środowiska i Alertmanager
1. **Administracja → Środowiska**: dodaj np. `UAT` i `PROD` z **warunkami na etykiety alertów** (np. `cluster = xxx-uat`).
   Alert bez pasującego środowiska trafia do **kwarantanny** (widzi ją administrator dostępu) – nic nie ginie.
2. **Administracja → Klucze API**: klucz dla Alertmanagera (ograniczony do tych środowisk). Klucz widać tylko raz.
3. **Grupy / role**: grupa z rolą *Operator* na obu środowiskach, siebie do niej.
4. W Waszym Alertmanagerze odbiorca (klucz w pliku, nie w konfiguracji):

```yaml
receivers:
  - name: alerta-next
    webhook_configs:
      - url: https://alerta.example.com/api/v1/ingest/alertmanager
        send_resolved: true
        http_config:
          authorization:
            type: Bearer
            credentials_file: /etc/alertmanager/secrets/alerta-next-token   # klucz ank_…
```

   i trasa do niego (np. `continue: true` w głównej trasie, żeby dotychczasowe powiadomienia działały dalej).
   Watchdog (alert zawsze aktywny) nie pojawia się na liście – jest heartbeatem całej ścieżki (strona „Stan systemu”).

## 7. Wyciszenia z konsoli (opcjonalnie)
W `config/environment.yml` adres API Alertmanagera (`url`), a jeśli wymaga logowania – Secret:

```sh
kubectl -n alerta-next create secret generic alerta-next-alertmanager --from-literal=token=<bearer>
#   albo --from-literal=username=… --from-literal=password=…
```

oraz komponent `../../components/alertmanager` w `kustomization.yaml` (NetworkPolicy wyjścia do Alertmanagera –
ustaw w nim adres i port). Bez tego konsola działa, tylko bez przycisku „Wycisz”.

## Aktualizacja i usunięcie
- Nowa wersja: zmień `newTag` w `images`, `kubectl apply -k …` – backend i frontend wymieniają się bez przerwy
  (2 repliki), migracje bazy są zgodne wstecz.
- Usunięcie wszystkiego (łącznie z bazą): `kubectl delete namespace alerta-next`.

## Gdy coś nie działa
- **Pody się restartują, w logu „host not found” / brak połączenia z bazą** – DNS zablokowany przez NetworkPolicy.
  `network-policies.yaml` wpuszcza port 53 do dowolnego adresu; jeśli klaster ma własny sposób na DNS, sprawdź go.
- **`ImagePullBackOff`** – adres rejestru w `images` albo sekret `alerta-next-registry`.
- **Baza w `Pending`** – brak domyślnej klasy dysków: wpisz `storageClassName` w łatce StatefulSetu.
- **Brak wejścia z F5** – `curl -H "Host: alerta.example.com" http://<worker>/api/v1/ping`; NetworkPolicy
  wpuszcza port 8080 frontendu z każdego źródła (także z kontrolera ingress).
- Logi: `kubectl -n alerta-next logs deploy/alerta-next-backend` (czytelne na konsoli; JSON dla ELK w pliku
  `/var/log/alerta/alerta-next.json` w podzie).

## Czym różni się od docelowego wdrożenia
Brak mesh = ruch między podami bez mTLS (zostają NetworkPolicy); konta lokalne zamiast SSO; baza w klastrze bez
backupów; brak samooceny ASVS i testu penetracyjnego. Na piaskownicę wystarcza, przed produkcją – nie.
