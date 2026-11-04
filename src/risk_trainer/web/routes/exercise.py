"""The exercise form, submission, scoring and debrief (PRD R6-R9), with the per-session
submission limit (R13), the attempt metric (R15) and the monthly stats totals (R22)."""

import logging
import re
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from risk_trainer.domain.debrief import build_debrief
from risk_trainer.domain.errors import ContentError, SubmissionInvalid
from risk_trainer.domain.models import Scenario, Status
from risk_trainer.domain.peers import PeerDistribution, distribution
from risk_trainer.domain.scoring import ScoreResult, score
from risk_trainer.domain.submission import (
    ACCEPT_RATIONALE_MIN,
    NOTE_MAX,
    RATIONALE_MAX,
    Submission,
    parse_submission,
)
from risk_trainer.storage.attempts import AttemptRecord, AttemptStore, Choice, StorageError
from risk_trainer.storage.rate_limits import RateLimiter, RateLimitUnavailable
from risk_trainer.web.csrf import CSRF_FIELD, csrf_token, csrf_valid, session_id
from risk_trainer.web.metrics import Metric, Metrics

logger = logging.getLogger("risk_trainer.web.exercise")
router = APIRouter()

SUBMIT_ID_FIELD = "submit_id"
_SUBMIT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_CONTROL_FIELDS = (CSRF_FIELD, SUBMIT_ID_FIELD)


def _scenario(request: Request, scenario_id: str) -> Scenario:
    scenario: Scenario | None = request.app.state.scenarios.get(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404)
    return scenario


def _form_page(
    request: Request,
    scenario: Scenario,
    *,
    values: dict[str, str] | None = None,
    errors: list[ContentError] | None = None,
    status_code: int = 200,
) -> Response:
    templates = request.app.state.templates
    response: Response = templates.TemplateResponse(
        request,
        "exercise.html",
        {
            "preview": request.app.state.preview,
            "draft": scenario.status is Status.DRAFT,
            "scenario": scenario,
            "csrf_token": csrf_token(request),
            "submit_id": secrets.token_urlsafe(16),
            "values": values or {},
            "errors": errors or [],
            "accept_rationale_min": ACCEPT_RATIONALE_MIN,
            "rationale_max": RATIONALE_MAX,
            "note_max": NOTE_MAX,
        },
        status_code=status_code,
    )
    return response


@router.get("/s/{scenario_id}")
async def exercise_form(request: Request, scenario_id: str) -> Response:
    return _form_page(request, _scenario(request, scenario_id))


@router.post("/s/{scenario_id}")
async def submit(request: Request, scenario_id: str) -> Response:
    scenario = _scenario(request, scenario_id)
    form = await request.form()
    items = [(name, value) for name, value in form.multi_items() if isinstance(value, str)]
    control = {name: [v for n, v in items if n == name] for name in _CONTROL_FIELDS}
    answers = [(name, value) for name, value in items if name not in _CONTROL_FIELDS]
    if len(items) != len(form.multi_items()):
        raise HTTPException(status_code=422)

    tokens = control[CSRF_FIELD]
    if len(tokens) != 1 or not csrf_valid(request, tokens[0]):
        raise HTTPException(status_code=403)
    _check_rate_limit(request, scenario)

    values = dict(answers)
    submit_ids = control[SUBMIT_ID_FIELD]
    if len(submit_ids) != 1 or not _SUBMIT_ID_RE.match(submit_ids[0]):
        error = ContentError("form", "This form is out of date. Check your answers and submit.")
        return _form_page(request, scenario, values=values, errors=[error], status_code=422)

    try:
        submission = parse_submission(scenario, answers)
    except SubmissionInvalid as exc:
        return _form_page(request, scenario, values=values, errors=exc.errors, status_code=422)

    result = score(scenario, submission)
    peers = _record_and_count(request, scenario, submission, submit_ids[0], result)
    templates = request.app.state.templates
    response: Response = templates.TemplateResponse(
        request,
        "result.html",
        {
            "preview": request.app.state.preview,
            "draft": scenario.status is Status.DRAFT,
            "scenario": scenario,
            "debrief": build_debrief(scenario, submission, result),
            "peers": peers,
        },
    )
    return response


def _check_rate_limit(request: Request, scenario: Scenario) -> None:
    """At most REQUESTS_PER_SESSION_PER_MINUTE submissions per session (R13).

    Runs after the CSRF check, so every counted request has a valid session. If the counter
    is unavailable the submission goes through: this is a courtesy limit, not an abuse control.
    """
    limiter: RateLimiter = request.app.state.rate_limiter
    metrics: Metrics = request.app.state.metrics
    try:
        count = limiter.hit(session_id(request), datetime.now(UTC))
    except RateLimitUnavailable:
        logger.warning(
            "rate limit unavailable",
            extra={"event": "rate_limit_unavailable", "scenario_id": scenario.id},
        )
        metrics.count(Metric.RATE_LIMIT_UNAVAILABLE)
        return
    if count > request.app.state.settings.requests_per_session_per_minute:
        logger.info("rate limited", extra={"event": "rate_limited", "scenario_id": scenario.id})
        metrics.count(Metric.RATE_LIMITED)
        raise HTTPException(status_code=429, headers={"Retry-After": "60"})


def _record_and_count(
    request: Request,
    scenario: Scenario,
    submission: Submission,
    submit_id: str,
    result: ScoreResult,
) -> PeerDistribution | None:
    """Record the attempt, then read the peer counts. Storage problems never block the debrief."""
    store: AttemptStore = request.app.state.store
    attempt = AttemptRecord(
        submit_id=submit_id,
        scenario_id=scenario.id,
        scenario_version=scenario.version,
        choices=tuple(Choice(a.finding_id, a.treatment, a.approver) for a in submission.answers),
        score=result.total,
        max_score=result.maximum,
        submitted_at=datetime.now(UTC),
    )
    try:
        recorded = store.record(attempt)
        counts = store.peer_counts(scenario.id, scenario.version)
    except StorageError:
        logger.exception(
            "attempt storage failed", extra={"event": "storage_error", "scenario_id": scenario.id}
        )
        return None
    logger.info(
        "attempt recorded" if recorded else "duplicate submission",
        extra={"event": "attempt" if recorded else "duplicate_attempt", "scenario_id": scenario.id},
    )
    if recorded:
        metrics: Metrics = request.app.state.metrics
        metrics.count(Metric.ATTEMPTS)
        _add_to_month(store, attempt)
    return distribution(
        counts.attempts,
        counts.counters,
        [finding.id for finding in scenario.findings],
        request.app.state.settings.peer_min_sample,
    )


def _add_to_month(store: AttemptStore, attempt: AttemptRecord) -> None:
    """Add a newly recorded attempt to the monthly stats totals (R22).

    Fail-open: the attempt is already saved, so a failure here only leaves it out of the stats.
    """
    try:
        store.add_to_month(attempt)
    except StorageError:
        logger.exception(
            "monthly stats update failed",
            extra={"event": "stats_bucket_error", "scenario_id": attempt.scenario_id},
        )
