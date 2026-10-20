"""Systematic Prediction Challenge: check a prompt before submitting it, keep the record.

BRAIN has no public API for SPC submissions, so nothing here calls the platform. See
:mod:`alpha_harness.spc`.
"""

import asyncio
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..schemas import Out
from ..spc import validation as rules
from ..spc.drafts import Draft, DraftStore
from .deps import State, refuse

router = APIRouter(prefix="/api/spc", tags=["spc"])

#: Generous bounds on what is accepted, so an oversized body is a 422 and a prompt a little
#: over BRAIN's own limit is still checked and reported on rather than refused outright.
PROMPT_CAP = 50_000
SAMPLE_CAP = 500_000
MAX_EXTRA_RUNS = 5


class SubmissionFields(BaseModel):
    """The form's seven fields, in the order BRAIN's form asks for them."""

    name: Annotated[str, Field(max_length=300)] = ""
    prompt: Annotated[str, Field(max_length=PROMPT_CAP)] = ""
    model: Annotated[str, Field(max_length=100)] = "Claude"
    model_version: Annotated[str, Field(max_length=300)] = ""
    frequency: Annotated[str, Field(max_length=20)] = "Daily"
    weight: float = 0.3
    sample_output: Annotated[str, Field(max_length=SAMPLE_CAP)] = ""


class ValidateRequest(SubmissionFields):
    #: Further runs of the same prompt in fresh chats, to compare with the sample.
    extra_runs: Annotated[
        list[Annotated[str, Field(max_length=SAMPLE_CAP)]], Field(max_length=MAX_EXTRA_RUNS)
    ] = []
    #: The draft being edited, left out of the overlap comparison.
    draft_id: str | None = None


class IssueOut(Out):
    level: str
    code: str
    message: str
    where: str | None


class StatsOut(Out):
    count: int
    long: int
    short: int
    gross: float
    net: float
    distinct_isins: int
    median_horizon: int | None


class StabilityOut(Out):
    runs: int
    identical: bool
    min_overlap: float
    max_confidence_shift: float
    unstable_names: list[str]


class OverlapOut(Out):
    draft_id: str
    name: str
    status: str
    shared: int
    overlap: float


class Report(Out):
    #: True when nothing blocks submitting. Warnings do not block.
    ready: bool
    issues: list[IssueOut]
    stats: StatsOut | None
    stability: StabilityOut | None
    overlaps: list[OverlapOut]


class DraftOut(Out):
    id: str
    name: str
    model: str
    model_version: str
    frequency: str
    weight: float
    prompt: str
    sample_output: str
    status: str
    created_at: str
    updated_at: str
    submitted_at: str | None
    names: int


class Limits(Out):
    active: int
    max_active: int
    today: int
    max_per_day: int
    #: Distinct instruments across active submitted prompts, against the 500 BRAIN asks for.
    coverage: int
    coverage_target: int


class Drafts(Out):
    drafts: list[DraftOut]
    limits: Limits
    models: list[str]
    frequencies: list[str]


def _store(state: State) -> DraftStore:
    return DraftStore(state.settings.data_dir)


def _isins(sample: str) -> set[str]:
    return {e.isin for e in rules.parse_output(sample).entries}


def _out(draft: Draft) -> DraftOut:
    return DraftOut.model_validate(
        asdict(draft) | {"names": len(rules.parse_output(draft.sample_output).entries)}
    )


def _limits(drafts: list[Draft]) -> Limits:
    today = datetime.now().astimezone().date()
    submitted = [d for d in drafts if d.status == "submitted"]
    active = [d for d in submitted if d.weight > 0]

    def on_today(d: Draft) -> bool:
        return (
            bool(d.submitted_at)
            and datetime.fromisoformat(d.submitted_at or "").astimezone().date() == today
        )

    covered: set[str] = set()
    for d in active:
        covered |= _isins(d.sample_output)
    return Limits(
        active=len(active),
        max_active=rules.MAX_ACTIVE_PROMPTS,
        today=sum(on_today(d) for d in submitted),
        max_per_day=rules.MAX_PROMPTS_PER_DAY,
        coverage=len(covered),
        coverage_target=rules.COVERAGE_TARGET,
    )


