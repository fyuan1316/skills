# hami-dev — HAMi 加速器技术栈 开发/测试/自动化 工作流

为 `projects/ai-infra/` 下的 HAMi 全家桶建立 **开发→构建→测试** 闭环,触发方式对齐
skill(model 改完代码重新调用 `run.sh` 取裁决,循环至绿)。本文是设计文档,脚本是实现。

## 第一性原理:按"真正需要什么"切分,而不是按仓切分

两个硬约束决定一切:

1. **devpod 是裸 Linux**:没有 go/cmake/docker,只有 make/gcc/git/kubectl。
2. **持久卷只剩 ~1G**(`/workspaces`),但容器 overlay 有 >200G 且**只有 `/tmp` 可写**、pod 重启即抹。
3. **HAMi-core(CUDA)和 e2e 需要真 GPU**,devpod 没有。

→ 不要把所有东西都塞进 devpod,也不要试图压缩空间。按**工作真正需要的环境**分层:

| 层 | 内容 | 在哪跑 | 硬件 | 入口 |
|---|---|---|---|---|
| **Tier 1** | 单测 + 构建 | devpod | 无 | `scripts/run.sh` ✅ 已验证 |
| **Tier 2** | 静态检查 / lint | devpod | 无 | `go vet` / staticcheck(待接) |
| **Tier 3** | e2e + HAMi-core CUDA 构建/功能测试 | P100(经 jumper) | NVIDIA GPU | `scripts/p100.sh` + accelerator-test |

**工具链落盘策略**:Go + module/build cache 装到大临时盘 `/tmp/hami-toolchain`,
**源码留持久盘**。`bootstrap.sh` 幂等,pod 重启后重跑一次即可(`run.sh` 在工具链缺失时自动调用)。

## 测试金字塔与各仓的映射

- **Tier 1(无硬件,快)**:`go test ./pkg/...`。HAMi 自带 `hack/unit-test.sh`(注入假
  kubeconfig),47 个 `_test.go`,完全在 devpod 跑。dcgm-exporter / HAMi-WebUI 同为 Go,可复用。
- **Tier 3(真硬件)**:`accelerator-test` 是统一 Ginkgo e2e,自动识别集群上是
  HAMi / PGPU / pNPU 并只跑对应用例。pgpu→**P100**(NVIDIA),pnpu→昇腾(另一条线)。
  HAMi-core 的 `libvgpu.so` 在 P100 上构建(宿主有 CUDA 头;或用其 `nerdctl` 起 CUDA 容器,
  对应仓里 `build-in-docker` 目标 docker→nerdctl)。

## 脚本

| 脚本 | 作用 |
|---|---|
| `scripts/bootstrap.sh` | L0:幂等装 Go 1.26.4 + cache 到大盘,产出 `env.sh`。`TOOLROOT`/`GO_VERSION` 可覆盖。 |
| `scripts/run.sh` | 一轮迭代:Go 仓走 build/test(模式 `test`/`build`/`build-test`/`pkg:<path>`);`hami-core` 委派给 core.sh。 |
| `scripts/p100.sh` | 在 P100 上执行命令(jumper 嵌套 ssh)。args 模式或 stdin 管脚本。连接参数全显式,Mac/devpod 通用。 |
| `scripts/core.sh` | Tier3 HAMi-core 流水线:`transfer`/`build`/`package`/`test`/`all`。容器内编(host 不脏)+ crane append→tar→load。 |

## 用法

```bash
# 第一次(或 pod 重启后):run.sh 会自动 bootstrap
scripts/run.sh hami                       # 跑 HAMi 单测
scripts/run.sh hami pkg:./pkg/device/...  # 快速内循环:只测一个包
scripts/run.sh hami build-test            # 编译所有 cmd 再单测

# Tier 3 远程 GPU
scripts/p100.sh 'nvidia-smi -L'
```

## 验证记录(2026-06-04)

