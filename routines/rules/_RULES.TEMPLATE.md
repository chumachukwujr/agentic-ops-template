---
title: <Routine> rules
tier: routine-rules
routine: agents/<routine>.md
source: <where these rules came from, e.g. "strategy_prompt.md v<N> §<WS>, split <DATE>">
last_verified: <YYYY-MM-DD>
ttl_days: 90
owner: <OWNER>
---

# <Routine>: standing policy

<!--
  One rules file per routine (not per beat: beats of the same routine share one file and branch
  inside it if they must). This is the policy layer ABOVE the routine prompt: what counts, what
  never gets claimed, which thresholds bind, where the numbers live. The routine prompt holds
  the mechanics: the steps, the file paths, the output format.

  Canon is pointed to, never restated. A fact copied here is a fact that will drift.
  Numbers are never written here. They come from state/now/state.md.

  Precedence, stated in the file so there is no argument at 3am: on a conflict between this
  file and the routine, the routine wins for this agent. This file exists to stop drift between
  the standing rules and the routine, not to override it.
-->

The routine holds the run procedure and the output formats. This file is the policy above it.
Canon referenced: `config/canon/<note>.md`, `config/canon/<note>.md`. Numbers:
`state/now/state.md` only. **Precedence:** the routine wins for this agent on conflict.

## 1. <Posture or scope>

- <The standing decision this routine operates under, and what would change it.>
- <What this routine observes but does not own, and who does.>

## 2. <Decision rules>

- Alert only when <criterion A> AND <criterion B>. Everything else is recorded and stays recorded.
- <A thing that is never proposed, and the file that proves why.>
- <A claim that must cite the query that established it.>

## 3. <Never rules>

- Never <claim> externally until <condition>. The honest phrasing before that is "<phrasing>".
- Never <action> without <gate>.

## Targets

Target values only. Live values are in `state/now/state.md`.

| Metric | Target | Tracked in |
|---|---|---|
| <metric> | <target> | `<state file or the decisions field>` |
| Decision-log discipline | 100% of runs carry a `decisions` field | `state/history.jsonl` |

## Not carried over

What was deliberately left out when this file was created, and where it went. The ledger is
how the next reader knows an omission was a decision.

- <item>: <canon note §N | routine step N | generated tier | retired <DATE>, <why>>
