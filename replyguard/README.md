# ReplyGuard: ReplyGuard (knowledge base)

This folder is the ReplyGuard's training material from the 10 Nov 2026 research sprint: a cited playbook, defaults, worked examples and a labelled test set. Code (`agent.py`, `__init__.py`) is added by the builder. The rules are written against the code that already handles replies: `orchestrator/inbound.py` (detector → suppression; company lock), `domain/optout.py`, `compliance/uae.py`, `orchestrator/gates/dnc.py`, `domain/lead_states.py`, `domain/suppression.py`, `orchestrator/account_health.py` (`record_account_signal`) and `services/erasure.py`.

```
replyguard/
├── defaults.yaml              labels and precedence, opt-out union + phrase lists, auto-reply headers and timings,
│                              confidence threshold, handover list, disclosure templates, pacing, follow-ups,
│                              stop rule, meetings, KPIs; each commented with its rule id; LOCKED keys marked
├── playbook/
│   ├── PLAYBOOK.md            v1.0: 48 rules CM-001 to CM-048 (31 locked, 17 default) + the output schema
│   ├── SOURCES.md             S1 to S28 (17 primary, 5 partial, 5 secondary, 1 not verified), accessed 10 Nov 2026
│   └── CHANGELOG.md           versions, plus 9 open points for a human or the builder
├── examples/
│   ├── good/*.yaml            10 good examples (STOP, Gulf opt-out, bot question, objection, referral, OOO, pricing …)
│   └── bad/*.yaml             8 bad examples (output_given vs output_expected)
└── testset/
    ├── cases/*.yaml           53 labelled cases (English, Arabic, Gulf, mixed, Arabizi, French; WhatsApp and email)
    ├── rubric.yaml            30 hard checks (R01 to R30), 4 classification metrics, 5 judge criteria with anchors
    └── pass.yaml              hard checks 100%, safety recall 1.0, label accuracy >= 0.90, judge mean >= 4.0
```

## The model in one screen
- **Labels (CM-002):** opt_out, complaint, bot_question, meeting_request, positive, question, objection, referral, wrong_person, not_now, not_interested, auto_reply, unclear. Safety labels win (CM-003).
- **Opt-out = detector OR classifier (locked, CM-004).** The classifier adds what the keyword detector misses ("please remove my number", "احذف رقمي", "شيلوا رقمي", "Stop. Who is this?"); it never clears a detector hit. A detector false positive ("الشغل ما توقف") stays suppressed and goes to a human (CM-006). Meaning over keywords: "stop by our showroom" and "remove the price column" are not opt-outs (CM-005).
- **On an opt-out:** suppressed on every channel at once, any hour; `do_not_contact`; jobs cancelled; "us" covers the company (CM-011, CM-012). One confirmation line only if the gates allow it (CM-013; Gate 2 blocks it today).
- **Complaint:** opt-out + `record_account_signal(complaint/report/block)` + human; no automated reply (CM-010, CM-044).
- **"Are you a bot?":** a plain, truthful yes naming the sender, then a human (CM-016). Never claim to be human (CM-017).
- **Never negotiate, pay, book or visit (CM-018, CM-027):** the self-service booking link only (none until Day 5 → human); no times, no visits, no WhatsApp calls.
- **Handover list (CM-028):** pricing, negotiation, legal/regulator, personal-data requests, complaint, bot question, visit, meeting without a link, disputed finding, outside evidence, report change, possible false opt-out, sarcasm, low confidence (< 0.80), unsupported language or media, banned-account thread, stop rule.
- **Company lock (CM-014):** any human reply pauses everyone at the company; only the replier's thread continues. Auto-replies release it with a logged reason (CM-008).
- **Auto-replies (CM-007, CM-009):** `Auto-Submitted` ≠ `no` and friends; never answered; not a reply for the KPI; WhatsApp away messages need timing + boilerplate (short human "ok" is human).
- **Replies by label:** yes → jab 2; question → two lines from the record, then jab 2; objection → label + one calibrated question; later → "when suits you?" + date → Warm; referral → thanks + Contact Finder, jab 1 only when verified; no → thanks + one optional why → Lost.
- **Speed and form:** as fast as possible, median < 15 working minutes (KPI, no speed figures in messages); chat delay 60–240 s; every draft through the 8 gates and allowed hours; < 60/80 words, one question, opt-out line.
- **WhatsApp:** two-unanswered cap; Cloud API free-form only inside 24 h (CM-036).
- **Follow-ups:** nudges on days 2, 5, 10, then Warm + 30-day check-in; Cold/Warm/Lost/DNC per the SOP table; stop rule after 3 automated replies without progress (CM-038 to CM-040).

