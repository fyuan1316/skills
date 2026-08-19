# Common Accelerator Test Failures

Use this list before applying an ad-hoc repair. Repeated failures should move
into wrapper/backend preflight whenever they can be detected safely.

| Symptom | Classification | Automated behavior | Follow-up when unresolved |
|---|---|---|---|
| `go: command not found` | local tool preflight | Stop before deployment/tests and record the missing compiler | Install Go and repair the agent shell PATH |
| `ginkgo: command not found` | local tool preflight | Read the exact version from `go.mod`, install and cache it before the test | Check Go, `GOPROXY`, network, and cache permissions |
| Ginkgo CLI/library version warning | local tool preflight | Ignore the mismatched binary and install the exact `go.mod` version | Check an explicitly configured `GINKGO_BIN` |
| kubeconfig path missing | input preflight | Stop before deployment or tests | Repair environment registration or pass the exact kubeconfig |
| deployment failed before Ginkgo | deployment/package layer | Preserve deploy logs and do not classify as functional case failure | Inspect package, OLM/Helm state, image pull and CR health |
| test Pod `Pending` | scheduling/resource layer | Preserve events and JUnit | Check taints/tolerations, host ports, selector, scheduler and allocatable |
| `ImagePullBackOff` | image distribution layer | Preserve image ref and events | Check rewrite, pull secret, architecture and digest |
| accelerator allocatable is zero | device-plugin/driver layer | Fail resource discovery before workload execution | Check active device-plugin, driver, kubelet registration and node labels |
| Pod Running but `npu-smi`/`nvidia-smi` fails | runtime/device injection layer | Preserve exec output | Check RuntimeClass, CDI, mounts, device nodes and dynamic libraries |
| stale test namespace affects rerun | cleanup layer | Prefer a unique explicit namespace and suite cleanup | Verify ownership before deleting leftovers |

When adding an item, record whether the long-term fix belongs to the local tool
preflight, cluster preflight, deployment workflow, or result classifier.