def _report(body: ValidateRequest, others: list[Draft]) -> Report:
    sample = rules.parse_output(body.sample_output)
    runs = [sample, *(rules.parse_output(r) for r in body.extra_runs if r.strip())]
    issues = [
        *rules.check_fields(
            name=body.name,
            prompt=body.prompt,
            model=body.model,
            model_version=body.model_version,
            frequency=body.frequency,
            weight=body.weight,
            sample_chars=len(body.sample_output),
        ),
        *sample.issues,
        *rules.check_book(sample.entries),
    ]
    stability = None
    if len(runs) > 1:
        stability, run_issues = rules.compare_runs(runs)
        issues += run_issues

    mine = {e.isin for e in sample.entries}
    overlaps: list[OverlapOut] = []
    for d in others:
        if d.id == body.draft_id or not mine:
            continue
        theirs = _isins(d.sample_output)
        shared = len(mine & theirs)
        share = rules.overlap(mine, theirs)
        if shared and share >= 0.2:
            overlaps.append(
                OverlapOut(
                    draft_id=d.id,
                    name=d.name,
                    status=d.status,
                    shared=shared,
                    overlap=round(share, 3),
                )
            )
    overlaps.sort(key=lambda o: o.overlap, reverse=True)
    if overlaps:
        issues.append(
            rules.Issue(
                "warning",
                "overlap_high",
                f"{len(overlaps)} saved prompt(s) share 20% or more of their instruments with "
                f"this one; the closest is {overlaps[0].name!r} at {overlaps[0].overlap:.0%}. "
                "BRAIN asks for prompts that target different equities.",
            )
        )
    return Report(
        ready=not any(i.level == "error" for i in issues),
        issues=[IssueOut.model_validate(asdict(i)) for i in issues],
        stats=StatsOut.model_validate(asdict(rules.book_stats(sample.entries)))
        if sample.entries
        else None,
        stability=StabilityOut.model_validate(asdict(stability)) if stability else None,
        overlaps=overlaps[:5],
    )


@router.post("/validate")
async def validate(body: ValidateRequest, state: State) -> Report:
    """Every check BRAIN's submission rules and the community guides support, without sending
    anything anywhere."""
    others = await asyncio.to_thread(_store(state).list)
    return await asyncio.to_thread(_report, body, others)


@router.get("/drafts")
async def list_drafts(state: State) -> Drafts:
    drafts = await asyncio.to_thread(_store(state).list)
    return Drafts(
        drafts=await asyncio.to_thread(lambda: [_out(d) for d in drafts]),
        limits=await asyncio.to_thread(_limits, drafts),
        models=list(rules.MODELS),
        frequencies=list(rules.FREQUENCIES),
    )


def _fields(body: SubmissionFields) -> dict[str, Any]:
    return {
        "name": body.name.strip(),
        "model": body.model,
        "model_version": body.model_version.strip(),
        "frequency": body.frequency,
        "weight": body.weight,
        "prompt": body.prompt,
        "sample_output": body.sample_output.strip(),
    }


@router.post("/drafts", status_code=201)
async def create_draft(body: SubmissionFields, state: State) -> DraftOut:
    draft = await asyncio.to_thread(lambda: _store(state).create(**_fields(body)))
    return _out(draft)


@router.put("/drafts/{draft_id}")
async def update_draft(draft_id: str, body: SubmissionFields, state: State) -> DraftOut:
    try:
        draft = await asyncio.to_thread(lambda: _store(state).update(draft_id, **_fields(body)))
    except KeyError as exc:
        raise refuse(404, "draft_not_found", "That prompt is no longer saved.") from exc
    return _out(draft)


class Submitted(BaseModel):
    submitted: bool


@router.post("/drafts/{draft_id}/submitted")
async def mark_submitted(draft_id: str, body: Submitted, state: State) -> DraftOut:
    """Record that the prompt was submitted on BRAIN (or take that back). Bookkeeping only."""
    try:
        draft = await asyncio.to_thread(
            lambda: _store(state).mark(draft_id, submitted=body.submitted)
        )
    except KeyError as exc:
        raise refuse(404, "draft_not_found", "That prompt is no longer saved.") from exc
    return _out(draft)


@router.delete("/drafts/{draft_id}", status_code=204)
async def delete_draft(draft_id: str, state: State) -> None:
    try:
        await asyncio.to_thread(_store(state).delete, draft_id)
    except KeyError as exc:
        raise refuse(404, "draft_not_found", "That prompt is no longer saved.") from exc
