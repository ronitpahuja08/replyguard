"""What the LLM returns: the classification of one reply and a drafted reply (pydantic, validated)."""

from __future__ import annotations

from pydantic import BaseModel, Field

LABELS = (
    "opt_out",
    "complaint",
    "bot_question",
    "meeting_request",
    "positive",
    "question",
    "objection",
    "referral",
    "wrong_person",
    "not_now",
    "not_interested",
    "auto_reply",
    "unclear",
)


class Person(BaseModel):
    name: str = ""  # Latin spelling
    name_original: str = ""  # as written (e.g. Arabic script)
    role_hint: str = ""
    email: str = ""


class OtherPerson(BaseModel):
    """A correction about someone else (CM-048): 'remove Ahmed, he left'."""

    name: str = ""
    issue: str = "left_company"  # left_company | wrong_title | wrong_contact


class Timing(BaseModel):
    """When they want to hear from us (CM-022) or when they are back (CM-008)."""

    kind: str = "none"  # none | date | weekday | quarter | relative_days | anchor
    value: str = ""  # ISO date | monday..sunday | Q1..Q4 | "14" | after_eid_al_fitr / after_eid_al_adha / ...
    text: str = ""  # their words


class Classification(BaseModel):
    label: str
    also: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    spans: list[str] = Field(default_factory=list)
    language: str = "en"  # en | ar | mixed | arabizi | other (name the language in `language_name`)
    language_name: str = ""
    sarcasm_suspected: bool = False
    speaks_for_company: bool = False  # "don't contact us" (CM-012)
    deletion_request: bool = False  # "delete my number / data" (CM-043)
    stated_signals: list[str] = Field(default_factory=list)  # report | block, when they SAY they did it
    handover_reasons: list[str] = Field(default_factory=list)  # from defaults.handover.reasons
    referral: Person | None = None  # a named colleague or an alternate contact
    other_person: OtherPerson | None = None
    left_company: bool = False
    timing: Timing | None = None
    reasoning: str = ""
    rule_ids: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    text: str
    source: str  # findings | company_report | brief_offer | offer_allow_list | approved_faq | thread
    ref: str = ""  # finding id, report id, "offer", or the thread item index


class Draft(BaseModel):
    body: str
    subject: str = ""
    claims: list[Claim] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
