"""FastAPI app factory (PRD R5-R10, R12, R13, R15, R22)."""

import mimetypes
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import Scope

from risk_trainer.config import ConfigError, Settings, check_ready, check_storage
from risk_trainer.content.repository import load_publishable
from risk_trainer.domain.models import Exposure, Scenario
from risk_trainer.domain.treatments import APPROVER_LABELS, TREATMENT_LABELS, Approver, Treatment
from risk_trainer.storage.attempts import AttemptStore
from risk_trainer.storage.rate_limits import RateLimiter
from risk_trainer.web.assets import VersionedStaticFiles, asset_version
from risk_trainer.web.logging import configure_logging
from risk_trainer.web.metrics import Metrics
from risk_trainer.web.middleware import (
    BodyLimitMiddleware,
    OriginVerifyMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from risk_trainer.web.routes import exercise, pages, stats
from risk_trainer.web.routes.stats import StatsCache

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
SESSION_COOKIE = "rt_session"

# Python 3.14 already maps .woff2 and .svg; this keeps them right if the host's mime.types differs.
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("image/svg+xml", ".svg")

EXPOSURE_LABELS = {
    Exposure.INTERNET_FACING: "Internet-facing",
    Exposure.INTERNAL: "Internal network",
    Exposure.SEGMENTED: "Segmented network",
    Exposure.THIRD_PARTY: "Third party",
    Exposure.PROCESS: "Business process",
}
ERROR_TITLES = {
    403: "This form has expired",
    404: "Page not found",
    405: "Not allowed",
    413: "That submission is too large",
    422: "Something in the form needs fixing",
    429: "Too many submissions",
    500: "Something went wrong",
}


def make_templates(static_version: str | None = None) -> Jinja2Templates:
    version = static_version if static_version is not None else asset_version(STATIC_DIR)

    def static_url(name: str) -> str:
        return f"/static/{version}/{name}"

    templates = Jinja2Templates(directory=WEB_DIR / "templates")
    templates.env.globals.update(
        static_url=static_url,
        treatment_labels=TREATMENT_LABELS,
        approver_labels=APPROVER_LABELS,
        exposure_labels=EXPOSURE_LABELS,
        treatments=list(Treatment),
        approvers=list(Approver),
    )
    return templates


def build_store(settings: Settings) -> AttemptStore:
    check_storage(settings)
    if settings.storage_backend == "memory":
        from risk_trainer.storage.memory import MemoryAttemptStore

        return MemoryAttemptStore()
    from risk_trainer.storage.dynamodb import DynamoAttemptStore, make_client

    table = settings.dynamodb_table or ""
    return DynamoAttemptStore(make_client(settings.aws_region), table)


def build_rate_limiter(settings: Settings) -> RateLimiter:
    """The per-session submission counter lives in the same store as the attempts (R13)."""
    check_storage(settings)
    if settings.storage_backend == "memory":
        from risk_trainer.storage.rate_limits import MemoryRateLimiter

        return MemoryRateLimiter()
    from risk_trainer.storage.dynamodb import make_client
    from risk_trainer.storage.rate_limits import DynamoRateLimiter

    return DynamoRateLimiter(make_client(settings.aws_region), settings.dynamodb_table or "")


def create_app(
    settings: Settings,
    store: AttemptStore | None = None,
    scenarios: list[Scenario] | None = None,
    *,
    preview: bool = False,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    """Build the app. Refuses unsafe settings: memory storage or no origin check in Lambda,
    or a session secret that hasn't been loaded."""
    check_ready(settings)
    session_secret = settings.session_secret
    if session_secret is None:  # check_ready has refused this; narrows the type
        raise ConfigError("the session secret has not been loaded")
    configure_logging(settings.log_level)
    static_version = asset_version(STATIC_DIR)
    templates = make_templates(static_version)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.templates = templates
    app.state.preview = preview
    app.state.store = store if store is not None else build_store(settings)
    app.state.rate_limiter = (
        rate_limiter if rate_limiter is not None else build_rate_limiter(settings)
    )
    app.state.metrics = Metrics(settings.metrics_namespace)
    app.state.stats_cache = StatsCache()
    loaded = scenarios if scenarios is not None else load_publishable(settings.content_dir)
    app.state.scenarios = {scenario.id: scenario for scenario in loaded}

    async def render_error(scope: Scope, status: int, request_id: str) -> tuple[bytes, str]:
        request = Request(scope)
        response = error_response(request, status, request_id)
        return bytes(response.body), "text/html; charset=utf-8"

    def error_response(
        request: Request,
        status: int,
        request_id: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "status": status,
                "title": ERROR_TITLES.get(status, "Something went wrong"),
                "request_id": request_id or getattr(request.state, "request_id", ""),
                "preview": preview,
            },
            status_code=status,
            headers=headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        return error_response(request, exc.status_code, headers=exc.headers)

    app.include_router(pages.router)
    app.include_router(exercise.router)
    app.include_router(stats.router)
    app.mount(
        "/static",
        VersionedStaticFiles(directory=STATIC_DIR, version=static_version),
        name="static",
    )

    # Added innermost first: the last one added runs first.
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret.get_secret_value(),
        session_cookie=SESSION_COOKIE,
        max_age=None,
        same_site="lax",
        https_only=settings.session_cookie_secure,
    )
    app.add_middleware(BodyLimitMiddleware, render_error=render_error)
    if settings.origin_verify_secret is not None:
        app.add_middleware(
            OriginVerifyMiddleware, secret=settings.origin_verify_secret.get_secret_value()
        )
    app.add_middleware(RequestContextMiddleware, render_error=render_error)
    app.add_middleware(SecurityHeadersMiddleware)
    return app