**Tier 1(MVP)**
- bootstrap 装 Go1.26.4 到 `/tmp/hami-toolchain` ✅;HAMi `go mod download`(首次 3m52s,缓存大盘)✅
- `go test ./pkg/...` 全 35 包绿 + `go build ./cmd/scheduler`(69M)✅;退出码裁决(注入失败→exit1)✅
- 闭环:新增 `pkg/device/mvp_loop_test.go`(表征 `IsManagedQuota`)经 `run.sh` 编译通过 ✅(未提交,验证物可弃)

**Tier 3(HAMi-core,crane 全链路)**
- 关键纠错:HAMi-core 需 CUDA ≥12.5 头(`CUctxCreateParams`);大 CUDA 镜像直拉 P100 反复 EOF → 改用 ubuntu:20.04 + 只读挂载 host CUDA 12.8 ✅
- 容器内编出 `libvgpu.so`(~664K),**host 零安装** ✅
- devpod crane append → 27MB 成品 OCI tar(daemonless,无 push)✅
- tar→jumper→P100 `nerdctl load`→`--gpus all` 运行:`PRELOAD_LOADED_OK` + `[HAMI-core Msg…]` NVML 劫持日志 + 真 Tesla P100 ✅
- `core.sh all` 固化脚本一把跑通 ✅
- **功能测试**(`core.sh gpu-test`):容器内编 lib + 17 个测试二进制(`.cu` 经挂载 host CUDA 的 nvcc),`--gpus` 跑 `test_alloc` + `CUDA_DEVICE_MEMORY_LIMIT=2g`:HAMi-core 把 16G 卡虚拟成 2G(每次 NVML 查询 `total: 2147483648`)+ 超额 `cuMemAlloc` 被拒(`Device 0 OOM .../2147483648`),断言 PASS ✅
- harbor 阻塞点:`env.harbor` 是只读凭据,push 被拒;暂走 tar/load(也是离网路径)。要 push 需另给有写权的 robot。

## 路线图(下一步)

1. ~~HAMi-core 容器构建 + 功能矩阵(14 用例)+ 框架级~~ ✅ 已通。
   - `core.sh gpu-matrix`:6 设备显存(含 OOM)+ 6 host/锁页(不计设备限额)+ 2 SM 算力,全绿@P100。
   - `core.sh framework`(✅ 皇冠用例):真 PyTorch 工作负载(P100 缓存的 torch-distributed:v2.9.1 镜像)+ LD_PRELOAD libvgpu + 限额 2g:4GiB 张量被 OOM(PyTorch 报总容量=2GB)、1GiB 成功。即真 ML 框架受 vGPU 显存限制约束——产品核心价值端到端验证。
   - dcgm-exporter:build ✅ devpod,13/16 单测包纯逻辑通过;**3 个需 libdcgm/NVML 的包在 P100 跑通 3/3**(`run.sh dcgm-exporter gputest`:编译@devpod→送 P100→nvmlprovider 用 ubuntu:22.04、transformation/cmd 用 dcgm 镜像,均 --gpus;按退出码判定;注 glibc≥22.04)。
2. ~~accelerator-test smoke~~ ✅ 已通(`run.sh e2e smoke`,从 devpod 直连集群跑 Ginkgo,HAMi vGPU 显存隔离 spec `1 Passed`;kubeconfig=envs/kubeconfig/g1-c1-x86.yaml)。可扩展:sanity/full、pgpu/pnpu 平台。
3. ~~Tier 2 提交前 gate~~ ✅ 已通(`run.sh hami lint` = go vet + golangci-lint v2.8.0,对齐仓库 .golangci.yaml;任一报错即 gate,已验证抓 misspell + 干净通过)。
4. 拿到可写 harbor robot 后,`core.sh` 增加 `crane push build-harbor.alauda.cn/test/...` 分支(替代 tar 分发)。

不做:自动 commit/push;feature 走 `feat/*`(见 memory feedback-branch-workflow),由用户发起。