## Test-case schema (`testset/cases/cm-tc-NNN.yaml`)
```yaml
id: cm-tc-NNN
title: what is being tested
tags: [whatsapp|email, en|ar|ar_gulf|mixed|arabizi|fr, opt_out|complaint|bot_question|..., tricky|detector_gap|detector_false_positive|locked, ...]
rules: [CM-0xx]
input:
  now: ISO-8601 (+04:00)
  channel: whatsapp|email
  campaign: {options: {arabic_auto_send, whatsapp_cold_first_touch}, booking_link: null|url}
  sender: {name, company, account}
  lead: {state, wave, is_company_contact}
  thread: [{dir: out|in, at, text, kind?: jab_1|jab_2}]
  reply: {at, text, headers?: {...}, seconds_after_our_last?: int, media?: voice_note}
  company?: {other_leads: [{id, state, next_job}]}     # company-lock cases
  account_status?: {<account>: banned}
  event?: no_reply_after_jab_2                          # follow-up schedule case
expect:
  label: <label>|null
  also: [labels]
  detector_opt_out: bool              # what domain/optout.detect_inbound_opt_out returns today (verified 10 Nov 2026)
  suppress: none|person|company
  erase?: bool
  lead_state_after?: replied|warm|lost|do_not_contact|unchanged
  account_signals?: [complaint|report|block]
  company_lock?: kept|released_auto_reply
  handover: false | {reasons: [..], attach?: [..]}
  reply: none|confirmation_only|bot_disclosure|holding_line|jab_2|two_line_answer_then_jab_2|label_then_calibrated_question|thanks|thanks_optional_why|when_suits_you|confirm_date|booking_link
  reply_language?: en|ar
  must_include? / must_not_include?: [strings]
  followup? / followup_plan?: dates (allowed hours applied)
  route_to?: [contact_finder|buyer_mapper]
  # plus case-specific fields: counts_as_reply, messages_to_new_person_before_verified, cancelled_jobs,
  # calendar_events_created, send_not_before, other_person, suppression_lifted, max_questions, ...
```
Examples use looser fields with `why: [rule ids]` and an `explanation`. All people, companies, addresses (`.example` domains) and numbers are **fictional**.

## Status
- Research complete for the Day-4 build. What could not be verified is in `playbook/SOURCES.md` under "Not found or not verified" (no peer-reviewed speed-to-lead study; Gulf Arabic phrases are ours and unreviewed; official law texts not reachable).
- Open points for a human or the builder: `playbook/CHANGELOG.md` (opt-out confirmation vs Gate 2; auto-replies moved to `replied` in code; detector gaps; WhatsApp written complaints not counted by the health triggers; EU disclosure; holiday calendar; agents-page catalog entry).
- Thresholds and timings marked "ours" in `defaults.yaml` are starting values, not researched numbers.

## Code (built 10 Nov 2026, playbook v1.1)
- `orchestrator/inbound.py` (intake, no model): detector opt-out → suppressed everywhere + Do-not-contact + jobs cancelled; automatic messages (email autoresponder headers; chat: within 10 s + boilerplate) → no company lock, no Replied; any other reply → company lock + Replied. Every new inbound message gets one `agent.replyguard` job (`agent.replyguard:<message id>`).
- `agent.py`: acceptance check → `signals.py` (detector floor, auto-reply signals, language, keyword hints) → classifier (LLM; unavailable → rules-only reading, confidence 0, a human) → `decide.py` (the locked rules as code) → `replies.py` (templates or LLM draft + self-check, one rewrite) → the decision + handover task. `followups.py` handles the follow-up events (nudges under the WhatsApp cap, Warm, check-ins).
- `effects.py` (after-run hook, the only writer): suppression / erasure / account signals / lock release / referrals to the Contact Finder / the reply as an approved `Message` + `message.send` job (all gates, outbox) / follow-up jobs / handover alerts / `conversation.classified` KPI event / `HandoverCheck`. `conversation.finalize_state` moves a lead to Lost only after its thanks left.
- `checks.py` (R01–R30), `kpis.py` (M1–M4, live KPIs), `record.py` (live record loader), `fakes.py` (demo/e2e stand-in model; not an eval).
- Eval: `paralax eval replyguard`. Live jobs need a passing eval for the configured model (none without `OPENAI_API_KEY`).
