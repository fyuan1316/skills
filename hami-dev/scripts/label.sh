#!/usr/bin/env bash
# hami-dev — fix the OCI build-image `org.opencontainers.image.source` label in a
# repo's Katanomi build config (.build/build.yaml) so it matches the repo itself.
#
# Background: several repos copy-pasted the labels block and left
# image.source=aml/ai-infra/HAMi-WebUI on the wrong repo. This sets it to
# aml/ai-infra/<repo>. Per-repo by design (the correct value IS the repo).
#
# Pure GitLab API (token from envs/env.gitlab) — no local git, no ssh, doesn't
# touch the working tree. Creates a feat/* branch + a clean MR and STOPS (never
# merges). Review + merge is the human's call.
#
# Usage: label.sh <repo>   e.g. label.sh HAMi
set -euo pipefail

REPO="${1:?usage: label.sh <repo> (e.g. HAMi)}"
# trunk per repo (HAMi's is release-2.8; others master). Override with TARGET=.
case "$REPO" in
  HAMi) TARGET="${TARGET:-release-2.8}" ;;
  *)    TARGET="${TARGET:-master}" ;;
esac
BRANCH="${BRANCH:-feat/aml-dev-fix-oci-image-source}"
FILE=".build/build.yaml"
WANT="aml/ai-infra/$REPO"

H="${GITLAB_HOST:-gitlab-ce.alauda.cn}"
# Author work as yuanfang (Developer), NOT envs/env.gitlab which is the
# alaudabot ADMIN token — MRs/commits must show as the real author.
TOK_FILE="${GITLAB_TOKEN_FILE:-/workspaces/home/secrets/gitlab.token}"
TOK="$(tr -d '[:space:]' < "$TOK_FILE" 2>/dev/null)"
[ -n "$TOK" ] || { echo "label: no yuanfang token at $TOK_FILE" >&2; exit 2; }
AUTHOR_NAME="${GIT_AUTHOR_NAME:-yuanfang}"
AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-yuanfang@alauda.io}"
ENC="aml%2Fai-infra%2F$REPO"
EFILE="$(printf '%s' "$FILE" | sed 's#/#%2F#g')"
api()  { curl -s --max-time 30 -H "PRIVATE-TOKEN: $TOK" "$@"; }
log()  { echo "label: $*" >&2; }

tmp=/tmp/label-$REPO; mkdir -p "$tmp"
log "fetch $FILE @ $TARGET"
api "https://$H/api/v4/projects/$ENC/repository/files/$EFILE/raw?ref=$TARGET" > "$tmp/build.yaml"
cur="$(grep -oE 'org\.opencontainers\.image\.source=\S+' "$tmp/build.yaml" | head -1 | cut -d= -f2- || true)"
log "current image.source = ${cur:-<none>}   want = $WANT"
if [ "$cur" = "$WANT" ]; then log "already correct — nothing to do"; exit 0; fi
[ -n "$cur" ] || { log "no image.source line in $FILE@$TARGET (this repo needs the labels block ADDED, not fixed); aborting"; exit 3; }

# apply the fix to all image.source lines (there should be exactly one)
sed -E "s#(org\.opencontainers\.image\.source=).*#\1$WANT#" "$tmp/build.yaml" > "$tmp/build.yaml.new"
log "diff:"; diff "$tmp/build.yaml" "$tmp/build.yaml.new" || true

log "create branch $BRANCH from $TARGET"
api -X POST "https://$H/api/v4/projects/$ENC/repository/branches?branch=$BRANCH&ref=$TARGET" \
  | jq -r 'if .name then "  branch: \(.name)" else "  (branch create: \(.message // .))" end'

log "commit fix to $BRANCH"
# This GitLab (14.x) only accepts encoding=base64 for the files API ("text"
# returns 'encoding does not have a valid value'), so base64 the content.
b64="$(base64 -w0 "$tmp/build.yaml.new")"
jq -n --arg b "$BRANCH" --arg c "$b64" \
   --arg m "fix(ci): correct OCI image.source label to $WANT" \
   --arg an "$AUTHOR_NAME" --arg ae "$AUTHOR_EMAIL" \
   '{branch:$b, encoding:"base64", content:$c, commit_message:$m, author_name:$an, author_email:$ae}' \
 | api -X PUT -H 'Content-Type: application/json' \
     "https://$H/api/v4/projects/$ENC/repository/files/$EFILE" --data @- \
 | jq -r 'if .file_path then "  commit ok: \(.file_path)" else "  commit FAILED: \(.error // .message)" end'

log "open MR $BRANCH -> $TARGET (no merge)"
api -X POST "https://$H/api/v4/projects/$ENC/merge_requests" \
   --data-urlencode "source_branch=$BRANCH" \
   --data-urlencode "target_branch=$TARGET" \
   --data-urlencode "title=fix(ci): correct OCI image.source label to $WANT" \
   --data-urlencode "description=The build labels block had \`org.opencontainers.image.source=$cur\` (copy-paste from another repo). This sets it to \`$WANT\` so the built image's OCI source points at this repo. One-line change to $FILE; repo-path was already correct." \
   --data-urlencode "remove_source_branch=true" \
 | jq -r 'if .web_url then "MR: \(.web_url)\n  state=\(.state) merge_status=\(.merge_status)" else "  (MR: \(.message // .))" end'
