# Pre-Release E2E Test Design

Use this reference before building and releasing a component. The goal is to test what the component actually provides, record the compatibility evidence gathered during the release run, and avoid unsupported compatibility claims.

## Capability Inspection

Inspect the repo before writing tests:

```bash
rg -n "CustomResourceDefinition|apiextensions.k8s.io|kind: (Deployment|StatefulSet|DaemonSet|Job|CronJob|Service|Ingress|Route|ValidatingWebhookConfiguration|MutatingWebhookConfiguration)|openapi|swagger|grpc|FastAPI|Flask|Django|Express|Gin|Echo|controller-runtime|leader-elect|replicaCount|autoscaling|pdb|PodDisruptionBudget|affinity|postgres|mysql|redis|mongodb|kafka|rabbitmq|minio|s3|nvidia.com/gpu|GPU|NPU" .
rg --files | rg "(docs|README|values|chart|manifests|config|api|crd|e2e|test|openapi|swagger|proto)"
```

Classify the component surfaces:

- Kubernetes APIs: CRDs, controllers, webhooks, RBAC, admission policies, conversion webhooks, finalizers, status conditions.
- Workloads: Deployments, StatefulSets, DaemonSets, Jobs, CronJobs, operators, Helm charts, cluster plugins.
- HTTP or gRPC APIs: health endpoints, CRUD endpoints, auth, OpenAPI or protobuf contracts.
- External dependencies: Kubernetes components, ingress or gateway controllers, cert-manager, OLM, Knative, Istio, KServe, storage classes, object storage, databases, queues, caches.
- Hardware dependencies: GPU, NPU, node labels, device plugins, kernel modules, special runtimes.
- Operational behavior: replicas, leader election, probes, PDBs, anti-affinity, autoscaling, backup or migration jobs.

## Smoke And Functional Tests

Reuse existing smoke tests if they cover the installed component through real user-facing behavior. If coverage is missing, add the smallest meaningful tests:

- For CRDs: create a minimal custom resource, wait for reconciliation, assert status conditions, verify generated Kubernetes resources, then delete and assert cleanup or finalizer behavior.
- For operators: verify CSV or controller health, CRD establishment, RBAC permissions needed by the controller, and at least one successful reconciliation.
- For charts or cluster plugins: verify install status, expected workloads, services, config, and a representative user workflow.
- For HTTP APIs: check health/readiness, one write or create flow, one read/list flow, auth behavior when applicable, and a negative case for invalid input.
- For webhooks: verify one accepted object and one rejected object with the expected validation message shape.

Keep the e2e runner image self-contained and runnable as a Kubernetes Job. Prefer existing test frameworks in the repo. Use `pytest`, `ginkgo`, `bats`, `kuttl`, `chainsaw`, `k6`, `hey`, or similar tools only when they fit the existing language and build style.

## Compatibility Tests

Generate minimal compatibility tests from dependencies that are documented or visible in manifests:

- Kubernetes version: inspect CRD `apiVersion`, webhook versions, Kubernetes client dependencies, controller-runtime/operator-sdk versions, chart annotations, README requirements, and CI test clusters. Test on the provided dev cluster and document its server version. If multiple Kubernetes versions are required but not available, add matrix-ready tests and mark untested versions explicitly.
- Kubernetes components: test required CRDs or APIs exist before the component starts, for example OLM, cert-manager, Knative, Istio, KServe, Gateway API, IngressClass, StorageClass, CSI, metrics-server, or GPU device plugins.
- OS and kernel: read docs, container base image notes, daemonset privileges, hostPath mounts, kernel module checks, and node selectors. If none are found, document "none identified from docs or manifests".
- Database and middleware: inspect charts, values, env vars, secrets, init containers, migrations, and docs for PostgreSQL, MySQL, Redis, Kafka, object storage, model stores, or message queues. Test the minimal supported configuration used by the release job.
- CRD or HTTP API breaking changes: compare served CRD versions, OpenAPI/protobuf specs, route paths, request and response fields, status fields, and deprecated fields against the previous release when available. Add a backward-compatible sample manifest or API request from the previous release if the repo has one.
- Hardware: test scheduling constraints and readiness for GPU/NPU components only when hardware is present. Otherwise verify the component handles missing hardware predictably and document hardware tests as not run.

## Compatibility Matrix Output

After tests pass, document the evidence in release notes, a repo compatibility document, or the PR/MR body. Use a concise table:

| Area | Requirement | Tested Version Or Config | Evidence | Result |
| --- | --- | --- | --- | --- |
| OS/kernel | None identified from docs/manifests | Cluster node OS/kernel from `kubectl get nodes -o wide` if relevant | docs/manifests checked | Pass/Not applicable |
| Kubernetes | Version range or minimum | `kubectl version --short` or equivalent | e2e job and CRD/API check | Pass |
| Kubernetes components | Required component list | Installed component versions or CRD groups | preflight checks | Pass |
| Database/middleware | Required service and version | Test instance or external service | smoke test logs | Pass |
| CRD/API compatibility | Served versions or endpoint contract | Previous sample and current API | schema/API checks | Pass |
| Hardware | GPU/NPU/none | Node/device plugin status | scheduling or preflight check | Pass/Not run |

Use "Unknown" only when the repo does not provide enough information. Use "Not tested" when a requirement is known but the environment did not include it.

## API Performance Tests

If the component exposes HTTP or gRPC APIs, add a lightweight performance test that can run after the smoke test:

- Target stable read or health endpoints plus one representative write endpoint when safe.
- Keep load conservative for pre-release validation: short duration, bounded concurrency, explicit thresholds for latency and error rate.
- Record endpoint, request rate or virtual users, duration, p50/p95/p99 latency, throughput, and error rate.
- Avoid destructive load against shared dev platforms. Use a dedicated namespace, tenant, project, or temporary test data.

If the repo already uses a performance tool, extend it. Otherwise prefer a small `k6` or `hey` script in the e2e runner image for HTTP endpoints. If no API endpoint exists, state that API performance tests are not applicable.

## High Availability Documentation

Check and document the component's HA posture:

- Replicas, leader election, active/passive behavior, PDBs, anti-affinity, topology spread, probes, autoscaling, and rolling update strategy.
- Stateful dependencies: external database mode, storage class requirements, backup/restore notes, queue or cache persistence, and migration jobs.
- Failure behavior that e2e can verify cheaply: restart one pod, confirm readiness recovers, and verify the smoke workflow still passes when multiple replicas are configured.
- Known single points of failure: singleton controllers without leader election, local storage, single external database, missing PDB, or required node-local hardware.

Document the supported HA values or chart settings, the tested configuration, and any gaps. Do not block release only because a component is not highly available unless the component's release requirements say HA is mandatory.
