---
title: Anti-patterns
tier: canon
last_verified: <YYYY-MM-DD>
ttl_days: 365
owner: <OWNER>
source_of_truth: this file
---

# Anti-patterns

<!--
  Rename to anti-patterns.md. Numbered, append-only. Never renumber: agents cite these by
  number ("held this draft under #4") and a renumbered list breaks every citation in the log.

  The bar for adding one: a real incident, a real correction, and a rule specific enough to be
  checkable. "Be careful with numbers" is not an anti-pattern. "Reconcile the stored value
  against its source of record and state which convention is in use" is.

  Format, one entry:
    N. **Short name of the failure.** What happened, one or two sentences, with the magnitude.
       **Rule:** the specific, checkable instruction. **Source:** escalation id, log entry, or
       session capture, with the date.

  scripts/generate_resume_prompt.py lifts the bold titles (and only the titles) into the resume
  prompt, so keep the title a complete thought: the reader may only ever see that line.

  Start empty. This is the one file in the repo that only gets more valuable.
-->

1. **<Short name of the failure>.** <What happened, with the magnitude.> **Rule:** <the checkable instruction.> **Source:** <id, date.>
