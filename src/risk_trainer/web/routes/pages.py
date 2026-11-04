"""Home, scenario list and static pages (PRD R5, R10)."""

from fastapi import APIRouter, Request
from fastapi.responses import Response

from risk_trainer.domain.models import Scenario

router = APIRouter()


def _render(request: Request, name: str, context: dict[str, object] | None = None) -> Response:
    templates = request.app.state.templates
    full = {"preview": request.app.state.preview, **(context or {})}
    response: Response = templates.TemplateResponse(request, name, full)
    return response


@router.get("/")
async def home(request: Request) -> Response:
    scenarios: list[Scenario] = sorted(request.app.state.scenarios.values(), key=lambda s: s.id)
    return _render(request, "home.html", {"scenarios": scenarios})


@router.get("/responses")
async def responses(request: Request) -> Response:
    return _render(request, "responses.html")


@router.get("/about")
async def about(request: Request) -> Response:
    return _render(request, "about.html")


@router.get("/privacy")
async def privacy(request: Request) -> Response:
    return _render(
        request, "privacy.html", {"min_sample": request.app.state.settings.peer_min_sample}
    )
