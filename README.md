# skills

- [bundle-iterate](bundle-iterate/README.md): 代码→流水线→打包→上架 ACP 集群→安装验证 的开发闭环,失败可迭代修复;面向 air-gap 目标集群(devpod create+package、scp、npuserver push 分裂流)。
- [cluster-image-import](cluster-image-import/README.md): 把外网/构建仓库镜像导入到内网或隔离集群的目标镜像仓库。
- [node-ssh-bootstrap](node-ssh-bootstrap/README.md): 给登不进的不可变/KubeOS 节点装免密 root SSH(`kubectl debug node` 写 `authorized_keys`,落 `/persist` overlay);每环境参数收敛到本地 `env.<name>`(不入库,见 `env.example`)。
- [sync-bundle](sync-bundle/README.md): 通过 `violet` 把 artifact 或 operator bundle image 同步到 Alauda 平台 catalog。
