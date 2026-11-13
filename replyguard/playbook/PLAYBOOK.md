# ReplyGuard (ReplyGuard): playbook v1.2

**Job ([S1]).** Turn every reply into the right next message as fast as possible, keep following up when a replier goes quiet, decide when a lead is cold, and get interested people onto the calendar.

**Receives.** Every reply and every delivery log from Agent 10. ReplyGuard's own acceptance rule: every reply arrives with the person, the company, the message it answered and the full thread ([S1]).

**Hands over.** Booked meetings to the closer with a one-page brief, and every lead in its correct state for Agent 12 (Analyst). Acceptance rule (the closer): every meeting has a brief with the company page, the person card and the full thread ([S1]).

**KPI ([S1], [S2 §6]).** Reply-to-meeting rate (starting target: **25% of positive replies become meetings**), with our **median response time under 15 minutes** in working hours, and **80% of meetings attended**. Owner decision #12 makes speed "as fast as possible" rather than a fixed deadline, so the 15 minutes is a KPI target, not a rule that justifies a worse reply ([S2 §2 #12]).

**Scope for week 1 ([S4]).** Revised build plan, 10 Nov 2026:
- classify each reply; STOP → suppressed on every channel; complaint or block → account-health signal; any reply → company paused;
- drafts go through the same gates; escalations go to a human as tasks;
- fixed rules: it never negotiates, pays, books or visits, and if asked it says truthfully that the message is automated;
- the booking link arrives before Day 5; until then a booking request is handed to a human.

**How to read this file**
- Rule blocks follow the other playbooks: Rule, Why, Source, Check, Example, Default or locked.
  - `locked`: a hard guardrail or an owner decision, enforced in code (`orchestrator/inbound.py`, `domain/optout.py`, `orchestrator/gates/*`, `domain/suppression.py`, `orchestrator/account_health.py`). The agent can never break it or propose changing it.
  - `default`: changes only through a Gate 4 decision proposal ([S2 §3a]).
  - `Check`: `deterministic` (a code or test-set hard check, ids in backticks match `testset/rubric.yaml`), `judge` (LLM judge with the rubric), `ab_test` (settled only by live results).
- Numbers live in `../defaults.yaml`. Sources are in `SOURCES.md`. Values marked "ours" are starting values, not researched numbers.

**What the research says, in one box**
- **Speed.** The only speed-to-lead data we could read is vendor-associated: the Lead Response Management study page (InsideSales.com data with Oldroyd; 15,000+ leads, 100,000+ call attempts) reports that qualification odds fell 21-fold between 5 and 30 minutes, but the page contradicts itself on the contact-odds figure [S14]. The HBR "Short Life of Online Sales Leads" article is paywalled; only its teaser was read [S15]. **Owner decision A3 bans the HBR figures from messages** [S3]. No peer-reviewed B2B speed-to-lead study was found. We use "reply fast" as an operating rule and keep every speed figure out of messages (CM-030).
- **Auto-replies.** RFC 3834: the `Auto-Submitted` header is the definitive marker (any value other than `no` means not sent by a person); responders must not answer automatic messages, and a "Auto:" subject is only a hint [S7].
- **WhatsApp.** The Business Messaging Policy (updated 23 Sep 2026) says businesses must honour requests to stop messages made on or off WhatsApp, allows automation inside the 24-hour window, requires a clear escalation path to a human, and lets blocks and reports limit how many people a business can message [S8]. On the Business Platform, free-form messages are allowed only inside the 24-hour customer service window opened by the user's message [S9].
- **Opt-outs on email.** Yahoo asks bulk senders to honour unsubscribes within 2 days [S11]; Google requires one-click unsubscribe for bulk senders and sets a 0.3% spam-rate line [S10]. We act at once, which is stricter than both.
- **UAE.** PDPL Art. 17 gives a right to object to processing for direct marketing; Art. 15 covers erasure [S12]. Cabinet Resolution 56/2024 (law-firm summary) covers marketing messages on social apps, requires consent, sets 09:00–18:00 calling hours and a TDRA do-not-call register [S13]. Owner decision D2 applies these rules to WhatsApp as if they apply [S3].
- **Replies that sell.** Huthwaite's SPIN whitepaper: describing features and imagined advantages is the easiest way to create objections and price concerns; benefit statements tied to a need the buyer stated go with success; closing techniques hurt in major sales [S16]. Gong (vendor data): good reps pause after an objection and answer with questions, not monologues [S21]. Voss: label first, then a calibrated "what/how" question [S17]; no-oriented questions make people feel safe [S18]; "Have you given up on…?" for silence [S19]. Keenan: value lives in the gap between current and future state [S20].
- **Automation disclosure.** EU AI Act Art. 50(1): people interacting with an AI system must be informed, unless it is obvious [S22]; California's bot law makes it unlawful to use a bot to mislead about its artificial identity to drive a sale [S24]. The owner rule is stricter for us than neither and simpler than both: say truthfully that it is automated whenever asked [S4]. Proactive disclosure is not required by any UAE source we found; it would be for EU recipients (open point in CHANGELOG).
- **Sarcasm and dialect.** Automatic sarcasm detection is hard and depends on context beyond the text [S25]; on Arabic tweets incl. Gulf dialect, a baseline model reached F1 0.46 and annotators' sentiment labels shifted with their biases [S26]. So suspected sarcasm goes to a human (CM-031).

---

## A. Intake and classification

### CM-001 · Every reply is classified and the decision is logged
- Rule: For every inbound message on our threads, record one decision: `label` (from CM-002), `also` (other intents present), `confidence` (0–1), the text spans that drove it, the rule ids applied, the action taken (reply / handover / no reply), the lead state after, and the playbook version. A reply without a logged decision is never answered.
- Why: The Analyst ties outcomes back to decisions and playbook versions; PROJECT_CONTEXT requires every agent decision to be recorded with inputs, options, choice, reasoning and confidence. ReplyGuard's acceptance rule makes the thread and context part of the input.
- Source: [S2 §3a decision log; §9 feedback loop], [S1 Agent 10 hands over; acceptance rule · ReplyGuard]
- Check: deterministic (`R26_decision_logged`)
- Example: `{label: not_now, also: [], confidence: 0.93, spans: ["not looking at this until Q1"], rules: [CM-022], action: reply, state_after: warm, followup_at: 2027-01-04}`.
- Default or locked: **locked**

### CM-002 · One fixed set of reply labels, mapped to the SOP's reply table
- Rule: Use exactly these labels:
  - `opt_out`: asks to stop, unsubscribe, be removed or not be contacted (CM-005).
  - `complaint`: calls it spam, threatens to report, or is angry about being contacted (CM-010).
  - `bot_question`: asks whether the sender is a bot, automated, AI or a real person (CM-016).
  - `meeting_request`: wants to talk, meet, call or invites us to visit (CM-027).
  - `positive`: says yes to what was offered ("send it", "go ahead") (CM-023).
  - `question`: asks something about us, the report or the offer (CM-024).
  - `objection`: pushes back with a reason (already have a tool, no budget, disputes a finding) (CM-025).
  - `referral`: names or forwards to someone else at the company (CM-019).
  - `wrong_person`: not the right person or has left, and names nobody (CM-020).
  - `not_now`: interested later, or busy now (CM-022).
  - `not_interested`: declines without asking to stop (CM-021).
  - `auto_reply`: out-of-office, away or greeting message, or any automatic response (CM-007 to CM-009).
  - `unclear`: none of the above with confidence (CM-031).
  SOP mapping: "Yes, send it" = `positive`; a question = `question`; "Let's talk" = `meeting_request`; "Later" = `not_now`; "Talk to <colleague>" = `referral`; "Not interested" = `not_interested`; "Stop" = `opt_out`.
