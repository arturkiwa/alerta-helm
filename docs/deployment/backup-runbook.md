# Database backups and restore – runbook

*Polski: [backup-runbook.pl.md](backup-runbook.pl.md)*

For the **internal PostgreSQL** (Helm: `database.internal.enabled: true`, compose: service `db`). With an external /
central database, backups and restore belong to the DBA – a consistent dump or PITR of Alerta's database (schema) is
enough; steps 3.4–3.6 (sessions, access undone by the restore, checks) apply all the same.

## 1. What is protected and how much may be lost

**Everything** is in the database: configuration (environments and their conditions, users, groups, roles, API keys,
labels, views, notification rules, heartbeats, maintenance windows), alerts with their history and notes, the audit
log, sessions. Losing the database = losing the configuration and the handling history; only the **active** alerts
are sent again by Alertmanager.

| | Value | From |
|---|---|---|
| RPO (data that may be lost) | up to 24 h | nightly dump; a manual one before every upgrade (2.3) |
| RTO (time to restore) | about a quarter of an hour | a dump is usually a few to a few tens of MB; `pg_restore` takes seconds |

For a shorter RPO: an external database with PITR (continuous WAL archiving) at the DBA.

## 2. Backups

### 2.1 Nightly dump (Helm)

```yaml
database:
  internal:
    backup:
      enabled: true
      schedule: "30 2 * * *"   # cron, the cluster's time zone (usually UTC)
      keep: 14                 # dumps kept on the volume
      storageClass: ""         # best ANOTHER storage than the database's (e.g. ceph-block when the DB is on CephFS)
      size: 20Gi
```

The chart adds the CronJob `<release>-db-backup` and the volume `<release>-db-backup` (kept on `helm uninstall`).
Every night: `pg_dump -Fc` to a temporary file → the dump is checked readable (`pg_restore --list`) → renamed to
`alerta-YYYYMMDDTHHMMSSZ.dump` → the oldest beyond `keep` are deleted. A failed dump deletes nothing. The job runs
with the database's service account (the same access to secrets, Vault CSI included) and has its own NetworkPolicy
(to the database only).

Check right after enabling it – run the job now instead of waiting for the night:

```sh
kubectl -n <ns> create job --from=cronjob/<release>-db-backup <release>-db-backup-test
kubectl -n <ns> logs -f job/<release>-db-backup-test
# backup done: alerta-20261001T083000Z.dump, 93303 bytes; kept: 1
```

### 2.2 A copy outside the cluster – required

The backup volume is **in the same cluster** (often on the same storage) – it protects against a broken database, a
bad migration, a human mistake, but **not** against losing the cluster or the storage. The files of the volume
`<release>-db-backup` must regularly leave the cluster – with the organisation's backup system (Velero / Kasten / a
file backup agent / a job copying to S3). Dumps hold personal data (logins, names, e-mails) and the password hashes of
local accounts – keep them like other backups of production systems (encrypted, access-controlled).

### 2.3 Before an upgrade

Before every version upgrade (a new version may bring schema migrations):

```sh
kubectl -n <ns> create job --from=cronjob/<release>-db-backup <release>-db-backup-pre-$(date +%Y%m%d%H%M)
kubectl -n <ns> wait --for=condition=complete job/<release>-db-backup-pre-... --timeout=10m
```

Without the nightly dump – a manual dump to a file on the administrator's machine:

```sh
kubectl -n <ns> exec <release>-db-0 -- sh -c \
  'PGPASSWORD="${POSTGRES_PASSWORD:-$(cat "$POSTGRES_PASSWORD_FILE")}" pg_dump -h 127.0.0.1 \
   -U "${POSTGRES_USER:-$(cat "$POSTGRES_USER_FILE")}" -Fc alerta' > alerta-$(date +%F).dump
# compose: docker compose exec -T db pg_dump -U alerta -Fc alerta > alerta-$(date +%F).dump
```

### 2.4 Watching the backups

Prometheus rules (kube-state-metrics) – no successful dump for more than 26 h, or a failed job:

