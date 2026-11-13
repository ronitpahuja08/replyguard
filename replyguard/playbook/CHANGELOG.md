# ReplyGuard playbook: changelog

Every change gets a version, a date, what changed, and the result or evidence that triggered it ([S2 §9]). A released version is never edited in place: add a new version instead. Changes happen one variable at a time, and only on a trigger (a human relabelling a reply, a missed opt-out, a KPI miss, a complaint).

## v1.2 · 10 Nov 2026 · owner decisions: no time promises; reply hours

**Trigger.** Owner review of the WhatsApp dry run (10 Nov 2026): drafts said "will come back to you today".

- **CM-049 (new, locked): no time promises.** Automated drafts never promise "today", "tonight", a time or a weekday; they say "shortly" or "during working hours". Only a human who has committed to a time names one. The holding lines (`handover.holding_line_en/ar`) and the meeting holding line changed accordingly, and the draft-text check refuses any such promise in English or Arabic.
- **Reply hours (owner decision G8):** replies to people who wrote to us first are scheduled inside the UAE pack's reply window, every day 09:00–21:00 Dubai time. First messages and follow-ups keep their hours; STOP is processed at intake at any hour.
- Examples: the playbook's and example 08's holding lines no longer name a person from earlier examples ("Ali"); the neutral test sender "Sam" is used.

## v1.0 · 10 Nov 2026 · research sprint

**Trigger.** Revised build plan of 10 Nov 2026 ([S4]): the ReplyGuard moved to Day 4 and needs a cited knowledge base before the build.

**Added**
- `PLAYBOOK.md`: 48 rules, CM-001 to CM-048, in five sections (intake and classification; truthfulness, safety and escalation; speed, form and channel rules; follow-ups, states and the stop rule; meetings, data, accounts and decisions) + the per-message output schema. 31 locked (fully or in part), 17 default.
- `SOURCES.md`: S1–S28 (17 primary, 5 partial, 5 secondary, 1 not verified).
- `defaults.yaml`: labels and precedence, opt-out union and phrase lists, auto-reply headers and timings, confidence threshold, handover list, truthfulness templates, pacing, follow-up cadence, stop rule, meetings, KPIs; each commented with its rule id; locked keys marked LOCKED.
- `examples/`: 10 good, 8 bad.
- `testset/`: 53 labelled cases (cm-tc-001 to cm-tc-053): 52 single replies + 1 follow-up schedule; English, Arabic, Gulf Arabic, mixed, Arabizi and French; 32 WhatsApp, 21 email; 9 where the code detector and the true intent disagree. `rubric.yaml` (30 hard checks R01–R30, 4 classification metrics, 5 judge criteria), `pass.yaml` (hard checks 100%, safety recall 1.0, label accuracy ≥ 0.90, judge mean ≥ 4.0).

**Locked rules match the existing hard guardrails** ([S2 §3], [S3 C], code in [S5]): STOP on every channel and account at once (CM-004, CM-011, CM-012); suppression never reversed by the agent (CM-006); complaints and blocks rest accounts via signals (CM-010, CM-044); the company reply-lock (CM-014); truthful automation disclosure and never negotiate, pay, book or visit (CM-016–CM-018, CM-027); evidence only, no HBR figures (CM-030, A3); the escalation list (CM-028); gates and allowed hours on every reply (CM-035); WhatsApp two-unanswered cap and Cloud API window (CM-036); banned accounts' threads never continued (CM-045); proposals for departures (CM-046).

