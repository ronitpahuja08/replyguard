# ReplyGuard (ReplyGuard): sources

Every rule in `PLAYBOOK.md` cites one or more of these by id. All web sources were accessed on **10 Nov 2026**. Quotes are kept under 15 words; everything else is paraphrased. **Vendor figures are vendor claims.**

**Status** (the four-level scale of `docs/research/SOURCES_OVERVIEW.md`, used directly):
- **primary**: the original page, RFC, law text, document or internal file was read.
- **partial**: only part was read (abstract, teaser), or the page was read but is inconsistent or does not say which data backs which claim.
- **secondary**: known only through someone else's summary (law firms, unofficial reproductions of law, third-party guides).
- **not verified**: cited but not read.

Pages were read through an automated fetcher. leginfo.legislature.ca.gov and law.justia.com returned 403; the Huthwaite PDF was extracted locally with pypdf. Some siblings label law-firm summaries of the UAE PDPL as primary (Buyer Mapper S43, Contact Finder S27); this file labels the same kind of page **secondary**, because the law text itself was not read.

---

## Internal

**[S1] Paralax Outreach OS SOP V3 (5 Nov 2026), `docs/SOP-V3-snapshot.txt`, agent 11 (and the agent 10 and 12 acceptance rules).** What we used:
- Job, receives, hands over, the closer's acceptance rule (company page, person card, full thread), ReplyGuard's own acceptance rule (every reply arrives with person, company, message answered and thread).
- KPI: reply-to-meeting rate, median response under 15 minutes, 80% of meetings attended, 25% of positive replies → meetings.
- The reply table (yes / question / let's talk / later / talk to colleague / not interested / stop → next message → state).
- Three nudges on days 2, 5 and 10 after a replier goes quiet, then Warm with a 30-day check-in; the no-reply 19-day schedule; "any reply from anyone at the company pauses everyone there".
- The "when a lead stops being worked" table (Cold, Warm, Lost, Do not contact).
- Booking: scheduling link, brief to the owner, reminders 24 h and 1 h, no-show reschedule within 10 minutes.
- Standards: one shared inbox, one owner per company; reply in their language; never argue with a no.

*Status: primary.*

**[S2] Project context, `docs/PROJECT_CONTEXT.md`.** §2 decisions #9 (defaults, not fixed rules), #12 (reply as fast as possible, no fixed timelines), #14, #16 (UAE law); §3 guardrails 4 (evidence only), 6 (never use extra accounts for people who blocked, reported or opted out), 7 (do-not-contact on every channel, immediately; delete on request), 9 (truthful if asked "are you a bot?"; never negotiate, pay, book or visit), 10, 11 (escalation list); §3a (decision log, proposals); §5 lead states; §6 agent 11; §9 training method; §10 DubiCars lessons ("human vs bot misclassification", "too much chatting" → stop rule). *Status: primary.*

**[S3] Owner decisions, `docs/decisions/2026-11-09-owner-decisions.md`.** A2 (UAE hours Mon–Fri 09:00–18:00 Asia/Dubai, provisional), A3 (HBR "Short Life of Online Sales Leads" figures banned from messages), B (owner switches, incl. B1 cold WhatsApp and B4 `arabic_auto_send`; agents never propose `campaign.` changes), C (locked guardrails: opt-out line, STOP on every channel and account, resting on blocks and complaints, complaint spike pauses the pool, banned threads never continued, platform limits, evidence-only, allowed hours), D2 (Cabinet Resolution 56/2024 rules applied to WhatsApp, pending legal review), D3 (deletion across all channels; source and date for every contact), G4 (booking link before Day 5). *Status: primary.*

**[S4] Revised build plan, `docs/BUILD_PLAN_REVISED_2026-11-10.md`.** ReplyGuard scope for Day 4: classify each reply (STOP / complaint / not interested / question / positive / out of office / "are you a bot?"); STOP suppressed on every channel; complaint or block → account-health signal; any reply → company paused; drafts through the same gates; escalations as tasks; fixed rules (never negotiates, pays, books or visits; truthful "yes, this is automated"); booking requests to a human until the link exists; replies polled once a minute, webhook planned; ~30 labelled chats for the reply classifier. *Status: primary.*

**[S5] Internal code (read 10 Nov 2026).** `domain/optout.py` (outbound opt-out lines; `detect_inbound_opt_out`: English and Arabic keyword and phrase rules, Arabic normalisation), `compliance/uae.py` (`UAE_RULES`: hours, opt-out lines, WhatsApp `max_unanswered: 2`, `detect_opt_out`), `orchestrator/inbound.py` (detector → `suppress_person_everywhere` + `do_not_contact` + cancel jobs; otherwise company lock + `replied`), `orchestrator/gates/dnc.py` (suppression of person, company and contact points; lead state; `dnc:company_locked` unless a reply), `domain/lead_states.py` (legal transitions; `lost`/`do_not_contact` terminal for automation), `domain/suppression.py`, `orchestrator/account_health.py` (`record_account_signal`, `SIGNAL_KINDS`: complaint, block, report, warning, restriction, banned, suspended; WhatsApp triggers count block/report). The detector was run on this playbook's test phrases to record `detector_opt_out` in every test case. *Status: primary.*

**[S6] Sibling knowledge bases (internal).** Copywriter v1.3 (CW-009 referrals, CW-013 jab 2, CW-016, CW-017 WhatsApp cap, CW-018 company pause and language, CW-023, CW-024 opt-out line, CW-025, CW-027 word limits, CW-032, CW-034, CW-041–CW-047, CW-053, CW-056–CW-060); Channel Operator (current, incl. CO-057 v1.3) (CO-004 banned threads, CO-005 complaint spike, CO-014 one sender per company, CO-028, CO-029 bounces, CO-031, CO-041 two unanswered, CO-042 block/report, CO-045 pacing, CO-047 quality, CO-049 Cloud API window, CO-050 no WhatsApp calls in the UAE); Contact Finder v1.3 (CF-001 verified only, CF-017, CF-018, CF-029, CF-040 erasure, CF-044 source and date, CF-045). Their external sources are not re-counted here. *Status: primary.*

## Email and platforms

**[S7] Moore, K. RFC 3834, Recommendations for Automatic Responses to Electronic Mail (Aug 2004).** https://www.rfc-editor.org/rfc/rfc3834.html. What we used:
- §5.1–5.2: `Auto-Submitted` values `no`, `auto-generated`, `auto-replied`; any value other than `no` means the message was not sent by a person.
- §2: responders must not answer every message, should not answer messages whose `Auto-Submitted` is not `no`, may refuse `Precedence: list`/bulk; one absence reply per sender per period (7 days suggested).
- §3.1.5: an "Auto:" subject prefix is a hint, not proof.

*Status: primary.*

**[S8] WhatsApp Business Messaging Policy (last updated 23 Sep 2026).** https://whatsappbusiness.com/hi/policy/ (Hindi locale; the policy's English page redirects here). What we used:
- Businesses must honour requests to block, end a conversation or stop messages, made on or off WhatsApp, including removal from a contact list.
- Automation may be used when responding inside the 24-hour window; a prompt, clear, direct escalation path to a human is required (in-chat transfer, phone, email, web support, store, form).
- Within 24 hours of a user's message a business may reply without a template; afterwards only approved templates.
- Users can block or report a business; feedback can limit how many people the business can message.

*Status: primary.* (The same policy is Copywriter S30 and Channel Operator S25.)

**[S9] Meta for Developers, WhatsApp Business Platform pricing: customer service window.** https://developers.facebook.com/docs/whatsapp/pricing. What we used: a 24-hour customer service window opens when a user messages or calls and resets on each new message; non-template messages only while it is open; templates outside it; message only users who opted in. No page date; reflects pricing changes effective 1 Oct 2026. *Status: primary.*

**[S10] Google, Email sender guidelines.** https://support.google.com/a/answer/81126. What we used: one-click unsubscribe (`List-Unsubscribe-Post`) mandatory for senders over 5,000 a day; keep spam rate below 0.10% and never reach 0.30%. The page gives **no** number of days to honour an unsubscribe. *Status: primary.*

**[S11] Yahoo, Sender Best Practices.** https://senders.yahooinc.com/best-practices/. What we used: "Honor unsubscribes within 2 days"; keep spam rate below 0.3%. *Status: primary.*

## UAE law

**[S12] DLA Piper, Data Protection Laws of the World: UAE (last modified 27 Jan 2025).** https://www.dlapiperdataprotection.com/countries/uae-general/law.html. What we used: PDPL (Federal Decree-Law 45/2021) Art. 17, right to object to processing for direct marketing (incl. profiling); Art. 15, erasure; no general electronic-marketing law; TDRA's Unsolicited Electronic Communications rules apply to licensees and define spam as marketing without consent; TMTM Law (Decree-Law 14/2023) Art. 6; Cabinet Decision 56/2024 Art. 4 consent for marketing via social media. A law firm's summary; the law texts were not read (uaelegislation.gov.ae returned 403 to siblings). *Status: secondary.*

**[S13] Helou, N. (Rouse), "New Telemarketing Regulations Introduced in UAE", Legal 500, 23 Jul 2024.** https://www.legal500.com/intelligence/united-arab-emirates/media-telecoms-it-entertainment/new-telemarketing-regulations-introduced-in-uae. What we used: Cabinet Resolution 56/2024 covers marketing calls and messages via social-media apps; explicit consent first; calling hours 09:00–18:00; TDRA do-not-call register; record-keeping; penalties in Resolution 57/2024. The article does not say what happens after a refusal. *Status: secondary.*

**[S28] TDRA, Unsolicited Electronic Communications regulatory policy (official text).** Cited only through [S12]; tdra.gov.ae was not opened. Not used for any number. *Status: not verified.*

## Speed to lead

**[S14] Lead Response Management study page (InsideSales.com data, with J. Oldroyd), leadresponsemanagement.org.** http://www.leadresponsemanagement.org/lrm_study. What we used: 3 years of data from 6 companies, 15,000+ web leads, 100,000+ call attempts; qualification odds fell 21-fold between 5 and 30 minutes; contact success fell sharply in the first hour. The page contradicts itself ("more than tenfold" vs "100-fold" for contact; inconsistent time-of-day baselines), carries unrelated ads, and the dataset is not published. Used only as directional support for "reply fast"; **no figure is used in a rule or a message**. *Status: partial.*

**[S15] Oldroyd, McElheran & Elkington (2011), "The Short Life of Online Sales Leads", HBR (March 2011).** https://hbr.org/2011/03/the-short-life-of-online-sales-leads. Only the teaser is readable (most companies do not respond fast enough); the body is paywalled. **Owner decision A3: its figures are banned from messages.** Cited to explain why no speed figure appears in replies. *Status: partial.* (Same work as Copywriter S6, Proxy Researcher S5, Report Builder S15.)

## Sales methods for replies

**[S16] Huthwaite International, "The Science behind SPIN Selling" (whitepaper, 2025).** https://www.huthwaiteinternational.com/hubfs/Whitepapers%20-%202025/Whitepaper%20PDFs/The%20Science%20behind%20SPIN%20Selling.pdf (text extracted and read for the passages used). What we used:
- Closing techniques are counter-productive in major sales; top performers propose the highest realistic commitment the customer can give.
- Highlighting features causes more objections: offering features and imagined advantages of little value is the easiest way to create objections and price concerns.
- The benefit statement most associated with success shows how the product meets an explicit need the customer stated.
- Implication and need-payoff questions (via Copywriter S40, same document).

The research firm's own document, not Rackham's text; no effect sizes. *Status: primary.* (Same document as Copywriter S40.)

**[S17] Voss, C. (23 Dec 2019), "Labels vs. Questions: The Key to Unlocking the Floodgates of Truth Talk", Black Swan Group.** https://www.blackswanltd.com/the-edge/labels-vs.-questions-the-key-to-unlocking-the-floodgates-of-truth-talk. What we used: pair each calibrated (what/how) question with a label; label first, then the question; "It seems" / "It sounds like" leave room to be wrong; calibrated questions can feel like traps to some counterparts. The article says nothing about avoiding "why"; we don't use that claim. *Status: primary.*

**[S18] Voss, C. (16 Sep 2019), "How Expert Negotiators Use 'No' to Close", Black Swan Group.** https://www.blackswanltd.com/newsletter/how-expert-negotiators-use-no-to-close. What we used: "yes" is often given out of politeness; a "no" makes people feel safe and in control; no-oriented questions ("Is now a bad time?"). *Status: primary.* (Same as Copywriter S50.)

**[S19] Voss, C. (23 Oct 2025), "The Magic Label: 'Have You Given Up On ___?'", Black Swan Group.** https://www.blackswanltd.com/newsletter/the-magic-label-have-you-given-up-on-_____. What we used: for silence after follow-ups; invites an easy "no"; draws attention to loss (so we limit it to tested variants, CW-034). *Status: primary.* (Same as Copywriter S51.)

**[S20] A Sales Growth Company (Keenan), "Gap Selling Method".** https://salesgrowth.com/gap-selling-method/. What we used: current state, future state, the gap where value lives; buyers "live with the limp"; discovery that becomes a feature dump builds no value; negotiating price to cover missing value loses. The page has no section on objections; linking objections to weak discovery is our reading. *Status: primary* (author's company page). (Same as Copywriter S41.)

**[S21] Orlob, C., Gong, "Objection handling techniques" (published 27 Apr 2018, modified 6 Mar 2026).** https://www.gong.io/blog/objection-handling-techniques. What we used: successful reps pause longer after an objection; they use questions to handle objections, while low performers answer with a long monologue; flustered reps speed up (173 → 188 words per minute). Vendor data; the post cites 67,149 meetings but does not say which finding comes from which dataset. *Status: partial.*

## Automation disclosure

**[S22] Regulation (EU) 2024/1689 (AI Act), Art. 50, EUR-Lex.** https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng. What we used: Art. 50(1) providers must design AI systems that interact with people so those people are informed they are interacting with an AI system, unless obvious; Art. 50(5) the information is given clearly at the latest at the first interaction. Applies to EU recipients; not to the UAE. *Status: primary.*

**[S23] artificialintelligenceact.eu, Article 50 page (Future of Life Institute reproduction).** https://artificialintelligenceact.eu/article/50/. What we used: Article 50 applies from 2 August 2026 (Art. 113); the official Art. 113 text was not reached in our EUR-Lex read. *Status: secondary.*

**[S24] California Business and Professions Code §17941 (SB 1001, 2018), via california.public.law.** https://california.public.law/codes/business_and_professions_code_section_17941. What we used: unlawful to use a bot to communicate online with intent to mislead about its artificial identity to incentivise a sale or influence a vote; no liability if the bot is disclosed clearly and conspicuously. The official site returned 403; AB 410 (2025–26) may amend it (status not checked). *Status: secondary.*

## Classification difficulty

**[S25] Joshi, A., Bhattacharyya, P. & Carman, M. J. (2016), "Automatic Sarcasm Detection: A Survey", arXiv:1602.03426.** https://arxiv.org/abs/1602.03426. What we used (abstract): sarcasm is prevalent and hard for sentiment analysis; progress relied on context beyond the target text. *Status: partial* (abstract).

**[S26] Abu Farha, I. & Magdy, W. (2020), "From Arabic Sentiment Analysis to Sarcasm Detection: The ArSarcasm Dataset", OSACT4 (LREC 2020 workshop), pp. 32–39.** https://aclanthology.org/2020.osact-1.5. What we used (abstract): 10,547 tweets, about 16% sarcastic, annotated for dialect; sentiment labels shifted with annotators' biases; BiLSTM baseline F1 0.46. Dialect list (incl. Gulf) from the dataset card via search, not the abstract. *Status: partial* (abstract).

**[S27] Third-party guides to WhatsApp Business app greeting and away messages (e.g. wati.io, setsmart.io; search results, 10 Nov 2026).** What we used: the free Business app has a greeting message (first contact, and again after 14 days without contact), a scheduled away message, and manual quick replies. No page on faq.whatsapp.com was found or read. *Status: secondary.*

---

### Not found or not verified
- **A peer-reviewed B2B speed-to-lead study.** Only the vendor-associated LRM page [S14] and the paywalled HBR article [S15]. Every circulating multiplier (21x, 100x, 391%, 78%) is unverified for our purposes and banned from messages (A3).
- **Gulf Arabic opt-out and reply phrases.** The phrase lists in `defaults.yaml` are ours; no dialect source was found, and no native Gulf speaker has reviewed them (accepted risk B4). Every real miss becomes a test case.
- **WhatsApp's own help page on away and greeting messages** [S27 is third-party].
- **Official texts** of the PDPL, Cabinet Resolution 56/2024, the TDRA policy [S28] and California §17941 (403s). All law points rest on law-firm or unofficial reproductions, except the EU AI Act [S22].
- **Rackham's own text on objection prevention.** Only Huthwaite's whitepaper [S16]; book excerpts were unreachable.
- **What Unipile reports when a WhatsApp user blocks or reports a number.** CM-044 relies on what the adapter can see; to be checked on the live account.
- **Our own values** (not sourced): confidence threshold 0.80, chat delay 60–240 s, out-of-office resume offsets (1 working day after return; 7 days without a date), not-now default 30 days, stop rule after 3 automated replies without progress, WhatsApp auto-reply timing 10 s, second-no-show handover.
