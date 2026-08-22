# <ORG> — Operating Context

<!--
  TEMPLATE. Replace everything below with your own facts, then delete this comment.

  This is the highest-leverage file in the repo and the one nobody wants to write.
  Every agent reads it. Facts that live here stop being re-derived, re-guessed,
  and quietly contradicted across a dozen prompts.

  Write it as though briefing a competent new hire who will be given real
  authority tomorrow and cannot ask you questions.

  Rules for maintaining it:
    - Date every fact that could go stale.
    - When a fact changes, change it here first, then let the maintainer
      propagate the consequence into the standing rules.
    - Agents never write to this file. Only the operator and the weekly sweep.
-->

> **Last synced:** <DATE> — <one-line summary of what changed this sync.>
> **Source-of-truth note:** decisions captured in `state/decisions/` after this date **outrank** this file. See "Standing agent rules" below.

## What this is

One paragraph. What the organisation does, what it is building, and what the agent fleet is for. An agent that reads only this paragraph should be able to tell whether an arbitrary task is in scope.

## People

| Name | Role | What they own | How to refer to them externally |
|---|---|---|---|
| `<NAME>` | `<ROLE>` | `<DOMAIN>` | `<PREFERRED FRAMING>` |

Include how each person should be described in anything an outsider reads. Getting a title or a credential wrong in an external document is one of the more embarrassing and more preventable failures.

## Current stage

Where things actually stand, as of the sync date. Stage, status of the main workstreams, what shipped, what has not.

Be specific and be honest. An agent that believes something is finished will write about it as finished.

## Current priorities

The three to five things that matter this cycle, ordered, with owners.

Say explicitly what is **not** a priority right now. Without that, agents treat every item ever mentioned as live, and the ones that matter get diluted.

> *Retired this cycle: <ITEM> — <why, and where its record now lives>.*

## Canonical facts

The numbers and identifiers that must never drift. Whatever your equivalents are of key dates, version numbers, capacity figures, thresholds, current counts.

| Fact | Value | As of | Source of record |
|---|---|---|---|
| `<FACT>` | `<VALUE>` | `<DATE>` | `<FILE OR SYSTEM>` |

**The source-of-record column is the important one.** For anything that changes often, this file holds a dated snapshot and the source of record holds the truth. State that explicitly, because otherwise an agent will quote the snapshot into an external document six weeks later:

> Numbers in this file are descriptive snapshots, not current truth. Before any figure enters an external document, read it from its source of record and reconcile.

Once the GENERATED tier is running (Pattern 11), this section shrinks: counts, last-run ages, open escalations and anything else derivable from a state file come from `state/now/state.md` and are not written here at all. What stays here is the fact that cannot be generated: a threshold the operator chose, a date that was agreed, a name.

## Naming and entity discipline

The exact names, and where each belongs. Legal names, product names, the public-facing short form, and anything that must never appear in external material.

| Name | Correct usage | Never |
|---|---|---|
| `<NAME>` | `<CONTEXT>` | `<MISUSE>` |

Naming drift is common, cheap to check mechanically, and expensive when it reaches a counterparty.

## Voice

How anything a human will read should sound. Lead with what you have, not what you lack. Whatever your house rules are on register, formality, punctuation, and length — put them here, with examples.

> ✅ `<good example>`
> ❌ `<bad example>` — `<why it fails>`

## Confidentiality

What may be said, to whom, and what stays internal. Be precise about the boundary rather than blanket-restrictive, because a rule that is too broad gets ignored.

| Item | Internal | External | Trigger to relax |
|---|---|---|---|
| `<ITEM>` | `<TREATMENT>` | `<TREATMENT>` | `<EVENT>` |

Name the trigger that lifts each restriction. Restrictions with no stated end condition outlive their reason and nobody remembers why they exist.

## Standing agent rules

Anything every agent must do or never do that is not already in a canon note or a rules file. Keep this short; if it grows, it belongs in `routines/rules/<routine>.md` or `config/canon/`.

Two things belong here because every session loads this file and nothing else is guaranteed to be loaded:

**Source-of-truth precedence.** Higher wins; within a tier, newer wins.

1. `<OWNER>`'s direct words in the current session
2. Decision captures in `state/decisions/`
3. This file
4. Canon notes in `config/canon/` and rules files in `routines/rules/`
5. State files, agent outputs, briefings

Never "correct" a newer decision capture against older canon. Flag the conflict; do not revert it.

**Freshness.** Every canon note and rules file carries `last_verified` and `ttl_days`. A note past its TTL is **SUSPECT**: say so in your output rather than acting on it silently.

**State writes** go through `scripts/state_io.py`; the ownership map is `agents/REGISTRY.json`. Escalations via `state_io.py escalate`. Numbers come from `state/now/state.md`, never from a document or memory.

## Model continuity

Record which model the fleet is validated against and when:

> **Model tested:** `<MODEL>` — validated `<DATE>`.

When the active model changes, run a shadow period of 48 hours or four to six scheduled runs before retiring the prior baseline. Diff the `decisions` field in `state/history.jsonl` across the boundary. If the new model makes materially different calls on the same inputs, fix the **prompt** rather than arguing with the model at runtime — a model that has become more cautious usually needs the premise stated explicitly, which is what STEP 0 in the example agent is for.

Log what you find here, including the incidents. The record of what broke and how it was fixed is worth more than the version number.
