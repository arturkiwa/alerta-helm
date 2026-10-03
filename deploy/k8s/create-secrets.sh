#!/usr/bin/env sh
# Creates the secrets that never live in git. Idempotent: existing secrets are left untouched.
#   REGISTRY_DOCKERCONFIG=/path/to/config.json ./create-secrets.sh
set -eu
NS=alerta-next

kubectl get namespace "$NS" >/dev/null 2>&1 || kubectl apply -f "$(dirname "$0")/base/namespace.yaml"

if ! kubectl -n "$NS" get secret alerta-next-db >/dev/null 2>&1; then
  kubectl -n "$NS" create secret generic alerta-next-db \
    --from-literal=username=alerta \
    --from-literal=password="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 40)"
  echo "created secret alerta-next-db (random password, stored only in the cluster)"
fi

if ! kubectl -n "$NS" get secret alerta-next-registry >/dev/null 2>&1; then
  : "${REGISTRY_DOCKERCONFIG:?set REGISTRY_DOCKERCONFIG to a docker config.json with access to cr.artbit.com.pl}"
  kubectl -n "$NS" create secret generic alerta-next-registry \
    --type=kubernetes.io/dockerconfigjson \
    --from-file=.dockerconfigjson="$REGISTRY_DOCKERCONFIG"
  echo "created secret alerta-next-registry"
fi
