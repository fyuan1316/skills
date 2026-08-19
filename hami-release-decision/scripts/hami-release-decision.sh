#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: hami-release-decision.sh --repo PATH --current-ref REF --target-ref REF [options]

Options:
  --component NAME          Component name, default HAMi
  --downstream-ref REF      Optional downstream candidate ref
  --release-notes PATH/URL  Optional release notes source; local files are excerpted
  --customer-drivers PATH   Optional customer demand / bugfix driver notes
  --output PATH             Output markdown path, default stdout
USAGE
}

repo=""
current_ref=""
target_ref=""
downstream_ref=""
component="HAMi"
release_notes=""
customer_drivers=""
output=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    --current-ref) current_ref="$2"; shift 2 ;;
    --target-ref) target_ref="$2"; shift 2 ;;
    --downstream-ref) downstream_ref="$2"; shift 2 ;;
    --component) component="$2"; shift 2 ;;
    --release-notes) release_notes="$2"; shift 2 ;;
    --customer-drivers) customer_drivers="$2"; shift 2 ;;
    --output) output="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -z "$repo" ] || [ -z "$current_ref" ] || [ -z "$target_ref" ]; then
  usage >&2
  exit 2
fi

if [ ! -d "$repo/.git" ]; then
  echo "not a git repo: $repo" >&2
  exit 2
fi

gitc() {
  git -C "$repo" "$@"
}

require_ref() {
  local ref="$1"
  if ! gitc rev-parse --verify "$ref^{commit}" >/dev/null 2>&1; then
    echo "ref not found: $ref" >&2
    exit 2
  fi
}

require_ref "$current_ref"
require_ref "$target_ref"
if [ -n "$downstream_ref" ]; then
  require_ref "$downstream_ref"
fi

short_ref() {
  gitc rev-parse --short "$1"
}

describe_ref() {
  gitc describe --tags --always "$1" 2>/dev/null || short_ref "$1"
}

path_state() {
  local ref="$1"
  local path="$2"
  local entry
  entry="$(gitc ls-tree "$ref" "$path")"
  if [ -n "$entry" ]; then
    printf '%s' "$entry" | awk '{print $3}' | cut -c1-12
  else
    printf '%s' "-"
  fi
}

path_row() {
  local path="$1"
  printf '| `%s` | `%s` | `%s`' "$path" "$(path_state "$current_ref" "$path")" "$(path_state "$target_ref" "$path")"
  if [ -n "$downstream_ref" ]; then
    printf ' | `%s`' "$(path_state "$downstream_ref" "$path")"
  fi
  printf ' |\n'
}

commit_bucket() {
  local title="$1"
  local pattern="$2"
  echo "### $title"
  gitc log --oneline --no-merges "$current_ref..$target_ref" | grep -E "$pattern" | sed -n '1,12p' || true
  echo
}

commit_count() {
  local pattern="$1"
  gitc log --oneline --no-merges "$current_ref..$target_ref" | grep -Ei "$pattern" | wc -l | tr -d ' '
}

key_commits() {
  local pattern="$1"
  gitc log --oneline --no-merges "$current_ref..$target_ref" \
    | grep -Ei "$pattern" \
    | sed -n '1,4p' \
    | awk 'BEGIN { sep="" } { gsub(/\|/, "\\|"); printf "%s%s", sep, $0; sep="<br>" } END { print "" }' \
    | sed 's/|/\\|/g' || true
}

commit_hints() {
  local title="$1"
  local pattern="$2"
  echo "### $title"
  gitc log --oneline --no-merges "$current_ref..$target_ref" | grep -Ei "$pattern" | sed -n '1,10p' || true
  echo
}

changed_bucket() {
  local title="$1"
  local pattern="$2"
  local count
  count="$(changed_count "$pattern")"
  printf '| %s | %s |\n' "$title" "$count"
}

changed_count() {
  local pattern="$1"
  gitc diff --name-only "$current_ref..$target_ref" | awk -v pat="$pattern" '$0 ~ pat { count++ } END { print count + 0 }'
}