```yaml
- alert: AlertaNextBackupMissing
  expr: time() - kube_cronjob_status_last_successful_time{cronjob=~".*-db-backup"} > 26 * 3600
  for: 15m
  labels: { severity: critical }
  annotations:
    summary: No successful Alerta Next database dump for more than a day
- alert: AlertaNextBackupFailed
  expr: kube_job_status_failed{job_name=~".*-db-backup-.*"} > 0
  labels: { severity: warning }
  annotations:
    summary: The Alerta Next database dump job failed ({{ $labels.job_name }})
```

## 3. Restore

A restore takes the database back **to the moment of the dump**: everything later (alerts, notes, configuration
changes **and audit entries**) is gone. That is why step 3.1 is required while the broken database still exists.

### 3.1 Keep the current state (if the database still runs)

A dump of the broken database is **evidence** (the audit log is append-only – after the restore its tail is gone) and
the source for step 3.5. Take it as in 2.3 (manually to a file) and keep it with the incident description.

### 3.2 Stop the backend

The backend must not write during the restore, nor – on an empty new database – create a fresh schema before it.

- **Argo CD** (auto-sync / self-heal undoes a manual `kubectl scale`): set `backend.replicas: 0` in the values
  (commit, sync) **or** turn the application's auto-sync off in Argo for the restore and then
  `kubectl -n <ns> scale deploy/<release>-backend --replicas=0`.
- Without Argo: `kubectl -n <ns> scale deploy/<release>-backend --replicas=0`.
- compose: `docker compose stop backend`.

Check: `kubectl -n <ns> get pods` – no `<release>-backend-…` pod.

### 3.3 Restore the dump

The database must run (pod `<release>-db-0` ready). **Database lost completely** (volume deleted): the StatefulSet
creates a new, empty `alerta` database when the pod starts – then restore as below.

A helper pod with access to the backup volume and to the database – labelled like the backup job (the NetworkPolicy
lets it through), with the database's service account (secrets, Vault CSI too). Save as `restore.yaml`, replace
`<release>`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: <release>-db-restore
  labels:
    app.kubernetes.io/name: <release>-db-backup
    app.kubernetes.io/instance: <helm-release-name>
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
        # secrets.mode = csi: uncomment the "secrets" volume below too
        # - { name: secrets, mountPath: /etc/alerta/secrets, readOnly: true }
  volumes:
    - { name: backup, persistentVolumeClaim: { claimName: <release>-db-backup } }
    - { name: tmp, emptyDir: {} }
    # - name: secrets
    #   csi: { driver: secrets-store.csi.k8s.io, readOnly: true, volumeAttributes: { secretProviderClass: <release>-db-secrets } }
```

`app.kubernetes.io/instance` = the Helm release name (`helm list`). With `secrets.mode` `values` / `existing` add
`PGUSER` / `PGPASSWORD` to `env` from the database secret (`<release>-db`, keys `username` / `password`, or your
`database.existingSecret`) – as in the backup CronJob (`kubectl get cronjob <release>-db-backup -o yaml`).

```sh
kubectl -n <ns> apply -f restore.yaml
kubectl -n <ns> wait --for=condition=ready pod/<release>-db-restore
kubectl -n <ns> exec <release>-db-restore -- ls -l /backup          # pick a dump
# a dump from outside the cluster: kubectl -n <ns> cp alerta-….dump <release>-db-restore:/tmp/alerta.dump
kubectl -n <ns> exec <release>-db-restore -- sh -c '
  export PGUSER="${PGUSER:-$(cat /etc/alerta/secrets/DB_USER)}"
  export PGPASSWORD="${PGPASSWORD:-$(cat /etc/alerta/secrets/DB_PASSWORD)}"
  pg_restore --clean --if-exists --no-owner --exit-on-error --single-transaction -d alerta /backup/alerta-….dump'
```

`--single-transaction`: either all of it is restored or nothing (the database stays as it was). compose:

```sh
docker compose exec -T db pg_restore -U alerta --clean --if-exists --no-owner --exit-on-error --single-transaction \
  -d alerta < alerta-….dump
