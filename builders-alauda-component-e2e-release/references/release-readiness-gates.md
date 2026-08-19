# Release Readiness Gates

Use these gates before committing a release candidate, pushing a release branch, creating or updating a release PR/MR, or declaring an Alauda component ready for AC publishing. They summarize the ACP 4.0 L5 plugin release flow and Alauda security handling standards without copying credentials or environment-specific examples.

When using this document to fix CVEs, cross-check it with the user-provided scan reports, security tickets, CVE notes, previous-release image references, vulnerability tracking documents, and `builders-alauda-security-scan` outputs. Use the referenced documents to determine whether each finding is fixed, false positive, approved residual risk, known issue, or release blocker. Do not rely only on a Dockerfile edit or a local scan summary when the referenced security documents require a stricter decision or extra evidence. Apply the same evidence discipline to Helm chart, Kubernetes manifest, and OLM operator security findings, including PSA, non-root, privilege, host access, secret, and RBAC issues.

## Security Fix Gate

Classify the release before applying thresholds:

- `.0` or security release: required security fixes are strict. Fix Critical and High vulnerabilities. Fix Medium and Low vulnerabilities when an upstream or vendor fix exists. If a required fix has no available remediation, is a false positive, or has prohibitive risk, record the review decision and approval before proceeding.
- `.x` non-security release: fix severe security issues identified by the security team or release owner. Do not silently carry known severe vulnerabilities.
- Security redline issues are treated as bugs and must follow the same tracking, fix, verification, and residual-risk process as release-blocking bugs.

Collect evidence before the release candidate is frozen:

- Target version, release type, previous released version, and vulnerability database freeze date. For L5 or agnostic plugins the freeze date is decided by the plugin owner, usually no more than one month before release.
- Current image, dependency, package, L5 dynamic, and manifest scan reports from `builders-alauda-security-scan` or an approved equivalent, including scanner name, scan time, package or image reference, manifest input path, and severity counts. Image CVE reports must cover the component-type-specific image set: Cluster Plugin images from release `values.yaml`; OLM operator or Helm operator operator image, bundle image, and all related runtime images needed when using the component.
- Referenced security documents checked: scan report paths, security tickets, CVE notes, vulnerability tracking links, and previous-release image references used to classify fixed CVEs.
- Dockerfile, base image, package manifest, lockfile, or build-argument changes used to fix required CVEs, with rebuilt image references and scan output for the rebuilt images.
- Helm chart, rendered Kubernetes manifest, OLM bundle or CSV, and live cluster scan reports when applicable, including PSA/non-root/RBAC findings and their fix or residual-risk status.
- Security Jira or tracking items tagged as security issues, with fix status, residual-risk decision, false-positive decision, or known-issue decision.
- Regression test evidence for security fixes because security changes often affect low-level dependencies or shared runtime behavior.
- E2E evidence that used the rebuilt images containing the CVE fixes, not stale pre-fix image tags.

Do not proceed to commit or release when:

- Required Critical or High fixes are unresolved.
- A required Medium or Low fix exists for a security release but has neither been applied nor formally reviewed.
- A false-positive or residual-risk decision lacks a recorded review.
- A security fix landed late enough to invalidate e2e, compatibility, or regression evidence.
- Dockerfile or image dependency changes have not been rebuilt, pushed, scanned when possible, and used by the e2e or release validation run.
- Required Helm, Kubernetes manifest, or OLM security findings are unresolved, unreviewed, or were fixed after e2e without re-rendering, repackaging, reinstalling, and rerunning validation.

For customer-reported or internally discovered security issues, preserve the workflow evidence: owner/team assignment, impact analysis, selected handling path, fix or mitigation, test result, and whether the solution should be added to the security solution knowledge base. Use severity labels Critical, High, Medium, and Low consistently with CVSS-style ranges.

When customer-facing security issues are part of the release, track the response SLA evidence as well: acknowledge all severities within 1 hour, provide a solution within 3 days for Critical, 5 days for High, 15 days for Medium, and 30 days for Low unless the release owner documents a different customer commitment.

## Product Documentation Gate

