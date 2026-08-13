# Pointer stub pattern

The file your scheduler executes should not contain the prompt. It should contain a pointer to the prompt, which lives in this repo where it can be diffed, reviewed, and reverted.

## The stub

Replace the entire body of the live scheduled-task file with this, keeping its frontmatter:

```markdown
---
name: <TASK_ID>
description: <PRESERVED VERBATIM FROM THE ORIGINAL TASK>
---

This agent's canonical prompt lives at `<ABSOLUTE_PATH>/agents/<TASK_ID>.md`. Read that file now and execute it as your complete instructions for this run. If the file is unreachable, write a CRITICAL escalation to `<ABSOLUTE_PATH>/state/escalations.json` describing the failure and stop without doing other work.
```

Two placeholders:

- `<TASK_ID>` — the scheduler's id for the task. Use it as the agent filename too, so the mapping needs no lookup table.
- `<ABSOLUTE_PATH>` — the repo root. Absolute, because the agent's working directory is whatever the scheduler decides.

## Three details that are not optional

**Preserve the frontmatter verbatim.** Schedulers key off `name` and display `description` in their UI. Copy both out of the original file byte-for-byte before overwriting. Verify afterwards:

```bash
diff <(grep -m1 '^description: ' <BACKUP>/<TASK_ID>/SKILL.md) \
     <(grep -m1 '^description: ' <TASK_DIR>/<TASK_ID>/SKILL.md)
```

**Include the failure branch.** Without it, a stub whose target is missing produces a run that does nothing and reports nothing, which is indistinguishable from a healthy quiet run. You will not notice for weeks. The escalation is the difference between a loud failure and a silent one.

**Keep the stub short.** Six lines. The drift check below uses length as its signal, and a stub that accumulates commentary defeats it.

## Migrating an existing fleet

1. **Back up the whole scheduled-task directory first.** `cp -R <TASK_DIR> <BACKUP>_$(date +%Y%m%d)`. This is your rollback.
2. **Diff live against your repo copies before overwriting anything.** If you have been keeping mirrors, expect drift in both directions: some tasks will have live edits your repo never saw, others will have repo edits that never reached the scheduler. Resolve per file. Do not assume one side wins globally — that is how you delete work.
3. **Convert one low-stakes task first.** Trigger it manually and confirm from the run output that it actually read the canonical file and did the work. Only then convert the rest.
4. **Verify the whole fleet** with the drift check below. It should print nothing.

Step 2 is where the real risk sits. A bidirectional diff takes minutes; a global overwrite silently discards whichever side you did not favour.

## The drift check

Editing a task through the scheduler UI overwrites the stub with a full prompt and re-forks the two copies. Assume it will happen. Run this weekly:

```bash
cd <TASK_DIR>
for d in */; do
  id="${d%/}"; f="$id/SKILL.md"
  [ -f "$f" ] || continue
  n=$(wc -l < "$f" | tr -d ' ')
  if [ "$n" -gt 10 ] || ! grep -q "agents/$id.md" "$f"; then
    echo "DRIFT: $id ($n lines)"
  fi
done
```

A healthy fleet prints nothing.

**When it prints something, do not auto-re-stub.** The full prompt in the live file is somebody's real edit and is the only copy of it. Diff it against the canonical, raise an escalation naming the task and summarising what the live file has that the canonical does not, and let a human decide what merges back. Re-stub only after that review. Automatic repair here destroys work, which is a worse failure than the drift it fixes.