```

### 3.4 Invalidate the sessions

The dump holds the sessions of its moment – after the restore they would come back to life. Delete them (everyone
signs in again):

```sh
kubectl -n <ns> exec <release>-db-restore -- sh -c '
  export PGUSER="${PGUSER:-$(cat /etc/alerta/secrets/DB_USER)}" PGPASSWORD="${PGPASSWORD:-$(cat /etc/alerta/secrets/DB_PASSWORD)}"
  psql -c "DELETE FROM spring_session"'
```

### 3.5 Take away again what had been taken away – security

A restore also undoes **revoked access**: an account disabled, an API key revoked, a role removed after the dump works
again. In the dump from step 3.1 (or in the backend log / SIEM – audit events go there too) check what changed after
the dump and repeat the revocations in the application:

```sql
-- on the dump of the broken database (e.g. restored temporarily elsewhere) or in the SIEM:
SELECT occurred_at, actor_name, action, target_name FROM audit_log
 WHERE occurred_at > '<time of the dump>' AND action IN ('user.disable', 'user.expire', 'user.kiosk',
       'user.password.reset', 'user.sessions.terminate', 'apikey.revoke', 'apikey.environments', 'assignment.delete',
       'group.member.remove', 'role.update', 'role.delete', 'environment.matchers')
 ORDER BY occurred_at;
```

No dump and no SIEM – go through the last day's changes with the access administrators.

### 3.6 Start and check

1. Backend back: `backend.replicas` to its previous value (commit / turn auto-sync on in Argo) or
   `kubectl scale … --replicas=2`; compose: `docker compose start backend`.
2. Delete the helper pod: `kubectl -n <ns> delete pod <release>-db-restore`.
3. Backend log: `Successfully validated N migrations` and `Schema "public" is up to date` (or a migration when the
   dump is from an older version – that is fine). The image version **the same or newer** than the one that made the
   dump.
4. Sign-in (SSO and a break-glass account), *System status* without errors, the environments and users, alerts from
   the last hours before the dump, *Audit log* – the last entry from before the dump, after it the current sign-ins.
5. Alertmanager sends the active alerts again at its next repeat (`repeat_interval`), heartbeats at their next ping;
   alerts resolved between the dump and the failure do not come back.
6. **Audit log – what was lost** (hash chain, since 0.47.0): in ELK find the last anchor before the failure
   (`event.action: audit.anchor`, fields `audit.chain.seq` and `audit.chain.hash`, hourly) and check it together with
   a few earlier ones:
   ```sh
   kubectl -n <ns> exec deploy/<release>-backend -- alerta-admin verify-audit <seq>:<hash> <seq>:<hash>
   ```
   The restored chain is whole (`Audit chain: OK`), anchors from before the dump give `MATCHES`, newer ones
   `TRUNCATED`: their numbers show how many audit entries were lost (in the database after the dump). `DIFFERENT` or
   `BROKEN` = something other than a restore (changed entries) – report it as a security incident. `INCOMPLETE` = older
   audit entries outside the chain (the command links them first, so usually only while the chain job held its lock)
   – run it again a minute later; if it stays, check the log (`linked late`) and report it.
7. Write it down: time of the failure, the dump used, the downtime, what was lost (including the range of lost audit
   entries from step 6).

## 4. Restore test

A backup that was never restored is not a backup. **Once a quarter** and after every change of how backups are made:
restore the latest dump into a **separate** database (another test installation, or `createdb alerta_test` on the same
server and `pg_restore -d alerta_test`), compare row counts (`users`, `environments`, `alerts`, `audit_log`,
`flyway_schema_history`) with production at the dump's time, start a test backend on it, write down the result and
the time it took.

First test (2026-09-30, local stack, version 0.39): dump by the chart's script (the check and the rotation work),
database volume deleted, restored into a new empty database – row counts identical, Flyway: 33 migrations unchanged,
sign-in works, the audit log goes on with the next number; restore over an existing broken database
(`--clean --single-transaction`) – correct too, the triggers (live updates, append-only audit) come back. The
`pg_restore` itself: ~4 s.
