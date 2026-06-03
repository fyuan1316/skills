---
name: node-ssh-bootstrap
description: Set up passwordless root SSH onto Kubernetes cluster nodes that have no SSH login — immutable / KubeOS / locked-down nodes reachable only through the K8s API via a jump host. Works by using `kubectl debug node/<n>` (profile sysadmin) to get a root shell on each node's writable rootfs and append your public key to authorized_keys, persisted on the KubeOS /persist overlay so it survives reboot and A/B image upgrade. Fully parameterized (jump host, kubectl wrapper, debug image, node list, key) so a new environment is a few flag/env changes. Use when the user asks to "做免密登录到这些节点/VM", "set up SSH key access to the cluster nodes", "I can't SSH the KubeOS nodes", "get a root shell on a node without SSH", or to inventory which VMs/nodes exist behind a jump host. NOT for nodes that already allow SSH (just ssh-copy-id), and it cannot reach a VM that is not a member of the target cluster (needs that cluster's kubeconfig or VM console creds instead).
---

# Node SSH Bootstrap (给"登不进去"的集群节点装免密)

Give yourself passwordless root SSH onto cluster nodes when **the nodes refuse SSH
login** and your only foothold is `kubectl` against that cluster (typically run on a
jump host that can reach the nodes' private IPs). The classic case: an **immutable /
KubeOS** node — `/` is read-only, SSH key auth is enabled but your key isn't in
`authorized_keys`, and there's no password and no key you can use to put it there.

## Topology (why this skill exists)

```
 you (devpod / laptop)            SSH_HOST = jump+exec host (e.g. npuserver)
  ssh <node>  ───ProxyJump───►      KUBECTL (e.g. kos2) ──API──► target cluster
       ▲ needs your pubkey                                         │
       └──────── this skill installs it ◄──── kubectl debug node/<n> ──► node rootfs
                                              (/host = node "/", writable overlay)
```

The node's SSH port is reachable from `SSH_HOST` (that's the ProxyJump), but you
can't authenticate. You *can* reach the node's **disk** through the K8s API:
`kubectl debug node/<n> --profile=sysadmin` schedules a privileged pod with the
node's root filesystem mounted at `/host`. That's a root shell on the node — enough
to write `authorized_keys`. After that, normal `ssh <node>` works.

> Full mechanism (two trust chains, the real pod spec, why the write persists, and
> the PSA defense that would block it) lives in the knowledge base note
> `[[特权 Pod + hostPath 逃逸到节点 root]]`. The summary above is enough to operate;
> read the note to understand or harden against it.

## When to use / not use

Use when:
- "做一个免密登录到这些节点/VM,只给我用" — install *your* key onto cluster nodes.
- "I can't SSH the KubeOS / openEuler immutable nodes" — pubkey not enrolled.
- "Get a root shell / read or edit a file on a node that has no SSH."
- "List the VMs on the hypervisor and the cluster nodes behind the jump host."

