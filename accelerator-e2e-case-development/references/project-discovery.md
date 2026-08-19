# Project discovery

Use this branch when no reliable tested base exists or the project has no established
release-E2E runner.

1. Resolve repository instructions, worktrees, dirty files, branch, target commit,
   release version, build definition, and package format.
2. Find the runtime ownership chain: API/values -> controller or templates -> workload
   -> node/runtime integration -> advertised resource or metric -> user workload.
3. Find build-time image injection, bundle/CSV `relatedImages`, chart defaults,
   architecture variants, and generated artifacts. Treat generated output as exposure
   evidence, not the source of behavior.
4. Inventory test entrypoints, fixtures, environment contracts, case IDs, artifact
   layout, JUnit/result generation, and cleanup behavior.
5. Identify owner boundaries: host versus container Driver, operator versus HAMi,
   platform package versus operand image, and release setup versus product case.

Discovery is complete when the runtime chain and test insertion points are both known,
or each unknown has a concrete investigation gap. Do not infer live support from a CRD,
values key, manifest, or successful build alone.
