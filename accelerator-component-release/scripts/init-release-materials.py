#!/usr/bin/env python3
"""Create the canonical accelerator release material skeleton."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

FILES = [
    "README.md", "_progress-table.md", "_release-readiness-gaps.md", "_approvals.md",
    "evidence/README.md", "01-change-list.md", "02-artifacts.md", "03-test-report.md",
    "04-security-report.md", "05-legacy-issues.md", "06-nonfunctional-decision.md",
    "07-release-note.md", "08-test-evidence.md", "09-release-rounds.md",
    "10-standard-review-checklist.md", "docs-update.md", "release-profile.yaml",
]


def valid(value: str, label: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", value):
        raise ValueError(f"{label} must contain lowercase letters, digits, dots or hyphens")
    return value


def render(path: str, component: str, version: str, branch: str, today: str) -> str:
    title = f"{component} {version}"
    if path == "release-profile.yaml":
        return f'''---
apiVersion: accelerator.alauda.io/v1alpha1
kind: AcceleratorReleaseProfile
metadata:
  name: {component}-{version}
  owner: TODO
  createdAt: '{today}'
  status: material-skeleton-created
  description: TODO: complete the source-first release profile.
release:
  component: {component}
  version: {version}
  candidate: TODO
  releaseType: TODO
  startMode: source-first
  currentDecision: BLOCKED
source:
  repo: TODO
  branch: {branch}
  revision: refs/heads/{branch}
  testedCommit: TODO
build:
  required: true
  triggerPolicy: manual-confirm
  skill: edge-buildrun-ops
  buildName: TODO
  cluster: business-build
  namespace: aml-dev
  revision: refs/heads/{branch}
  candidateVersion: TODO
  candidateCommit: TODO
artifacts:
  package:
    url: ''
    sha256: ''
pluginPackage:
  requiredForAcUpload: true
formalPackageSmoke:
  status: not-run
acUpload:
  status: blocked
facts:
  material.release-skeleton.created: true
  gate.release-material-skeleton.passed: true
knownGaps:
  - id: GAP-MATERIAL-FACTS
    type: MATERIAL
    severity: P0
    blocking: true
    status: open
    title: Fill source, artifact, test, security and approval facts
'''
    bodies = {
        "README.md": f"# {title} Release Materials\n\nCanonical source-first release directory for `{component}` `{version}`.\n\nStatus: `BLOCKED` until every required gate is backed by evidence.\n\nMain entry: [release-profile.yaml](release-profile.yaml).\n\nTODO: record the current RC, formal tag, package, test and AC state.\n",
        "_progress-table.md": "# Progress Table\n\n| Stage | Status | Evidence / next action |\n|---|---|---|\n| Material skeleton | complete | release profile and standard files created |\n| Source audit | TODO | record branch, upstream tag and commit |\n| RC build and artifacts | TODO | record BuildRun, package and image digests |\n| RC function/security gates | TODO | record test and scan evidence |\n| Formal package and smoke | TODO | install exact final package and verify cleanup |\n| AC listing and docs | TODO | upload/list and update product docs |\n",
        "_release-readiness-gaps.md": "# Release Readiness Gaps\n\n| ID | Type | Severity | Status | Required closure |\n|---|---|---:|---|---|\n| GAP-SOURCE | ARTIFACT | P0 | open | source branch/tag/commit evidence |\n| GAP-RC-ARTIFACTS | ARTIFACT | P0 | open | RC package, checksum and image digests |\n| GAP-RC-FUNCTION | FUNCTION | P0 | open | blocking hardware/e2e matrix passed |\n| GAP-RC-SECURITY | SECURITY | P0 | open | release-grade scan and residual approval |\n| GAP-FORMAL | ARTIFACT | P0 | open | formal tag/build/package/smoke |\n| GAP-AC-DOCS | DOCUMENTATION | P0 | open | AC listing and product docs |\n",
        "_approvals.md": "# Approvals\n\n| Decision | Status | Scope / evidence |\n|---|---|---|\n| RC build trigger | TODO | explicit user approval plus profile fact |\n| RC package rollout | TODO | exact package and target environment |\n| Formal tag/build | not approved | only after RC gates close |\n| Formal package smoke | not approved | exact final package required |\n| AC upload | not approved | only after formal smoke |\n",
        "evidence/README.md": "# Evidence Index\n\nRecord exact commands, timestamps, source commits, image digests, package checksums, environment facts, results and cleanup for every gate.\n\nTODO: add action result files under `evidence/actions/` and test/security evidence under their respective directories.\n",
        "01-change-list.md": f"# Change List — {title}\n\nSource branch: `{branch}`.\n\nTODO: compare against the upstream baseline and group changes by runtime, packaging, CRD, security and documentation impact.\n",
        "02-artifacts.md": f"# Artifact Inventory — {title}\n\nTODO: record controller/bundle/plugin refs, immutable digests, package URLs/checksums, relatedImages and package-content proof.\n",
        "03-test-report.md": f"# Test Report — {title}\n\nCurrent conclusion: `BLOCKED` until the candidate function matrix is actually executed.\n\nTODO: record environments, cases, results, logs, JUnit and cleanup.\n",
        "04-security-report.md": f"# Security Report — {title}\n\nTODO: record scanner/database, immutable image refs, severity counts and residual-risk approvals.\n",
        "05-legacy-issues.md": f"# Legacy Issues and Known Risks — {title}\n\n| ID | Risk | Impact | Status / handling |\n|---|---|---|---|\n| L-1 | TODO | TODO | open |\n",
        "06-nonfunctional-decision.md": f"# Non-functional Decision — {title}\n\nTODO: state what is tested, deferred or accepted, with owner and follow-up evidence.\n",
        "07-release-note.md": f"# Release Note — {title}\n\nTODO: summarize user-visible changes, prerequisites, upgrade/rollback and known limitations.\n",
        "08-test-evidence.md": f"# Test Evidence — {title}\n\nTODO: index environment baseline, deployment output, result files, runtime image IDs and cleanup.\n",
        "09-release-rounds.md": f"# Release Rounds — {title}\n\n| Round | Candidate | Source | Result | Notes |\n|---|---|---|---|---|\n| Current | TODO | TODO | TODO | preserve failed/superseded rounds |\n",
        "10-standard-review-checklist.md": f"# Standard Review Checklist — {title}\n\n- [ ] Source provenance\n- [ ] RC package and image digests\n- [ ] Package-owned/related image inventory, synchronization, mapping and runtime image IDs\n- [ ] Package-external runtime image refs, architecture, import/rewrite path and runtime image IDs\n- [ ] RC function/e2e\n- [ ] Release-grade security scan\n- [ ] Formal tag/build\n- [ ] Exact formal package smoke\n- [ ] AC listing\n- [ ] Product documentation covers both image delivery sets\n\nCurrent decision: `BLOCKED`.\n",
        "docs-update.md": f"# Product Documentation Update — {title}\n\nStatus: pending final artifact facts.\n\nTODO: update installation, prerequisites, versions, upgrade/rollback, known limitations and final package references. Classify package-owned/related images separately from package-external runtime images; record acquisition, architecture, target registry, mapping/rewrite and runtime image-ID verification for both.\n",
    }
    return bodies[path]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--component", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-branch", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        component = valid(args.component, "component")
        version = valid(args.version, "version")
        if not args.source_branch or any(c.isspace() for c in args.source_branch):
            raise ValueError("source-branch must be non-empty and contain no whitespace")
        output = args.output.resolve()
        existing = [output / p for p in FILES if (output / p).exists()]
        if existing and not args.force:
            print("refusing to overwrite existing release files:", file=sys.stderr)
            print("\n".join(str(p) for p in existing), file=sys.stderr)
            return 2
        today = dt.date.today().isoformat()
        for rel in FILES:
            dest = output / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(render(rel, component, version, args.source_branch, today), encoding="utf-8")
        result = {"releaseDir": str(output), "files": FILES, "facts": ["material.release-skeleton.created", "gate.release-material-skeleton.passed"]}
        print(json.dumps(result, indent=2) if args.json else f"created {len(FILES)} release material files under {output}")
        return 0
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
