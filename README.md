# skills

- [accelerator-e2e-case-development](accelerator-e2e-case-development/SKILL.md): 从发版源码 delta 构建影响锥,对照已有 case 与候选证据,设计或实现缺失 E2E case,并生成最小 live 重跑与发版证据交接。
- [builders-alauda-component-e2e-release](builders-alauda-component-e2e-release/SKILL.md): Alauda 组件发版前端到端验证编排,覆盖 buildkitd 构建、制品上传、安装、e2e、安全扫描、文档/ERRATA/readiness gate 和 PR/MR 收尾。
- [builders-roadmap-studio](builders-roadmap-studio/SKILL.md): Jira 驱动的 Roadmap 治理与 Gantt 生成,支持标签审计、快照刷新、Sprint 冻结、团队 Dashboard、半月进度时间线和跨团队进度总览。
- [bundle-iterate](bundle-iterate/README.md): 代码→流水线→打包→上架 ACP 集群→安装验证 的开发闭环,失败可迭代修复;面向 air-gap 目标集群(devpod create+package、scp、npuserver push 分裂流)。
- [cluster-image-import](cluster-image-import/README.md): 把外网/构建仓库镜像导入到内网或隔离集群的目标镜像仓库。
- [edge-ci-build](edge-ci-build/SKILL.md): 轻量 Edge BuildRun 辅助,适合 dev/default tag rebuild、status、wait、image 查询;release/RC 分支构建优先用 `hyperflux-pipeline-ops`。
- [edge-plugin-package-rollout](edge-plugin-package-rollout/SKILL.md): Edge 已经构建出 plugin/operator 包后,把包同步/推进到目标 ACP,并按 OLM + Helm operator 链路验证 Subscription、CSV、Helm release、Pod 和 CR 状态。
- [hami-dev](hami-dev/README.md): HAMi 技术栈 `edit→build→unit-test` 一次迭代驱动(出 PASS/FAIL);Tier1 无卡@devpod、Tier3 e2e+CUDA@P100;自动 bootstrap 工具链到大临时盘。是 hami-fix 的 oracle 层。
- [hami-fix](hami-fix/README.md): 有纪律的自治 HAMi 修复闭环(在 hami-dev oracle 之上):基线→feat 分支→修到绿+强制新测+机器判别器检查+对抗 reviewer+严重度人判闸+人棘轮;绝不自动 merge。是 `research/automation/` 探索 loop 的固化。
- [hami-release-decision](hami-release-decision/SKILL.md): 基于上游 release note / git delta / 下游 overlay / 客户驱动 / 验证能力的 HAMi 生态发版 go/no-go 决策模型;先跑一票否决,再按价值与风险打分,输出 `GO` / `GO with constraints` / `DEFER` / `NO-GO`。
- [node-ssh-bootstrap](node-ssh-bootstrap/README.md): 给登不进的不可变/KubeOS 节点装免密 root SSH(`kubectl debug node` 写 `authorized_keys`,落 `/persist` overlay);每环境参数收敛到本地 `env.<name>`(不入库,见 `env.example`)。
- [sync-bundle](sync-bundle/README.md): 通过 `violet` 把 artifact 或 operator bundle image 同步到 Alauda 平台 catalog。
