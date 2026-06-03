#!/usr/bin/env bash
# Wrap `violet push` on npuserver for the platform-side of the bundle-iterate
# air-gap split. Pushes a packaged bundle tgz (already scp'd to npuserver:/tmp/...)
# into the target ACP cluster's catalog.
#
# Usage:
#   npuserver-push.sh --tgz <remote-tgz-path> --cluster <cluster-name> \
#     --platform-username <user> --platform-password <pass> \
#     [--platform-address <url>]
#
# Defaults:
#   --platform-address: https://127.0.0.1  (npuserver-local ACP global)
#
# Credentials are read from CLI or env vars (PLATFORM_USERNAME / PLATFORM_PASSWORD).
# Never passed via argv on the remote — piped to bash via heredoc + env.

set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
usage: npuserver-push.sh --tgz <remote-path> --cluster <name>
       --platform-username <u> --platform-password <p>
       [--platform-address <url>] [--ssh-host <host>]

  --tgz                 path to bundle tgz on npuserver, e.g. /tmp/inbridge.tgz
                        (caller is responsible for scp'ing it there first)
  --cluster             target ACP cluster name, e.g. kubeos2
  --platform-address    ACP platform URL as reachable from npuserver
                        (default: https://127.0.0.1)
  --platform-username   ACP admin user
  --platform-password   ACP admin password (alt: PLATFORM_PASSWORD env)
  --ssh-host            ssh alias / host (default: npuserver)

The script does not log the password.
USAGE
}

TGZ=""
CLUSTER=""
PLATFORM_ADDRESS="https://127.0.0.1"
PLATFORM_USERNAME="${PLATFORM_USERNAME:-}"
PLATFORM_PASSWORD="${PLATFORM_PASSWORD:-}"
SSH_HOST="npuserver"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tgz)                TGZ="${2:-}"; shift 2 ;;
    --cluster)            CLUSTER="${2:-}"; shift 2 ;;
    --platform-address)   PLATFORM_ADDRESS="${2:-}"; shift 2 ;;
    --platform-username)  PLATFORM_USERNAME="${2:-}"; shift 2 ;;
    --platform-password)  PLATFORM_PASSWORD="${2:-}"; shift 2 ;;
    --ssh-host)           SSH_HOST="${2:-}"; shift 2 ;;
    -h|--help)            usage; exit 0 ;;
    *)                    echo "unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

: "${TGZ:?missing --tgz}"
: "${CLUSTER:?missing --cluster}"
: "${PLATFORM_USERNAME:?missing --platform-username (or PLATFORM_USERNAME env)}"
: "${PLATFORM_PASSWORD:?missing --platform-password (or PLATFORM_PASSWORD env)}"

echo "[npuserver-push] pushing $TGZ → cluster=$CLUSTER via $PLATFORM_ADDRESS" >&2

# Pass creds via env, NOT argv, so they don't appear in the remote process list
# longer than the bash subprocess argv would expose.
ssh "$SSH_HOST" "TGZ='$TGZ' CLUSTER='$CLUSTER' PLATFORM_ADDRESS='$PLATFORM_ADDRESS' \
    PLATFORM_USERNAME='$PLATFORM_USERNAME' PLATFORM_PASSWORD='$PLATFORM_PASSWORD' bash -s" <<'REMOTE'
set -euo pipefail
violet push --force \
  --clusters="$CLUSTER" \
  --platform-address="$PLATFORM_ADDRESS" \
  --platform-username="$PLATFORM_USERNAME" \
  --platform-password="$PLATFORM_PASSWORD" \
  "$TGZ" 2>&1 | grep -iE "artifactversion.*created|error" || true
REMOTE

echo "[npuserver-push] push complete" >&2
