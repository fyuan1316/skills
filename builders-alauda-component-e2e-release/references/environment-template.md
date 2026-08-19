# Alauda Component E2E Release Environment

Ask the user to provide this file before editing a component repo. Secrets may be provided as environment variable names instead of literal values.

## Build

- buildkitd_endpoint:
- buildctl_command:
- build_platforms:

## Registry

- registry:
- image_namespace:
- username_env:
- password_env:
- pull_secret_name:

## Security And CVE Evidence

- image_security_scanner_path:
- image_security_scanner_image:
- db_image_scanner_image:
- security_scan_report_dir:
- trivy_command:
- image_scan_report_paths:
- image_scan_command:
- manifest_scan_report_paths:
- manifest_scan_command:
- security_ticket_query_or_links:
- cve_notes_or_security_doc_paths:
- previous_release_image_refs:

## Kubernetes

- dev_cluster_context:
- global_cluster_context:
- test_namespace:

## ACP Platform

- PLATFORM_ADDRESS:
- PLATFORM_USERNAME_ENV:
- PLATFORM_PASSWORD_ENV:
- CLUSTERS:

## Git

- remote:
- target_branch:
- should_commit_and_push:

## Optional Component Context

- product_name:
- product_version:
- component_type:
- chart_or_bundle_artifact:
- helm_chart_path:
- helm_values_files:
- olm_bundle_or_csv_paths:
- e2e_image:
- expected_e2e_command:
- upstream_repo:
- upstream_version:

## Access Checks

Before editing, verify:

- `buildctl --addr <buildkitd_endpoint> debug workers` succeeds or the provided `buildctl_command` can run an equivalent non-mutating probe.
- Registry credentials are present in the named environment variables.
- Current image CVE evidence is available from `image_scan_report_paths`, `image_scan_command`, linked security tickets, or `cve_notes_or_security_doc_paths` before e2e validation starts.
- Helm, Kubernetes, and OLM manifest security evidence is available from `manifest_scan_report_paths`, `manifest_scan_command`, `trivy_command`, or linked security tickets before packaging and e2e validation starts.
- `kubectl --context <dev_cluster_context> get nodes` succeeds.
- `kubectl --context <global_cluster_context> get moduleplugins` succeeds for Cluster Plugin workflows, or OLM API resources are visible for OLM workflows.
- `PLATFORM_ADDRESS`, `PLATFORM_USERNAME`, and `PLATFORM_PASSWORD` can be resolved from the file or named environment variables.
- `git remote -v` and the selected target branch are available.
