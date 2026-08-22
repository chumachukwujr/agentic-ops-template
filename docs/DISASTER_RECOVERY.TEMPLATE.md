# Disaster recovery - rebuild the fleet on a new machine

<!--
  TEMPLATE. Rename to DISASTER_RECOVERY.md. Fill the table from your actual layout, then
  re-verify it whenever a repo, remote, or backup root changes. Date the verification line:
  a runbook nobody has re-read since the layout changed is worse than none, because it is
  trusted.

  The question this document answers is not "do we have backups". It is "which specific
  things exist in exactly one place, and how long does it take to put them back".
-->

Verified <DATE>. Re-verify the "Where it lives" table whenever a repo, remote or backup root changes.

## 1. Where it lives

| Thing | Path | Git remote | Off-machine backup | Notes |
|---|---|---|---|---|
| Durable layer: `agents/`, `routines/`, `config/`, `scripts/`, `docs/`, root docs | `<REPO_ROOT>/` | `<PRIVATE_REMOTE>` | `<yes/no>` | The repo is the copy. Push after every promotion. |
| Runtime state: `state/`, `outputs/`, `reports/` | `<REPO_ROOT>/state` etc. | **none, by design** (gitignored) | `<yes/no>` - **name the mechanism** | Machine-churned and commercially live. If the answer in the backup column is "no", this row is your single point of failure. |
| Canon notes | `<REPO_ROOT>/config/canon/` | same as the repo | `<yes/no>` | If your canon lives in a separate vault, give it its own row and its own remote. |
| Scheduler registrations (pointer stubs) | `<TASK_DIR>/<id>/SKILL.md` or the crontab | none | **no** | Rebuilt from `agents/REGISTRY.json` with `scripts/registry_stubs.py render`. Nothing in a stub is worth backing up. |
| Scheduler app settings | `<SETTINGS_PATH>` | none | no | List the two or three keys that matter (model, permission mode, timezone). |
| Secrets: API keys, service configs | `<SECRETS_PATH>` | **never** | `<password manager>` | If these live only on the disk, say so here and fix it in §4. |
| Secret: heartbeat ping URL | `<REPO_ROOT>/config/heartbeat_url.txt` (gitignored) | none | `<password manager>` | Also recoverable from the monitoring service's dashboard. |
| Other repos the routines touch | `<PATHS>` | `<REMOTES>` | no | Plain clones; nothing local is unique. |

Backup root, stated exactly: `<what is synced, from where, by what>`. State what is **not** backed up
just as explicitly: `<e.g. ~/.config/<scheduler>/ and the secrets directory are not>`.

## 2. What is lost if the machine dies today

Write this as a sentence, not a table, and be specific. The honest version usually reads:

> Nothing in git. Everything in `<backup>` as of the last sync. **Lost:** `<the secrets files>`, the scheduler
> registrations, and the app settings - all recreatable in under an hour with this runbook, faster once the
> secrets are in a password manager.

If any row in §1 has "no" in both the remote and backup columns and is not rebuildable, it belongs in this
paragraph by name.

## 3. Rebuild order

1. **Runtime.** Install the agent runtime and sign in. Install the interpreter and the few packages the
   scripts need: `python3 -m pip install --user pytest <others>`.
2. **Restore the durable layer.** `git clone <PRIVATE_REMOTE> <REPO_ROOT>`. Set the git identity the
   routines commit under.
3. **Restore runtime state** from the off-machine backup into `<REPO_ROOT>/state/`, `outputs/`. `git status`
   should show only ignored paths.
4. **Restore secrets** from the password manager: `<SECRETS_PATH>`, `config/heartbeat_url.txt`. Clone the
   other repos.
5. **Recreate the scheduler registrations from the registry.** Nothing is typed by hand:
   ```bash
   python3 scripts/registry_stubs.py check --task-dir <TASK_DIR>      # should list every agent as MISSING
   python3 scripts/registry_stubs.py render --task-dir <TASK_DIR>     # writes the stubs
   python3 scripts/registry_stubs.py check --task-dir <TASK_DIR>      # should print "stubs match the registry"
   ```
   For a plain cron scheduler, `python3 scripts/registry_stubs.py crontab --runner "<your runner>"` prints the
   lines. Beats are separate registrations of the same routine; the renderer handles them.
6. **Scheduler settings:** `<the keys from §1>`. The routines cannot answer interactive prompts, so the
   permission mode must let them run unattended.
7. **Verify, in this order:**
   - `python3 -m pytest scripts/tests -q` - all green.
   - Run the daily guard by hand. The heartbeat service should show a fresh ping; `state/now/state.md` should
     regenerate; `fleet_watch.py` will report every agent as missed (none has run yet) - expected on day one.
   - Run the briefing by hand. It should read the regenerated state and arrive where it normally arrives.
   - Next morning: `fleet_watch.py` should be clean.

## 4. Gaps worth closing (recommended, in order)

1. **Secrets into a password manager.** Stop relying on a single un-backed-up directory.
2. **Every canon store gets a private remote.** A sync service's version history is not a git history.
3. **Keep git directories out of file-sync tools.** They corrupt each other. Keep the repo local plus remote;
   let the sync tool hold the binaries.
4. **Test the runbook on a clean machine once.** A runbook that has never been executed is a hypothesis.
