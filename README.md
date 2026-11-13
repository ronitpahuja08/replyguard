# ReplyGuard

ReplyGuard is a policy-first conversation agent for B2B outreach. It classifies inbound replies, gives safety intents priority, decides whether automation is allowed, drafts constrained responses, and routes uncertain or sensitive conversations to a human.

The project is designed around one principle: a reply should never be sent merely because a model can produce one. Deterministic rules decide what may happen; language models are limited to classification and drafting inside those boundaries.

## What it handles

- opt-outs and deletion requests across English, Arabic, mixed-language, and Arabizi messages
- complaints, bot questions, referrals, objections, meeting requests, and automatic replies
- company-wide contact locks and do-not-contact decisions
- channel-aware pacing, working hours, follow-up caps, and stop rules
- human handover when confidence is low or a request involves pricing, legal, or sensitive data
- hard-check evaluation using labelled positive and negative cases

## Processing flow

```text
inbound reply
    -> deterministic safety signals
    -> structured intent classification
    -> rule-based decision engine
    -> constrained draft or human handover
    -> audited side effects and follow-up plan
```

## Repository layout

- `replyguard/` — schemas, signal extraction, decision rules, reply construction, timing, effects, and KPI helpers
- `replyguard/playbook/` — the cited operating rules and change history
- `replyguard/examples/` — worked good and bad outcomes
- `replyguard/testset/` — labelled multilingual evaluation cases and pass criteria
- `tests/` — unit, integration, and evaluation coverage from the original host application

## Integration note

This repository is an extracted agent module, not a complete outreach platform. Database models, queues, provider adapters, and the agent registry are supplied by its host runtime and are intentionally not duplicated here. The portable policy engine, schemas, fixtures, evaluation set, and integration contracts are included so the behavior can be inspected and adapted.

All names, companies, domains, contact details, and conversations in the fixtures are synthetic.

## Safety model

Safety labels always outrank commercial intent. Detector hits cannot be cleared by a model, automated replies cannot override a human-looking message, and uncertain classifications produce a handover instead of an optimistic response. Drafts are checked for unsupported claims, hidden automation, pricing, and channel limits before they can be queued.

## License

MIT
