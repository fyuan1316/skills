---
name: hami-fix
description: Run ONE disciplined, mostly-unattended dev/test/fix loop on a HAMi tech-stack Go repo (under projects/ai-infra) and hand a reviewed result to the human. Given a small, unit-testable task, it establishes a green baseline, branches, then loops edit→build→unit-test against the hami-dev oracle until green — requiring a NEW unit test for the change, machine-verifying that test is a real discriminator (fails on pre-change code), running an adversarial reviewer, and forcing a human severity/reachability judgement before anything ratchets forward. It NEVER auto-commits to trunk, merges, or pushes. Use when the user asks to "fix a HAMi bug", "make a small change to the HAMi scheduler/device/quota with tests", "run the autonomous fix loop", "do a disciplined fix on projects/ai-infra/<repo>", or to crystallize an edit→test→fix iteration into a reviewed branch. For raw build/test execution use hami-dev; for the whole loop discipline use this.
---

# hami-fix — 有纪律的自治修复闭环（探索 loop 的第一个固化机制）

This skill crystallizes the validated v0 run (`research/automation/runs/v0-quota-del-symmetry.md`)
into a repeatable procedure. It is the **orchestration layer**; the **oracle**
(build + unit test) is delegated to the `hami-dev` skill — this skill never
re-implements build/test.

It is the executable form of the automation methodology in
`research/automation/` — specifically the **exploration loop's inner
mechanical cycle** (generate→test→fix) run mostly-unattended, with the human
pulled back to the loop boundary (define spec, own the oracle, judge severity,
ratchet). Read `L0-principles.md` §3.1/§3.2 and `L1-loops.md` (Loop A) for the
"why" behind every gate below.

## Loop contract (the four-piece template)

```
trigger : a small, unit-testable HAMi task with an UNAMBIGUOUS spec
signal  : hami-dev oracle (go build + go test) — deterministic, agent can't fake
exit    : oracle green + new test present + new test is a DISCRIMINATOR + reviewer clears
give-up : 8 edit→build→test iterations OR ~30 min → STOP, report where stuck
memory  : branch + diff + report appended to research/automation/runs/
human   : OUT of the inner loop; AT the boundary for spec(0), severity(7), ratchet(8)
```

## The oracle (delegated to hami-dev — never reimplement)

```bash
HD=/workspaces/yuanfang-base-ubuntu/kbs/fy-skills/hami-dev/scripts/run.sh
bash $HD hami pkg:./pkg/device/...   # scoped fast inner-loop oracle (go test, non-zero on fail)
bash $HD hami                        # full hack/unit-test.sh
bash $HD hami build-test             # build all cmds + unit test
bash $HD hami lint:./pkg/device/...  # Tier-2 gate (go vet + golangci-lint)
```
A green Tier-1 oracle says nothing about real-hardware paths. e2e/CUDA
(Tier 3, P100) is a **separate gate at the 晋级/发布 boundary**, NOT part of
this inner loop — see hami-dev `scripts/p100.sh`.

## Procedure — run the stages in order; the discipline is the point

