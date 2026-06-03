#!/usr/bin/env bash
# bootstrap-ssh.sh — install a public key into the authorized_keys of cluster nodes
# that have no SSH login, so you get passwordless root SSH. Uses node-debug-exec.sh
# (kubectl debug node) to reach each node's writable rootfs.
#
# Designed for immutable / KubeOS nodes where:
#   - "/" is read-only, but "/etc" and "/root" are overlay mounts whose upperdir is
#     on a persistent partition (KubeOS: /persist) — writes survive reboot AND the
#     A/B image upgrade. The script verifies the target dir is on such a mount and
#     refuses to write to a volatile (tmpfs/lowerdir-only) location.
#
# For each node it: (1) preflights sshd + existing keys + writability, (2) installs
# the key (idempotent; additive by default), (3) verifies passwordless `ssh <node>`.
#
# Usage:
#   bootstrap-ssh.sh --nodes auto
#   bootstrap-ssh.sh --nodes "kubeos2 kubeos3" --pubkey-file ~/.ssh/id_ed25519.pub
#   bootstrap-ssh.sh --nodes auto --preflight-only
#   bootstrap-ssh.sh --nodes auto --mode exclusive    # DANGER: removes all other keys
#
# Env defaults (override per environment — see env.example):
#   SSH_HOST, KUBECTL, DEBUG_IMAGE   (passed through to node-debug-exec.sh)
#   PUBKEY_FILE   local public key to install        (default: ~/.ssh/id_ed25519.pub)
#   AUTHKEYS      authorized_keys path ON the node   (default: /root/.ssh/authorized_keys)
#   NODES         space-separated node list or "auto" (default: auto)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXEC="$HERE/node-debug-exec.sh"

SSH_HOST="${SSH_HOST:-npuserver}"
KUBECTL="${KUBECTL:-kos2}"
DEBUG_IMAGE="${DEBUG_IMAGE:-auto}"
PUBKEY_FILE="${PUBKEY_FILE:-$HOME/.ssh/id_ed25519.pub}"
PUBKEY=""
AUTHKEYS="${AUTHKEYS:-/root/.ssh/authorized_keys}"
NODES="${NODES:-auto}"
MODE="additive"          # additive | exclusive
PREFLIGHT_ONLY=0
NO_VERIFY=0
VERIFY_ALIAS=""          # ssh alias pattern; %s = node name. default: the node name

usage() { sed -n '2,30p' "$0" >&2; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --nodes)         NODES="${2:-}"; shift 2 ;;
    --ssh-host)      SSH_HOST="${2:-}"; shift 2 ;;
    --kubectl)       KUBECTL="${2:-}"; shift 2 ;;
    --image)         DEBUG_IMAGE="${2:-}"; shift 2 ;;
    --pubkey-file)   PUBKEY_FILE="${2:-}"; shift 2 ;;
    --pubkey)        PUBKEY="${2:-}"; shift 2 ;;
    --authkeys)      AUTHKEYS="${2:-}"; shift 2 ;;
    --mode)          MODE="${2:-}"; shift 2 ;;
    --preflight-only) PREFLIGHT_ONLY=1; shift ;;
    --no-verify)     NO_VERIFY=1; shift ;;
    --verify-alias)  VERIFY_ALIAS="${2:-}"; shift 2 ;;
    -h|--help)       usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

export SSH_HOST KUBECTL DEBUG_IMAGE

# ── resolve the public key ────────────────────────────────────────────────────
if [[ -z "$PUBKEY" ]]; then
  [[ -r "$PUBKEY_FILE" ]] || { echo "bootstrap-ssh: cannot read $PUBKEY_FILE" >&2; exit 2; }
  PUBKEY="$(cat "$PUBKEY_FILE")"
fi
PUBKEY="${PUBKEY#"${PUBKEY%%[![:space:]]*}"}"   # ltrim
BLOB="$(awk '{print $2}' <<<"$PUBKEY")"          # key body — used for idempotency match
[[ -n "$BLOB" ]] || { echo "bootstrap-ssh: '$PUBKEY' is not a valid public key line" >&2; exit 2; }
echo "[bootstrap] key: $(awk '{print $1" "substr($2,1,16)"… "$3}' <<<"$PUBKEY")" >&2

# ── resolve node list ─────────────────────────────────────────────────────────
if [[ "$NODES" == "auto" ]]; then
  NODES="$(ssh "$SSH_HOST" "$KUBECTL get nodes -o name" 2>/dev/null | sed 's#node/##' | tr '\n' ' ')"
