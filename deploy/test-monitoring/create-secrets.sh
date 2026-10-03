#!/bin/sh
# Creates the two secrets (never committed): Prometheus basic auth (user "admin", random password, printed once
# and kept in the Secret under "password") and the Alerta Next API key for Alertmanager.
# Usage: ./create-secrets.sh [ALERTA_API_KEY]      (without a key a placeholder is stored; set it later the same way)
set -eu
NS=monitoring
PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)
HASH=$(docker run --rm httpd:2.4-alpine htpasswd -nbB -C 12 admin "$PASSWORD" | cut -d: -f2)
printf 'basic_auth_users:\n  admin: %s\n' "$HASH" > /tmp/web.yml.$$
kubectl -n $NS create secret generic prometheus-basic-auth \
  --from-file=web.yml=/tmp/web.yml.$$ --from-literal=password="$PASSWORD" --dry-run=client -o yaml | kubectl apply -f -
rm -f /tmp/web.yml.$$
kubectl -n $NS create secret generic alertmanager-alerta-token \
  --from-literal=token="${1:-SET-ME}" --dry-run=client -o yaml | kubectl apply -f -
echo "Prometheus: user admin, password: $PASSWORD"
