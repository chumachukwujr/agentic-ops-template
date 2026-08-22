# State files

The `state/` directory is the fleet's shared memory. Everything in it is written by agents and read by agents; none of it is hand-maintained, and since Pattern 8 every write goes through `scripts/state_io.py`, which enforces one owner per file. The ownership map is `agents/REGISTRY.json -> state_files`, not this document; this document says what each file is for.

The schemas here are JSON Schema (draft-07) and describe the load-bearing files. They are documentation you can also validate against, not something the agents load at runtime.

## Create the files empty

```bash
mkdir -p state/drafts state/archive state/decisions state/now
echo '[]' > state/escalations.json
echo '{"_schema_version":"1.0","_last_updated":null,"contacts":{}}' > state/outreach_tracker.json
echo '{"_schema_version":"1.0","_last_scan":null,"_scan_number":0,"deals":[],"price_history":[]}' > state/market_state.json
: > state/history.jsonl
: > state/activity_log.jsonl
: > state/agent_messages.jsonl
```

Then let the agents populate them. Do not seed with example data; an agent that reads a fabricated entry will reason from it.

---

## Ownership modes (Pattern 8)

| Mode | Who writes | How |
|---|---|---|
| `append-only` | anyone | `state_io.append_event()` - one line, clock-stamped, never rewritten |
| `single-writer` | the registered owner (or an alias from `agent_aliases`) | `state_io.write_state()` - atomic whole-file replace, recorded in `_writes.jsonl` |
| `frozen` | nobody | read only; a retired file kept for reference |

The append-only files are the only shared files. Appends do not conflict; whole-file rewrites do. Nobody rewrites an append-only file: the audit chain would break if they did.

---

## activity_log.jsonl - the bus

**Shape:** JSONL, one object per line, append-only. Newest last.

**Written by:** every agent, after every run that did something other agents should know about. Also by interactive sessions that produce a consequential outcome; see the two-way rule in the README.

**Read by:** every agent, before every run.

This is the coordination surface. If an agent needs to know what another agent did, it learns it here.

| Field | Type | Notes |
|---|---|---|
| `timestamp` | ISO 8601 string | UTC, `Z` suffix. **Stamped by the helper, never by the agent.** |
| `reported_timestamp` | string | Present only if the agent supplied a timestamp; the helper demotes it here. |
| `agent` | string | Stable identifier, matching the registry's `history_identity`. |
| `run` | integer | Monotonic per agent. Lets a reader spot gaps. |
| `action` | string | One line. What this run did, including the verdict. |
| `details` | string | **The numbers.** Counts, prices, file paths, identifiers, message ids. Other agents reason from this field, so specifics belong here rather than in `action`. |
| `affects` | array of strings | Which agents or workstreams should care. A routing hint, not a guarantee anyone reads it. |
| `decisions` | array of strings | One or two judgment calls, as "chose X over Y because Z". |

**On `decisions`:** this is the cheapest useful thing in the whole system. It costs a sentence per run and it is the only practical way to detect behavioural drift after a model upgrade. Make it mandatory.

**On the older array form:** the first version of this template used `activity_log.json`, a JSON array that agents prepended to. A prepend is a whole-file rewrite by every agent, which is exactly the contention Pattern 8 removes. `activity_log.schema.json` still describes the entry shape; it applies to each JSONL line unchanged. `validate_state.py` and `audit_chain.py` still read the array form; each loads the log in one place.

---

## history.jsonl - the complete record

**Shape:** JSONL, append-only. No schema file, because entries vary by agent.

**Written by:** every agent, every run, **including no-op runs**, through `state_io.log_run()`, which derives `run` and refuses an entry without `decisions`. **Read by:** the maintainer, the fleet watch, the live-numbers generator, and anyone doing forensics.

Minimum shape:

```json
{"timestamp":"<ISO, helper-stamped>","agent":"<history_identity>","run":0,"decisions":["..."]}
```

Keep this separate from the bus. The bus is for coordination and must stay short enough to read every run. The history is for forensics and is allowed to grow without bound; rotate it, compress it, but never trim it for readability. Recording a no-op run matters: an agent that ran and found nothing looks identical to an agent that did not run at all, and only this file tells them apart. `fleet_watch.py` depends on it.

---

## agent_messages.jsonl - the message bus

**Shape:** JSONL, append-only. Two record kinds: messages and acks.

**Written by:** any agent, through `state_io.send_message()` / `ack_message()`. **Read by:** the addressees via `state_io.inbox()`, the fleet watch, the live-numbers generator.

| Field | Type | Notes |
|---|---|---|
| `timestamp` | ISO 8601 | helper-stamped |
| `id` | string | `msg-<date>-<slug>-<hash>`; cited in acks |
| `from` | string | sender identity |
| `to` | array of strings | addressees; an alias group's canonical name reaches every beat |
| `subject`, `body` | string | |
| `priority` | string | `normal` \| `high` |
| `type` | string | optional; `escalation` has special handling (see below) |
| `payload` | object | optional structured content |

Ack records: `{"type":"ack","ack_of":"<id>","acked_by":"<agent>","acked_at":"<ISO>","disposition":"DONE|FOLDED|DECLINED","note":"..."}`. An ack by an addressee clears the message for that addressee only; an ack by anyone else (a human, a manual backfill) clears it for everyone.

This is how an agent asks the owner of a file it does not own to change it. A run that ends with unacked inbox messages is a failed run.

---

## escalations.json - things needing a human

**Shape:** JSON array. **Mode:** single-writer; the owner is the daily guard.

