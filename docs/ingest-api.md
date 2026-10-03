# API przyjmowania alertów (dla skryptów, Zabbixa i innych nadawców)

Prometheus/Alertmanager wysyła alerty na `/api/v1/ingest/alertmanager` (webhook). Każdy inny nadawca używa
**`POST /api/v1/ingest/alerts`** – ten sam format alertu co w Alertmanagerze, ta sama dalsza obsługa: środowisko
z etykiet (warunki środowisk), kwarantanna, okno uspokojenia, flapping, wyciszenia, raporty.

## Uwierzytelnienie
Klucz API (Administracja → Klucze API) w nagłówku `Authorization: Bearer ank_…`. Klucz może wysyłać tylko dla swoich
środowisk – alert pasujący do innego jest odrzucany (licznik `rejected`). Tak samo, gdy to samo `source` +
`fingerprint` należy już do alertu w środowisku spoza klucza (inny nadawca): klucz nie zmieni, nie przeniesie ani nie
rozwiąże cudzego alertu; alert w kwarantannie zmienia tylko klucz, który go utworzył, albo klucz „wszystkie środowiska”.

## Treść

```json
{
  "source": "zabbix",
  "alerts": [
    {
      "status": "firing",
      "labels": { "alertname": "DiskFull", "severity": "critical", "cluster": "prod-1", "host": "db-1" },
      "annotations": { "summary": "Na /var zostało 3% miejsca", "description": "…", "runbook_url": "https://wiki/…" },
      "startsAt": "2026-09-25T10:00:00Z",
      "endsAt": "2026-09-25T10:30:00Z",
      "fingerprint": "zbx-event-123456",
      "generatorURL": "https://zabbix.example.com/tr_events.php?triggerid=1&eventid=123456"
    }
  ]
}
```

| Pole | Znaczenie |
|---|---|
| `source` | nazwa nadawcy (`a-z0-9._-`, do 32 znaków), domyślnie `api`. Alerty są unikalne w obrębie źródła – ten sam alert z dwóch źródeł to dwa alerty. `alertmanager` i `heartbeat` są zastrzeżone |
| `status` | `firing` (domyślnie) albo `resolved` |
| `labels` | wymagane, w tym `alertname`; `severity` jak w Prometheusie (`critical`, `warning`, `info` …); pozostałe dowolne – po nich działają warunki środowisk, filtry, widoki |
| `annotations` | opcjonalne: `summary`, `description`, `runbook_url` (tylko http/https) i dowolne inne |
| `fingerprint` | opcjonalny identyfikator alertu u nadawcy (`A-Za-z0-9._:-`, do 128 znaków). Bez niego liczony z **etykiet** (jak w Alertmanagerze) – wtedy zmiana dowolnej etykiety to nowy alert |
| `startsAt` | kiedy problem się zaczął (domyślnie: chwila nadejścia) |
| `endsAt` | przy `firing`: do kiedy alert „trzyma”, jeśli nadawca zamilknie – po tym czasie zostanie rozwiązany (zdarzenie od `expiry`). Każde ponowne wysłanie przesuwa termin. Bez `endsAt` alert czeka na `resolved`. Przy `resolved`: czas rozwiązania |
| `generatorURL` | link do źródła (tylko http/https) |

Limity: do `alerta.alerts.max-alerts-per-request` alertów w jednym żądaniu (domyślnie 1000), 64 etykiety
(nazwa do 128 znaków, wartość do 1024), 32 adnotacje (wartość do 16 384 znaków).

## Odpowiedzi
- `200` – liczniki: `created`, `updated`, `reopened`, `resolved`, `resolving` (czeka w oknie uspokojenia),
  `quarantined`, `rejected`, `ignored`, `stale` (komunikat o wystąpieniu starszym niż bieżące – spóźniony, nie zmienia
  stanu). Webhook Alertmanagera ma te same reguły podstawowe, ale błędny alert jest pomijany (licznik `invalid`), a
  reszta paczki przyjęta.
- `400 INVALID_ALERT` – **cała paczka odrzucona, nic nie zapisano**; `details.index` = numer alertu (od 0),
  `details.field` = co jest nie tak (np. `alertname`, `labels.<nazwa>`, `status`, `fingerprint`).
- `400 INVALID_SOURCE` / `RESERVED_SOURCE`, `400 MALFORMED_REQUEST`, `413 TOO_MANY_ALERTS`, `401 INVALID_API_KEY`.

Ponawianie jest bezpieczne: to samo wysłane drugi raz tylko aktualizuje alert (licznik `updated`).

## Przykład (curl)

```sh
curl -fsS -X POST https://alerta.example/api/v1/ingest/alerts \
  -H "Authorization: Bearer $ALERTA_KEY" -H "Content-Type: application/json" \
  -d '{"source":"cron","alerts":[{"labels":{"alertname":"BackupFailed","severity":"critical","cluster":"prod-1"},
       "annotations":{"summary":"Nocny backup bazy nie powiódł się"}}]}'
```

## Zabbix (kierunek)
Media type (webhook) Zabbixa wysyła problem jako `firing` z `fingerprint` = identyfikator zdarzenia i etykietami
z tagów/hosta, a odzyskanie jako `resolved` z tym samym `fingerprint`; ważność Zabbixa mapowana na `severity`
(aliasy w `alerta.alerts.severity-aliases`).
