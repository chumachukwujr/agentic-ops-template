# Governance: what this system records, what that proves, and what you may claim

The audit layer in this template — the decision log, the escalation record, and the hash chain — exists to make an agent fleet *auditable*: every consequential action traceable to an agent, a run, a timestamp, and a stated reason, with tamper-evidence over the whole history.

This document maps that to the compliance frameworks operators most often face, and draws a hard line around the claims the tooling does and does not support. The line matters: an overclaim about compliance is itself a compliance failure, and a sophisticated buyer who catches one will discount everything else you say.

---

## What the system records

| Record | File | What it captures |
|---|---|---|
| Decision log | `state/activity_log.json` | Every run: what was done, the specifics, and 1-2 judgment calls in "chose X over Y because Z" form |
| Complete run history | `state/history.jsonl` | Every run including no-ops, append-only |
| Escalations | `state/escalations.json` | Every item referred to a human: severity, owner, resolution |
| Human approvals | Escalation status transitions + the two-way bus | Which human decided, and when the decision re-entered the system |
| Standing rules over time | `config/strategy_prompt.md` + `config/archive/` | Which rules were in force at any date, and when each changed |
| Incident record | The anti-patterns section | Each failure, its correction, and the rule that prevents recurrence |
| Tamper-evidence | `state/audit_chain.jsonl` | SHA-256 hash chain over the decision log; `verify` proves integrity |

Two properties an auditor will care about:

- **Human-in-the-loop is structural, not asserted.** Under the escalate-don't-act pattern, external actions require a human send. The record of that gate is the escalation file plus the drafts directory, not a policy PDF.
- **Integrity is checkable by a third party.** `python3 scripts/audit_chain.py verify` recomputes the chain from genesis. No trust in the operator required for the *integrity* claim.

## What the chain does and does not prove

`audit_chain.py` proves that sealed history has not been mutated, deleted from, or reordered since sealing. It does **not** prove:

- that an entry was *true* when written (source-citation rules handle that, upstream);
- that *all* activity was logged (an agent that never wrote to the log is invisible to the chain);
- anything about the period before sealing began.

Seal frequently (the weekly routine at minimum; a daily cron is better) so the window between event and seal stays small. State the sealing cadence in your own governance doc.

---

## Framework mapping

The honest verb throughout is **supports**. The tooling produces records and evidence that these frameworks require or that their audits ask for. It does not make anything "compliant" — compliance attaches to an organisation and its practices, assessed as a whole, usually by a third party.

### United States

**SOC 2 (AICPA Trust Services Criteria).** SOC 2 is an attestation over your organisation's controls, audited by a CPA firm — a *report*, not a feature. What this tooling contributes is evidence: the decision log and escalation record map to monitoring and change-management evidence requests (CC7.x monitoring activities, CC8.1 change management), the standing-rules archive shows control evolution with dates, and the hash chain supports the completeness and integrity of that evidence. If a vendor tells you their product "is SOC 2 compliant" as a property of the software itself, they are compressing "would be useful evidence in a SOC 2 audit" into a claim the framework does not define.

**FedRAMP.** A US federal cloud authorization with hundreds of controls (NIST SP 800-53), a sponsoring agency, and a continuous-monitoring regime. No file convention contributes meaningfully until you are pursuing an authorization package, at which point the audit log maps to the AU control family. Do not name FedRAMP in marketing unless federal deployment is a real, resourced path.

**EU AI Act (for US operators too).** If your agents' outputs reach EU users, note the Act's extraterritorial reach; see below.

### European Union

**EU AI Act — record-keeping (Art. 12) and human oversight (Art. 14).** For systems classified high-risk, the Act requires automatic recording of events over the system's lifetime, sufficient to trace operation and support post-market monitoring — which is close to a description of the decision log plus the run history. Art. 14's human-oversight requirement is the escalate-don't-act pattern stated as law: a natural person able to intervene before consequential effect. Most business-ops agent fleets will not be high-risk under Annex III, but the record-keeping shape is the right target to build to regardless, because it is also what any serious enterprise buyer asks for.

**GDPR (and its record-keeping cousin, Art. 30 ROPA).** If any state file holds personal data, the fleet is processing it: the data-minimisation habit (keep counterparty detail out of the public-adjacent files, reference records by id), the rotation scripts (retention), and the log (processing record) all contribute. The chain adds integrity evidence for Art. 5(1)(f).

### Nigeria

**NDPA 2023 (Nigeria Data Protection Act) and the NDPC's GAID (General Application and Implementation Directive, 2025).** The NDPA imposes accountability and record-keeping duties on data controllers, with the NDPC as regulator; GAID operationalises them, including audit-return filings for controllers above thresholds. An agent fleet operating on Nigerian personal data should be able to show what was processed, by what process, on whose decision — which is the decision log's exact shape. The escalation record demonstrates the human accountability chain the NDPC's audit-return process asks controllers to evidence.

**Sector overlays.** Nigerian financial-services deployments add CBN expectations, including data-localisation requirements for certain classes of payments data — an infrastructure question (where state files and models physically live) rather than a logging one, but your governance doc should state the answer.

### South Africa

**POPIA (Protection of Personal Information Act).** POPIA's accountability condition and s17 record-keeping duty require a responsible party to maintain documentation of processing operations; the Information Regulator enforces. The same mapping applies: decision log as processing record, escalations as the accountability chain, chain verification as integrity evidence. POPIA also has an automated-decision-making provision (s71): decisions with legal effect made *solely* by automated processing are restricted — which the escalate-don't-act pattern addresses structurally, because consequential decisions are referred to a human by design. That is a genuinely strong story; tell it precisely.

---

## Claims discipline

Copy this table into your standing rules.

| ✅ May claim | ❌ May not claim |
|---|---|
| "Every agent decision is logged with a stated rationale, and the log is sealed in a tamper-evident SHA-256 hash chain; verification is a one-command check anyone can run." | "Tamper-proof." (It is tamper-*evident*. Nothing on a machine you control is tamper-proof.) |
| "Designed to support the record-keeping and human-oversight expectations of frameworks like SOC 2, the EU AI Act, NDPA, and POPIA." | "SOC 2 / FedRAMP / EU AI Act compliant." (Compliance attaches to an organisation and an assessment, not to a file format.) |
| "Consequential actions are gated on human approval by architecture, and the approval trail is part of the record." | "Fully autonomous operations." (If true, your s71 / Art. 14 story dies with it.) |
| "Audit-ready: the records an auditor asks for exist as a by-product of normal operation." | "Audit-grade" as a bare adjective with no stated verification path. |
| "The incident record is part of the system: N numbered anti-patterns, each a real failure with its correction." | Any claim that the system prevents all classes of error. The record itself shows otherwise, which is precisely why it is credible. |

One more rule, learned the expensive way: **never publish a specific compliance-adjacent number (a control count, a coverage percentage, an uptime figure) that you have not reconciled against its source of record on the day of publication.** The guard node exists because fresh numbers can still be wrong.
