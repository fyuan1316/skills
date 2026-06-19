#!/usr/bin/env bash
# Wrap `violet create + package` for the devpod side of the bundle-iterate
# air-gap split. Reads harbor pull creds from envs/env.harbor (USER + PSSSWORD).
# Auto-downloads violet to /tmp/violet if missing.
#
# Usage:
#   devpod-package.sh --artifact <image-ref> [--output <tgz>] [--platforms <list>]
#
# Defaults:
#   --output: /tmp/$(basename artifact-name)-$(timestamp).tgz
#   --platforms: linux/amd64,linux/arm64
#     Per-project: pass --platforms to match the target cluster's arch(es).
#     (e.g. infernex-bridge → kubeos2/Ascend is arm64-only: --platforms linux/arm64)

set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
usage: devpod-package.sh --artifact <bundle-image-ref> [--output <tgz>] [--platforms <list>]
  --artifact      bundle image reference, e.g. build-harbor.alauda.cn/mlops/infernex/infernex-bridge-bundle:vX
  --output        path to write packaged tgz (default: /tmp/<basename>-<ts>.tgz)
  --platforms     comma-separated platforms (default: linux/amd64,linux/arm64; match the target cluster's arch)

Reads envs/env.harbor for build-harbor pull credentials (USER + PSSSWORD).
USAGE
}

ARTIFACT=""
OUTPUT=""
PLATFORMS="linux/amd64,linux/arm64"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact)  ARTIFACT="${2:-}"; shift 2 ;;
    --output)    OUTPUT="${2:-}"; shift 2 ;;
    --platforms) PLATFORMS="${2:-}"; shift 2 ;;
    -h|--help)   usage; exit 0 ;;
    *)           echo "unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ -z "$ARTIFACT" ]]; then
  echo "missing --artifact" >&2
  usage
  exit 2
fi

# Locate workspace root by walking up from this script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE:-}"
if [[ -z "$WORKSPACE" ]]; then
  # default: <workspace>/kbs/fy-skills/bundle-iterate/scripts/  → 4 up
  WORKSPACE="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
fi

ENV_HARBOR="$WORKSPACE/envs/env.harbor"
if [[ ! -f "$ENV_HARBOR" ]]; then
  echo "harbor env file not found: $ENV_HARBOR" >&2
  echo "set WORKSPACE env var if your layout differs" >&2
  exit 3
fi

# shellcheck disable=SC1090
set -a; source "$ENV_HARBOR"; set +a
: "${USER:?env.harbor missing USER}"
# Accept the corrected PASSWORD spelling, with the historical PSSSWORD typo as fallback.
PSSSWORD="${PASSWORD:-${PSSSWORD:-}}"
: "${PSSSWORD:?env.harbor missing PASSWORD}"

VIOLET="${VIOLET:-/tmp/violet}"
if [[ ! -x "$VIOLET" ]]; then
  echo "[devpod-package] downloading violet to $VIOLET"
  curl -fsS -o "$VIOLET" "http://package-minio.alauda.cn:9199/packages/violet/latest/violet_linux_amd64"
  chmod +x "$VIOLET"
fi

TS="$(date +%Y%m%d-%H%M%S)"
BASENAME="$(printf '%s' "$ARTIFACT" | sed -E 's@.*/([^:/]+):.*@\1@; s@.*/@@')"
OUT_DIR="${OUT_DIR:-/tmp/${BASENAME}-${TS}}"
OUTPUT="${OUTPUT:-/tmp/${BASENAME}-${TS}.tgz}"

# Pre-existing files would make violet create refuse.
rm -rf "$OUT_DIR" "$OUTPUT"

echo "[devpod-package] violet create $OUT_DIR"
"$VIOLET" create "$OUT_DIR" \
  --default-catalog-source=platform \
  --artifact="$ARTIFACT" \
  --username="$USER" \
  --password="$PSSSWORD" \
  --platforms="$PLATFORMS"

echo "[devpod-package] violet package → $OUTPUT"
"$VIOLET" package "$OUT_DIR" \
  --username="$USER" \
  --password="$PSSSWORD" \
  --output="$OUTPUT"

rm -rf "$OUT_DIR"

ls -lh "$OUTPUT" >&2
printf '%s\n' "$OUTPUT"
