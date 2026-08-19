# Evidence states

Use one state per assertion, not one optimistic state for the whole journey.

| State | Meaning |
|---|---|
| designed | Contract exists; executable implementation does not |
| implemented | Executable code exists; validation not yet recorded |
| static-pass | Syntax/unit/contract validation passed without a real target |
| diagnostic | Live observation exists but lacks the required transition or identity |
| live-pass | Required behavior passed on the named candidate and environment |
| live-fail | Required behavior ran and failed |
| blocked | A named dependency, owner, artifact, or environment prevents execution |
| not-run | Runnable but not executed for this candidate |
| reusable | Earlier evidence remains valid because its inputs and affected behavior are unchanged |
| invalidated | Candidate or affected operand changed, so earlier evidence cannot qualify it |
| out-of-scope | Excluded with product or ownership rationale |

Reuse evidence at assertion granularity. A package-only change can preserve independent
Driver evidence while invalidating package identity and rollout evidence. An operand
image change invalidates its resolved/deployed/runtime identity and user workload path;
unrelated lifecycle assertions may remain reusable when their inputs are unchanged.

Every `blocked` state needs an owner and next action. Every `reusable` state needs the
unchanged inputs that justify reuse. Every `live-pass` needs candidate, commit/package,
environment, timestamp, raw evidence, and cleanup result.
