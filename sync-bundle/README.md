# sync-bundle

把 artifact 或 operator bundle image 通过 `violet` 打包并同步到 Alauda 平台 catalog。

## 快速开始

1. 准备配置文件：

```bash
mkdir -p ~/.config/violet-sync
cp assets/config.env.example ~/.config/violet-sync/config.env
```

然后在 `~/.config/violet-sync/config.env` 里填写真实平台账号、密码和目标信息。不要把真实凭据保存到 skill 仓库。

2. 执行同步：

```bash
scripts/sync-bundle <artifact> [profile]
scripts/sync-bundle-envs <artifact> <env-or-alias> [cluster]

# 例
scripts/sync-bundle charts/model-catalog
scripts/sync-bundle build-harbor.alauda.cn/mlops/model-registry-operator-bundle:v0.3.0-hotfix.6.1.g263306a3-dev-catalog-v0.1.0-release-0.3 cata
scripts/sync-bundle-envs build-harbor.alauda.cn/foo/bar:v1 dev kubeos
scripts/sync-bundle-envs build-harbor.alauda.cn/foo/bar:v1 dev-global-compute microos
scripts/sync-bundle-envs build-harbor.alauda.cn/foo/bar:v1 p100
```

`profile` 可选；提供后会加载 `~/.config/violet-sync/<profile>.env` 覆盖默认配置。

如果目标来自 `/Volumes/macOS-2/Users/yuan/Dev/tools/envs/dev-*`，优先用 `scripts/sync-bundle-envs`。它会临时生成 violet-sync profile，不需要为每个 dev/cluster 长期维护 `~/.config/violet-sync/*.env`。

## 文件

| 文件 | 作用 |
|------|------|
| `SKILL.md` | Codex skill 指令，说明运行前检查、参数解释、错误处理和回报格式。 |
| `scripts/sync-bundle` | 本地包装脚本，负责下载/调用 `violet`、创建包、打包并推送 catalog。 |
| `scripts/sync-bundle-envs` | envs-aware 包装脚本，从 `envs/dev-*` 解析平台和集群，临时生成 profile 后调用 `sync-bundle`。 |
| `assets/config.env.example` | 安全的配置模板，不包含真实凭据。 |
| `agents/openai.yaml` | skill 在 OpenAI/Codex 侧的显示元数据。 |

## 配置变量

见 [SKILL.md](SKILL.md) 的 `Config Contract` 部分。