### Open points for a human or the builder (not decided here)
1. **Opt-out confirmation vs Gate 2.** The SOP says "Removal confirmed in one line", but `orchestrator/gates/dnc.py` blocks every message to a suppressed person. CM-013 sends nothing unless the gates support a confirmation-only message. Decide whether to add a narrow, tested exemption (one line, no links, within 24 h of the opt-out, once).
2. **Auto-replies move the lead to `replied` in code.** `orchestrator/inbound.py` locks the company and transitions to `replied` on any non-opt-out inbound, including out-of-office mail. CM-008 releases the lock with a logged reason; the state transition should be skipped for `auto_reply` (and for messages with `Auto-Submitted` ≠ `no`) so reply rates are not inflated.
3. **Detector gaps found on 10 Nov 2026** (`domain/optout.detect_inbound_opt_out`; cases in `testset/`): misses "Please remove my number from your list", "احذف رقمي", "شيلوا رقمي", "Stop. Who is this?", "This is spam. Reported."; fires on "الشغل عندنا ما توقف…" ("our work never stopped"). CM-004 (union with the classifier) covers the misses; CM-006 covers the false positive. Adding the missed forms to the detector is a code change outside this folder.
4. **Written complaints on WhatsApp do not count toward the WhatsApp triggers.** `account_health.whatsapp_triggers` counts `block` and `report` only; a written "this is spam" recorded as `complaint` (CM-010) does not throttle the number. Decide whether it should.
5. **Proactive automation disclosure for EU recipients.** EU AI Act Art. 50 applies from 2 Aug 2026 [S22][S23]. Our UAE-only campaigns disclose when asked (owner rule). A campaign reaching people in the EU would need a disclosure at the first interaction; add it to that country's compliance pack before such a campaign.
6. **Gulf Arabic phrase lists** (`opt_out.extra_phrases.ar_gulf`, `labels` hints) are ours and unreviewed (B4). A native review is recommended before volume.
7. **Holiday calendar for "after Eid".** CM-022 needs a configured holiday calendar (Eid dates move with the lunar calendar). Until one exists, "after Eid" replies get "when suits you?" and a human sets the date.
8. **SOP "two times offered directly"** is treated as a human action (CM-027) because it commits a person's calendar (owner rule: agents never book).
9. **Agents page.** `services/agent_catalog.py` has no `DISPLAY_NAMES`/`ORDER` entry for `replyguard`, so `tests/web/test_research_pages.py::test_agents_page_lists_agents_with_source_counts` fails now that this folder exists (the page falls back to the title-cased name; the test expects the mapping). One line each; outside this folder.

## v1.1 · 10 Nov 2026 · build (ReplyGuard code)

**Trigger.** The ReplyGuard was built against v1.0; open points 2, 3 and 9 were closed in code, which changes what the detector returns on eight test-set replies. Rules and defaults are unchanged.

**Changed (code outside this folder)**
- Open point 3 closed: `domain/optout.detect_inbound_opt_out` now catches "Please remove my number from your list", "احذف رقمي", "شيلوا رقمي", "Stop. Who is this?", "This is spam. Reported.", "Pls stop, ما ابي رسايل" (and "I will report this number"), and no longer fires on a negated "توقف" ("الشغل عندنا ما توقف…").
- Open point 2 closed: `orchestrator/inbound.py` no longer locks the company or moves the lead to `replied` for an automatic message (email autoresponder headers; on chat channels timing + boilerplate, CM-009). A human opt-out now also locks the company (any human reply, CM-014).
- Open point 9 closed: `services/agent_catalog.py` lists `replyguard`.

**Test set (labels unchanged; `detector_opt_out` follows the detector)**
- cm-tc-005, 006, 007, 009, 038, 041, 053: `detector_opt_out` false → true (the gaps are fixed; the classifier still labels them, CM-004).
- cm-tc-014: the detector no longer fires on this text, so the case now gives the agent the verdict recorded at intake (`input.detector_opt_out: true`, the v1.0 detector's hit) and still tests CM-006: an intake hit stays suppressed and goes to a human, whatever the classifier says. In production the agent reads the intake verdict stored on the message, never a re-run of a newer detector.

**Still open:** 1 (opt-out confirmation vs Gate 2: nothing is sent; no exemption added), 4 (written WhatsApp complaints are recorded as `complaint` signals by the agent; `account_health.whatsapp_triggers` still counts only block/report), 5, 6, 7, 8.