### Stage 0 — Spec gate (precondition; human owns this)
The task MUST have an **unambiguous, machine-checkable spec** — a precise
"correct behavior" you can assert in a test. If the intended behavior is
debatable (needs the original PR's intent, or "what should this do?"), **STOP
and get the human to pin the spec.** A fuzzy spec = no trustworthy oracle = the
agent will spec-game (`L0` §3.1). This is exactly why 3 of the 4 v0 candidates
were rejected. Do not proceed past this gate on a guess.

### Stage 1 — Green baseline (prove the oracle is green BEFORE touching anything)
```bash
bash $HD hami pkg:<scoped-path>     # must print "hami-dev: PASS"
```
If baseline is red, the oracle is untrustworthy — fix/quarantine that first.
Flaky test in scope? Quarantine it; never let retry-to-green count (`L0` §3.1).

### Stage 2 — Isolate on a feat branch (reversibility)
```bash
cd projects/ai-infra/<REPO> && git checkout -b feat/<scope>
```
Per repo branch policy: feature work on `feat/*`, never commit to trunk/release.

### Stage 3 — Autonomous fix loop (inner mechanical cycle; mostly unattended)
Loop: **edit production code → run oracle → read failure → fix**, until green
or give-up. May be driven by a sub-agent. Hard bans (violating any = failed run,
report it, do NOT force green):
- **Do NOT modify, delete, or weaken any EXISTING test / assertion / test data**
  to go green. The existing suite is the trustworthy regression oracle. If a
  pre-existing test breaks, STOP and report — that's signal, not an obstacle.
- No skipping tests, no build tags to hide tests, no special-casing inputs.
- Scope to the minimal files (the fix + its test). Leave unrelated files alone.
- **Give-up budget: 8 iterations or ~30 min.** On exhaustion, STOP and report
  exactly where stuck. Never thrash or delete things to force green.

### Stage 4 — New test required, intent from the SPEC (not the diff)
The production change MUST come with a new/extended unit test, following the
repo's existing test patterns. Its asserted behavior derives from the Stage-0
spec, **not** from your own diff (else it just encodes your possibly-wrong
understanding — `L0` §3.1 "回归才是可信的那半").

### Stage 5 — Discriminator check (MACHINE-verified, automatic)
Prove the new test actually exercises the fix — it must FAIL against pre-change
production code:
```bash
bash scripts/discriminator-check.sh hami <base_ref> <go-test-selector...>
# e.g.  ... hami HEAD  ./pkg/device/ -run TestDelQuotaIgnoresNonLimitsKey
#   (base_ref = the commit/state WITHOUT your fix; HEAD if fix is uncommitted in worktree,
#    or HEAD~1 if you already committed the fix)
```
- `VERDICT=DISCRIMINATOR` (exit 0) → good, proceed.
- `VERDICT=TAUTOLOGY` (exit 3) → the test passes even without the fix; it's
  meaningless. Go back to Stage 4. Do NOT proceed.
The script reverts only production (`*.go` non-`_test.go`) files, keeps your
test, runs it, then restores — index untouched, working tree left clean.

### Stage 6 — Adversarial reviewer (L2; fires once, at convergence)
Spawn an INDEPENDENT reviewer agent (not the fixer). It must:
- read the **Stage-0 spec / issue**, NOT the fixer's narrative — re-derive the
  expected behavior itself, then compare to the diff (avoid anchoring);
- actually run the oracle + reproduce, not just reason;
- be prompted to **refute**, default to "reject unless convinced".
Tie-break (mandatory — adding a judge obliges adding arbitration, `L0` §3.2):
reviewer rejects → back to Stage 3 with its objection; persistent deadlock →
escalate to the human. Never let fixer and reviewer loop unbounded.

### Stage 7 — Severity / reachability judgement (HUMAN gate; do NOT self-certify)
A green, discriminating oracle proves the code matches the test — it does **NOT**
prove a real-world input triggers the defect (`L0` §3.1, last note; the v0
DelQuota bug needed a contrived key and was real-world-unreachable). Classify,
with explicit reasoning the human signs off:
- **real-bug-fix** — a legitimate input hits it → normal fix framing; or
- **consistency/robustness cleanup** — no realistic trigger → frame honestly as
  hardening, and say so in any PR.
Do not let the agent rate its own severity. This determines upstream framing.

### Stage 8 — Handoff to human ratchet (L3); NEVER auto-merge
Produce: the `feat/*` branch + diff + final oracle output + discriminator
verdict + reviewer verdict + a one-paragraph self-assessment (what changed, why,
where uncertain, severity class). Append a run record to
`research/automation/runs/`. Then **STOP**: committing to the feat branch is OK
only if the human asked; **never** merge, push, or commit to trunk — those are
irreversible棘轮 actions reserved for the human (`L0` 原则 1 & 5).

## Scope & boundaries
- Targets the **Go logic layer** (Tier 1, no hardware): scheduler, device,
  quota, util, config — anything `go test ./pkg/...` can judge on the devpod.
- HAMi-core (CUDA) / accelerator-test e2e need the P100 — that's Tier 3, a
  separate downstream gate, out of this loop.
- One task per run. For unknown-size bug hunts, run it repeatedly (each a
  discrete, reviewed unit), don't widen a single run's scope.

## Skill self-healing (borrowed from team dev-loop — copy-not-depend)
If a step here fails because the SKILL itself is wrong (bad path, missing/renamed
script, stale oracle command, step logic diverges from reality), **fix this
SKILL.md / its scripts and re-run** — don't paper over it with an ad-hoc
workaround. Capture the fix in the skill so the next run works. (Do NOT self-edit
for transient causes: network, user-misconfigured env, flaky external call.)

## Files
- `scripts/discriminator-check.sh` — machine discriminator gate (Stage 5),
  validated both ways (real test → DISCRIMINATOR exit 0; tautology → exit 3).
- Oracle: `../hami-dev/scripts/run.sh` (do not duplicate).

## See also
- `research/automation/` — the methodology this skill implements (README, L0, L1,
  decisions, runs/). This skill IS Loop A's固化; v2 adds the e2e晋级 gate, v3
  generalizes the loop beyond HAMi.
