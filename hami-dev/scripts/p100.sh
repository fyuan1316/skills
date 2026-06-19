#!/usr/bin/env bash
# hami-dev Tier-3 helper — run a command on the Tesla P100 GPU box, reached via
# the QQ jumper (nested ssh; the jumper has a passwordless key to the P100).
# This is the NVIDIA functional-test target for HAMi-core and accelerator-test
# pgpu cases. Verified reachable 2026-06-04; see memory ref-p100-gpu-access.
#
# Connection params are explicit (not relying on ~/.ssh/config) so this works
# unchanged on Mac or any devpod that has the jumper key.
#
# Usage:
#   p100.sh 'nvidia-smi -L'
#   p100.sh < script.sh          # pipe a script to run on the P100
#   echo 'hostname' | p100.sh
#
# Env overrides: JUMPER_KEY JUMPER_HOST JUMPER_PORT JUMPER_USER P100_HOST P100_USER
set -euo pipefail

JUMPER_KEY="${JUMPER_KEY:-$HOME/.ssh/fy-qq-jumper.pem}"
JUMPER_HOST="${JUMPER_HOST:-192.168.144.101}"
JUMPER_PORT="${JUMPER_PORT:-52022}"
JUMPER_USER="${JUMPER_USER:-fangyuan}"
P100_HOST="${P100_HOST:-192.168.138.15}"
P100_USER="${P100_USER:-root}"

[ -f "$JUMPER_KEY" ] || { echo "p100: jumper key not found: $JUMPER_KEY (set JUMPER_KEY=)" >&2; exit 2; }

SSH_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=10"
INNER_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=8"

# Command: from args, else from stdin (a script to run remotely under bash -s).
if [ "$#" -gt 0 ]; then
  remote_cmd="$*"
  exec ssh -i "$JUMPER_KEY" -p "$JUMPER_PORT" $SSH_OPTS "$JUMPER_USER@$JUMPER_HOST" \
    "ssh $INNER_OPTS $P100_USER@$P100_HOST $(printf '%q' "$remote_cmd")"
else
  # Stale-host-key guard (P100 was reinstalled; jumper may hold an old key).
  ssh -i "$JUMPER_KEY" -p "$JUMPER_PORT" $SSH_OPTS "$JUMPER_USER@$JUMPER_HOST" \
    "ssh-keygen -R $P100_HOST >/dev/null 2>&1; ssh $INNER_OPTS $P100_USER@$P100_HOST 'bash -s'"
fi
