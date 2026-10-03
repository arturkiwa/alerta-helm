#!/bin/sh
# Accounts of the test Alertmanager's login (basic auth). Kubernetes keeps only bcrypt hashes (Secret
# monitoring/alertmanager-web-config); Alertmanager reads them on every request, no restart needed.
#
#   ./alertmanager-auth.sh add <account> [<namespace>/<secret>]
#       new random password; with a secret it goes straight there (keys username, password) and is not shown,
#       otherwise it is printed once – for a sender in another cluster
#   ./alertmanager-auth.sh remove <account>
#   ./alertmanager-auth.sh list
#
# Accounts used here: alerta (Alerta Next: silences → alerta-next/alerta-next-alertmanager),
# prometheus-testcluster (this cluster's Prometheus → monitoring/prometheus-alertmanager-auth),
# prometheus-<cluster> for each Prometheus in another cluster.
set -eu

NS=monitoring
SECRET=alertmanager-web-config
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

current() { # "account hash" per line
  kubectl -n "$NS" get secret "$SECRET" -o jsonpath='{.data.web\.yml}' 2>/dev/null | base64 -d \
    | sed -n 's/^  \([A-Za-z0-9._-]*\): "\(.*\)"$/\1 \2/p' || true
}

write() { # stdin: "account hash" per line
  { echo "basic_auth_users:"; while read -r account hash; do echo "  $account: \"$hash\""; done; } > "$TMP/web.yml"
  kubectl -n "$NS" create secret generic "$SECRET" --from-file=web.yml="$TMP/web.yml" --dry-run=client -o yaml \
    | kubectl apply -f - >/dev/null
}

case "${1:-}" in
  add)
    account=${2:?account name}
    echo "$account" | grep -Eq '^[A-Za-z0-9._-]{1,64}$' || { echo "Invalid account name" >&2; exit 1; }
    password=$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-32)
    hash=$(printf '%s' "$password" | docker run --rm -i httpd:2.4-alpine htpasswd -niBC 12 "$account" | cut -d: -f2)
    { current | grep -v "^$account " || true; echo "$account $hash"; } | write
    if [ -n "${3:-}" ]; then
      target_ns=${3%%/*}; target=${3#*/}
      kubectl -n "$target_ns" create secret generic "$target" --from-literal=username="$account" \
        --from-literal=password="$password" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
      echo "Account $account: password stored in $3 (keys username, password)."
    else
      echo "Account $account – password (shown once, hand it over securely): $password"
    fi
    ;;
  remove)
    account=${2:?account name}
    remaining=$(current | grep -vc "^$account " || true)
    # An empty list would switch the login off altogether – never leave Alertmanager open.
    [ "$remaining" -gt 0 ] || { echo "Refusing to remove the last account" >&2; exit 1; }
    current | grep -v "^$account " | write
    echo "Account $account removed."
    ;;
  list)
    current | cut -d' ' -f1
    ;;
  *)
    sed -n '2,15p' "$0"; exit 1
    ;;
esac
