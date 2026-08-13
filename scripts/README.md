# scripts

Four generic utilities, dependency-free.

## validate_state.py

The guard node from Pattern 7. Shape checks (files parse, required fields present, enums sane), magnitude checks (key metrics within ±25% of the stored baseline, never below a stated floor), and monotonicity checks (run counters only go up). The baseline updates only for values that passed.

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

It only ever touches top-level files in `state/` whose name contains `bak`, and it never recurses into subdirectories. Live canonical files never contain `bak` in their names, which is what makes the rule safe. Run `--dry-run` first.

State grows without bound if nothing rotates it, and the file every agent reads every run is the one you least want to be large.

## build_letterhead_pdf.py

Renders a letterhead HTML document to PDF via headless Chromium, then fixes the last-page footer.

With `table-footer-group` pagination the footer on the final page sits directly under the last line of content rather than at the page bottom, which looks broken on any document that runs to more than one page. This measures the gap on the rendered PDF, injects a spacer, and re-renders until the footer sits at the same height on every page.

```bash
FOOTER_TOKEN="yourdomain.com" python3 scripts/build_letterhead_pdf.py input.html output.pdf
```

Set `FOOTER_TOKEN` to a short string that appears in your footer; it is how the script locates the footer on each rendered page. Requires Chromium (set `CHROMIUM`) and poppler-utils for `pdftotext` and `pdfinfo`.
