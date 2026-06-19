#!/usr/bin/env bash
# edge-ci.sh — trigger / watch Alauda Edge (Katanomi) BuildRuns.
# Reads envs/env.edge (TOKEN). Never prints the token.
#
# Usage:
#   edge-ci.sh builds [grep]              list Build names in the namespace
#   edge-ci.sh trigger <BUILD> <REV>      create a BuildRun for git revision REV
#   edge-ci.sh status  <BUILDRUN>         show phase + Succeeded condition
#   edge-ci.sh wait    <BUILDRUN> [secs]  poll until terminal (default 1800s)
#   edge-ci.sh image   <BUILDRUN>         print built image:tag from status/results
#
# Env overrides: EDGE_ENV (default envs/env.edge), NS (aml-dev), CLUSTER (business-build)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"   # -> /workspaces/yuanfang-base-ubuntu
EDGE_ENV="${EDGE_ENV:-$REPO_ROOT/envs/env.edge}"
NS="${NS:-aml-dev}"
CLUSTER="${CLUSTER:-business-build}"
BASE="https://edge.alauda.cn/kubernetes/$CLUSTER/apis/builds.katanomi.dev/v1alpha1/namespaces/$NS"

[ -f "$EDGE_ENV" ] || { echo "ERR: edge env not found: $EDGE_ENV" >&2; exit 1; }
# shellcheck disable=SC1090
set -a; . "$EDGE_ENV"; set +a
TOK="${TOKEN:-${EDGE_TOKEN:-}}"
[ -n "$TOK" ] || { echo "ERR: TOKEN empty in $EDGE_ENV" >&2; exit 1; }
command -v jq >/dev/null || { echo "ERR: jq required" >&2; exit 1; }

api() { curl -s --max-time 40 -H "Authorization: Bearer $TOK" "$@"; }

cmd="${1:-}"; shift || true
case "$cmd" in
  builds)
    api "$BASE/builds?limit=200" | jq -r '.items[]?.metadata.name' | { [ $# -ge 1 ] && grep -i "$1" || cat; }
    ;;
  trigger)
    BUILD="${1:?build name}"; REV="${2:?git revision (branch/tag/commit)}"
    body=$(jq -n --arg b "$BUILD" --arg ns "$NS" --arg rev "$REV" '{
      apiVersion:"builds.katanomi.dev/v1alpha1", kind:"BuildRun",
      metadata:{ generateName:($b+"-"), namespace:$ns, labels:{"builds.katanomi.dev/build":$b} },
      spec:{ buildRef:{name:$b, namespace:$ns}, git:{revision:$rev}, serviceAccount:{name:""}, status:"" }
    }')
    resp=$(api -X POST -H "Content-Type: application/json" --data-binary "$body" "$BASE/buildruns")
    name=$(echo "$resp" | jq -r '.metadata.name // empty')
    if [ -n "$name" ]; then
      echo "$resp" | jq -r '"triggered: \(.metadata.name)  build=\(.spec.buildRef.name)  rev=\(.spec.git.revision)"'
    else
      echo "FAILED:"; echo "$resp" | jq -r '{code:.code, reason:.reason, message:.message}'; exit 1
    fi
    ;;
  status)
    BR="${1:?buildrun name}"
    api "$BASE/buildruns/$BR" | jq '{name:.metadata.name, phase:.status.phase,
      started:.status.startTime, completed:.status.completionTime,
      succeeded:(.status.conditions[]?|select(.type=="Succeeded")|{status,reason,message})}'
    ;;
  wait)
    BR="${1:?buildrun name}"; MAX="${2:-1800}"; t=0
    while :; do
      j=$(api "$BASE/buildruns/$BR")
      st=$(echo "$j" | jq -r '(.status.conditions[]?|select(.type=="Succeeded")|.status)//"Unknown"')
      ph=$(echo "$j" | jq -r '.status.phase // "?"')
      rs=$(echo "$j" | jq -r '(.status.conditions[]?|select(.type=="Succeeded")|.reason)//""')
      echo "[$t s] phase=$ph succeeded=$st reason=$rs"
      case "$st" in
        True)  echo "BUILD SUCCEEDED"; exit 0 ;;
        False) echo "BUILD FAILED"; echo "$j" | jq -r '.status.conditions[]?|select(.type=="Succeeded")|.message'; exit 2 ;;
      esac
      [ "$t" -ge "$MAX" ] && { echo "TIMEOUT after ${MAX}s"; exit 3; }
      sleep 30; t=$((t+30))
    done
    ;;
  image)
    BR="${1:?buildrun name}"
    api "$BASE/buildruns/$BR" | jq -r '
      [.status.results[]?|select(.name|test("IMAGE|URL|DIGEST|TAG";"i"))|"\(.name)=\(.value)"] as $r
      | if ($r|length)>0 then $r[] else "no image results yet (phase=\(.status.phase))" end'
    ;;
  *)
    sed -n '2,16p' "$0"; exit 1 ;;
esac
