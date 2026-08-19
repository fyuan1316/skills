# Post-AC Plugin Release Email

Generate this Chinese release email automatically only after both AC CN and AC
IO upload/listing evidence is recorded. Keep the structure and field order
exact. Save Markdown as the internal audit record and provide
Outlook-compatible HTML as the user-facing email. Generate and return or save
content only. This workflow has no email delivery action.

## Required facts

- Product display name and formal version
- One-sentence product positioning
- Three to six product-facing capabilities or release highlights
- One formal validation and security conclusion
- Release date and maintenance end date
- Supported ACP versions and architectures
- Confirmed public documentation URL
- Upstream or product baseline
- Upgrade path
- ERRATA conclusion

Use only formal evidence. Do not expose BuildRuns, digests, checksums, internal
registries, package-minio URLs, RC history, or internal documentation branches.
The package links are always the AC CN and AC IO application pages.

Describe fixes as user-visible problem symptoms and impact. Do not describe
the internal implementation, field mapping, decoder algorithm, container-slot
ordering, or how the code was changed unless that detail is required for a
published workaround or ERRATA.

## Strict content format

The Markdown internal record and Outlook HTML must contain the same facts in
this exact order. The HTML must use inline styles, a real two-column table, and
`role="presentation"` for reliable Outlook rendering. Do not return Markdown as
the user-facing delivery format.

```text
标题：{product_name} {version} 版本发布

大家好！
{product_name} {version} 已上架到 Alauda Cloud，正式发布。
{product_positioning}
{highlights_heading}
{capability_1}
{capability_2}
{capability_n}
{formal_validation_conclusion}
以下是产品的关键信息供参考：
| **分类** | **详细说明** |
| --- | --- |
| **版本名称** | {product_name} {version} |
| **版本发布时间** | {release_date} |
| **适配 ACP 版本** | {acp_versions} |
| **支持架构** | {architectures} |
| **版本维护截止时间** | {maintenance_end_date} |
| **产品安装包** | 国内：[https://cloud.alauda.cn/apps](https://cloud.alauda.cn/apps)<br>国外：[https://cloud.alauda.io/apps](https://cloud.alauda.io/apps) |
| **产品交付文档** | [{docs_url}]({docs_url}) |
| **版本基线** | {baseline} |
| **产品升级路径** | {upgrade_path} |
| **产品 ERRATA** | {errata} |
```

Render with:

```bash
python3 scripts/render-plugin-release-email.py \
  --input <release-email-input.json> \
  --output <release-dir>/11-release-email.md \
  --html-output <release-dir>/11-release-email-outlook.html
```

Record `communication.release-email.generated=true` only when the renderer
succeeds, both generated outputs match the release profile, and their facts are
synchronized. If the docs URL is not verified as the intended public path, keep
both materials in draft state and do not present them as ready to send.

## HAMi-WebUI v1.10.3 reference

The user-approved reference is titled `Alauda Build of HAMi-WebUI v1.10.3
版本发布`. It uses release date `2026-07-27`, maintenance end date
`2027-07-27`, ACP `v4.0` through `v4.3`, architectures `AMD64` and `ARM64`,
documentation URL `https://docs.alauda.cn/hami/2.9/install/hami-webui.html`,
baseline `基于社区 HAMi-WebUI v1.2.0`, upgrade from `v1.10.2` to `v1.10.3`,
and `暂无` for ERRATA.

Do not present v1.10.3 as the first HAMi v2.9.0-compatible WebUI release;
v1.10.2 already introduced the HAMi v2.9 metric update. Lead the v1.10.3
email with the heading `本次版本主要修复以下问题：` and these two
user-visible fixes:

1. Searching the task list by Pod or workload name could fail to find the
   corresponding task.
2. When a Pod contains init containers, device-allocation information for its
   regular workload containers could be misplaced or displayed incorrectly.