- Why: The SOP's reply table has seven reply types; the build plan adds complaint, out-of-office and "are you a bot?"; objection, wrong person and unclear are split out because each needs a different action (objections need a question, not a sequence step; wrong person needs re-mapping; unclear needs a human). A fixed set makes the test set and the Analyst's numbers comparable.
- Source: [S1 ReplyGuard "When a reply comes" table], [S4 ReplyGuard build], [S2 §10 human vs bot lesson]
- Check: deterministic (`R01_label_correct`)
- Example: "We already use a CRM for this, why would we need you?" → `objection`, not `question`.
- Default or locked: default (adding a label is a Gate 4 proposal; removing a safety label is not allowed)

### CM-003 · When a reply carries more than one intent, safety labels win
- Rule: Pick the primary label in this order: `complaint` > `opt_out` > `bot_question` > `meeting_request` > `positive` > `question` > `objection` > `referral` > `not_now` > `not_interested` > `wrong_person` > `auto_reply` > `unclear`. Record the rest in `also`. A safety intent (`complaint`, `opt_out`, `bot_question`) anywhere in the message is always acted on, even if the person also asked for something else.
- Why: A missed opt-out breaks a locked guardrail and the law; a missed "yes" only delays a sale. Complaint outranks opt-out because it needs everything an opt-out needs plus an account-health signal and a human.
- Source: [S2 §3 guardrails 7, 11], [S3 C], [S8 opt-out]
- Check: deterministic (`R01_label_correct`, `R02_safety_never_missed`)
- Example: "Not interested. Please stop." → `opt_out` with `also: [not_interested]`; "Is this a bot? Anyway send the report" → `bot_question` with `also: [positive]`: answer the bot question truthfully and hand over; the report waits for the human.
- Default or locked: **locked** (safety labels first); default (order among the other labels)

### CM-004 · Opt-out = the code detector OR the classifier; never overridden downward
- Rule: A message is an opt-out if the deterministic detector (`domain/optout.detect_inbound_opt_out`, run by `orchestrator/inbound.py` before the agent sees the message) fires, **or** the classifier labels it `opt_out` or `complaint`. The classifier can add opt-outs the detector missed; it can never turn a detector hit into "not an opt-out".
- Why: The detector is fast and auditable but has known gaps (see CM-005: "please remove my number", Gulf phrases such as "احذف رقمي" and "شيلوا رقمي", "This is spam" do not fire it as of 10 Nov 2026). The classifier is better at meaning but can be wrong. Taking the union keeps recall at its highest, which is what the locked guardrail needs.
- Source: [S5 `domain/optout.py`, `orchestrator/inbound.py`], [S3 C "STOP respected immediately"], [S2 §3 guardrail 7]
- Check: deterministic (`R02_safety_never_missed`, `R03_detector_floor`)
- Example: "Please remove my number from your list" → detector `false`, classifier `opt_out` → suppressed. "الشغل عندنا ما توقف" ("our work never stopped") → detector `true` → stays suppressed (CM-006).
- Default or locked: **locked**

### CM-005 · What is an opt-out, and what only looks like one
- Rule: An opt-out is any request, in any language or channel, to stop messages, be removed, unsubscribe, delete the person's number or details, or not be contacted, including short forms ("STOP", "Stop." as its own sentence, "unsub", "remove me") and Gulf Arabic forms (`defaults.yaml` `opt_out.extra_phrases`, e.g. "لا ترسل", "لا تراسلني", "احذف رقمي", "شيلوا رقمي", "وقفوا الرسايل", "خلاص لا تراسلني"). These are **not** opt-outs on their own: "stop by our showroom", "I'll stop you right there", "can you remove the price column / the company name from the report", "remove my colleague, he left" (a data correction about someone else, CM-048), "our work never stopped". Decide on the whole message and its thread, not on a keyword.
- Why: Keyword matching both over- and under-fires: "stop" and "remove" are common in ordinary business requests, while Gulf dialect opt-outs use verbs the detector does not list. The SOP's "Stop" row and the policy's "honour requests to stop messages, on or off WhatsApp" cover meaning, not a keyword. The Arabic phrase list is ours and has not been reviewed by a native Gulf speaker (accepted risk B4).
- Source: [S1 reply table "Stop"], [S8], [S5 `domain/optout.py` keyword lists], [S3 B4]
- Check: deterministic (`R01_label_correct`, `R02_safety_never_missed`); judge (`classification_judgement`)
- Example: "Can you remove the price column from the report before you send it?" → `positive` (they want the report) with a handover for the report change, not `opt_out`.
- Default or locked: **locked** (meaning over keywords; union with the detector); default (the phrase list, extended by proposal or from real misses)

### CM-006 · A detector false positive stays suppressed until a human decides
- Rule: When the detector fired but the classifier is confident the person did not ask to stop, do nothing to reverse it: the person stays suppressed, the lead stays `do_not_contact`, no message is sent. Raise a handover task `possible_false_opt_out` with the message and both verdicts. Only a human can lift a suppression, and the agent never proposes it.
- Why: Suppression on a detector hit is done in code before the agent runs, and STOP is a locked guardrail; a wrongly lost lead costs less than one message to someone who asked to stop. A human, reading the Arabic, can judge it.
- Source: [S5 `orchestrator/inbound.py`, `domain/suppression.py`], [S3 C], [S6 CF-045 "the agent never removes a suppression"]
- Check: deterministic (`R03_detector_floor`, `R11_handover_triggers`)
- Example: "الشغل عندنا ما توقف طول رمضان، ارسل التقرير" ("our work didn't stop all Ramadan, send the report") → detector hit on "توقف"; classifier `positive` 0.9 → no reply, task `possible_false_opt_out` to the owner.
- Default or locked: **locked**

### CM-007 · Auto-replies: headers first, and never answer one
- Rule: Label `auto_reply` when an email has `Auto-Submitted` other than `no`, or `X-Autoreply`, `X-Autorespond`, `Precedence: auto_reply|bulk|junk|list`, or an `X-Auto-Response-Suppress` set by an autoresponder, or (as a hint, needing text support) a subject starting "Automatic reply", "Auto:", "Out of Office", or an Arabic equivalent. Never send any message in answer to an auto-reply. It does not count as a reply for the KPI and does not move the lead to `replied`. Delivery failure notices go to Agent 10's bounce handling, not here.
- Why: RFC 3834 makes `Auto-Submitted` the definitive marker and says responders should not answer automatic messages (loops); the subject prefix is only a hint. Counting an out-of-office as a reply would inflate reply rates and pause the company for nothing.
- Source: [S7 §2, §3.1.5, §3.1.7, §5.2], [S6 CO-029 bounces]
- Check: deterministic (`R09_auto_reply_handled`)
- Example: `Auto-Submitted: auto-replied`, "I'm out of the office until 24 Nov" → `auto_reply`, no reply, next touch on the first working day after the return date (CM-008).
- Default or locked: **locked** (never answer an auto-reply); default (header list)