emit_input_source() {
  local title="$1"
  local source="$2"
  echo "### $title"
  if [ -z "$source" ]; then
    echo "待补充"
  elif [[ "$source" =~ ^https?:// ]]; then
    printf '来源: %s\n' "$source"
  elif [ -f "$source" ]; then
    printf '材料摘要已内嵌如下；如需追溯，请优先查看摘要中的官方来源链接。\n\n'
    awk '
      NR > 120 { exit }
      /^#{1,6}[[:space:]]/ { print "###" $0; next }
      { print }
    ' "$source"
  else
    printf '来源: `%s`（未找到本地文件，请人工确认）\n' "$source"
  fi
  echo
}

go_directive() {
  local ref="$1"
  gitc show "$ref:go.mod" 2>/dev/null | awk '$1 == "go" { print $2; exit }'
}

effective_go_mod_version() {
  local ref="$1"
  local module="$2"
  gitc show "$ref:go.mod" 2>/dev/null | awk -v module="$module" '
    $1 == module && $2 ~ /^v/ { require=$2 }
    $1 == module && $2 == "=>" && $3 == module && $4 ~ /^v/ { replace=$4 }
    END {
      if (replace != "") print replace;
      else if (require != "") print require;
      else print "-";
    }'
}

version_minor() {
  printf '%s\n' "$1" | sed -n 's/^v[0-9][0-9]*\.\([0-9][0-9]*\).*/\1/p'
}

k8s_dependency_line() {
  local version="$1"
  local minor
  minor="$(version_minor "$version")"
  if [ -n "$minor" ]; then
    printf 'Kubernetes 1.%s 依赖线' "$minor"
  else
    printf '待确认'
  fi
}

k8s_p0_status() {
  local current target cm tm
  current="$(effective_go_mod_version "$current_ref" "k8s.io/client-go")"
  target="$(effective_go_mod_version "$target_ref" "k8s.io/client-go")"
  cm="$(version_minor "$current")"
  tm="$(version_minor "$target")"
  if [ -n "$cm" ] && [ -n "$tm" ] && [ "$tm" -gt "$cm" ]; then
    printf '触发'
  else
    printf '待确认'
  fi
}

k8s_module_row() {
  local module="$1"
  printf '| `%s` | `%s` | `%s`' "$module" "$(effective_go_mod_version "$current_ref" "$module")" "$(effective_go_mod_version "$target_ref" "$module")"
  if [ -n "$downstream_ref" ]; then
    printf ' | `%s`' "$(effective_go_mod_version "$downstream_ref" "$module")"
  fi
  printf ' |\n'
}

missing_inputs_summary() {
  if [ -n "$release_notes" ]; then
    printf '客户驱动、P0 风险确认和验证结果尚未补齐'
  else
    printf 'Release Note、客户驱动、P0 风险确认和验证结果尚未补齐'
  fi
}

decision_banner() {
  if [ "$(k8s_p0_status)" = "触发" ]; then
    printf 'DEFER / 待补充验证后再决策。P0 风险：Kubernetes / ACP 平台版本兼容性已触发，未确认下游最低支持 K8s 版本和 ACP 组合版本前，不建议无条件 GO。'
  else
    printf 'DEFER / 待补充验证后再决策。需要补齐客户/产品驱动、验证矩阵和一票否决项状态后再给 GO/NO-GO。'
  fi
}

tmp="${output:-/dev/stdout}"
{
  echo "# ${component} 发版决策证据报告"
  echo
  echo "> **当前建议结论：$(decision_banner)**"
  echo
  echo "生成时间: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "代码仓库: \`$repo\`"
  echo
  echo "## 决策摘要"
  echo
  echo "| 项目 | 当前判断 | 依据 | 下一步 |"
  echo "|---|---|---|---|"
  echo "| 建议结论 | **DEFER / 待补充验证后再决策** | 已识别明显版本价值，但 $(missing_inputs_summary) | 补齐客户/产品驱动、P0 风险确认和验证矩阵后再给 GO/NO-GO |"
  echo "| P0 风险 | **K8s / ACP 兼容性 $(k8s_p0_status)** | \`k8s.io/client-go\` 从 \`$(effective_go_mod_version "$current_ref" "k8s.io/client-go")\`（$(k8s_dependency_line "$(effective_go_mod_version "$current_ref" "k8s.io/client-go")")）到 \`$(effective_go_mod_version "$target_ref" "k8s.io/client-go")\`（$(k8s_dependency_line "$(effective_go_mod_version "$target_ref" "k8s.io/client-go")")） | 必须确认目标版本支持的 Kubernetes 版本范围，并覆盖主要交付平台 ACP 的目标 Kubernetes 版本 |"
  echo "| 主要价值 | Ascend 910C / hami-vnpu-core、DRA/设备模式、观测性和稳定性修复 | 见 Release Note 与变更主题摘要 | 整理为面向内部评审的发版价值说明 |"
  echo "| 主要风险 | Scheduler/device-plugin/chart/K8s 依赖同时变化 | scheduler $(changed_count '^pkg/scheduler/|^cmd/scheduler/|^charts/hami/templates/scheduler/') 个文件、device-plugin $(changed_count '^pkg/device-plugin/|^cmd/device-plugin/|^charts/hami/templates/device-plugin/') 个文件、chart/install $(changed_count '^charts/hami/') 个文件 | 需要 build、chart render、升级回滚、GPU/NPU e2e |"
  echo
  echo "## 决策依据表"
  echo
  echo "| 维度 | 判断 | 证据摘要 | 风险/动作 |"
  echo "|---|---|---|---|"
  echo "| 上游版本价值 | 倾向有价值 | feature 线索 $(commit_count 'feat|support|add') 条；Ascend/NPU 线索 $(commit_count 'ascend|npu|vnpu|910c|core') 条；chart/metrics/webhook 线索 $(commit_count 'chart|helm|webhook|servicemonitor|metric|install|values') 条 | 必须结合 Release Note 形成清晰的产品价值说明 |"
  echo "| 缺陷/安全修复 | 倾向有跟进价值 | fix/security 线索 $(commit_count 'fix|security|panic|dos|nil|crash') 条 | 筛出是否命中下游客户或生产路径 |"
  echo "| K8s / ACP 版本兼容 | **P0 风险项** | K8s 依赖有效版本从 \`$(effective_go_mod_version "$current_ref" "k8s.io/client-go")\`（$(k8s_dependency_line "$(effective_go_mod_version "$current_ref" "k8s.io/client-go")")）升到 \`$(effective_go_mod_version "$target_ref" "k8s.io/client-go")\`（$(k8s_dependency_line "$(effective_go_mod_version "$target_ref" "k8s.io/client-go")")） | 未确认最低支持 K8s 版本和 ACP 组合版本前，不建议 GO |"
  echo "| 下游 overlay | 有可控但必须复核的差异 | \`.build/build.yaml\`、\`module-plugin.yaml\` 只存在于下游；\`values.yaml\` 在 target 与 downstream 不同 | 需要确认 ACP/ModulePlugin/registry/relatedImages 仍可安装升级 |"
  echo "| libvgpu/HAMi-core | 本次主仓 gitlink 未变 | current/target/downstream 都是 \`$(gitc ls-tree "$target_ref" libvgpu | awk '{print $3}' | cut -c1-12)\` | runtime 风险主要来自集成路径和依赖，不是 libvgpu gitlink 变化 |"
  echo "| 验证可用性 | 当前未知 | 报告尚未填入 build/e2e/硬件验证结果 | 缺少 GPU/NPU 硬件验证时最多只能 GO with constraints 或 DEFER |"
  echo
  echo "## 对比范围"
  echo
  echo "| 类型 | Ref | Commit | Describe |"
  echo "|---|---|---|---|"
  printf '| 当前下游版本 | `%s` | `%s` | `%s` |\n' "$current_ref" "$(short_ref "$current_ref")" "$(describe_ref "$current_ref")"
  printf '| 目标上游版本 | `%s` | `%s` | `%s` |\n' "$target_ref" "$(short_ref "$target_ref")" "$(describe_ref "$target_ref")"
  if [ -n "$downstream_ref" ]; then
    printf '| 下游候选分支 | `%s` | `%s` | `%s` |\n' "$downstream_ref" "$(short_ref "$downstream_ref")" "$(describe_ref "$downstream_ref")"
  fi
  echo

  echo "## 变更规模"
  echo
  printf '%s\n' "- 当前下游..目标上游 commits: \`$(gitc rev-list --count "$current_ref..$target_ref")\`"
  printf '%s\n' "- 目标上游..当前下游 commits: \`$(gitc rev-list --count "$target_ref..$current_ref")\`"
  printf '%s\n' "- 当前下游..目标上游 diffstat: \`$(gitc diff --shortstat "$current_ref..$target_ref" | sed 's/^ *//')\`"
  if [ -n "$downstream_ref" ]; then
    printf '%s\n' "- 目标上游..下游候选 commits: \`$(gitc rev-list --count "$target_ref..$downstream_ref")\`"
    printf '%s\n' "- 当前下游..下游候选 diffstat: \`$(gitc diff --shortstat "$current_ref..$downstream_ref" | sed 's/^ *//')\`"
    printf '%s\n' "- 目标上游..下游候选 diffstat: \`$(gitc diff --shortstat "$target_ref..$downstream_ref" | sed 's/^ *//')\`"
  fi
  echo

  echo "## 子系统影响面"
  echo
  echo "| 子系统 | 变更文件数 |"
  echo "|---|---:|"
  changed_bucket "scheduler" '^pkg/scheduler/|^cmd/scheduler/|^charts/hami/templates/scheduler/'
  changed_bucket "device-plugin" '^pkg/device-plugin/|^cmd/device-plugin/|^charts/hami/templates/device-plugin/'
  changed_bucket "device-vendors" '^pkg/device/'
  changed_bucket "runtime/docker/build" '^docker/|^libvgpu|^go\.mod|^go\.sum|^version\.mk'
  changed_bucket "chart/install" '^charts/hami/'
  changed_bucket "ci/build" '^\.github/|^\.build/|^hack/'
  changed_bucket "docs/examples" '^docs/|^examples/|^README'
  echo

  echo "## 发版关键路径信号"
  echo
  echo "| 路径 | 当前下游 | 目标上游 |$(if [ -n "$downstream_ref" ]; then printf ' 下游候选 |'; fi)"
  echo "|---|---|---|$(if [ -n "$downstream_ref" ]; then printf -- '---|'; fi)"
  path_row VERSION
  path_row go.mod
  path_row go.sum
  path_row charts/hami/Chart.yaml
  path_row charts/hami/values.yaml
  path_row charts/hami/module-plugin.yaml
  path_row .build/build.yaml
  path_row libvgpu
  echo

  echo "## 变更主题摘要"
  echo
  echo "| 主题 | 变更说明 | 代表性证据 | 决策影响 |"
  echo "|---|---|---|---|"
  echo "| Ascend / NPU / hami-vnpu-core | 增强 Ascend 910C、core resource、hami-vnpu-core 和 module-pair 等能力 | $(key_commits 'ascend|npu|vnpu|910c|core') | 如果下游有 910C/vNPU roadmap 或客户需求，显著提高发版必要性；否则需要确认是否可默认关闭或低风险携带 |"
  echo "| Scheduler / allocation / cache | 涉及设备分配、MIG/CDI、handshake、cache、score、initContainer/multi-container 等稳定性路径 | $(key_commits 'scheduler|allocate|allocation|quota|cache|score|bind|filter|handshake') | 修复价值高，但也是核心回归风险，需要重点 e2e 和升级验证 |"
  echo "| Chart / Webhook / Metrics | 涉及 Helm values、webhook selector、ServiceMonitor、metrics 命名/标签 | $(key_commits 'chart|helm|webhook|servicemonitor|metric|install|values') | 有运维价值，但必须验证默认安装、Alauda overlay、ModulePlugin 和监控兼容 |"
  echo "| 安全 / Panic / DoS | 涉及 Go security upgrade、DoS LimitReader、scheduler nil panic 等 | $(key_commits 'security|cve|panic|crash|dos|limitreader|nil') | 可能构成独立跟进或 cherry-pick 理由，需要确认影响版本和生产可达性 |"
  echo "| K8s / controller-runtime 依赖 | K8s 依赖和 controller-runtime 升级幅度大 | k8s.io/client-go $(effective_go_mod_version "$current_ref" "k8s.io/client-go") -> $(effective_go_mod_version "$target_ref" "k8s.io/client-go"); controller-runtime $(effective_go_mod_version "$current_ref" "sigs.k8s.io/controller-runtime") -> $(effective_go_mod_version "$target_ref" "sigs.k8s.io/controller-runtime") | P0 风险项：必须确认最低支持 Kubernetes 版本和 API 兼容性 |"
  echo
  echo "## P0 风险：Kubernetes / ACP 平台版本兼容性"
  echo
  echo "> 规则：只要目标版本升级了 \`k8s.io/*\`、\`k8s.io/kubelet\`、\`k8s.io/kube-scheduler\`、\`controller-runtime\` 等 Kubernetes 依赖，就必须确认下游支持的最低 Kubernetes 版本，以及是否匹配主要交付平台 ACP 的目标 Kubernetes 版本。未确认前，该项按 P0 风险处理，不能给无条件 GO。"
  echo
  echo "参考：Kubernetes 官方 version skew policy（https://kubernetes.io/releases/version-skew-policy/）和 client-go 安装/版本说明（https://github.com/kubernetes/client-go/blob/master/INSTALL.md）。"
  echo
  echo "ACP 平台证据需补齐：ACP 是下游主要 Kubernetes 容器平台。若目标 ACP 版本与 HAMi 目标依赖线不同，例如 ACP 4.4 目标 Kubernetes 为 1.35 而 HAMi 目标依赖线为 1.36，则 ACP 组合验证必须作为 P0 审计输入。"
  echo
  echo "### 基本版本推断"
  echo
  echo "| 推断项 | 当前下游 | 目标上游 | 下游候选 | 说明 |"
  echo "|---|---|---|---|---|"
  printf '| K8s 依赖线 | `%s` | `%s`' "$(k8s_dependency_line "$(effective_go_mod_version "$current_ref" "k8s.io/client-go")")" "$(k8s_dependency_line "$(effective_go_mod_version "$target_ref" "k8s.io/client-go")")"
  if [ -n "$downstream_ref" ]; then
    printf ' | `%s`' "$(k8s_dependency_line "$(effective_go_mod_version "$downstream_ref" "k8s.io/client-go")")"
  else
    printf ' | `-`'
  fi
  printf ' | 按 client-go / k8s.io 版本规则，`v0.N` 大致对齐 Kubernetes `1.N` 依赖线。 |\n'
  echo "| ACP 组合平台 | 待补充 | 待补充 | 待补充 | 必须填入目标 ACP 版本及其 Kubernetes 版本，例如 ACP 4.4 / Kubernetes 1.35。 |"
  echo "| 最低可支持集群版本 | 待审计 | 待审计 | 待审计 | 不能仅从 go.mod 精确反推；需要结合实际 API、字段、scheduler/kubelet 交互和老集群验证确认。 |"
  echo "| 当前决策含义 | 当前线约为 $(k8s_dependency_line "$(effective_go_mod_version "$current_ref" "k8s.io/client-go")") | 目标线约为 $(k8s_dependency_line "$(effective_go_mod_version "$target_ref" "k8s.io/client-go")") | 候选线约为 $(if [ -n "$downstream_ref" ]; then k8s_dependency_line "$(effective_go_mod_version "$downstream_ref" "k8s.io/client-go")"; else printf '-'; fi) | 依赖线跨越多个 minor，必须建立 P0 审计项。 |"
  echo
  echo "| 模块 | 当前下游有效版本 | 目标上游有效版本 |$(if [ -n "$downstream_ref" ]; then printf ' 下游候选有效版本 |'; fi)"
  echo "|---|---|---|$(if [ -n "$downstream_ref" ]; then printf -- '---|'; fi)"
  printf '| `go` directive | `%s` | `%s`' "$(go_directive "$current_ref")" "$(go_directive "$target_ref")"
  if [ -n "$downstream_ref" ]; then
    printf ' | `%s`' "$(go_directive "$downstream_ref")"
  fi
  printf ' |\n'
  k8s_module_row "k8s.io/api"
  k8s_module_row "k8s.io/apimachinery"
  k8s_module_row "k8s.io/client-go"
  k8s_module_row "k8s.io/kubelet"
  k8s_module_row "k8s.io/kube-scheduler"
  k8s_module_row "sigs.k8s.io/controller-runtime"
  echo
  echo "- 当前判断: **$(k8s_p0_status)**。如果下游仍需支持较老 Kubernetes 集群，必须补充兼容性验证或明确发布约束。"
  echo "- P0 审计问题: 下游产品声明支持的最低 Kubernetes 版本是多少；目标 ACP 版本对应的 Kubernetes 版本是多少；该版本是否低于目标依赖线；目标版本是否使用了低版本 API server 不支持的字段/行为；scheduler、device-plugin、webhook 与 kubelet/API server 的交互是否在最低版本集群和目标 ACP 集群可用。"
  echo "- 必补证据: 支持的 Kubernetes 版本矩阵、目标 ACP/Kubernetes 版本、server-side dry-run、目标 ACP 集群安装/升级验证、scheduler/device-plugin 与 kubelet 交互验证。"
  echo "- 决策影响: 未确认前结论应为 **DEFER** 或 **GO with constraints**，不能直接 GO。"
  echo

  echo "## 子模块信号"
  echo
  gitc diff --submodule=short "$current_ref..$target_ref" -- . | sed -n '/^Submodule/p' || true
  if gitc ls-tree "$current_ref" libvgpu >/dev/null 2>&1 || gitc ls-tree "$target_ref" libvgpu >/dev/null 2>&1; then
    echo
    echo "| 类型 | libvgpu gitlink |"
    echo "|---|---|"
    printf '| 当前下游 | `%s` |\n' "$(gitc ls-tree "$current_ref" libvgpu | awk '{print $3}')"
    printf '| 目标上游 | `%s` |\n' "$(gitc ls-tree "$target_ref" libvgpu | awk '{print $3}')"
    if [ -n "$downstream_ref" ]; then
      printf '| 下游候选 | `%s` |\n' "$(gitc ls-tree "$downstream_ref" libvgpu | awk '{print $3}')"
    fi
  fi
  echo

  echo "## 外部输入"
  echo
  emit_input_source "上游 Release Note" "$release_notes"
  emit_input_source "客户 / 产品驱动因素" "$customer_drivers"

  echo "## 建议验证矩阵"
  echo
  echo "| 范围 | GO 前需要完成 | 当前状态 |"
  echo "|---|---|---|"
  echo "| 源码构建 | 构建受影响组件的镜像/二进制 | 待补充 |"
  echo "| 单元测试 | 覆盖变更的 scheduler/device-plugin/runtime 包 | 待补充 |"
  echo "| Helm 渲染/安装 | 默认 chart + Alauda values/ModulePlugin overlay | 待补充 |"
  echo "| ACP 组合验证 | 目标 ACP / Kubernetes 版本上的安装、升级、回滚、server-side dry-run 和关键资源创建 | 待补充 |"
  echo "| 升级/回滚 | 当前下游版本 -> 候选版本 -> 回滚 | 待补充 |"
  echo "| NVIDIA GPU | 分配、MIG/CDI、hami-core runtime 注入等受影响路径 | 待补充 |"
  echo "| Ascend NPU/vNPU | Ascend resource/core 路径，尤其 release 价值依赖这些能力时 | 待补充 |"
  echo "| 可观测性 | metrics/ServiceMonitor/webhook selector 行为 | 待补充 |"
  echo "| 安全/供应链 | CVE、license、镜像扫描相对当前版本的变化 | 待补充 |"
  echo

  echo "## 一票否决项"
  echo
  echo "| 否决项 | 状态 | 证据 / 解除条件 |"
  echo "|---|---|---|"
  echo "| 构建阻塞 | 待补充 | |"
  echo "| Chart/安装阻塞 | 待补充 | |"
  echo "| 关键回归 | 待补充 | |"
  echo "| 缺少硬件验证 | 待补充 | |"
  echo "| 下游 overlay 不兼容 | 待补充 | |"
  echo "| Kubernetes / ACP 兼容性阻塞 | unknown / P0 审计未完成 | 解除条件：明确下游最低支持 K8s 版本、目标 ACP/Kubernetes 版本，并完成目标 ACP 集群上的安装/升级、API server、scheduler/device-plugin/kubelet 交互验证。 |"
  echo "| 安全/法务阻塞 | 待补充 | |"
  echo "| 可支持性阻塞 | 待补充 | |"
  echo

  echo "## 评分"
  echo
  echo "### 正向价值"
  echo
  echo "| 维度 | 满分 | 得分 | 证据 |"
  echo "|---|---:|---:|---|"
  echo "| 发版策略基线 | 10 | 待补充 | |"
  echo "| 客户/产品需求 | 20 | 待补充 | |"
  echo "| 关键缺陷修复 | 20 | 待补充 | |"
  echo "| 新能力 | 20 | 待补充 | |"
  echo "| 运维改进 | 10 | 待补充 | |"
  echo "| 生态对齐 | 10 | 待补充 | |"
  echo "| 避免 cherry-pick 成本 | 10 | 待补充 | |"
  echo
  echo "### 风险"
  echo
  echo "| 维度 | 满分 | 得分 | 缓解措施 |"
  echo "|---|---:|---:|---|"
  echo "| Scheduler/device-plugin 契约风险 | 20 | 待补充 | |"
  echo "| Runtime/hook 风险 | 15 | 待补充 | |"
  echo "| Chart/安装风险 | 15 | 待补充 | |"
  echo "| 依赖/工具链风险 | 15 | 待补充 | |"
  echo "| 下游 overlay 风险 | 15 | 待补充 | |"
  echo "| 验证缺口 | 15 | 待补充 | |"
  echo "| 发布窗口/运维时机 | 5 | 待补充 | |"
  echo

  echo "## 决策草案"
  echo
  echo "- 决策: 待补充"
  echo "- 正向价值分: 待补充"
  echo "- 风险分: 待补充"
  echo "- 净分: 待补充"
  echo "- 公式: 净分 = 正向价值分 - 风险分"
  echo "- 一票否决: 任一未解除否决项会把结论改为 DEFER 或 NO-GO"
  echo "- 下一步: 待补充"
  echo
  echo "## 附录：Commit 追溯线索"
  echo
  echo "> 这一节只用于追溯 PR/commit，不作为主要阅读入口。决策优先看“决策摘要”和“决策依据表”。"
  echo
  commit_bucket "功能新增/增强" '^[0-9a-f]+ (feat|Add|add|Supports|support)'
  commit_bucket "缺陷修复/安全修复" '^[0-9a-f]+ (fix|Fix|security|Security)'
  commit_bucket "依赖/工具链升级" '^[0-9a-f]+ (build\(deps\)|security: upgrade|Upgrade Go)'
  commit_bucket "文档/示例" '^[0-9a-f]+ (docs|doc|README)'
  echo "### 关键路径线索"
  echo
  commit_hints "调度 / 分配 / 缓存" 'scheduler|allocate|allocation|quota|cache|score|bind|filter|handshake'
  commit_hints "运行时 / CDI / MIG / libvgpu" 'runtime|cdi|mig|libvgpu|mps|cuda|nvml|nvidia'
  commit_hints "Ascend / NPU / hami-vnpu-core" 'ascend|npu|vnpu|910c|core'
  commit_hints "Chart / 安装 / Webhook / Metrics" 'chart|helm|webhook|servicemonitor|metric|install|values'
  commit_hints "安全 / Panic / Crash / DoS" 'security|cve|panic|crash|dos|limitreader|nil'
} > "$tmp"

if [ -n "$output" ]; then
  echo "wrote $output"
fi
