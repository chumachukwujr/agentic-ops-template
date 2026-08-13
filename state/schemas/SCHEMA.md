# State files

The `state/` directory is the fleet's shared memory. Everything in it is written by agents and read by agents; none of it is hand-maintained.

The schemas here are JSON Schema (draft-07) and describe the four load-bearing files. They are documentation you can also validate against, not something the agents load at runtime.

## Create the files empty

```bash
mkdir -p state/drafts state/archive
echo '[]' > state/activity_log.json
echo '[]' > state/escalations.json
echo '{"_schema_version":"1.0","_last_updated":null,"contacts":{}}' > state/outreach_tracker.json
echo '{"_schema_version":"1.0","_last_scan":null,"_scan_number":0,"deals":[],"price_history":[]}' > state/market_state.json
: > state/history.jsonl
```

Then let the agents populate them. Do not seed with example data — an agent that reads a fabricated entry will reason from it.

---

## activity_log.json — the bus

**Shape:** JSON array, **newest first**. Agents prepend.

**Written by:** every agent, after every run. Also by interactive sessions that produce a consequential outcome — see the two-way rule in the README.

**Read by:** every agent, before every run.

This is the coordination surface. If an agent needs to know what another agent did, it learns it here.

| Field | Type | Notes |
|---|---|---|
| `timestamp` | ISO 8601 string | UTC. When the run finished. |
| `agent` | string | Stable identifier, matching the agent filename. |
| `run` | integer | Monotonic per agent. Lets a reader spot gaps. |
| `action` | string | One line. What this run did, including the verdict. |
| `details` | string | **The numbers.** Counts, prices, file paths, identifiers, message ids. Other agents reason from this field, so specifics belong here rather than in `action`. |
| `affects` | array of strings | Which agents or workstreams should care. A routing hint, not a guarantee anyone reads it. |
| `decisions` | array of strings | One or two judgment calls, as "chose X over Y because Z". |

**On `decisions`:** this is the cheapest useful thing in the whole system. It costs a sentence per run and it is the only practical way to detect behavioural drift after a model upgrade — diff the last twenty decisions against the prior baseline and see whether the same inputs still produce the same calls. Make it mandatory.

**On growth:** this file is read every run by every agent, so it must stay readable. Trim old entries to `state/archive/` on a schedule and let `history.jsonl` carry the complete record.

---

## escalations.json — things needing a human

**Shape:** JSON array.

**Written by:** any agent, when a trigger fires. **Read by:** the briefing agent and the operator.

| Field | Type | Notes |
|---|---|---|
| `id` | string | `ESC-<YYYY-MM-DD>-<AREA>-<NN>`. Stable, so it can be cited from a log entry. |
| `date` | date string | When raised. |
| `opened` | ISO 8601 string | Precise timestamp. |
| `agent` | string | Who raised it. |
| `run` | integer | Which run. Ties back to the log. |
| `severity` | enum | `LOW` \| `MEDIUM` \| `HIGH` \| `CRITICAL` |
| `status` | enum | `OPEN` \| `OPEN_ADVISORY` \| `RESOLVED` \| `SUPERSEDED` \| `STALE` |
| `title` | string | One line. **What decision is needed**, not what was observed. |
| `detail` | string | The numbers, the source, and what happens if this is not decided. |
| `owner` | string | Who must act. An escalation with no owner will not be actioned. |

Keep this file small. Archive anything that is not `OPEN` and is older than a couple of weeks. An escalations file with a hundred resolved entries is one the operator stops opening, and the point of the file is that it gets opened.

`OPEN_ADVISORY` is for things a human should know but need not decide. Keeping it distinct from `OPEN` is what stops the file becoming a newsfeed.

---

## outreach_tracker.json — external relationship state

**Shape:** JSON object keyed by contact identifier.

**Written by:** the agents that draft external communication. **Read by:** the same agents, plus the briefing agent.

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

## market_state.json — domain state

**Shape:** JSON object. This one is illustrative; substitute your own domain.

**Written by:** the monitoring agent. **Read by:** the monitoring agent and anything downstream of it.

| Field | Type | Notes |
|---|---|---|
| `_schema_version` | string | |
| `_last_scan` | ISO 8601 string | |
| `_scan_number` | integer | Monotonic. |
| `deals` | array | Individual observations. See the schema file. |
| `price_history` | array | One entry per scan, appended whether or not anything moved. |

**Append to `price_history` on every scan, including flat ones.** The trend is the product; individual observations are raw material. A history with gaps on quiet weeks cannot answer "how long has this been stable", which is the question that actually gets asked.

Every observation carries the date it was captured. A price without a date is not a data point.

---

## history.jsonl — the complete record

**Shape:** JSONL, one object per line, append-only. No schema file, because entries vary by agent.

**Written by:** every agent, every run, **including no-op runs**. **Read by:** the maintainer, and anyone doing forensics.

Minimum shape:

```json
{"timestamp":"<ISO>","agent":"<name>","run":0,"decisions":["..."]}
```

Agents add their own fields. The monitoring agent records scan counts; the maintainer records the version proposed; a housekeeping routine records what it rotated.

Keep this separate from `activity_log.json`. The log is for coordination and must stay short enough to read every run. The history is for forensics and is allowed to grow without bound — rotate it, compress it, but never trim it for readability. Recording a no-op run matters: an agent that ran and found nothing looks identical to an agent that did not run at all, and only this file tells them apart.
