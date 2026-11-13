"""ReplyGuard, the ReplyGuard: turns every reply on our threads into the right next step.

``agent.py`` registers the agent (job kind ``agent.replyguard``); ``effects.py`` is its after-run
hook (the single place that writes: suppression, account signals, the reply draft, follow-ups).
"""
