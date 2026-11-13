"""The eval harness over ALL 53 ReplyGuard cases with the test FakeLLM (canned classifier readings
and three free-form drafts) and a fixed judge: every case passes, all 30 rubric checks pass on every output
(the "always" ones included), and the classification metrics meet pass.yaml. Without a model the agent fails
its eval, so it is never qualified for live jobs."""

from __future__ import annotations

from paralax.agents.replyguard import agent as cm_agent  # noqa: F401  (registers agent + checks)
from paralax.agents.replyguard.checks import ALL_CHECKS
from paralax.agents.replyguard.kpis import classification_metrics, metrics_pass
from paralax.agents.knowledge import KnowledgeBase
from paralax.llm import FakeLLM
from paralax.training import is_qualified, run_eval
from paralax.training.hard_checks import CheckInput, case_checks, registered_checks, run_check
from tests.canned import FixedJudge, eval_llm

KB = KnowledgeBase.load("replyguard")


def test_every_rubric_check_is_registered() -> None:
    names = {str(h["id"]) for h in KB.rubric["hard_checks"]}
    assert len(names) == 30 and names == set(ALL_CHECKS)
    names |= {n for c in KB.cases for n, _ in case_checks(c, KB.rubric)}
    names |= set(KB.pass_rules["hard_checks"]["locked_rule_checks"])
    assert names <= set(registered_checks("replyguard"))


def test_eval_over_all_53_cases_passes(session, clock) -> None:
    judge = FixedJudge()
    llm = eval_llm()
    run = run_eval(session, "replyguard", llm=llm, clock=clock, judge=judge)
    res = run.results
    assert res["summary"]["cases"] == 53 and not res["partial"]
    failed = {
        cr["id"]: (cr["errors"], [h for h in cr["hard"] if not h["passed"]])
        for cr in res["cases"]
        if not cr["passed"]
    }
    assert failed == {}
    assert run.passed is True and res["summary"]["hard_pass_rate"] == 1.0
    assert judge.calls == 53
    assert is_qualified(session, "replyguard", llm.model_config_hash())

    # every one of the 30 checks (the "always" ones are not selected by `reads`) on every output
    cases = {c["id"]: c for c in KB.cases}
    for cr in res["cases"]:
        for name in ALL_CHECKS:
            r = run_check(
                name,
                CheckInput(case=cases[cr["id"]], output=cr["output"], now=clock.now()),
                agent="replyguard",
            )
            assert r.passed, (cr["id"], name, r.message)

    # M1-M4 against pass.yaml (accuracy >= 0.90, safety recall 1.0, opt-out precision, auto-reply precision)
    metrics = classification_metrics(KB.cases, {cr["id"]: cr["output"] for cr in res["cases"]})
    assert metrics["labelled_cases"] == 52
    assert metrics_pass(metrics, KB.pass_rules) == []
    assert metrics["M2_safety_recall"] == 1.0


def test_without_a_model_the_agent_fails_its_eval_and_is_not_qualified(session, clock) -> None:
    llm = FakeLLM({}, label="no-model")  # every call raises LLMUnavailable, as with no OPENAI_API_KEY
    run = run_eval(session, "replyguard", llm=llm, clock=clock, judge=FixedJudge())
    assert run.passed is False
    assert not is_qualified(session, "replyguard", llm.model_config_hash())
    # it still never misses a detector opt-out or answers anything it could not read
    for cr in run.results["cases"]:
        out = cr.get("output") or {}
        if out.get("detector_opt_out"):
            assert out["actions"]["suppress"] != "none"
        if out.get("classified_by") == "rules_only" and out.get("label") not in ("opt_out", "bot_question"):
            assert not (out.get("reply") or {}).get("body"), cr["id"]
