# hami-fix

有纪律的、基本无人值守的 HAMi 修复闭环：给一个小的、单测可判定且 **spec 不可争议**的任务，
它建绿色基线 → 拉 feat 分支 → 在 [hami-dev](../hami-dev/README.md) oracle 上跑
`edit→build→test→fix` 直到绿，并且：

- 强制为改动**新增单测**；
- **机器自动验证**这个测试是真判别器（对 pre-change 代码必挂，`scripts/discriminator-check.sh`）；
- 跑一个**对抗 reviewer**（独立、对着 spec 不对着叙事、默认拒）；
- 强制一道**严重度/可触达性的人判闸**（oracle 绿 ≠ 真 bug）；
- **绝不**自动 commit 到 trunk / merge / push——棘轮交给人。

它是 `research/automation/` 方法论里**探索 loop 内层机械循环**的固化（v0 跑通后提炼，
见 `research/automation/runs/`）。oracle 委派给 hami-dev，本 skill 只做闭环编排。

细节与逐阶段纪律见 [SKILL.md](SKILL.md)。