### CM-008 · Out-of-office: resume after the return date, and release the company lock with a reason
- Rule: From an out-of-office, take the return date if one is stated and resume the person's sequence on the first allowed working day after it (`auto_reply.resume_business_days_after_return`: 1); if no date, resume after `auto_reply.default_resume_days` (7). Because the code locks the company on any inbound, the agent releases the lock for an auto-reply only, logging `company.lock_released` with the reason `auto_reply`. The code also moves the lead to `replied`; record the label so the Analyst excludes it, and flag the state for the builder (CHANGELOG open point 2).
- Why: The SOP pauses a company for a reply from a person; an autoresponder is not a person. Holding everyone at the company for a vacation notice wastes the sequence. The resume offsets are ours.
- Source: [S1 "Any reply from anyone at the company pauses everyone there"], [S5 `orchestrator/inbound.py` company lock], [S7]
- Check: deterministic (`R09_auto_reply_handled`, `R18_followup_dates`)
- Example: Return 24 Nov (Tuesday) → next touch Wednesday 25 Nov in the window; lock released at classification.
- Default or locked: default

### CM-009 · WhatsApp away and greeting messages need two signals; short human replies are human
- Rule: On WhatsApp (no headers), label `auto_reply` only when **two** signals agree: it arrived within `auto_reply.whatsapp_max_seconds_after_our_message` (10 s) of our message or of a previous auto-message, **and** its text is generic business boilerplate (thanks for contacting, we will get back to you, opening hours, a menu of options) that does not respond to what we wrote. A short reply such as "ok", "👍", "yes", "who?" is human unless both signals hold.
- Why: The WhatsApp Business app has built-in greeting and away messages (third-party guides only; not confirmed on WhatsApp's help pages). In DubiCars the small model called short human replies "auto-replies"; the fix in PROJECT_CONTEXT is explicit decision rules plus reply-timing features.
- Source: [S27], [S2 §10 human vs bot lesson]
- Check: deterministic (`R09_auto_reply_handled`, `R01_label_correct`)
- Example: "Thank you for contacting Al Noor Motors! We will reply shortly." 3 s after jab 1 → `auto_reply`. "ok" 40 minutes after "Shall I send it?" → `positive`.
- Default or locked: default

### CM-010 · A complaint is an opt-out plus an account-health signal plus a human
- Rule: On `complaint` (calls it spam, says they reported or will report us, threatens a regulator or lawyer, or is angry about being contacted, including sarcastically), do everything in CM-011 (suppress everywhere), then record an account-health signal on the sending account with `account_health.record_account_signal(kind="complaint", payload={lead_id})`, and if they say they blocked or reported the number, also `kind="report"` or `"block"`. Hand over with reason `complaint`. Send no automated reply; a human decides whether a one-line apology goes out.
- Why: Rising complaints mean the messages need fixing, and the hard guardrails rest accounts on complaints and pause a pool on a spike; extra accounts are never used to keep messaging people who reported us. Angry and legal replies are on the escalation list.
- Source: [S2 §3 guardrails 6, 11], [S3 C], [S5 `orchestrator/account_health.py` `SIGNAL_KINDS`], [S6 CO-005, CO-031, CO-042], [S8 blocks and reports]
- Check: deterministic (`R05_complaint_signal`, `R04_suppression_scope`, `R11_handover_triggers`)
- Example: "This is spam. Reported." on WhatsApp → person suppressed, `do_not_contact`, signals `complaint` + `report` on Ali's number, task `complaint`, no reply.
- Default or locked: **locked**

### CM-011 · An opt-out is honoured at once, on every channel and every account
- Rule: On `opt_out` (detector or classifier): suppress the person on every channel (`suppress_person_everywhere`, reason `opt_out`, source `inbound:<message id>`), move the lead to `do_not_contact`, cancel every pending job for the person, and never contact them again from any account. This happens the moment the message is classified, at any hour, before anything else. A deletion request ("delete my data / my number") also runs erasure (CM-043).
- Why: "STOP / do-not-contact respected immediately on every channel and account" is a locked owner guardrail and PROJECT_CONTEXT guardrail 7. WhatsApp's policy requires honouring stop requests made on or off WhatsApp; PDPL gives a right to object to direct marketing; Yahoo allows 2 days, we act at once.
- Source: [S3 C], [S2 §3 guardrail 7], [S8], [S12 Art. 17], [S11], [S10], [S5 `domain/suppression.py`, `orchestrator/inbound.py`]
- Check: deterministic (`R04_suppression_scope`, `R19_state_after`)
- Example: "stop sending me these" by email at 21:40 → suppressed on email, WhatsApp and LinkedIn at 21:40; the WhatsApp touch planned for tomorrow is cancelled.
- Default or locked: **locked**

### CM-012 · "Us" opt-outs cover the company
- Rule: When the opt-out speaks for the company ("don't contact us", "remove our company", "stop messaging anyone here", "لا تراسلونا"), suppress the company as well as the person, so nobody there is contacted on any channel. When it speaks only for the person ("remove me"), suppress the person only; the company stays locked by the reply (CM-014).
- Why: Do-not-contact must match what was asked. The suppression model supports company-level entries (`is_suppressed(company_id=...)`).
- Source: [S2 §3 guardrail 7], [S5 `domain/suppression.py`, `orchestrator/gates/dnc.py`]
- Check: deterministic (`R04_suppression_scope`)
- Example: "Please don't contact us again" from the GM → company suppressed; the W2 sales manager's pending LinkedIn invite is cancelled.
- Default or locked: **locked**

### CM-013 · Opt-out confirmation: one line, their language, nothing else, only through the gates
- Rule: After an opt-out (not a complaint), send at most one confirmation line in the person's language on the same channel ("Done, you won't hear from us again." / "تم، لن نراسلك مرة أخرى."), with no question, no link, no pitch and no re-engagement. Send it only if the gates accept a confirmation-only message for a `do_not_contact` lead; if they don't (as of 10 Nov 2026 Gate 2 blocks every message to a suppressed person), send nothing. Never bypass a gate to confirm.
- Why: The SOP says "Removal confirmed in one line". The do-not-contact gate is locked and blocks it today; whether to add a narrow confirmation exemption is a builder decision (CHANGELOG open point 1). Silence is always safe; a gate bypass never is.
- Source: [S1 reply table "Stop"], [S5 `orchestrator/gates/dnc.py`], [S3 C]
- Check: deterministic (`R16_gates_and_hours`, `R21_reply_form`)
- Example: "STOP" on WhatsApp → `reply_allowed: confirmation_only`; if Gate 2 blocks it, no message, decision logged `confirmation_blocked_by_gate`.
- Default or locked: default (the confirmation); **locked** (never through a bypass)

### CM-014 · Any reply locks the company: one voice, one owner
- Rule: Any human reply from anyone at a company pauses every other sequence at that company on every channel (`company_lock_at`, set in code). Only the thread with the person who replied continues, from the same account, handled by the company's one owner. Other people there are contacted again only through the ReplyGuard's own plan for this company (a referral's jab 1, CM-019) or an approved proposal (CM-015).
- Why: The SOP standard: one shared inbox, one owner per company, so no company hears from two of us; a reply on any channel stops the sequence on every channel for everyone at that company. The do-not-contact gate enforces it (`dnc:company_locked`).
- Source: [S1 Standards], [S5 `orchestrator/inbound.py`, `orchestrator/gates/dnc.py`], [S6 CW-018, CO-014]
- Check: deterministic (`R08_company_lock`)
- Example: Feras replies on email; his colleague Mona's WhatsApp touch due tomorrow is cancelled (`dnc:company_locked`).
- Default or locked: **locked**

### CM-015 · Replanning a locked company is a decision, not a default
- Rule: The agent may: (a) release the lock for an auto-reply (CM-008); (b) send jab 1 to a referred, verified colleague (CM-019). Anything else that contacts another person at a locked company (resuming a paused colleague after a "not interested", or after a positive reply that went quiet) is a Gate 4 proposal with the thread as evidence. After a `not_interested` from a W1 decision maker, the default is to keep everyone paused for this campaign.
- Why: Agents decide, humans approve departures (§3a). Re-contacting a company that said no, through a colleague, can read as ignoring the no ("never argue with a no").
- Source: [S2 §3a], [S1 Standards "Never argue with a no"]
- Check: deterministic (`R08_company_lock`); judge (`handover_quality`)
- Example: The head of sales said "not for us"; the W2 manager's sequence stays paused; a proposal to contact the W2 manager with a different angle waits for approval.
- Default or locked: default

## B. Truthfulness, safety and escalation

### CM-016 · "Are you a bot?": say yes, truthfully, then hand over
- Rule: When someone asks whether they are talking to a bot, an automated system, AI, or a real person, the very next message says plainly that the messages are sent by an automated assistant working for the named sender, and that the sender will reply personally (template `bot_disclosure` in `defaults.yaml`, in their language). Then hand over (reason `bot_question`). No pitch, no question in that message.
- Why: Owner rule: agents say truthfully they are automated if asked; bot questions are on the escalation list. WhatsApp's policy requires a clear path to a human when automation is used. The EU AI Act and California's bot law point the same way for the markets they cover.
- Source: [S4 fixed rules], [S2 §3 guardrails 9, 11], [S8 escalation paths], [S22 Art. 50(1), (5)], [S23], [S24]
- Check: deterministic (`R06_bot_truthful`, `R11_handover_triggers`)
- Example: "هل هذا بوت؟" → "نعم، هذه الرسائل يرسلها مساعد آلي نيابةً عن علي من Paralax، وسيرد عليك علي بنفسه." + the Arabic opt-out line; task to Ali.
- Default or locked: **locked**

### CM-017 · Never claim to be human, never deny, never dodge
- Rule: No message may say or imply that a human is typing it in real time ("just saw this on my phone", "sorry, was in a meeting"), deny automation, change the subject when asked, or invent personal details of the sender. Messages are signed with the sender's name from the brief, which is allowed because they are sent on that person's behalf and approved by them; if asked, CM-016 applies.
- Why: The owner rule is truthful disclosure when asked; a lie found out later costs the sender's credibility and breaks the platforms' and the EU's transparency direction.
- Source: [S4], [S2 §3 guardrail 9], [S22], [S24], [S6 CW-025 sender identification]
- Check: deterministic (`R07_never_claim_human` via phrase list `truthfulness.forbidden_claims`); judge (`honesty`)
- Example: Draft "Sorry for the delay, I was driving!" → blocked.
- Default or locked: **locked**

### CM-018 · Never negotiate, pay, book or visit
- Rule: The agent never quotes or discusses prices, discounts, payment terms, contract terms, scope or delivery dates; never agrees to anything that commits a human (a visit, a call at a specific time, a trial, a deadline); never pays or asks for payment; never creates or changes calendar events. It may send the approved self-service booking link (the person books themselves) once one is configured (CM-027). Any request in these areas is a handover.
- Why: Owner rule for the ReplyGuard (build plan, fixed rules) and PROJECT_CONTEXT guardrail 9; pricing and payment talk is on the escalation list (guardrail 11). Huthwaite's research links early feature and advantage talk to more objections and price concerns.
- Source: [S4 fixed rules], [S2 §3 guardrails 9, 11], [S16]
- Check: deterministic (`R12_never_negotiate_book_visit`)
- Example: "Please stop by our showroom on Sheikh Zayed Road, we can talk there" → `meeting_request`, handover `visit_request`; no "see you Tuesday".
- Default or locked: **locked**

### CM-019 · Referrals: thanks, then jab 1 to a verified colleague, naming who referred us
- Rule: On `referral` ("talk to Priya", a forward with the colleague in copy, "كلم سالم"): thank the person in one line; create or find the colleague as a person at the company and send them to the Contact Finder; only when the colleague has a **verified** contact detail, the Copywriter writes jab 1 naming the referrer first (CW-009), and it goes through the gates. If the colleague writes to us directly on the forwarded thread, treat them as a new replier (their own lead), not as the original person.
- Why: The SOP: "Thanks, then jab 1 to the colleague, naming who referred us" → state "Contacted new person". Verified contacts only is a hard guardrail, so a name or an address in a reply is not enough.
- Source: [S1 reply table "Talk to <colleague>"], [S2 §3 guardrail 6], [S6 CW-009, CF-001]
- Check: deterministic (`R10_verified_referrals_only`)
- Example: "Forwarding to Hana who runs our call centre. Hana, see below." with `hana@...` in Cc → thanks to the sender; Hana → Contact Finder; no message to Hana until her address verifies.
- Default or locked: **locked** (verified only); default (the wording)

### CM-020 · Wrong person or left the company: thank, record, re-map
- Rule: On `wrong_person` with no name: thank them in one line and ask once who looks after the topic (one question). If they have left the company, do not ask; thank them, mark the person `left_company` for the Buyer Mapper and Contact Finder, and stop all touches to them for this company. Never ask twice.
- Why: A courteous single ask often yields a referral; pushing someone who has left wastes their time and ours, and their details for this company are now wrong.
- Source: [S1 "Later or referral" row], [S6 CF-029 remap]
- Check: deterministic (`R19_state_after`); judge (`reply_quality`)
- Example: "I left Al Noor Motors in August" → "Thanks for letting me know, and all the best." + opt-out line; person flagged; Buyer Mapper re-map queued.
- Default or locked: default

### CM-021 · Never argue with a no
- Rule: On `not_interested`: one line of thanks and at most one optional, easy question on why ("Out of interest, is it timing or just not a fit?"), then `lost` with the reason in their words. No second attempt, no counter-argument, no "just one more thing". If they answer the why, record it and reply only to thank them.
- Why: SOP: "Not interested" → "Thanks, and one optional question on why" → Lost; "Never argue with a no". The reason in their words feeds the Analyst's weekly fix.
- Source: [S1 reply table; Standards; "Said no → Lost, reason logged in their words"], [S6 CW-044]
- Check: deterministic (`R28_no_argue_after_no`, `R19_state_after`)
- Example: "مب مهتم، مشكور" → "مشكور على ردك. للعلم فقط، هل السبب التوقيت أم أنه غير مناسب لكم؟" + Arabic opt-out line; state `lost`, reason "مب مهتم".
- Default or locked: **locked** (no argument, no second attempt); default (the optional question)

### CM-022 · Not now: agree, ask when, set the date
- Rule: On `not_now`: "No problem, when suits you?" (or confirm the date they gave), set a follow-up for that date in the next allowed window, and move the lead to `warm`. A stated date wins; "after Eid" uses the configured holiday calendar; a quarter means its first working day; no date at all → `followup.not_now_default_days` (30). If the date they ask for falls outside allowed hours (e.g. a Sunday in the UAE), use the next allowed window and say so.
- Why: SOP: "Later" → "No problem, when suits you?" and a follow-up set for that date → Warm. Allowed hours are locked (A2), so their preferred time can't override them.
- Source: [S1 reply table "Later"], [S3 A2], [S6 CW-058 Gulf timing]
- Check: deterministic (`R18_followup_dates`, `R16_gates_and_hours`)
- Example: Tue 10 Nov: "Busy now, msg me Sunday" → "No problem, I'll message you on Monday morning." → follow-up Mon 16 Nov 10:00 Dubai (Sunday is outside the UAE pack's Mon–Fri hours).
- Default or locked: default

### CM-023 · "Yes, send it": jab 2
- Rule: On `positive`: send jab 2, their one-page report with the headline in one line, plus the personal walkthrough video only if one exists and is approved (otherwise the report alone), then `replied`. Ask one easy question at the end. If the "yes" came with a request we can't fulfil from the record (change the report, remove a name from it), hand over that part.
- Why: SOP: "Yes, send it" → "Jab 2: their report and a personal walkthrough video" → Replied. Videos outside the approved plan are decision proposals (§3a; CW-059).
- Source: [S1 reply table], [S6 CW-013, CW-059], [S2 §3a]
- Check: deterministic (`R19_state_after`); judge (`reply_quality`)
- Example: "Yes send it" → jab 2 drafted by the Copywriter for this thread, through the gates.
- Default or locked: default

### CM-024 · A question: a two-line answer from the record, then jab 2
- Rule: On `question`: answer in at most two lines using only the research findings, the report, the brief's offer and the approved FAQ in `answers.allowed_sources`; then offer jab 2. If the true answer is not in those sources, do not guess: hand over (`outside_evidence`). Pricing, terms, legal and data questions are always handovers (CM-028).
- Why: SOP: a question → "A two-line answer, then jab 2". Evidence-only is a hard guardrail; a confident wrong answer to a real prospect costs more than a delayed one.
- Source: [S1 reply table], [S2 §3 guardrails 4, 11], [S6 CW-001, CW-060]
- Check: deterministic (`R13_evidence_only`); judge (`reply_quality`)
- Example: "Sounds interesting, what does it involve?" → two lines from the offer ("an instant first reply on WhatsApp, in Arabic and English, using your stock list"), then "Shall I send you the one-pager we made on your enquiries?"
- Default or locked: **locked** (evidence only); default (the two-line shape)

### CM-025 · Objections: label, then one calibrated question; no rebuttal, no feature list
- Rule: On `objection`: name what you heard tentatively ("It sounds like you already have this covered with your CRM."), then ask one calibrated "what" or "how" question ("What happens today when an enquiry comes in after 6pm?"). Do not rebut, do not list features or advantages, do not send a longer message than theirs. If the objection disputes one of our findings ("we reply in 5 minutes"), do not argue it: hand over (`finding_disputed`).
- Why: Huthwaite: features and imagined advantages are the easiest way to create objections and price concerns. Gong (vendor data): reps who handle objections well pause and use questions, while weaker reps answer with a monologue. Voss: start with a label, then follow with the calibrated question; labels leave room to be wrong. A disputed finding needs a human to check the evidence.
- Source: [S16], [S21], [S17], [S6 CW-044]
- Check: judge (`reply_quality`); deterministic (`R22_length`, `R23_one_question`)
- Example: "We already use a CRM for this, why would we need you?" → "Sounds like the CRM already holds every enquiry. How quickly does the first reply go out when the team's busy?"
- Default or locked: default

### CM-026 · Use SPIN and Gap only as questions they answer
- Rule: In replies, build need by asking: an implication question (what the measured problem leads to) or a need-payoff question (what fixing it would be worth to them). Let them say the value; never assign them a revenue or loss figure, and never use outside statistics. Propose the highest realistic next step (the report, then the 20-minute walkthrough), not a "close".
- Why: Huthwaite: explicit needs stated by the buyer go with success; closing techniques reduce success in major sales; top performers propose the highest realistic commitment. Keenan: value lives in the gap between current and future state. Numbers must come from our evidence (A3; CW-045, CW-046).
- Source: [S16], [S20], [S6 CW-041, CW-042, CW-045, CW-046], [S3 A3]
- Check: judge (`reply_quality`); deterministic (`R13_evidence_only`, `R14_no_outside_stats`)
- Example: "If after-hours enquiries wait until morning, what does that mean for the weekend buyers?"
- Default or locked: default

### CM-027 · Meetings: the booking link only, never a time, never a call on WhatsApp
- Rule: On `meeting_request`: if the campaign has an approved booking link (`meetings.booking_link`), send it with one line ("Here's the link to pick a 20-minute slot that suits you: <link>"). If not (true until Day 5), hand over (`meeting_request_no_link`) with a one-line holding reply allowed ("Great, Ali will confirm a time with you today."). Never propose, accept or confirm a specific time, never accept a visit, never create a calendar event, never offer or place a WhatsApp voice or video call to a UAE recipient (offer the link or a phone call by a human). The lead becomes `meeting_booked` only when the booking system reports a booking.
- Why: Owner rule: never book; the build plan routes booking requests to a human until the link exists. The SOP's "two times offered directly" commits a person's calendar, so it is a human action. UAE VoIP restrictions mean WhatsApp calls are avoided (CO-050).
- Source: [S4 fixed rules; booking], [S3 G4], [S1 reply table "Let's talk"; booking section], [S6 CO-050]
- Check: deterministic (`R12_never_negotiate_book_visit`, `R11_handover_triggers`)
- Example: "Can we jump on a WhatsApp call now?" → no call; with a link: the link; without: handover + "Ali will call you on a normal line shortly to set a time."
- Default or locked: **locked** (never book, never a time, no WhatsApp call); default (wording)

### CM-028 · The handover list
- Rule: Hand over to a human (a task with the reason, the thread and a suggested draft) whenever any of these is present: `pricing` (price, cost, discount, payment, invoice); `negotiation` (terms, scope, timeline, contract, trial); `legal_or_regulator` (lawyer, TDRA, PDPL, police, report to authorities); `personal_data_request` ("who gave you my number", "what data do you have", "delete my data" after erasure runs); `complaint` or anger; `bot_question` (after CM-016); `visit_request`; `meeting_request_no_link`; `finding_disputed`; `outside_evidence`; `report_change_request`; `possible_false_opt_out`; `sarcasm_suspected`; `low_confidence` (CM-031); `unsupported_language`; `unsupported_media` (voice note, image, file we can't read); `banned_account_thread` (CM-045); `stop_rule` (CM-040). One reply can have several reasons; list them all.
- Why: The escalation list is a hard guardrail (payment or pricing talk, legal or angry replies, bot questions, personal-data requests, anything the agent isn't confident about). The rest are this agent's own "would have to guess" cases (CW-060). WhatsApp's policy requires a clear human escalation path.
- Source: [S2 §3 guardrail 11], [S4], [S8], [S6 CW-060]
- Check: deterministic (`R11_handover_triggers`)
- Example: "Hi, how much would this cost us per month?" → handover `pricing`; holding line allowed (CM-029).
- Default or locked: **locked** (the guardrail items); default (the agent's own additions, which can only grow)

### CM-029 · How to hand over: fast, complete, with at most one holding line
- Rule: A handover task carries: the reasons, the classification, the full thread, the company page and person card links, the account and channel, and a suggested reply draft. For `pricing`, `negotiation`, `meeting_request_no_link` and `report_change_request` the agent may send one holding line that commits nobody to anything ("Good question, Sam will come back to you on that shortly.") inside allowed hours. For `complaint`, `legal_or_regulator`, `possible_false_opt_out`, `sarcasm_suspected` and `banned_account_thread`, send nothing. Tasks for safety reasons (complaint, legal, opt-out doubt) are created at once, at any hour.
- Why: A holding line keeps the reply fast without making a promise; silence is right where any words could make things worse. The human needs the whole context to act in one step.
- Source: [S2 §3 guardrail 11], [S8 escalation paths], [S1 one shared inbox]
- Check: deterministic (`R11_handover_triggers`, `R12_never_negotiate_book_visit`); judge (`handover_quality`)
- Example: "كم السعر؟" → Arabic holding line ("سؤال مهم، سام بيرد عليك بنفسه قريباً.") + task `pricing`.
- Default or locked: default (holding lines); **locked** (no message on the no-message reasons)

### CM-030 · Answer only from the record; outside statistics stay out
- Rule: Every claim in a reply must trace to a stored finding, the company's report, the brief's offer or the offer allow-list. No outside statistics, studies or "industry data" in messages, and specifically none of the HBR "Short Life of Online Sales Leads" figures (owner decision A3). Estimates are labelled as estimates.
- Why: Evidence-only is a hard guardrail and is checked at the gate; A3 bans the HBR figures because they are paywalled and unverified.
- Source: [S2 §3 guardrail 4], [S3 A3], [S6 CW-045, CW-046, CW-047], [S15]
- Check: deterministic (`R13_evidence_only`, `R14_no_outside_stats`)
- Example: Draft "Studies show leads go cold after 5 minutes" → blocked.
- Default or locked: **locked**

### CM-031 · Uncertain or sarcastic: a human reads it
- Rule: If the primary label's confidence is below `classification.min_confidence` (0.80, ours), or sarcasm or irony is suspected and changes the meaning, or the classifier and a second pass disagree, do not reply: hand over (`low_confidence` / `sarcasm_suspected`). Safety intents are still acted on first (an uncertain opt-out is treated as an opt-out, CM-004).
- Why: Sarcasm detection depends on context beyond the text and is hard even for trained models; on Arabic including Gulf dialect a baseline reached F1 0.46 and human annotators disagreed. "Anything the agent isn't confident about" is on the escalation list.
- Source: [S25], [S26], [S2 §3 guardrail 11]
- Check: deterministic (`R11_handover_triggers`); judge (`classification_judgement`)
- Example: "Lol nice try" → `unclear` 0.55 → handover `sarcasm_suspected`, no reply.
- Default or locked: **locked** (low confidence → human); default (the 0.80 threshold)

### CM-032 · Language: reply in theirs; Arabic follows the owner switch
- Rule: Reply in the language of their last message (CW-018, CW-056). Arabic replies follow the Copywriter's Arabic rules and are sent automatically only while the campaign switch `arabic_auto_send` is on; when it is off, the Arabic draft goes to a human. Mixed messages: the language of most of the words. Arabizi (Arabic in Latin letters): reply in English, short and simple, unless the thread was in Arabic. Any other language (e.g. French, Hindi): hand over (`unsupported_language`). Every reply carries the opt-out line in the reply's language.
- Why: SOP: reply in the language they used. B4 accepted Arabic without native review behind a switch. The compliance pack requires the Arabic opt-out line on Arabic messages.
- Source: [S1 Standards], [S3 B4], [S5 `compliance/uae.py` opt-out rules], [S6 CW-018, CW-024, CW-056, CW-057]
- Check: deterministic (`R15_language_match`, `R21_reply_form`)
- Example: "Merci, pas intéressé" → label `not_interested`, handover `unsupported_language`, state `lost` recorded by the human.
- Default or locked: **locked** (their language; switch; opt-out line); default (Arabizi handling)

## C. Speed, form and channel rules

### CM-033 · Reply as fast as possible; measure it honestly
- Rule: Classify every reply as soon as it arrives (webhook, else the 1-minute poll) and send the reply at the earliest moment the gates allow. Measure response time from the reply's arrival to our first human-meaningful response (a reply or a holding line), counting only allowed hours; report the median per campaign and channel (target under 15 minutes). Do not cite any speed statistic in messages (CM-030).
- Why: The SOP's KPI is a median under 15 minutes in working hours; decision #12 says reply as fast as possible with no fixed deadline. The speed-to-lead data we could read is vendor-associated and internally inconsistent [S14]; the HBR article is paywalled and banned from messages [S15][S3 A3].
- Source: [S1 KPI; "Classified and answered in 15 minutes, working hours"], [S2 §2 #12], [S14], [S15], [S4 polling]
- Check: deterministic (`R30_kpi_measured`)
- Example: Reply at 10:02, holding line at 10:05 → 3 minutes; reply at 22:30 Thursday, answered Friday 09:00 → 0 working minutes counted at 09:00.
- Default or locked: default (the target); **locked** (no speed figures in messages)

### CM-034 · Human pace in chat
- Rule: On WhatsApp and LinkedIn, wait a random `response.chat_delay_seconds` (60–240 s, ours) before sending a reply, never less than 20 s between any two outgoing messages on a number, and send one bubble, not several. The delay never applies to suppression, signals or handover tasks.
- Why: Instant replies to every message look automated to platforms that detect bulk and automated sending; the Channel Operator sets 20 s minimum gaps (CO-045) and one bubble (CW-053). This is pacing, not pretending to be human (CM-017 still applies).
- Source: [S6 CO-045, CW-053], [S8]
- Check: deterministic (`R16_gates_and_hours`)
- Example: "Yes send it" at 10:00:00 → jab 2 sent at 10:02:40.
- Default or locked: default (the 60–240 s); **locked** (≥ 20 s gap, mirrors CO-045's floor)

### CM-035 · Replies go through every gate and respect allowed hours
- Rule: Every outgoing message (replies, holding lines, nudges, confirmations, reminders) is a draft that passes the same 8 gates and the send-once outbox. Allowed hours apply to replies too (UAE pack: Mon–Fri 09:00–18:00 Asia/Dubai, A2): a reply that arrives outside them is answered at the next window opening. Suppression, account signals and handover tasks are not messages and happen at once.
- Why: Drafts go through the same gates (build plan). The UAE hours are a locked owner guardrail and apply to every channel (D2).
- Source: [S4], [S3 A2, C, D2], [S13] (09:00–18:00 for marketing calls; do-not-call register), [S28] (not verified), [S5 `compliance/uae.py` `allowed_now`]
- Check: deterministic (`R16_gates_and_hours`)
- Example: "Yes, send it" Thursday 22:30 → jab 2 queued for Friday 09:00 Dubai; nothing at 22:31.
- Default or locked: **locked**

### CM-036 · WhatsApp: the 24-hour window and the two-unanswered cap
- Rule: On the WhatsApp Business Platform (Cloud API), free-form replies only inside the 24-hour customer service window opened by their last message; outside it, only an approved template, or another channel. On the WhatsApp Business app via Unipile (our current transport), there is no platform window, but never more than two unanswered outbound messages in a row (CO-041): a third nudge moves to another verified channel in the plan, or stops.
- Why: Meta: the window opens when the user messages and each new message resets it; outside it only templates can be sent. The policy allows automation inside the 24-hour window. Unanswered repeats lead to blocks and reports (CO-041, CW-017, locked).
- Source: [S8], [S9], [S6 CO-041, CO-049, CW-017], [S5 `compliance/uae.py` `max_unanswered`]
- Check: deterministic (`R17_whatsapp_window_and_cap`)
- Example: A replier went quiet after jab 2 on WhatsApp; nudge 1 (day 2) and nudge 2 (day 5) unanswered → nudge 3 (day 10) goes by email if a verified email exists, else none.
- Default or locked: **locked**

### CM-037 · Reply form: short, one question, the opt-out line
- Rule: Chat replies under 60 words and email replies under 80 (excluding the opt-out line and signature), at most one question and it comes last, no link except the report (jab 2) or the booking link (CM-027), and the opt-out line in the reply's language in every message. Mirror their register: a two-word reply gets a short answer.
- Why: These are the Copywriter's limits and the compliance pack's opt-out rule, which apply to every message; long answers to short questions read as a script.
- Source: [S6 CW-023, CW-024, CW-027, CW-032], [S5 `compliance/uae.py` opt-out], [S3 C]
- Check: deterministic (`R21_reply_form`, `R22_length`, `R23_one_question`)
- Example: "ok" → "Great, here it is: <report>. Anything in it you'd like me to explain?" + opt-out line.
- Default or locked: **locked** (opt-out line); default (word limits)

## D. Follow-ups, states and the stop rule

### CM-038 · Replied, then quiet: three nudges that each add something
- Rule: If someone replied and then goes quiet, send up to three nudges on days `followup.nudge_days` (2, 5, 10) after our last message, each adding something new (a finding not yet shared, a short answer to their last point, an easy no-oriented question), then move them to `warm` with a check-in after `followup.warm_checkin_days` (30). WhatsApp nudges obey the cap (CM-036). "Have you given up on…?" is allowed only as an A/B-tested variant after real engagement, never as pressure.
- Why: SOP: three nudges (days 2, 5, 10), each adding something new, then Warm with a check-in after 30 days. Voss uses "Have you given up on…?" for silence; the Copywriter restricts it to tested variants after engagement (CW-044, CW-034).
- Source: [S1 "If someone replied once and then goes quiet"], [S19], [S18], [S6 CW-016, CW-034, CW-044]
- Check: deterministic (`R18_followup_dates`, `R17_whatsapp_window_and_cap`); ab_test (no-oriented variants)
- Example: Jab 2 sent Mon 9 Nov → nudges Wed 11, Fri 13 (WhatsApp), Thu 19 Nov by email (WhatsApp cap) → `warm`, check-in 19 Dec.
- Default or locked: default (days); **locked** (the WhatsApp cap)

### CM-039 · Lead states when nobody replies
- Rule: Apply the SOP table:
  - 7 touches, no open, view or accept → `cold`: pause `followup.cold_pause_days` (60), ask the Proxy Researcher for fresh research, restart at day 1 with the new result.
  - 7 touches, engaged (opened, viewed, accepted) but no reply → `warm`: one more touch at day 30 with a new fact, then `cold`.
  - Said no → `lost`, reason in their words, no more touches.
  - Asked to stop → `do_not_contact`, never contacted again on any channel.
  Only legal transitions in `domain/lead_states.py` are used; `lost` and `do_not_contact` are never reopened by the agent.
- Why: The SOP's "When a lead stops being worked" table; the state machine is code. Email open tracking is off (CO-028), so "engaged" on email relies on replies, link views of the report, or LinkedIn accepts.
- Source: [S1 table], [S5 `domain/lead_states.py`], [S6 CO-028]
- Check: deterministic (`R19_state_after`)
- Example: 7 touches, LinkedIn invite accepted, no reply → `warm`, day-30 touch with a new finding, then `cold`.
- Default or locked: default (timings); **locked** (`do_not_contact` and `lost` are terminal for the agent)

### CM-040 · The stop rule: stop talking when the job is done or progress stops
- Rule: Stop sending automated replies on a thread and hand over (`stop_rule`) when: a meeting is booked; the report has been delivered and a next step is set; or `stop_rule.max_automated_replies_without_progress` (3) automated replies in a row have not moved the lead forward (no new state, no booking, no referral). Never keep chatting for its own sake.
- Why: DubiCars lesson: the agent kept talking after it had enough; the fix is a stop rule (enough → hand over). The threshold is ours.
- Source: [S2 §10 "Too much chatting"]
- Check: deterministic (`R20_stop_rule`)
- Example: Three exchanges of questions about Arabic support without progress → handover with a summary.
- Default or locked: **locked** (a stop rule exists); default (the count)

## E. Meetings, data, accounts and decisions

### CM-041 · Every meeting goes to the closer with a one-page brief
- Rule: When a booking is confirmed, send the company owner a brief with: the company page (report and rank), the person card, the full thread on every channel, the classification history, and what they said they want. A meeting without all three of company page, person card and thread is not handed over; it is flagged.
- Why: The closer's acceptance rule.
- Source: [S1 Hands over; acceptance rule · the closer; booking section]
- Check: deterministic (`R24_meeting_brief`)
- Example: Booking for Thu 11:00 → brief with `company_page`, `person_card`, `thread` links to Ali.
- Default or locked: **locked**

### CM-042 · Reminders and no-shows
- Rule: Reminders 24 h and 1 h before the meeting, by email and WhatsApp (where verified), each through the gates and allowed hours; a no-show gets one reschedule message with the booking link within 10 minutes of the missed start. A second no-show → handover.
- Why: SOP booking section; the KPI includes 80% of meetings attended. The second-no-show handover is ours.
- Source: [S1 booking section; KPI]
- Check: deterministic (`R18_followup_dates`, `R16_gates_and_hours`)
- Example: Meeting Thu 11:00, no join by 11:00 → reschedule message by 11:10 with the link.
- Default or locked: default

### CM-043 · Data requests: erase everywhere, show the source, hand over
- Rule: "Delete my data / my number" → run erasure (`paralax erase`) on every channel at once, plus the opt-out steps (CM-011). "Who gave you my number?" or "what data do you have on me?" → hand over (`personal_data_request`) with the contact point's recorded `source` and `collected_at` attached, so the human can answer truthfully; the agent does not answer it itself. A correction about someone else ("remove Ahmed, he left") marks that person's contact point as stale and queues re-verification; it does not suppress the sender.
- Why: Guardrail 7 (personal data deleted on request) and owner decision D3 (honour deletion requests across all channels immediately; store source and date). PDPL Arts. 15 and 17. Personal-data requests are on the escalation list.
- Source: [S2 §3 guardrails 7, 11], [S3 D3], [S12 Arts. 15, 17], [S6 CF-040, CF-044]
- Check: deterministic (`R27_data_requests`, `R11_handover_triggers`)
- Example: "Who gave you my number?" → no reply from the agent; task with `source: lusha:req-8812, collected_at: 2026-11-09T09:10Z`.
- Default or locked: **locked**

### CM-044 · Blocks and reports seen by the adapter
- Rule: When the channel adapter reports a block, a report or a sudden undeliverable state right after our message to this person, record the account signal (`block` or `report`), suppress the person everywhere, and stop the thread. Never continue the conversation from another account.
- Why: Locked guardrails: automatic resting on bans, blocks and complaints; extra accounts are never used to keep messaging people who blocked or reported. The Channel Operator's CO-042 does the resting; this agent's job is to feed it and stop.
- Source: [S3 C], [S2 §3 guardrail 6], [S6 CO-042, CO-047], [S8]
- Check: deterministic (`R05_complaint_signal`, `R25_no_cross_account`)
- Example: WhatsApp shows the dealer blocked Ali's number → signal `block`, dealer suppressed, no email follow-up.
- Default or locked: **locked**

### CM-045 · A thread stays on its account; a banned account's threads are not continued
- Rule: Reply only from the account that holds the thread. If that account is banned, suspended or paused, do not continue the thread from another account; hand over (`banned_account_thread`).
- Why: Locked guardrail: a banned account's threads are never continued from another account (CO-004, CO-014).
- Source: [S3 C], [S6 CO-004, CO-014]
- Check: deterministic (`R25_no_cross_account`)
- Example: Harman's number is banned while a dealer asks "send it" → task to Harman; no message from Ronit's number.
- Default or locked: **locked**

### CM-046 · Departures from the defaults are proposals
- Rule: Anything outside these defaults (a voice note or video reply, a different follow-up count or cadence, contacting a paused colleague, a new label, a different confidence threshold, a channel switch) is a Gate 4 decision proposal with what, why, evidence from the thread, expected effect, cost, risk and the default fallback. Nothing happens until a human approves. Never propose anything that breaks a locked rule, and never propose changing a `campaign.` owner switch.
- Why: PROJECT_CONTEXT §3a; `campaign.` keys are locked in `services/decisions.py`.
- Source: [S2 §2 #9, §3a], [S3 B], [S6 CW-059]
- Check: deterministic (`R29_proposal_well_formed`)
- Example: A dealer asked "can you show me how it would answer in Arabic?" → proposal: a 60-second demo video as the reply; fallback: the text reply plus handover.
- Default or locked: **locked** (the mechanism)

### CM-047 · KPIs the Analyst can trace
- Rule: Log per reply: arrival time, label, confidence, action, response time in working minutes, handover reasons, state after; per lead: positive reply → meeting conversion; per meeting: attended or not. The Analyst computes: reply-to-meeting rate (positive replies → meetings, target 25%), median response time (target < 15 working minutes), attendance (target 80%), handover rate by reason, classification corrections by humans (every correction becomes a test case).
- Why: SOP KPI; the Analyst's acceptance rule (every dashboard number traces to a log entry); the training method grows the test set from real mistakes.
- Source: [S1 KPI; Agent 12 acceptance rule], [S2 §9]
- Check: deterministic (`R30_kpi_measured`)
- Example: 12 positive replies, 3 meetings → 25% (target met); 2 human relabels this week → 2 new test cases.
- Default or locked: **locked** (logging); default (targets)

### CM-048 · Corrections about other people are data, not opt-outs
- Rule: When a replier corrects data about someone else (left the company, wrong title, "stop emailing Ahmed, he's gone"), stop touches to that other person, mark their contact point stale and queue re-verification with the Contact Finder, and continue the replier's own thread according to their label. Do not suppress the replier.
- Why: The replier did not ask to stop; the colleague's details are now wrong, and messaging a departed person's mailbox wastes touches and risks bounces.
- Source: [S6 CF-017, CF-018], [S1 Standards]
- Check: deterministic (`R04_suppression_scope`, `R01_label_correct`)
- Example: "yes please send. also please remove my colleague Ahmed from your emails, he left" → `positive`; Ahmed's email stale, his touches cancelled; jab 2 to the replier.
- Default or locked: default

### CM-049 · No time promises in an automated draft
- Rule: An automated draft never promises a time: not "today", "tonight", "this afternoon", "within the hour", a weekday or a clock time. Use "shortly" or "during working hours". Only a human who has actually committed to a time may name one, in a message they send themselves.
- Why: Owner decision of 10 Nov 2026. A promise the system makes on a person's behalf can be broken (the owner is busy, it is late, it is the weekend), and a broken promise in the first reply costs more trust than a vague but true one.
- Source: owner decision 10 Nov 2026 (docs/decisions/2026-11-09-owner-decisions.md, part 6); [S2 §3 guardrail 11]
- Check: deterministic (`R12_never_negotiate_book_visit`: the draft-text check `NEVER_IN_DRAFT` refuses any "will ... today" style promise in English or Arabic)
- Example: "How much does it cost?" → "Good question, Sam will come back to you on that shortly." Not: "... today."
- Default or locked: locked

---

## Output schema (per inbound message)

```yaml
message_id: str
lead_id: str
channel: email|whatsapp|linkedin
language: en|ar|mixed|arabizi|other
label: opt_out|complaint|bot_question|meeting_request|positive|question|objection|referral|wrong_person|not_now|not_interested|auto_reply|unclear
also: [labels]
confidence: float                     # CM-031
detector_opt_out: bool                # result of domain/optout.detect_inbound_opt_out (CM-004)
spans: [str]                          # the words that drove the label
actions:
  suppress: none|person|company       # CM-011, CM-012
  erase: bool                         # CM-043
  account_signals: [complaint|block|report]   # CM-010, CM-044
  company_lock: kept|released_auto_reply      # CM-008, CM-014
  route_to: [contact_finder|buyer_mapper]     # CM-019, CM-020, CM-048
  handover: {reasons: [..], task_id?: str}    # CM-028
reply:
  allowed: true|false|confirmation_only|holding_line
  language: en|ar|null
  draft_id: str|null                  # goes through the 8 gates (CM-035)
  send_at: ISO-8601|null              # allowed hours + chat delay (CM-034, CM-035)
lead_state_after: replied|warm|meeting_booked|lost|cold|do_not_contact|unchanged
followup: {at: ISO-8601|null, kind: nudge|not_now|warm_checkin|resume_after_ooo|null}
rules: [CM-0xx]
version: {playbook: "1.0", defaults_sha256: str}
```
