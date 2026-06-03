# node-ssh-bootstrap

给"SSH 登不进去"的集群节点装免密 root 登录。针对 **不可变 / KubeOS** 这类节点:`/`
只读、公钥认证开着但你的 key 不在 `authorized_keys` 里、又没有口令和可用的 key 去把它塞
进去。思路:用 `kubectl debug node/<n>`(profile sysadmin)拿到节点 rootfs 的 root
shell(`/host` = 节点 `/`),把你的公钥追加进 `authorized_keys`,落在 KubeOS 的
`/persist` overlay 上(重启 + A/B 升级都保留)。之后普通 `ssh <node>` 即可。

## 网络拓扑现实

```
你 (devpod/笔记本)            SSH_HOST 跳板+执行机 (npuserver)
  ssh <node> ──ProxyJump──►     KUBECTL (kos2) ──API──► 目标集群
      ▲ 缺你的公钥                                       │
      └──── 本 skill 装进去 ◄──── kubectl debug node/<n> ──► 节点 rootfs (/host)
```

- 节点 SSH 端口从 SSH_HOST 可达(就是 ProxyJump),但你认证不了。
- 节点的**磁盘**却能经 K8s API 够到:debug pod 把节点 `/` 挂到 `/host`,等于一个 root shell。

> **原理一句话:** 走 kubelet 不走 sshd——建一个挂 `hostPath:/` 的特权 Pod 钉到目标 node,即得该节点 root;能在集群建特权 Pod ≈ 节点 root。完整机制(信任链、真实 pod spec、为什么持久、PSA 防御)见知识库 [[特权 Pod + hostPath 逃逸到节点 root]]。

## 适用 / 不适用

适用:
- "做免密登录到这些节点/VM,只给我用"——把**你的** key 装到集群节点。
- 登不进 KubeOS / openEuler 不可变节点(公钥没收录)。
- 想在没有 SSH 的节点上拿 root shell 读日志 / 改配置 / 看 `/persist`。

不适用:
- 节点本来就能 SSH——直接 `ssh-copy-id`。
- 目标机**不是你有 kubectl 的那个集群的节点**——`kubectl debug node` 够不到。需要那台机
  自己的集群 kubeconfig,或 VM console / 口令。(参考环境里 `kubeos`/`192.168.122.234`
  就是这种孤儿:是 libvirt VM,但不是 `kos2` 节点,本 skill 做不了。)

## 怎么"换个环境切换参数"

所有环境差异收敛到一个 `env.<name>` 文件,`source` 它即可(也可用同名 CLI flag 覆盖):

| 变量 | 参考环境值 | 含义 |
|---|---|---|
| `SSH_HOST` | `npuserver` | 跑 kubectl 的跳板+执行机,也是 `ssh <node>` 的 ProxyJump |
| `KUBECTL` | `kos2` | SSH_HOST 上绑定**目标集群**的 kubectl 包装 |
| `DEBUG_IMAGE` | `auto` | 集群**能拉**且带 shell 的镜像;`auto` 复用已存在的 kubectl/busybox/toolbox 镜像(air-gap 友好) |
| `NODES` | `auto` | `auto`=`kubectl get nodes`,或 `"kubeos2 kubeos3"` |
| `PUBKEY_FILE` | `~/.ssh/id_ed25519.pub` | 要装的公钥 |
| `AUTHKEYS` | `/root/.ssh/authorized_keys` | 节点上的路径(脚本自动加 `/host` 前缀) |
| `LIBVIRT_NET` | `default` | discover.sh 取 VM→IP 租约用的 libvirt 网络 |

换环境示例:抄 `env.example` 成 `env.<新环境>`,改掉 `SSH_HOST`/`KUBECTL`/(必要时
`DEBUG_IMAGE`),`source` 后跑同样的命令。

## 三步走

```bash
source kbs/fy-skills/node-ssh-bootstrap/env.kubeos2

# 0. 盘点:hypervisor 上的 VM + 集群节点(看哪些 VM 是节点、哪些是孤儿)
bash kbs/fy-skills/node-ssh-bootstrap/scripts/discover.sh

# 1. 预检(只读):sshd 策略、现有都有谁的 key、目标路径是否可写且持久、你的 key 在不在
bash kbs/fy-skills/node-ssh-bootstrap/scripts/bootstrap-ssh.sh --nodes auto --preflight-only

# 2. 安装(幂等,默认 additive 追加,不动别人的 key)+ 实测 ssh 登录
bash kbs/fy-skills/node-ssh-bootstrap/scripts/bootstrap-ssh.sh --nodes auto

# 之后
ssh kubeos2   # 免密,经 npuserver 跳板
```

`--mode exclusive` 会**覆盖** authorized_keys(删掉所有别人的 key)——破坏性、影响同事,
必须先拿到明确确认。

## 为什么能持久(KubeOS 细节)

KubeOS 节点 `/` 是只读镜像分区,但 `/etc`、`/root` 是 **overlay**,`upperdir` 落在持久
数据分区(`/persist/...`,如 `/dev/vda4`)。写 `/root/.ssh/authorized_keys` 实际进了
`/persist/root/.ssh/...`,重启在、**A/B 镜像升级也在**(persist 分区不参与 rootfs 交换)。
`bootstrap-ssh.sh` 写之前会校验目标目录确实在这种挂载上,否则拒写,避免装个一重启就没的 key。

## 核心原语 `node-debug-exec.sh`

可单独复用——对没 SSH 的节点 rootfs 跑**任意** shell:

```bash
echo 'cat /host/etc/os-release' | scripts/node-debug-exec.sh --node kubeos2
scripts/node-debug-exec.sh --node kubeos3 <<'EOF'
  ls -la /host/persist
EOF
```

base64 包裹片段(任意引号/换行都安全)→ 建 debug pod →`/host` 即节点 `/`→ 从 pod 日志取
输出 → 删 pod。读日志、改配置、查 `/persist` 都用它。

## 工作流来源

2026-06-03。任务:从物理机 npuserver 盘点出 3 个 libvirt VM(`kubeos` 234 /
`kubeos2` 235 / `kubeos3` 236),给它们装免密。发现 KubeOS 节点默认不开 SSH 口令登录、
也没收录我的 key;走 `kubectl debug node`(经 `kos2` + 内网 registry 的
`3rdparty/kubectl:v4.3.1` 镜像)拿到 rootfs,把 devpod 公钥追加进 kubeos2/kubeos3,实测
免密通过。`kubeos`(234)不是 kos2 节点,无 kubeconfig/口令,留作待办。
相关记忆见 `[[project-infernex-eval]]`、`[[ref-acp-console-access]]`。

## 关键依赖 / 注意

- 依赖到 SSH_HOST 的免密 ssh 已就绪(见 `ai-platform-passwordless-ssh` / `envs/npuserver`)。
- `--image auto` 需集群里有带 shell 的镜像;纯 distroless 集群要显式 `--image`。
- `kubectl debug node` 会留 `node-debugger-*` pod;脚本删自己建的,被中断的需手动清。
- 一切操作 `/host/...`(节点),写 `/root/...`(没 /host)只改了一次性 debug 容器,等于白做。
