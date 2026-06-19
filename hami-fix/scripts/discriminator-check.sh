#!/usr/bin/env bash
# discriminator-check.sh — machine-verify that a new test is a REAL discriminator,
# not a tautology. Implements the "judgement gate" from the automation L0 3.1:
# an un-fakeable oracle only means something if the new test FAILS against the
# pre-change production code and PASSES with the fix.
#
# Procedure:
#   1. At the current working state, the target test(s) must PASS.
#   2. Revert every changed *production* (non-_test.go) file to <base> — keeping
#      the new/changed test files exactly as they are — then the SAME test(s)
#      must FAIL. (If they still pass, the test doesn't exercise the fix: tautology.)
#   3. Restore the production files to their exact prior content (never touches
#      the git index; pure file-content swap, with a restore trap).
#
# Usage:
#   discriminator-check.sh <repo> <base_ref> <go-test-args...>
# Example (validates the v0 quota fix on the feat branch, HEAD = fix commit):
#   discriminator-check.sh hami HEAD~1 ./pkg/device/ -run TestDelQuotaIgnoresNonLimitsKey
set -euo pipefail

REPO_ALIAS="${1:?usage: discriminator-check.sh <repo> <base_ref> <go-test-args...>}"
BASE="${2:?need base ref (pre-change), e.g. HEAD~1 or a commit/branch}"
shift 2
TEST_ARGS=("$@")
[ ${#TEST_ARGS[@]} -gt 0 ] || { echo "discriminator-check: need go-test args" >&2; exit 2; }

AI_INFRA="${AI_INFRA:-/workspaces/yuanfang-base-ubuntu/projects/ai-infra}"
TOOLROOT="${TOOLROOT:-/tmp/hami-toolchain}"
HAMI_DEV="${HAMI_DEV:-/workspaces/yuanfang-base-ubuntu/kbs/fy-skills/hami-dev}"

# toolchain (reuse hami-dev's idempotent bootstrap)
if [ ! -x "$TOOLROOT/go/bin/go" ]; then
  TOOLROOT="$TOOLROOT" bash "$HAMI_DEV/scripts/bootstrap.sh" >&2
fi
# shellcheck disable=SC1091
. "$TOOLROOT/env.sh"

case "$(echo "$REPO_ALIAS" | tr '[:upper:]' '[:lower:]')" in
  hami) REPO=HAMi ;;
  hami-webui|webui) REPO=HAMi-WebUI ;;
  dcgm|dcgm-exporter) REPO=dcgm-exporter ;;
  *) REPO="$REPO_ALIAS" ;;
esac
repo_dir="$AI_INFRA/$REPO"
[ -d "$repo_dir" ] || { echo "discriminator-check: no such repo dir: $repo_dir" >&2; exit 2; }
cd "$repo_dir"

run_test() { go test "${TEST_ARGS[@]}" -count=1; }

# --- 1. current state must PASS ---
echo "discriminator-check: [1/3] target test must PASS at current state ..." >&2
if ! run_test >/dev/null 2>&1; then
  echo "discriminator-check: FAIL — target test does not pass at current state (fix incomplete?)" >&2
  exit 1
fi
echo "discriminator-check:       ok, passes now." >&2

# --- identify changed PRODUCTION files (non-_test.go) vs base ---
mapfile -t PROD < <(git diff --name-only "$BASE" -- '*.go' | grep -v '_test\.go$' || true)
if [ ${#PROD[@]} -eq 0 ]; then
  echo "discriminator-check: FAIL — no production (.go non-test) files changed vs $BASE; nothing to revert." >&2
  exit 1
fi
echo "discriminator-check: production files to revert vs $BASE:" >&2
printf '  - %s\n' "${PROD[@]}" >&2

# --- back up current content, set restore trap (pure file-content swap; index untouched) ---
BK="$(mktemp -d)"
restore() {
  for f in "${PROD[@]}"; do
    [ -f "$BK/$f" ] && { mkdir -p "$(dirname "$f")"; cp "$BK/$f" "$f"; }
  done
  rm -rf "$BK"
}
trap restore EXIT
for f in "${PROD[@]}"; do mkdir -p "$BK/$(dirname "$f")"; cp "$f" "$BK/$f"; done

# --- 2. revert production to base, SAME test must FAIL ---
echo "discriminator-check: [2/3] reverting production to $BASE; target test must now FAIL ..." >&2
for f in "${PROD[@]}"; do
  if git cat-file -e "$BASE:$f" 2>/dev/null; then
    git show "$BASE:$f" > "$f"
  else
    rm -f "$f"   # file didn't exist at base (newly added production file)
  fi
done

if run_test >/dev/null 2>&1; then
  echo "discriminator-check: VERDICT=TAUTOLOGY — test still PASSES against pre-change code." >&2
  echo "discriminator-check:   The new test does NOT exercise the fix. Reject it." >&2
  exit 3
fi
echo "discriminator-check:       good, it fails against pre-change code." >&2

# --- 3. restore happens via trap ---
echo "discriminator-check: [3/3] restored production files." >&2
echo "discriminator-check: VERDICT=DISCRIMINATOR — test fails on old code, passes on fix. ✅" >&2
