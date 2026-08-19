# E2E case contract

Each release case must define:

| Field | Required content |
|---|---|
| ID | Stable product/release case identifier |
| Risk | Source delta and user-visible failure it detects |
| Preconditions | Hardware, OS, owner, installed state, and source identity |
| Action | Exact lifecycle transition or workload operation |
| Resolved assertion | Input/package/CSV/image identity selected by the platform |
| Deployed assertion | Rendered object, rollout readiness, and actual image ID |
| Runtime assertion | Resource, device, metric, or loaded-driver behavior |
| User assertion | Allocation, CUDA/NPU work, scheduling, telemetry, or rejection |
| Evidence | Candidate-bound raw artifacts plus concise result |
| Cleanup | Owning API and convergence target |
| Status | Implemented, static PASS, live PASS/FAIL, BLOCKED, or NOT RUN |

Strengthen an existing journey when the affected component is already on its critical
path. Split a new case when setup/cleanup ownership differs, the failure needs an
independent diagnosis, or the lifecycle transition can pass while the existing journey
does not observe it.

For upgrades, prove distinct source and target identities before and after the
transition. For operand changes, prove both the expected immutable image and the actual
running `imageID`. Readiness without identity is partial evidence; identity without a
real workload is deployment evidence only.
