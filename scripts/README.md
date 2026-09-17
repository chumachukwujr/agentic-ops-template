# scripts

Nine generic utilities, dependency-free (standard library only; Python 3.9+). Tests:

```bash
python3 -m pytest scripts/tests -q
```

Every script that touches `state/` takes `AGENT_STATE_DIR`; the ones that read the registry take `AGENT_REGISTRY`. Defaults are `<repo>/state` and `<repo>/agents/REGISTRY.json`.

## state_io.py

The single-writer helper from Pattern 8. The only code path that writes state. Refuses a caller that is not the registered owner (exit 2, `REFUSED:`), writes atomically (temp file in the same directory, then rename, under an advisory lock in `state/.locks/`), records every whole-file write in `state/_writes.jsonl`, stamps append-only entries with the clock and demotes any caller-supplied timestamp to `reported_timestamp`, derives run numbers from the history, and requires a `decisions` field on every run log. Also the message bus (`send` / `inbox` / `ack`), escalation routing (`escalate` by a non-owner goes over the bus; `fold-escalations` by the owner lands them), and decision-note delivery (`decisions` / `deliver`).

```bash
python3 scripts/state_io.py owners
python3 scripts/state_io.py write market_state.json --agent intel --from-file /tmp/ms.json
python3 scripts/state_io.py append activity_log.jsonl --agent intel --json '{"action":"...","details":"...","affects":["briefing"]}'
python3 scripts/state_io.py log-run --agent intel --json '{"summary":"...","decisions":["chose X over Y because Z"]}'
python3 scripts/state_io.py escalate --agent intel --severity HIGH --title "..." --detail "..." --run 12
python3 scripts/state_io.py send --from intel --to outreach --subject "..." --body "..."
python3 scripts/state_io.py inbox --agent outreach
```

## registry_stubs.py

Pattern 9. The scheduler stubs are a view of `agents/REGISTRY.json`. `list` prints the roster; `render --task-dir DIR` writes `<DIR>/<id>/SKILL.md` pointer stubs (and refuses to overwrite one that has grown into a real prompt, unless `--force`); `check --task-dir DIR` is the registry-aware drift check (`MISSING` / `DRIFT` / `UNKNOWN`, exit 1 on findings); `crontab --runner CMD` prints crontab lines for a plain cron scheduler.

```bash
python3 scripts/registry_stubs.py render --task-dir ~/.your-scheduler/tasks
python3 scripts/registry_stubs.py check  --task-dir ~/.your-scheduler/tasks
```

## fleet_watch.py

Pattern 10, the local half. Reads the registry's crons and identities, `history.jsonl`, `agent_messages.jsonl`, and `state/decisions/`. Reports `missed_runs` (an enabled agent with no run since its second-last expected fire; one miss is tolerated), `unacked_messages` (older than `--stale-hours`, default 48), and `undelivered_decisions`. JSON on stdout; exit 1 if any finding. The daily guard escalates each class with a stable id.

```bash
python3 scripts/fleet_watch.py
python3 scripts/fleet_watch.py --now 2026-01-15T12:00:00Z --grace-hours 3
```

## heartbeat.sh

Pattern 10, the external half. Pings the dead-man's-switch URL in `config/heartbeat_url.txt` (gitignored). Exit 0 when unconfigured, so the guard never fails on it. `--fail` hits the `/fail` endpoint; `--status` prints whether it is configured without pinging.

```bash
bash scripts/heartbeat.sh
```

## generate_now_state.py

Pattern 11, the live-numbers note. Writes `state/now/state.md` from the state files: open escalations by severity, one row per registered agent with its last run, unacked bus messages, and how long since a human decision was written back. Add your domain metrics in `domain_blocks()`. `--dry-run` prints; `--check` exits 1 if the file would change.

## generate_resume_prompt.py

Pattern 11, the human resume prompt. Writes `state/now/resume_prompt.md` from `CONTEXT.md`, selected sections of the canon notes (edit `RESUME_SOURCES`; a lettered subsection such as `"3a"` is listed by name, and one you left out is named in the freshness block), the anti-pattern titles, and two sections of the live-numbers note. Every canon note's TTL is checked and a note past its TTL is flagged SUSPECT at the top. Refuses to write past a size cap. `--dry-run`, `--check`.

## validate_state.py

The guard node from Pattern 7. Shape checks (files parse, required fields present, enums sane), magnitude checks (key metrics within ±25% of the stored baseline, never below a stated floor), monotonicity checks (run counters only go up), and write-back enforcement. The baseline updates only for values that passed.

```bash
AGENT_STATE_DIR=/path/to/state python3 scripts/validate_state.py
```

Exit 1 with `FINDING:` lines means escalate, not auto-fix. Rename the two `platform_*_state.json` references to your own state files.

## audit_chain.py

Tamper-evident SHA-256 hash chain over the decision log (Pattern 7). `seal` is idempotent; `verify` recomputes from genesis; `verify --check-log` also confirms sealed entries still exist in the live log. See `GOVERNANCE.md` for what this does and does not prove.

```bash
AGENT_STATE_DIR=/path/to/state python3 scripts/audit_chain.py seal
AGENT_STATE_DIR=/path/to/state python3 scripts/audit_chain.py verify --check-log
```

## rotate_state.py

Tiered, compressed rotation of `state/` backup files. Loose backups older than 7 days are zipped weekly, weekly zips are bundled monthly, monthly zips are bundled yearly.

```bash
AGENT_STATE_DIR=/path/to/state python3 scripts/rotate_state.py --dry-run
```

It only ever touches top-level files in `state/` whose name contains `bak`, and it never recurses into subdirectories. Once Pattern 8 is in place there are no new `bak` files for it to find; it stays for the backlog and for any state you keep outside the helper.

## build_letterhead_pdf.py

Renders a letterhead HTML document to PDF via headless Chromium, then fixes the last-page footer.

With `table-footer-group` pagination the footer on the final page sits directly under the last line of content rather than at the page bottom, which looks broken on any document that runs to more than one page. This measures the gap on the rendered PDF, injects a spacer, and re-renders until the footer sits at the same height on every page.

```bash
FOOTER_TOKEN="yourdomain.com" python3 scripts/build_letterhead_pdf.py input.html output.pdf
```

Set `FOOTER_TOKEN` to a short string that appears in your footer; it is how the script locates the footer on each rendered page. Requires Chromium (set `CHROMIUM`) and poppler-utils for `pdftotext` and `pdfinfo`.

## A seam to know about

`validate_state.py` and `audit_chain.py` predate Pattern 8 and read the bus as a JSON array (`activity_log.json`). The helper's registry template registers the append-only form (`activity_log.jsonl`). Each script loads the log in one place; point it at the JSONL when you move the bus. `generate_now_state.py` reads either.
