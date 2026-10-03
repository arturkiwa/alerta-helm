#!/usr/bin/env bash
# Vulnerability scan of the images of one release (and the database image), HIGH and CRITICAL only – the monthly
# dependency review and before every release (ASVS V15.1.1, docs/security/asvs-l2.md A.10). Trivy runs in a container:
# nothing to install, no dependency of the project. The vulnerability database is cached in the volume "trivy-cache".
#
#   deploy/scan-images.sh 0.22.0                       # docker.io/arturkiwa/alerta-next-{backend,frontend}:0.22.0
#   REGISTRY=cr.example.com/team deploy/scan-images.sh 0.22.0
#   deploy/scan-images.sh local                        # images built by docker-compose in deploy/ (alerta-next-*:dev)
#
# Exit code 1 when a fixable HIGH/CRITICAL vulnerability is found in our images (a fix exists: update or rebuild).
# Deadlines from its publication: critical 7 days, high 30 days. The database image is reported, not counted – it is
# upstream's (production normally uses a central PostgreSQL).
set -euo pipefail

VERSION="${1:?usage: $0 <version>|local}"
REGISTRY="${REGISTRY:-docker.io/arturkiwa}"
TRIVY="aquasec/trivy:0.74.0"
DB_IMAGE="${DB_IMAGE:-docker.io/library/postgres:18-alpine}"

if [ "$VERSION" = local ]; then
  OURS=(alerta-next-backend:dev alerta-next-frontend:dev)
else
  OURS=("$REGISTRY/alerta-next-backend:$VERSION" "$REGISTRY/alerta-next-frontend:$VERSION")
fi

scan() { # image → prints a summary; fails when a fixable HIGH/CRITICAL finding exists
  local json
  json=$(mktemp)
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v trivy-cache:/root/.cache/ "$TRIVY" image \
    --quiet --scanners vuln --severity HIGH,CRITICAL --format json "$1" > "$json"
  python3 - "$1" "$json" <<'PY'
import json, sys
image, path = sys.argv[1], sys.argv[2]
d = json.load(open(path))
seen, lines, fixable = set(), [], 0
for r in d.get("Results") or []:
    for v in r.get("Vulnerabilities") or []:
        key = (v["VulnerabilityID"], v["PkgName"])
        if key in seen:
            continue
        seen.add(key)
        fix = v.get("FixedVersion") or ""
        fixable += 1 if fix else 0
        lines.append("  %-8s %-16s %s %s -> %s  [%s]" % (v["Severity"], v["VulnerabilityID"], v["PkgName"],
                     v.get("InstalledVersion"), fix or "(no fix yet)", r["Target"]))
print("%s: %d HIGH/CRITICAL, fixable: %d" % (image, len(lines), fixable))
if lines:
    print("\n".join(lines))
sys.exit(1 if fixable else 0)
PY
  local rc=$?
  rm -f "$json"
  return $rc
}

failed=0
for image in "${OURS[@]}"; do
  scan "$image" || failed=1
done
echo "--- database image (upstream, informational)"
scan "$DB_IMAGE" || true
exit $failed