**Written by:** the owner only. Every other agent calls `state_io.raise_escalation()`, which sends a `type: escalation` bus message to the owner; the owner's `fold_escalations()` appends it and acks the message. The briefing reads both the file and the bus, so an escalation raised overnight is visible in the morning whether or not the fold has run.

| Field | Type | Notes |
|---|---|---|
| `id` | string | `ESC-<YYYY-MM-DD>-<AGENT>-<SLUG>`, derived unless supplied. Stable, so it can be cited and so the guard can suppress known findings by id. |
| `date` | date string | When raised. |
| `opened` | ISO 8601 string | Precise timestamp. |
| `agent` | string | Who raised it. |
| `run` | integer | Which run. Ties back to the log. |
| `severity` | enum | `LOW` \| `MEDIUM` \| `HIGH` \| `CRITICAL` |
| `status` | enum | `OPEN` \| `OPEN_ADVISORY` \| `RESOLVED` \| `SUPERSEDED` \| `STALE` |
| `title` | string | One line. **What decision is needed**, not what was observed. |
| `detail` | string | The numbers, the source, and what happens if this is not decided. |
| `owner` | string | Who must act. An escalation with no owner will not be actioned. |
| `findings` | array | optional; structured list so tomorrow's suppression is a field comparison |
| `bus_message` | string | set by the fold: the message id it came from |

Keep this file small. The owner compacts it weekly: anything not `OPEN` and older than two weeks moves to `state/archive/`. An escalations file with a hundred resolved entries is one the operator stops opening.

`OPEN_ADVISORY` is for things a human should know but need not decide. Keeping it distinct from `OPEN` is what stops the file becoming a newsfeed.

---

## _writes.jsonl - the write sidecar

**Shape:** JSONL, append-only. **Written by:** the helper, on every `write_state()`. Never by hand.

```json
{"timestamp":"<ISO>","file":"market_state.json","agent":"intel","bytes":4812}
```

Who wrote which file when. It is the answer to "which run changed this", and it is what replaced the pre-write backup copies: the restore point is the run history, not an 800 KB copy of the file.

---

## decisions/ - session captures and decision notes

**Shape:** Markdown files with frontmatter, one per decision or session. **Mode:** single-writer, owner `human`; agents touch only the `propagated_to` and `delivered` frontmatter keys, through `state_io.mark_decision_delivered()`.

```yaml
---
title: <what was decided>
date: <YYYY-MM-DD>
for_agents: [intel, outreach]      # or: true (everyone)
delivered: false
propagated_to: []
---
```

`state_io.pending_decisions(agent)` lists the notes an agent has not yet seen. `delivered: true` means *some* agent has had it; `propagated_to` is the per-agent truth. `fleet_watch.py` flags a note undelivered to any targeted agent after 48 hours. The maintainer prepends `> STATUS: MERGED ...` once the decision is reflected in canon.

---

## now/ - the GENERATED tier

**Shape:** Markdown. **Mode:** single-writer, owner the daily guard, produced by `scripts/generate_now_state.py` and `scripts/generate_resume_prompt.py`. Never hand-edited; a hand edit is overwritten the next morning.

`state/now/state.md` is the only place any fleet number is quoted from. `state/now/resume_prompt.md` is what the operator pastes into a session that does not load the repo context by itself. Both carry a `generated_at` line. Both are gitignored: they are build artifacts.

---

## outreach_tracker.json - external relationship state

**Shape:** JSON object keyed by contact identifier. **Mode:** single-writer; the owner is the outreach routine. Other agents that discover a contact send it over the bus.

| Field | Type | Notes |
|---|---|---|
| `_schema_version` | string | Bump when the shape changes. |
| `_last_updated` | ISO 8601 string | |
| `contacts` | object | Keyed by slug. |
| `contacts.<slug>.name` | string | |
| `contacts.<slug>.org` | string | |
| `contacts.<slug>.workstream` | string | Which workstream this belongs to. |
| `contacts.<slug>.status` | enum | `draft_pending_approval` \| `awaiting_approval` \| `sent` \| `replied` \| `on_hold` \| `closed` \| `exhausted` |
| `contacts.<slug>.touches` | array | Each: `{date, direction, channel, summary, reference_id}`. |
| `contacts.<slug>.next_action` | string | What happens next, and what would trigger it. |
| `contacts.<slug>.next_action_date` | date string | Null if event-triggered rather than scheduled. |

Two rules that prevent the common failures:

**`sent` is set from the record, never inferred.** An agent that marks something sent because it drafted it will report false state for weeks. Set it from the actual sent-folder or outbox record, and store the `reference_id` that proves it.

**`exhausted` is a real terminal state.** Without it, agents keep generating touch number four for contacts who have not answered three. Define the limit and let the tracker enforce it.

---

## market_state.json - domain state

**Shape:** JSON object. This one is illustrative; substitute your own domain. **Mode:** single-writer; the owner is the monitoring agent (or the intel routine's alias group, if the monitor is one of its beats).

| Field | Type | Notes |
|---|---|---|
| `_schema_version` | string | |
| `_last_scan` | ISO 8601 string | |
| `_scan_number` | integer | Monotonic. |
| `deals` | array | Individual observations. See the schema file. |
| `price_history` | array | One entry per scan, appended whether or not anything moved. |

**Append to `price_history` on every scan, including flat ones.** The trend is the product; individual observations are raw material. A history with gaps on quiet weeks cannot answer "how long has this been stable", which is the question that actually gets asked.

Every observation carries the date it was captured. A price without a date is not a data point.
