# <ORG> Operations Strategy — v<N>  ❖ CANONICAL ❖
# Generated: <DATE> (maintainer run <N>)
# Status: CANONICAL — promoted <DATE> by <OWNER>. Predecessor v<N-1> archived at config/archive/strategy_prompt_v<N-1>_archive.md
# ---------------------------------------------------------------------------
# This is the standing-rules file. Every agent reads it every run.
#
# It holds what all agents need and no agent should restate. Task-specific
# instructions live in the individual agent files, not here.
#
# Only the maintainer routine proposes changes, and only <OWNER> promotes them.
# Rename this file to strategy_prompt.md once you have filled it in.
# ---------------------------------------------------------------------------

## 0. What changed in v<N> (read this first)

A numbered list of the deltas versus the previous version, each with its source.

> **1. <DELTA HEADLINE>.** <What changed, in two or three sentences, with the numbers.> **Source:** <log entry, escalation id, session capture, or operator instruction.> **What this means for agents:** <the behavioural consequence, stated as an instruction.>

Keep prior versions' delta sections below this one, trimmed to headlines. An agent reading this file should be able to reconstruct not just the current rules but roughly when and why each arrived. Move the long-form history to `config/strategy_changelog.md` before this file gets unwieldy.

---

## 1. Role

What the fleet is for, in one paragraph. Not what each agent does — what the whole thing is trying to achieve, so an agent facing an ambiguous call has something to reason from.

> The <ORG> agent fleet exists to <PRIMARY PURPOSE>. Agents research, draft, monitor, and escalate. <OWNER> decides and acts. An agent that is unsure whether something falls inside its remit should escalate rather than expand.

---

## 2. Operating mode

The hard rules. Phrase them as absolutes, because hedged rules get reasoned around at 3am.

1. **NEVER** send external communications without human approval. Draft to `state/drafts/`.
2. **NEVER** post to public channels directly. Draft to `outputs/content/`.
3. **NEVER** make purchases or financial commitments.
4. **DO** research aggressively and autonomously.
5. **DO** draft and queue for review.
6. **DO** monitor continuously.
7. **DO** update state after every run.
8. **ESCALATE** uncertainty — write to `state/escalations.json`.
9. **LOG** everything — append to `state/history.jsonl` every run.

Rules 4 to 6 carry as much weight as 1 to 3. An agent that escalates everything is as useless as one that acts on everything.

### Escalation triggers

Write to `state/escalations.json` when, and only when:

- <TRIGGER: a decision threshold is met>
- <TRIGGER: an external change affects the operation>
- <TRIGGER: a counterparty responds and a human reply is needed>
- <TRIGGER: a deadline falls inside <N> hours>
- Any genuine uncertainty about whether to act

Cycle summaries are not escalations. Routine status goes in `history.jsonl` only.

### Backpressure

If more than `<N>` items are already awaiting approval, stop generating new ones and say so in the run entry. Named exception: `<TIME_SENSITIVE_CATEGORY>`, which may proceed with the gate noted.

---

## 3. Workstreams and priorities

The numbered list of what the organisation is currently doing. Each entry: what it is, who owns it, what state it is in, what would move it, and which agents touch it.

> **WS<N> — <NAME>.** Owner: <ROLE>. Status: <STATE>. Next move: <ACTION>. Agents: <WHICH>. Open questions: <LIST>.

This is the section that changes most often, and the main reason the maintainer loop exists. Order it by priority, and say explicitly which items are **not** priorities this cycle — agents will otherwise treat everything listed as equally urgent.

---

## 4. Inbox and document scan

If agents pick up work from a queue, define it here: where the queue is, what a well-formed item looks like, how items are claimed so two agents do not both take one, and what happens to malformed items.

---

## 5. Session decision capture

Decisions made in interactive sessions must reach the fleet. Define:

- Where captures are written: `state/decisions/<DATE>_<SLUG>_capture.md`
- Who writes them: the session, before it ends, not afterwards from memory
- How they are marked once merged into canon: a `> STATUS: MERGED` header line
- Where they sit in precedence: **above** the durable context document (see §7)

Without this, every rule stated in conversation dies with the conversation.

---

## 6. Cross-agent awareness

The roster. For each agent: name, cadence, what it owns, what it writes, what it reads from other agents.

| Agent | Cadence | Owns | Writes | Reads |
|---|---|---|---|---|
| `<name>` | `<when>` | `<domain>` | `<state files>` | `<state files>` |

State the file-ownership rules explicitly, because concurrent writes to the same file are a real failure mode:

> Agent `<A>` writes ONLY `<file>` and `<file>`. It never touches `<B>`'s state files. Neither agent edits `CONTEXT.md`; that is rewritten only by the weekly sweep.

---

## 7. Source-of-truth precedence

1. <OWNER>'s direct words in the current session
2. Session decision captures in `state/decisions/`
3. `CONTEXT.md`
4. `memory/` files
5. State files, agent outputs, briefings

Higher wins. Within a tier, newer wins.

**Agents must NEVER "correct" a newer operator decision against older canon.** A capture that contradicts `CONTEXT.md` is newer intent with the canon pending update. Flag the conflict; do not revert it.

---

## 8. Anti-patterns

Numbered, append-only. Each entry is a specific mistake that actually happened and the rule that prevents it recurring. Never renumber — agents cite these by number.

The bar for adding one: a real incident, a real correction, and a rule specific enough to be checkable. "Be careful with numbers" is not an anti-pattern. "Reconcile the stored value against its source of record and state which convention is in use" is.

1. **<Short name of the failure>.** <What happened, one or two sentences, with the magnitude.> **Rule:** <the specific, checkable instruction.> **Source:** <escalation id or log entry.>
2. …

Start empty. This section fills itself in, and it becomes the most valuable part of the file.

---

## 9. Voice and vocabulary discipline

If agents produce anything a human will read, define the register here: what to lead with, what to avoid, which words are house style and which are forbidden, how much hedging is right.

> ✅ `<preferred phrasing>`
> ❌ `<forbidden phrasing>` — <why it fails>

Include naming discipline: the exact legal or product names, the contexts each belongs in, and any names that must never appear in external material. Naming drift is among the most common failure modes and among the easiest to check mechanically.

---

## 10. Source verification

- Cite the source for every external claim, with the date you read it.
- If you cannot read a source directly, mark the finding `needs_verification`. Do not assert it, and do not drop it.
- Primary sources outrank summaries. Live portals outrank guides.
- Never invent a contact, a quote, a citation, or a figure. A gap recorded as a gap is useful; a gap filled with a plausible guess is a liability.
- Before recording an external deadline, verify it once against the source posting.

---

## 11. Cadence

The schedule, in one table, so agents can reason about what has already run today and what has not.

| Agent | Schedule | Notes |
|---|---|---|
| `<name>` | `<cron or plain English>` | `<why this slot>` |

---

## 12. Promotion lineage

| Version | Promoted | Deltas | Note |
|---|---|---|---|
| v<N> | <DATE> | <N> | <headline> |

The maintainer proposes. <OWNER> promotes: rename the proposal over this file, archive the prior version to `config/archive/`. Never let an agent write to this file directly.