Do **not** use when:
- The node already allows your SSH (then just `ssh-copy-id` / append the key).
- The target is **not a node of the cluster** you have kubectl for — `kubectl debug
  node` can't reach it. You need that machine's own cluster kubeconfig, or its VM
  console / a password. (In the reference env, `kubeos` / `192.168.122.234` is such
  an orphan — a libvirt VM but not a `kos2` node — so this skill can't do it.)
- You only need API-level ops on the node's workloads — use kubectl directly.

## Prerequisites

| Thing | Reference-env value | Notes |
|---|---|---|
| Passwordless ssh to `SSH_HOST` | `npuserver` (key in `~/.ssh/config`) | this skill assumes it; bootstrap that first |
| kubectl wrapper on `SSH_HOST` | `kos2` → kubeos2 cluster | bound to the **target** cluster |
| Debug image (cluster-pullable, has a shell) | `…:11443/3rdparty/kubectl:v4.3.1` | `--image auto` finds an already-present one (air-gap safe) |
| RBAC to create debug pods | cluster-admin via the wrapper | `kubectl debug node` = privileged pod |
| Your public key | `~/.ssh/id_ed25519.pub` | the key that should get passwordless access |
| `~/.ssh/config` Host entries for nodes | `kubeos2`,`kubeos3` w/ `ProxyJump npuserver` | for the verify step + day-to-day `ssh <node>` |

## Parameters (switch environments by changing these)

Put them in an `env.<name>` file (see `env.example`, `env.kubeos2`) and `source`
it, or pass as flags. The scripts read both.

| Var / flag | Default | Meaning |
|---|---|---|
| `SSH_HOST` / `--ssh-host` | `npuserver` | jump+exec host running kubectl, ProxyJump for `ssh <node>` |
| `KUBECTL` / `--kubectl` | `kos2` | kubectl invocation on `SSH_HOST`, bound to target cluster (may include args) |
| `DEBUG_IMAGE` / `--image` | `auto` | shell image **the cluster can pull**; `auto` reuses a present kubectl/busybox/toolbox image |
| `NODES` / `--nodes` | `auto` | `auto` = `kubectl get nodes`, or `"kubeos2 kubeos3"` |
| `PUBKEY_FILE` / `--pubkey-file` | `~/.ssh/id_ed25519.pub` | key to install (or `--pubkey "ssh-ed25519 …"`) |
| `AUTHKEYS` / `--authkeys` | `/root/.ssh/authorized_keys` | path on the node (auto-prefixed with `/host`) |
| `LIBVIRT_NET` / `--libvirt-net` | `default` | libvirt net for VM→IP leases in `discover.sh` |
| `--mode` | `additive` | `additive` appends your key; `exclusive` overwrites (removes everyone else — destructive) |

## Procedure

### 0. (optional) Inventory what's there

```bash
source kbs/fy-skills/node-ssh-bootstrap/env.kubeos2
bash kbs/fy-skills/node-ssh-bootstrap/scripts/discover.sh
```

Lists libvirt VMs on the hypervisor (`virsh list` + DHCP leases → IPs) and the
cluster nodes (`kubectl get nodes`). Cross-check: a VM that's **not** in the node
list is out of scope for this skill (see "not use" above).

### 1. Preflight (read-only — confirm it's feasible & whether it's already done)

```bash
bash scripts/bootstrap-ssh.sh --nodes auto --preflight-only
```

Per node it reports: sshd policy (`PermitRootLogin`, `PubkeyAuthentication`,
`AuthorizedKeysFile`), the **existing** authorized_keys (so you see who already has
access), whether the target dir is a **writable persistent overlay**, and whether
*your* key is already present. If `WRITABLE=no`, stop — the path isn't persistent;
pick a different `AUTHKEYS` on the `/persist`-backed overlay.

### 2. Install the key (idempotent, additive by default)

```bash
bash scripts/bootstrap-ssh.sh --nodes auto
```

Appends your pubkey (skips if already present), fixes perms (`700` dir / `600`
file, `root:root`), and **verifies real `ssh <node>` login**. Re-running is safe.

To make it exclusive (remove all other keys — affects colleagues, get explicit
sign-off first):

```bash
bash scripts/bootstrap-ssh.sh --nodes auto --mode exclusive
```

### 3. Use it

```bash
ssh kubeos2     # passwordless, via ProxyJump npuserver
ssh kubeos3
```

## Why the key persists (KubeOS specifics)

On a KubeOS node, `/` is a read-only image partition, but `/etc` and `/root` are
**overlay** mounts whose `upperdir` lives on the persistent data partition
(`/persist/...`, e.g. `/dev/vda4`). Writing `/root/.ssh/authorized_keys` lands in
`/persist/root/.ssh/...`, which survives reboots **and** the A/B image upgrade
(the persist partition is not part of the swapped rootfs). `bootstrap-ssh.sh`
explicitly checks the target dir is on such a mount before writing, and refuses a
volatile location — so you don't install a key that silently vanishes on next boot.

## The core primitive: `node-debug-exec.sh`

Reusable on its own — run **any** shell snippet against a node's rootfs with no SSH:

```bash
echo 'cat /host/etc/os-release' | scripts/node-debug-exec.sh --node kubeos2
scripts/node-debug-exec.sh --node kubeos3 <<'EOF'
  ls -la /host/persist
  grep -i permitroot /host/etc/ssh/sshd_config
EOF
```

It base64-wraps the snippet (any quoting/newlines are safe), creates a
`debug node` pod, runs the snippet with `/host` = node `/`, returns the output from
the pod logs, and deletes the pod. This is your "root shell on a node that won't let
you SSH" — handy for reading logs, patching a config, or inspecting `/persist`.

## Red flags / gotchas

- **`--image auto` needs a present shell image.** Distroless-only clusters have none
  → pass an explicit `--image` of something the cluster registry holds. Don't pass a
  public image in air-gap; the pull will hang and the pod never runs.
- **`kubectl debug node` leaves a `node-debugger-<node>-xxxxx` pod.** The scripts
  delete the one they create, but a killed run can orphan one — `kubectl get pods | grep node-debugger` and clean up.
- **`exclusive` mode is destructive and affects other people.** It overwrites
  authorized_keys. Default is additive for a reason; never run exclusive without
  explicit user confirmation.
- **`/host` is the node, not the pod.** Always operate on `/host/...`. Writing to
  `/root/...` (without `/host`) edits the throwaway debug container — a no-op that
  looks like success.
- **Verify step needs an ssh-config Host entry** (`Host <node>` + `ProxyJump
  <SSH_HOST>` + `IdentitiesOnly yes`). Without it the install still succeeds but the
  verify prints a hint; use `--verify-alias '%s'` or `--no-verify`.
- **Not every VM is a node.** If `discover.sh` shows a VM absent from `get nodes`,
  this skill cannot reach it; say so rather than pretending it's covered.

## Output

Per node, report: sshd policy + who already had access, writable/persistent = y/n,
ADDED vs ALREADY_PRESENT, and the verify verdict (✅ passwordless login works / ⚠).
For out-of-scope VMs, state explicitly that they need their own cluster kubeconfig
or console creds.
