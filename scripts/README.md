# scripts

Two generic utilities. Neither is required by the patterns in this repo; both are here because every fleet ends up needing something like them.

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