fi
[[ -n "${NODES// }" ]] || { echo "bootstrap-ssh: no nodes (try --nodes 'a b')" >&2; exit 2; }
echo "[bootstrap] nodes: $NODES" >&2

AUTHDIR="$(dirname "$AUTHKEYS")"
HOSTKEYS="/host$AUTHKEYS"
HOSTDIR="/host$AUTHDIR"

# ── per-node ──────────────────────────────────────────────────────────────────
for NODE in $NODES; do
  echo; echo "==================== $NODE ===================="

  # 1) preflight: sshd policy, existing keys, writability + persistence of target dir
  PRE="$("$EXEC" --node "$NODE" <<EOF
echo "--- sshd policy ---"
grep -iE 'permitrootlogin|pubkeyauthentication|authorizedkeysfile' /host/etc/ssh/sshd_config 2>/dev/null | grep -v '^[[:space:]]*#'
echo "--- existing authorized_keys (${AUTHKEYS}) ---"
if [ -f "$HOSTKEYS" ]; then awk '{print NR": "\$1" … "\$NF}' "$HOSTKEYS"; else echo "(none)"; fi
echo "--- backing mount of ${AUTHDIR} (want persistent overlay, not tmpfs) ---"
awk -v d="$HOSTDIR/" '{ if (index(d, \$2"/")==1 && length(\$2)>=L){L=length(\$2); line=\$0} } END{ if(line)print line; else print "(no backing mount found)" }' /proc/mounts 2>/dev/null
echo "--- write test ---"
mkdir -p "$HOSTDIR" 2>/dev/null && touch "$HOSTDIR/.wtest" 2>/dev/null && echo "WRITABLE=yes" && rm -f "$HOSTDIR/.wtest" || echo "WRITABLE=no"
echo "--- key already present? ---"
grep -qF "$BLOB" "$HOSTKEYS" 2>/dev/null && echo "PRESENT=yes" || echo "PRESENT=no"
EOF
)"
  echo "$PRE"

  if [[ "$PREFLIGHT_ONLY" == 1 ]]; then continue; fi
  if ! grep -q 'WRITABLE=yes' <<<"$PRE"; then
    echo "[$NODE] target not writable — skipping install (need a writable persistent path)" >&2
    continue
  fi
  if grep -q 'PRESENT=yes' <<<"$PRE"; then
    echo "[$NODE] key already installed — nothing to do"
  else
    # 2) install. additive = append; exclusive = overwrite (removes everyone else!)
    if [[ "$MODE" == "exclusive" ]]; then
      echo "[$NODE] MODE=exclusive — OVERWRITING authorized_keys (all other keys removed)" >&2
      WRITE="printf '%s\n' \"\$KEYLINE\" > \"$HOSTKEYS\""
    else
      WRITE="grep -qF \"$BLOB\" \"$HOSTKEYS\" 2>/dev/null || printf '\n%s\n' \"\$KEYLINE\" >> \"$HOSTKEYS\""
    fi
    INSTALL_OUT="$("$EXEC" --node "$NODE" <<EOF
KEYLINE='$PUBKEY'
mkdir -p "$HOSTDIR"
$WRITE
chmod 700 "$HOSTDIR"; chmod 600 "$HOSTKEYS"; chown -R 0:0 "$HOSTDIR"
grep -qF "$BLOB" "$HOSTKEYS" && echo "INSTALLED=ok" || echo "INSTALLED=FAILED"
echo "now \$(grep -c . "$HOSTKEYS") key line(s)"
EOF
)"
    echo "$INSTALL_OUT"
    grep -q 'INSTALLED=ok' <<<"$INSTALL_OUT" || { echo "[$NODE] install FAILED" >&2; continue; }
  fi

  # 3) verify real passwordless login
  if [[ "$NO_VERIFY" == 1 ]]; then continue; fi
  ALIAS="$NODE"; [[ -n "$VERIFY_ALIAS" ]] && printf -v ALIAS "$VERIFY_ALIAS" "$NODE"
  echo "--- verify: ssh $ALIAS (passwordless) ---"
  if ssh -o BatchMode=yes -o ConnectTimeout=20 "$ALIAS" 'echo LOGIN_OK; ls / | tr "\n" " "; echo' 2>&1; then
    echo "[$NODE] ✅ passwordless login works"
  else
    echo "[$NODE] ⚠ login test failed — check ~/.ssh/config has Host $ALIAS (ProxyJump $SSH_HOST) or pass --verify-alias / --no-verify" >&2
  fi
done
