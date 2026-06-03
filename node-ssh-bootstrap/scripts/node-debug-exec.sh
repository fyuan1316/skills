#!/usr/bin/env bash
# node-debug-exec.sh — run an arbitrary shell snippet against a cluster node's
# ROOT FILESYSTEM, even when the node has no SSH login (immutable / KubeOS / locked
# down). It works by creating an ephemeral `kubectl debug node/<node>` pod (profile
# sysadmin) whose host root is mounted at /host, running the snippet there, then
# harvesting the output from the pod logs and deleting the pod.
#
# This is the reusable primitive the rest of node-ssh-bootstrap is built on: any
# time you have kubectl-to-a-cluster (often via a jump host) but cannot SSH the
# nodes, this gives you a root shell on each node's disk.
#
# The snippet is read from STDIN. Inside it, the node's "/" is at "/host".
# The snippet is base64-wrapped before transport, so it may contain any quoting,
# spaces, parens, newlines — no escaping needed by the caller.
#
# Usage:
#   echo 'ls -la /host/root/.ssh' | node-debug-exec.sh --node kubeos2
#   node-debug-exec.sh --node kubeos3 --image auto <<'EOF'
#     grep -iE 'permitroot|pubkey' /host/etc/ssh/sshd_config
#     cat /host/root/.ssh/authorized_keys
#   EOF
#
# Env defaults (override per environment — see env.example):
#   SSH_HOST     host where kubectl/the wrapper runs and can reach the cluster (default: npuserver)
#   KUBECTL      kubectl invocation on SSH_HOST, may include args (default: kos2)
#   DEBUG_IMAGE  container image with a shell, pullable BY THE CLUSTER. "auto" =
#                pick an already-present /3rdparty/kubectl|busybox|toolbox image so
#                no registry pull is needed in air-gap (default: auto)
set -euo pipefail

SSH_HOST="${SSH_HOST:-npuserver}"
KUBECTL="${KUBECTL:-kos2}"
DEBUG_IMAGE="${DEBUG_IMAGE:-auto}"
NODE=""
PROFILE="sysadmin"
TIMEOUT="90"

usage() { sed -n '2,40p' "$0" >&2; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --node)     NODE="${2:-}"; shift 2 ;;
    --ssh-host) SSH_HOST="${2:-}"; shift 2 ;;
    --kubectl)  KUBECTL="${2:-}"; shift 2 ;;
    --image)    DEBUG_IMAGE="${2:-}"; shift 2 ;;
    --profile)  PROFILE="${2:-}"; shift 2 ;;
    --timeout)  TIMEOUT="${2:-}"; shift 2 ;;
    -h|--help)  usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

: "${NODE:?missing --node}"

SNIPPET="$(cat)"
[[ -n "$SNIPPET" ]] || { echo "node-debug-exec: empty snippet on stdin" >&2; exit 2; }
B64="$(printf '%s' "$SNIPPET" | base64 | tr -d '\n')"

# Everything below runs on SSH_HOST. Creds-free (kubectl access is via the wrapper).
ssh "$SSH_HOST" "NODE='$NODE' KUBECTL='$KUBECTL' DEBUG_IMAGE='$DEBUG_IMAGE' \
  PROFILE='$PROFILE' TIMEOUT='$TIMEOUT' B64='$B64' bash -s" <<'REMOTE'
set -euo pipefail

# Resolve the debug image: prefer one already present in the cluster (air-gap safe).
if [[ "$DEBUG_IMAGE" == "auto" ]]; then
  DEBUG_IMAGE="$($KUBECTL get pods -A \
      -o jsonpath='{range .items[*]}{range .spec.containers[*]}{.image}{"\n"}{end}{end}' 2>/dev/null \
      | sort -u | grep -m1 -iE '/3rdparty/kubectl(:|$)|/busybox(:|$)|/toolbox(:|$)' || true)"
  if [[ -z "$DEBUG_IMAGE" ]]; then
    echo "node-debug-exec: could not auto-detect a debug image; pass --image <ref>" >&2
    exit 3
  fi
fi
echo "node-debug-exec: node=$NODE image=$DEBUG_IMAGE" >&2

newest_pod() {
  $KUBECTL get pods \
    -o jsonpath='{range .items[*]}{.metadata.creationTimestamp}{" "}{.metadata.name}{"\n"}{end}' 2>/dev/null \
    | grep "node-debugger-$NODE-" | sort | tail -1 | awk '{print $2}'
}

# Launch the debug pod DETACHED — do not rely on attach (over a non-TTY ssh it can
# return before the container has even started). We discover the pod, wait for it to
# terminate, then read its logs.
( timeout "$TIMEOUT" $KUBECTL debug "node/$NODE" -q --attach=false \
    --image="$DEBUG_IMAGE" --profile="$PROFILE" \
    -- sh -c "echo $B64 | base64 -d | sh" ) >/dev/null 2>&1 || true

# Wait for the pod object to appear (RFC3339 timestamps sort lexicographically).
POD=""
for _ in $(seq 1 30); do POD="$(newest_pod)" || true; [[ -n "$POD" ]] && break; sleep 1; done
if [[ -z "$POD" ]]; then
  echo "node-debug-exec: no debugger pod appeared for $NODE (debug create failed?)" >&2
  exit 4
fi

# Wait for the container to finish so logs are complete (not ContainerCreating).
for _ in $(seq 1 "$TIMEOUT"); do
  PHASE="$($KUBECTL get pod "$POD" -o jsonpath='{.status.phase}' 2>/dev/null)" || true
  case "$PHASE" in Succeeded|Failed) break ;; esac
  sleep 1
done

$KUBECTL logs "$POD" 2>&1
$KUBECTL delete pod "$POD" --ignore-not-found >/dev/null 2>&1 || true
REMOTE
