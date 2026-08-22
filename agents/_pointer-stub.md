# Pointer stub pattern

The file your scheduler executes should not contain the prompt. It should contain a pointer to the prompt, which lives in this repo where it can be diffed, reviewed, and reverted.

Since Pattern 9, the stubs are not written by hand either. `agents/REGISTRY.json` says which routine each registration runs, on what schedule, under what identity, and with which beat; `scripts/registry_stubs.py render` writes the stubs from it. This file documents what the renderer produces and why each line is there.

## The stub

```markdown
---
name: <TASK_ID>
description: <FROM THE REGISTRY, OR PRESERVED VERBATIM FROM THE ORIGINAL TASK>
---

Read and execute the routine at <ABSOLUTE_PATH>/agents/<routine>.md with beat=<BEAT>. Follow it end-to-end. That file is authoritative; do not summarise or substitute for it.
Working directory: <ABSOLUTE_PATH>

This is a pointer stub. Edit the canonical routine, never this file.
If the routine file is unreachable, run:
  python3 <ABSOLUTE_PATH>/scripts/state_io.py escalate --agent <IDENTITY> --severity CRITICAL --title "<routine>.md unreachable" --detail "stub <TASK_ID> could not read agents/<routine>.md"
and stop without doing other work.
```

Drop `with beat=<BEAT>` for a routine that has only one registration.

Placeholders:

- `<TASK_ID>` - the scheduler's id for the task; the registry's `agents[].id`.
- `<ABSOLUTE_PATH>` - the repo root. Absolute, because the agent's working directory is whatever the scheduler decides.
- `<BEAT>` - for a routine registered more than once (Pattern 9), the value the routine branches on. Each beat is its own registration with its own id and history identity.
- `<IDENTITY>` - the registry's `history_identity` for this registration, so the failure escalation is attributed to the right agent.

## Four details that are not optional

**Preserve the frontmatter.** Schedulers key off `name` and display `description` in their UI. The renderer takes `description` from the registry; if you are converting an existing task, copy its description into the registry first so nothing changes in the UI.

**Include the failure branch.** Without it, a stub whose target is missing produces a run that does nothing and reports nothing, which is indistinguishable from a healthy quiet run. The escalation goes through `state_io.py escalate` (Pattern 8): the stub's identity is not the escalations owner, so the helper routes it over the bus and the daily guard folds it the next morning. The briefing reads both, so it surfaces either way.

**Keep the stub short.** The drift check uses length as its signal, and a stub that accumulates commentary defeats it.

**Carry the beat in the stub, not in the routine.** The routine file is shared; the stub is the only thing that knows which registration fired.

## Migrating an existing fleet

1. **Back up the whole scheduled-task directory first.** `cp -R <TASK_DIR> <BACKUP>_$(date +%Y%m%d)`. This is your rollback.
2. **Write the registry** from what is actually registered: every task's id, cron, enabled flag, and the identity it logs under. `scripts/registry_stubs.py list` shows what you wrote.
3. **Diff live against your repo copies before overwriting anything.** If you have been keeping mirrors, expect drift in both directions. Resolve per file. Do not assume one side wins globally; that is how you delete work.
4. **Render one low-stakes task first.** Trigger it manually and confirm from the run output that it read the canonical file and did the work. Only then render the rest.
5. **Verify the whole fleet** with the check below. It should print `stubs match the registry`.

Step 3 is where the real risk sits. A bidirectional diff takes minutes; a global overwrite silently discards whichever side you did not favour.

## The drift check

Editing a task through the scheduler UI overwrites the stub with a full prompt and re-forks the two copies. Assume it will happen. The daily guard or the weekly housekeeping runs:

```bash
python3 scripts/registry_stubs.py check --task-dir <TASK_DIR>
```

It reports `MISSING` (registered but no stub), `DRIFT` (a stub that grew, or points at the wrong routine or beat), and `UNKNOWN` (scheduled but not in the registry). A healthy fleet prints one line.

**When it prints DRIFT, do not auto-re-stub.** The full prompt in the live file is somebody's real edit and is the only copy of it. `render` refuses to overwrite it for that reason. Diff it against the canonical, raise an escalation naming the task and summarising what the live file has that the canonical does not, and let a human decide what merges back. Re-render with `--force` only after that review. Automatic repair here destroys work, which is a worse failure than the drift it fixes.
