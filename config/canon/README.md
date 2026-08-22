# config/canon - facts that do not change (often)

The canon tier of Pattern 11. One note per topic: entities and naming, voice, citation rules,
anti-patterns, and whatever else your fleet must never get wrong. Agents load the note they
need; nothing loads all of them.

## Frontmatter is mandatory

```yaml
---
title: <Topic>
tier: canon
last_verified: <YYYY-MM-DD>
ttl_days: <N>
owner: <who re-verifies it>
source_of_truth: <where the truth lives if not here, e.g. a registry, a contract, a filing>
---
```

`last_verified` + `ttl_days` is the freshness rule. Every reader, human or agent, checks it: a
note past its TTL is **SUSPECT**, and an agent that relies on one says so in its output rather
than acting on it silently. `scripts/generate_resume_prompt.py` prints the state of every note
at the top of the resume prompt for the same reason.

Pick TTLs by how fast the underlying fact moves, not by how often you want to be nagged. Legal
entity facts: long. Funding or pricing terms: 30 days. Anything quoted in external documents:
shorter than you think.

## What goes here and what does not

| Here | Not here |
|---|---|
| The legal names and which one goes on which document | Registration numbers and addresses, unless this vault is private |
| The house rule on a phrase ("say X, never Y") | The reason it was decided, at length; put a one-line source |
| The numbered anti-pattern list | Live counts, prices, dates of the next deadline: those are GENERATED (`state/now/state.md`) or routine rules |
| A citation rule per claim type | The citations themselves; they live with the documents that use them |

The test: if the line would still be true in six months without anyone touching it, it is
canon. If it would need a refresh, it belongs in a rules file with a shorter TTL or in the
generated tier.

## Files

- `_NOTE.TEMPLATE.md` - the skeleton for a new note.
- `anti-patterns.TEMPLATE.md` - the numbered, append-only incident list. Rename to
  `anti-patterns.md`; the resume-prompt generator reads the titles from it.
- `entities.md`, `voice.md`, `citations.md` - create from the template as you need them. The
  generator's `RESUME_SOURCES` list names which sections of which notes reach the resume prompt.
