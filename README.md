# skills

- [bundle-iterate](bundle-iterate/README.md): 代码→流水线→打包→上架 ACP 集群→安装验证 的开发闭环,失败可迭代修复;面向 air-gap 目标集群(devpod create+package、scp、npuserver push 分裂流)。
- [cluster-image-import](cluster-image-import/README.md): 把外网/构建仓库镜像导入到内网或隔离集群的目标镜像仓库。
- [edge-ci-build](edge-ci-build/SKILL.md): 给指定 git 分支/tag 手动触发 Alauda Edge(Katanomi)CI 构建并跟踪到终态。feat 分支不会被 gitTrigger 自动构建(只认 master/PR),须手动 POST BuildRun;是 bundle-iterate 里"触发构建+取 tag"那段的独立版,适合修完只想重构一个镜像(如改 CVE 后重构重扫)。
- [hami-dev](hami-dev/README.md): HAMi 技术栈 `edit→build→unit-test` 一次迭代驱动(出 PASS/FAIL);Tier1 无卡@devpod、Tier3 e2e+CUDA@P100;自动 bootstrap 工具链到大临时盘。是 hami-fix 的 oracle 层。
- [hami-fix](hami-fix/README.md): 有纪律的自治 HAMi 修复闭环(在 hami-dev oracle 之上):基线→feat 分支→修到绿+强制新测+机器判别器检查+对抗 reviewer+严重度人判闸+人棘轮;绝不自动 merge。是 `research/automation/` 探索 loop 的固化。
- [node-ssh-bootstrap](node-ssh-bootstrap/README.md): 给登不进的不可变/KubeOS 节点装免密 root SSH(`kubectl debug node` 写 `authorized_keys`,落 `/persist` overlay);每环境参数收敛到本地 `env.<name>`(不入库,见 `env.example`)。
- [sync-bundle](sync-bundle/README.md): 通过 `violet` 把 artifact 或 operator bundle image 同步到 Alauda 平台 catalog。