Product documents usually live in a separate docs repository, not in the component repository. Before running the full release workflow for a component, ask the user which repo or local directory stores that component's product documentation unless the docs location is already explicit in the request or discoverable from local workspace metadata. Do not guess the docs repo from the component name.

After e2e passes and before formal AC publishing, update or record the status of product documents that apply to the component in the user-confirmed docs repo or directory:

- Release notes with fixed bugs, known issues, breaking changes, upgrade impact, and links to compatibility evidence.
- User guide, API guide, operations guide, deployment guide, upgrade guide, disaster-recovery guide, and architecture/design notes when the component exposes those surfaces.
- Product feature list, product security statement, product lifecycle/support notes, and upgrade matrix.
- Test documents or links: quality/e2e report, security test report, API automation report when applicable, and compatibility matrix.
- Internal product roadmap records or release inventory entries when the release owner expects them.

Use "not applicable" only after checking the component surface. For example, API docs are not applicable only when the component exposes no customer-facing API. Upgrade documentation is required when a previous version exists or when data/schema/CRD migration can affect users.

Product documentation gaps block formal release. They do not have to block an early development commit unless the user explicitly asks for a release-ready commit or MR.

## Frozen Package Security Scan And CVE Database Gate

After the package is tested and no more package changes are expected:

1. Scan the frozen release package or installation bundle.
2. Record remaining vulnerabilities for the AC CVE database source when required by the release process.
3. Compare the frozen package with the previous release to identify CVEs fixed by this release.
4. Reconcile scan results with the security fix gate: fixed, residual-risk approved, false positive, or not applicable.

This gate must finish before Security ERRATA is produced, because Security ERRATA needs the list of fixed CVEs and security issues.

## ERRATA Gate

Prepare ERRATA after release testing finishes and before formal release communication or AC front-stage publishing:

- New products or first-time plugins generally do not need ERRATA.
- Existing products, follow-up releases, and components split from previous L3/L4 products need ERRATA when bugs or security issues were fixed.
- If bug fixes exist, prepare Bugfix ERRATA from release-note fix descriptions.
- If CVEs or security redline issues were fixed, prepare Security ERRATA from the CVE database comparison and security tracking evidence.
- If both bug fixes and security fixes exist, prepare both Bugfix and Security ERRATA.

ERRATA content must include:

- Product or plugin name, version, compatible ACP or plugin versions, AC bundle ID/product classification when known, release date, and publish status.
- Bugfix ERRATA: type `Bugfix`, severity `none`, no CVE IDs, fixes copied or summarized from approved release notes.
- Security ERRATA: type `Security`, severity set to the highest fixed security severity, CVE IDs where available, security-fix description, and upgrade solution text.
- Description and solution text customized for the component, with links to release notes and upgrade documentation.
- Separate ERRATA per independently installable plugin unless multiple plugins must be installed together for the fix to be valid.

Validate the created ERRATA in AC and record the resulting ERRATA URL or identifier. If ERRATA is not applicable, record the reason in the PR/MR or release notes.

## Commit And Release Checklist

Before committing release workflow changes, pushing a release branch, creating a release PR/MR, or marking release validation complete, report:

- Security gate result: fixed counts, residual approved counts, false-positive counts, unresolved blockers, scan references, and vulnerability database freeze date.
- CVE remediation details: referenced security documents checked, `builders-alauda-security-scan` image or DB scanner outputs, Dockerfiles or image dependency inputs changed, rebuilt image references, scanner result for rebuilt images, and confirmation that e2e used those image references.
- Manifest security details: `builders-alauda-security-scan` manifest outputs, Helm values and rendered manifest paths checked, OLM bundle or CSV paths checked, Trivy or equivalent scanner results, PSA/non-root/RBAC status, fixes applied, and residual-risk decisions.
- Product documentation status: updated files or external document links, plus any not-applicable decisions.
- Frozen package scan and CVE database status.
- ERRATA status: Bugfix ERRATA link, Security ERRATA link, or explicit not-applicable reason.
- E2E, compatibility, performance, and HA evidence from the normal e2e workflow.

If any required item is missing, stop and list the missing release blocker instead of treating the release as complete.
