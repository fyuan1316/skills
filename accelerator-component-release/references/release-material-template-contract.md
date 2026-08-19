# Release Material Template Contract

The canonical directory is:

```text
docs/releases/<component>-<version>/
```

The template factory creates these files before any mutating release action:

```text
README.md
_progress-table.md
_release-readiness-gaps.md
_approvals.md
evidence/README.md
01-change-list.md
02-artifacts.md
03-test-report.md
04-security-report.md
05-legacy-issues.md
06-nonfunctional-decision.md
07-release-note.md
08-test-evidence.md
09-release-rounds.md
10-standard-review-checklist.md
docs-update.md
release-profile.yaml
```

The generated files are intentionally factual placeholders. Replace every
`TODO` before the corresponding gate closes; do not replace missing evidence
with a success statement.

Minimum stage contract:

| Stage | Required material |
|---|---|
| Source-first | profile, README, change list, progress table, gap register |
| RC build | artifacts, test evidence, action result, RC round entry |
| RC gate | test report, security report, approvals, checklist |
| Formal package | package URL/checksum, package content proof, formal image digests |
| Formal smoke | environment, install output, workload, runtime image IDs, cleanup |
| AC/docs close | AC listing evidence, release note, docs-update and final checklist |

The package/image and documentation sections must classify images into two
delivery sets:

- Package-owned or packaged `relatedImages`: record the authoritative inventory,
  exact refs/digests, package synchronization result, and any runtime
  source-to-target mapping or rewrite required by the installation platform.
- Package-external runtime images: record every image referenced by supported
  bootstrap/sample/runtime paths but excluded from the package, including its
  exact source ref, architecture, acquisition/import procedure, target registry,
  rewrite rule, owner, and verification evidence.

Do not close the docs gate from a `relatedImages` list alone. The standard
checklist and `docs-update.md` must cover both sets. Runtime verification should
use representative Pod `imageID` values and digests; a source ref remaining in
the Pod spec is not itself a failure when an approved platform rewrite policy is
part of the documented install contract.

Historical RC directories are additive. Keep failed and superseded rounds; do
not rename them to make the current formal release look successful.
