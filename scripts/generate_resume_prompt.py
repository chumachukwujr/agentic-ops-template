#!/usr/bin/env python3
"""generate_resume_prompt.py - the human resume prompt, generated from canon (Pattern 11).

The resume prompt is what the operator pastes as the first message of an interactive session
that does not load the repo's context automatically (a web chat, a different tool). It used to
be a hand-maintained file that a weekly routine tried to keep in sync with the standing rules,
and it drifted anyway. Now it is GENERATED from the sources every morning by the daily guard,
so it cannot drift from canon: to change a rule, change the canon note it came from.

Sources (edit RESUME_SOURCES to fit your vault):
  CONTEXT.md                         verbatim
  config/canon/<note>.md             selected `## N.` sections, TTL-checked
  config/canon/anti-patterns.md      numbered titles only (cite by number; full text stays in canon)
  state/now/state.md                 the generated live-numbers note: selected sections
Every canon note's TTL is checked; a note past its TTL is flagged SUSPECT at the top.

Usage: python3 scripts/generate_resume_prompt.py [--dry-run] [--check]
Env overrides: AGENT_REPO_ROOT (repo root), AGENT_STATE_DIR (for state/now/state.md and the output).
"""
from __future__ import annotations
import argparse, datetime, os, re, sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import state_io as sio  # noqa: E402

# (relative path under the repo root, [section numbers to include]); [] means the whole body
RESUME_SOURCES = [
    ("config/canon/entities.md", [1]),
    ("config/canon/voice.md", [1, 3]),
    ("config/canon/citations.md", [1]),
]
ANTI_PATTERNS = "config/canon/anti-patterns.md"
STATE_SECTIONS = ["Escalations", "Fleet - registered agents and last run"]
SIZE_CAP = 40_000       # bytes; a resume prompt that needs more than this is a canon problem, not a cap problem
TITLE = "# <ORG> Operations Resume Prompt - GENERATED "


def repo_root() -> Path:
    return Path(os.path.expanduser(os.environ.get("AGENT_REPO_ROOT")
                                   or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def out_path() -> Path:
    return Path(sio.state_dir()) / "now" / "resume_prompt.md"


def _today() -> datetime.date:
    return datetime.date.today()


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _body(text: str) -> str:
    return re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.S)


def section(text: str, number: int) -> str:
    """Body of `## <number>.` up to the next `## ` heading, heading line included."""
    m = re.search(rf"^## {number}\.[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not m:
        return ""
    head = text[m.start():text.index("\n", m.start())]
    return head + "\n" + m.group(1).rstrip() + "\n"


def named_section(text: str, title: str) -> str:
    m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else ""


def ttl_flag(name: str, text: str) -> str:
    fm = sio._parse_frontmatter(text)
    try:
        lv = datetime.date.fromisoformat(str(fm.get("last_verified", "")))
        ttl = int(fm.get("ttl_days", "0"))
    except ValueError:
        return f"{name}: no TTL frontmatter (add last_verified and ttl_days)"
    due = lv + datetime.timedelta(days=ttl)
    if _today() > due:
        return f"{name}: **SUSPECT** - last_verified {lv}, TTL {ttl} d, expired {due}. Verify before acting on it."
    return f"{name}: current (last_verified {lv}, suspect after {due})"


def anti_pattern_titles(text: str) -> list:
    out = []
    for m in re.finditer(r"^(\d{1,3})\. \*\*([\s\S]+?)\*\*", _body(text), re.M):
        title = " ".join(m.group(2).split())          # bold titles may wrap onto a second line
        out.append(f"#{m.group(1)} {title.rstrip('.')}")
    return out


def build() -> str:
    root = repo_root()
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = _read(out_path().parent / "state.md")
    gen_at = re.search(r"\*\*generated_at:\*\*\s*(\S+)", state)
    L = [TITLE + now,
         "# Generator: scripts/generate_resume_prompt.py (run by the daily guard each morning).",
         "# Do not hand-edit; to change a rule, change the canon note it came from. Paste this whole file as the",
         "# first message of an interactive session that does not load the repo context by itself.", "",
         "## Canon freshness", ""]
    notes = [(p, _read(root / p)) for p, _ in RESUME_SOURCES] + [(ANTI_PATTERNS, _read(root / ANTI_PATTERNS))]
    for p, t in notes:
        L.append(f"- {ttl_flag(os.path.basename(p), t) if t else os.path.basename(p) + ': not found'}")
    L += ["", "## A. Operating context (verbatim: CONTEXT.md)", "", _read(root / "CONTEXT.md").rstrip() or "(CONTEXT.md not found)", ""]
    letter = ord("B")
    for p, secs in RESUME_SOURCES:
        t = _read(root / p)
        L += [f"## {chr(letter)}. {os.path.basename(p)}" + (f" (sections {', '.join(map(str, secs))})" if secs else ""), ""]
        if not t:
            L += [f"({p} not found)", ""]
        elif secs:
            L += [section(t, n) for n in secs]
        else:
            L += [_body(t).rstrip(), ""]
        letter += 1
    L += [f"## {chr(letter)}. Anti-patterns - cite by number; full text in {ANTI_PATTERNS}", ""]
    ap = _read(root / ANTI_PATTERNS)
    L += [f"- {t}" for t in anti_pattern_titles(ap)] or ["- (none recorded yet)"]
    letter += 1
    L += ["", f"## {chr(letter)}. Live numbers (state/now/state.md, generated_at {gen_at.group(1) if gen_at else '?'}) - the ONLY number source", ""]
    for title in STATE_SECTIONS:
        body = named_section(state, title)
        L += [f"### {title}", body if body else "(section missing from state.md)", ""]
    letter += 1
    L += [f"## {chr(letter)}. Session rules", "",
          "1. **Capture decisions when they land.** Write `state/decisions/<date>_<slug>.md` and an activity-log entry "
          "the moment the operator decides, prices, retires or approves something. Sessions that do not run on the "
          "fleet's machine never reach disk by themselves: if you do not write it, it did not happen.",
          "2. Numbers come from the Live numbers section or `state/now/state.md`, never from a document or memory.",
          "3. State writes go through `scripts/state_io.py` (ownership: `agents/REGISTRY.json`); escalations via `state_io.py escalate`.",
          "4. A canon note flagged SUSPECT above is verified before it is acted on.",
          "5. Routines and their rules: `agents/REGISTRY.json`, `routines/rules/`.", ""]
    return "\n".join(L)


def write() -> tuple:
    text = build()
    data = text.encode("utf-8")
    if len(data) > SIZE_CAP:
        raise SystemExit(f"generated prompt is {len(data):,} bytes, over the {SIZE_CAP:,} cap - trim the sources, do not ship")
    out = out_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    sio._atomic_write(str(out), text)
    return str(out), len(data)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.dry_run:
        print(build())
        return 0
    if a.check:
        strip = lambda s: "\n".join(l for l in s.splitlines() if not l.startswith(TITLE))  # noqa: E731
        same = strip(_read(out_path())) == strip(build())
        print("resume_prompt.md current" if same else "DRIFT: resume_prompt.md would change")
        return 0 if same else 1
    p, n = write()
    print(f"wrote {p} ({n:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
