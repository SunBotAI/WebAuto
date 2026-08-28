"""FastAPI control plane delegating all mutations to ApplicationService."""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from webauto.domain import Action
from webauto.runtime.file_workspace import FileWorkspaceViolation, RunFileWorkspace

from .auth import LocalSessionError, LocalSessionManager
from .dashboard import render_dashboard
from .mcp_client_config import build_mcp_client_config
from .service import Actor, ApplicationService, PermissionDenied, Role
from .settings import RuntimeConfigStore


class GoalCreate(BaseModel):
    objective: str = Field(min_length=1)
    success_criteria: list[str] = Field(min_length=1)
    constraints: dict[str, object] = Field(default_factory=dict)


class RunCreate(BaseModel):
    goal_id: str
    plan_id: str
    placement: str | None = None
    profile_id: str | None = None


class ApprovalCreate(BaseModel):
    step_id: str | None = None
    action: dict[str, object]
    preview: dict[str, object] = Field(default_factory=dict)
    diff: dict[str, object] = Field(default_factory=dict)
    page_revision: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    object_scope: dict[str, object] = Field(min_length=1)
    ttl_seconds: int = Field(default=300, ge=1, le=86400)


class ResourceUpsert(BaseModel):
    id: str
    value: dict[str, object]


class PlanViewUpdate(BaseModel):
    candidates: list[dict[str, object]] = Field(min_length=1)
    selection_reason: str = Field(min_length=1)


class SettingsUpdate(BaseModel):
    settings: dict[str, object] = Field(default_factory=dict)
    secrets: dict[str, str | None] = Field(default_factory=dict)


class ButlerMessage(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None


class BrowserSessionOpen(BaseModel):
    profile_id: str = Field(default="default", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    allowed_domains: list[str] = Field(min_length=1)


class ShoppingWorkspaceCreate(BaseModel):
    source_run_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    request: dict[str, Any] = Field(default_factory=dict)
    uncertainties: list[str] = Field(default_factory=list)


class XianyuBuyWorkspaceCreate(BaseModel):
    source_run_id: str = Field(min_length=1)
    item: dict[str, Any] = Field(min_length=1)


class XianyuListingWorkspaceCreate(BaseModel):
    source_run_id: str = Field(min_length=1)
    draft: dict[str, Any] = Field(min_length=1)
    file_ids: list[str] = Field(min_length=1)
    previous: dict[str, Any] = Field(default_factory=dict)


class XianyuStoreWorkspaceCreate(BaseModel):
    source_run_id: str = Field(min_length=1)
    records: list[dict[str, Any]] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class VerticalActionPrepare(BaseModel):
    operation: str = Field(min_length=1)
    object_scope: dict[str, Any] = Field(default_factory=dict)
    preview: dict[str, Any] = Field(min_length=1)
    page_revision: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    source_url: str = Field(min_length=1)
    file_ids: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    ttl_seconds: int = Field(default=300, ge=1, le=86400)


class FileUploadCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=180)
    media_type: str = Field(min_length=1, max_length=160)
    content_base64: str = Field(min_length=1, max_length=36_000_000)


def _actor(
    request: Request,
    x_user_id: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None),
    x_roles: str | None = Header(default=None),
) -> Actor:
    if request.app.state.allow_trusted_headers:
        if not x_user_id or not x_tenant_id or not x_roles:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="trusted test authentication required",
            )
        try:
            roles = {Role(value.strip()) for value in x_roles.split(",") if value.strip()}
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="unknown trusted-test role") from exc
        if not roles:
            raise HTTPException(status_code=403, detail="trusted-test role required")
        return Actor(x_user_id, x_tenant_id, roles)
    try:
        return request.app.state.session_manager.authenticate(
            request.cookies.get(LocalSessionManager.cookie_name)
        )
    except LocalSessionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


ActorDependency = Annotated[Actor, Depends(_actor)]


def _stub_legacy(*args, **kwargs):
    """B4-01c: legacy Butler Service handler removed with Browser Use stack."""
    raise HTTPException(status_code=410, detail='butler/legacy endpoint removed in v3.3')


def create_app(
    service: ApplicationService | None = None,
    settings_store: RuntimeConfigStore | None = None,
    *,
    allow_trusted_headers: bool = False,
) -> FastAPI:
    app_service = service or ApplicationService()
    config_store = settings_store or RuntimeConfigStore(Path.cwd() / "var")
    session_manager = LocalSessionManager(config_store.config_dir / "session.key")
    file_workspace = RunFileWorkspace(
        config_store.runtime_dir / "files",
        config_store.runtime_dir / "downloads",
    )
    app = FastAPI(title="WebAuto Control API", version="3.0.0")
    # Mount v3.3 web pages (status + approvals) defined in web_pages.py.
    from .web_pages import register_routes as _register_web_pages

    _register_web_pages(app)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "test", "testserver"],
    )
    app.state.application_service = app_service
    app.state.settings_store = config_store
    app.state.session_manager = session_manager
    app.state.file_workspace = file_workspace
    # B4-01c: vertical_workflows + butler_service removed with Browser Use stack.
    # Stub bindings so the legacy v1/v2 routes below don't NameError at startup.
    verticals = None  # type: ignore[assignment]
    butler_service = None  # type: ignore[assignment]
    app.state.allow_trusted_headers = allow_trusted_headers

    @app.middleware("http")
    async def enforce_csrf(request: Request, call_next):
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)
        path = request.url.path
        if path == "/v1/session/bootstrap":
            return await call_next(request)
        if path.startswith("/v1/settings"):
            if config_store.authorizer.verify(
                request.headers.get("x-webauto-setup-token")
            ):
                return await call_next(request)
            try:
                session_manager.verify_csrf(
                    request.cookies.get(LocalSessionManager.cookie_name),
                    request.headers.get("x-webauto-csrf-token"),
                )
            except LocalSessionError as exc:
                return JSONResponse(status_code=403, content={"detail": str(exc)})
            return await call_next(request)
        if allow_trusted_headers:
            return await call_next(request)
        try:
            session_manager.verify_csrf(
                request.cookies.get(LocalSessionManager.cookie_name),
                request.headers.get("x-webauto-csrf-token"),
            )
        except LocalSessionError as exc:
            return JSONResponse(status_code=403, content={"detail": str(exc)})
        return await call_next(request)

    def require_setup_token(
        request: Request,
        x_webauto_setup_token: str | None = Header(default=None),
    ) -> None:
        if config_store.authorizer.verify(x_webauto_setup_token):
            return
        try:
            session_manager.authenticate(request.cookies.get(LocalSessionManager.cookie_name))
        except LocalSessionError as exc:
            raise HTTPException(
                status_code=401, detail="valid local setup session required"
            ) from exc

    @app.post("/v1/session/bootstrap")
    async def bootstrap_session(
        response: Response,
        _: None = Depends(require_setup_token),
    ):
        issued = session_manager.issue()
        response.set_cookie(
            LocalSessionManager.cookie_name,
            issued.token,
            max_age=int(session_manager.ttl.total_seconds()),
            httponly=True,
            samesite="strict",
            secure=False,
            path="/",
        )
        return {
            "user_id": issued.actor.user_id,
            "tenant_id": issued.actor.tenant_id,
            "roles": sorted(role.value for role in issued.actor.roles),
            "csrf_token": issued.csrf_token,
            "expires_at": issued.expires_at.isoformat(),
        }

    @app.get("/v1/session")
    async def current_session(request: Request, actor: ActorDependency):
        token = request.cookies.get(LocalSessionManager.cookie_name)
        return {
            "user_id": actor.user_id,
            "tenant_id": actor.tenant_id,
            "roles": sorted(role.value for role in actor.roles),
            "csrf_token": session_manager.csrf_token(token) if token else None,
        }

    @app.delete("/v1/session")
    async def close_session(response: Response, _: ActorDependency):
        response.delete_cookie(LocalSessionManager.cookie_name, path="/")
        return {"status": "signed_out"}

    @app.post("/v1/files", status_code=201)
    async def add_user_file(payload: FileUploadCreate, actor: ActorDependency):
        try:
            content = base64.b64decode(payload.content_base64, validate=True)
            record = file_workspace.add_user_file(
                owner_id=actor.user_id,
                filename=payload.filename,
                media_type=payload.media_type,
                content=content,
            )
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=422, detail="file content is not valid base64") from exc
        except FileWorkspaceViolation as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return record.public()

    @app.get("/v1/files")
    async def list_user_files(actor: ActorDependency):
        return [
            record.public() for record in file_workspace.list_user_files(owner_id=actor.user_id)
        ]

    @app.post("/v1/runs/{run_id}/files/{file_id}/authorize")
    async def authorize_run_file(
        run_id: str,
        file_id: str,
        actor: ActorDependency,
    ):
        await app_service.get_run(actor, run_id)
        try:
            return file_workspace.authorize_for_run(
                owner_id=actor.user_id,
                file_id=file_id,
                run_id=run_id,
            ).public()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileWorkspaceViolation as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/runs/{run_id}/downloads")
    async def list_run_downloads(run_id: str, actor: ActorDependency):
        await app_service.get_run(actor, run_id)
        try:
            return file_workspace.list_downloads(run_id=run_id)
        except FileWorkspaceViolation as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/", include_in_schema=False)
    async def dashboard():
        return RedirectResponse(url="/setup", status_code=307)

    @app.get("/setup", response_class=HTMLResponse)
    async def setup_page(request: Request):
        client_host = request.client.host if request.client else ""
        try:
            local_client = ipaddress.ip_address(client_host).is_loopback
        except ValueError:
            local_client = client_host in {"localhost", "testclient"}
        if not local_client:
            raise HTTPException(status_code=403, detail="configuration page is local-only")
        issued = session_manager.issue()
        response = HTMLResponse(render_dashboard(issued.csrf_token))
        response.set_cookie(
            LocalSessionManager.cookie_name,
            issued.token,
            max_age=int(session_manager.ttl.total_seconds()),
            httponly=True,
            samesite="strict",
            secure=False,
            path="/",
        )
        return response

    @app.exception_handler(PermissionDenied)
    async def permission_error(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.post("/v1/butler/messages")
    async def butler_message(payload: ButlerMessage, actor: ActorDependency):
        return await butler_service.handle(
            actor,
            payload.message,
            conversation_id=payload.conversation_id,
        )

    @app.get("/v1/conversations")
    async def list_conversations(
        actor: ActorDependency,
        limit: int = 50,
    ):
        return await app_service.list_conversations(actor, limit=limit)

    @app.get("/v1/conversations/{conversation_id}")
    async def get_conversation(
        conversation_id: str,
        actor: ActorDependency,
    ):
        return await app_service.get_conversation(actor, conversation_id)

    @app.post("/v1/browser-sessions")
    async def open_browser_session(payload: BrowserSessionOpen, actor: ActorDependency):
        try:
            return await butler_service.open_browser_session(
                actor,
                profile_id=payload.profile_id,
                allowed_domains=tuple(payload.allowed_domains),
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/browser-sessions/{profile_id}")
    async def browser_session_status(profile_id: str, actor: ActorDependency):
        try:
            return await butler_service.browser_session_status(actor, profile_id=profile_id)
        except (RuntimeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.delete("/v1/browser-sessions/{profile_id}")
    async def close_browser_session(profile_id: str, actor: ActorDependency):
        try:
            return await butler_service.close_browser_session(actor, profile_id=profile_id)
        except (RuntimeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    vertical_categories = {
        "shopping": [],
        "xianyu_buy": [],
        "xianyu_listing": [],
        "xianyu_store": [],
    }

    def category_value(alias: str) -> str:
        try:
            return vertical_categories[alias]
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="unknown vertical workspace category"
            ) from exc

    @app.post("/v1/shopping/workspaces", status_code=201)
    async def create_shopping_workspace(payload: ShoppingWorkspaceCreate, actor: ActorDependency):
        try:
            return await verticals.create_shopping_workspace(
                actor,
                source_run_id=payload.source_run_id,
                message=payload.message,
                candidates=payload.candidates,
                request_overrides=payload.request,
                uncertainties=payload.uncertainties,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/xianyu/buy/workspaces", status_code=201)
    async def create_xianyu_buy_workspace(
        payload: XianyuBuyWorkspaceCreate, actor: ActorDependency
    ):
        try:
            return await verticals.create_xianyu_buy_workspace(
                actor,
                source_run_id=payload.source_run_id,
                item=payload.item,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/xianyu/listings", status_code=201)
    async def create_xianyu_listing_workspace(
        payload: XianyuListingWorkspaceCreate, actor: ActorDependency
    ):
        try:
            grants = [
                file_workspace.get_run_grant(
                    owner_id=actor.user_id,
                    file_id=file_id,
                    run_id=payload.source_run_id,
                )
                for file_id in payload.file_ids
            ]
            if any(
                Path(grant.filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}
                for grant in grants
            ):
                raise ValueError("Xianyu listing files must all be images")
            return await verticals.create_xianyu_listing_workspace(
                actor,
                source_run_id=payload.source_run_id,
                draft=payload.draft,
                image_grants=[grant.public() for grant in grants],
                previous=payload.previous,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (FileWorkspaceViolation, OSError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/xianyu/store/workspaces", status_code=201)
    async def create_xianyu_store_workspace(
        payload: XianyuStoreWorkspaceCreate, actor: ActorDependency
    ):
        return await verticals.create_xianyu_store_workspace(
            actor,
            source_run_id=payload.source_run_id,
            records=payload.records,
            uncertainties=payload.uncertainties,
        )

    @app.get("/v1/vertical/workspaces/{category}/{workspace_id}")
    async def get_vertical_workspace(category: str, workspace_id: str, actor: ActorDependency):
        try:
            return await verticals.get_workspace(actor, category_value(category), workspace_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post(
        "/v1/vertical/workspaces/{category}/{workspace_id}/actions",
        status_code=201,
    )
    async def prepare_vertical_action(
        category: str,
        workspace_id: str,
        payload: VerticalActionPrepare,
        actor: ActorDependency,
    ):
        resource_category = category_value(category)
        try:
            workspace = await verticals.get_workspace(actor, resource_category, workspace_id)
            file_ids = list(payload.file_ids)
            if payload.operation == "xianyu_publish":
                if resource_category != "xianyu_listing":
                    raise ValueError("publish requires a Xianyu listing workspace")
                expected = [str(item["file_id"]) for item in workspace["draft"]["images"]]
                if file_ids and file_ids != expected:
                    raise ValueError("publish file ids differ from the approved listing draft")
                file_ids = expected
            elif file_ids:
                raise ValueError("files are accepted only for a Xianyu publish action")
            source_grants = [
                file_workspace.get_run_grant(
                    owner_id=actor.user_id,
                    file_id=file_id,
                    run_id=workspace["source_run_id"],
                )
                for file_id in file_ids
            ]
            prepared = await verticals.prepare_action(
                actor,
                workspace_category=resource_category,
                workspace_id=workspace_id,
                operation=payload.operation,
                object_scope=payload.object_scope,
                preview=payload.preview,
                page_revision=payload.page_revision,
                evidence_ids=payload.evidence_ids,
                source_url=payload.source_url,
                available_files=[grant.public() for grant in source_grants],
                allowed_domains=payload.allowed_domains or None,
                ttl_seconds=payload.ttl_seconds,
            )
            for file_id in file_ids:
                file_workspace.authorize_for_run(
                    owner_id=actor.user_id,
                    file_id=file_id,
                    run_id=prepared["action_run_id"],
                )
            return prepared
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (FileWorkspaceViolation, OSError, RuntimeError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/governed-actions/{preview_id}")
    async def get_governed_action(preview_id: str, actor: ActorDependency):
        try:
            return await verticals.get_action_preview(actor, preview_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/governed-actions/{preview_id}/execute")
    async def execute_governed_action(preview_id: str, actor: ActorDependency):
        if not butler_service.supports_governed_actions():
            raise HTTPException(
                status_code=409,
                detail=(
                    "dynamic Browser Agent governed writes are not enabled; "
                    "the approval remains unconsumed"
                ),
            )
        try:
            record = await verticals.get_action_preview(actor, preview_id)
            action_files = [
                file_workspace.get_run_grant(
                    owner_id=actor.user_id,
                    file_id=str(item["file_id"]),
                    run_id=record["action_run_id"],
                )
                for item in record.get("available_files", [])
            ]
            consumed = await verticals.consume_action(actor, preview_id)
            action = {
                **consumed["action"],
                "approval_id": consumed["approval_id"],
            }
            execution = await butler_service.execute_governed_action(
                actor,
                {
                    **consumed,
                    "action": action,
                    "available_files": [str(grant.path) for grant in action_files],
                    "objective": (
                        "Execute exactly the approved operation "
                        f"{consumed['operation']} and verify its business result"
                    ),
                    "success_criteria": ["页面状态或业务查询确认批准的写操作结果"],
                },
            )
            final_state = {
                "succeeded": "executed",
                "waiting_human": "waiting_human",
            }.get(str(execution["status"]), "failed")
            final = await verticals.record_action_result(
                actor,
                preview_id,
                status=final_state,
                result=execution,
            )
            return {"action": final, "execution": execution}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (FileWorkspaceViolation, OSError, RuntimeError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/goals", status_code=201)
    async def create_goal(payload: GoalCreate, actor: ActorDependency):
        try:
            return await app_service.create_goal(
                actor,
                objective=payload.objective,
                success_criteria=payload.success_criteria,
                constraints=payload.constraints,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/runs", status_code=201)
    async def create_run(payload: RunCreate, actor: ActorDependency):
        from webauto.domain import Placement

        placement = Placement(payload.placement) if payload.placement else None
        return await app_service.create_run(
            actor,
            goal_id=payload.goal_id,
            plan_id=payload.plan_id,
            placement=placement,
            profile_id=payload.profile_id,
        )

    @app.get("/v1/runs")
    async def list_runs(
        actor: ActorDependency,
        states: str | None = None,
        limit: int = 100,
    ):
        state_values = (
            [value.strip() for value in states.split(",") if value.strip()] if states else None
        )
        try:
            return await app_service.list_runs(actor, states=state_values, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/runs/{run_id}")
    async def get_run(run_id: str, actor: ActorDependency):
        return await app_service.get_run(actor, run_id)

    transitions = {
        "start": app_service.start_run,
        "pause": _stub_legacy,
        "resume": _stub_legacy,
        "cancel": _stub_legacy,
        "takeover": _stub_legacy,
        "return-control": _stub_legacy,
    }
    for route_name, operation in transitions.items():

        def register(name=route_name, handler=operation):
            @app.post(f"/v1/runs/{{run_id}}/{name}")
            async def transition(run_id: str, actor: ActorDependency):
                try:
                    return await handler(actor, run_id)
                except (RuntimeError, TypeError) as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc

            return transition

        register()

    @app.get("/v1/runs/{run_id}/detail")
    async def run_detail(run_id: str, actor: ActorDependency):
        return await app_service.run_detail(actor, run_id)

    @app.get("/v1/runs/{run_id}/result")
    async def get_run_result(run_id: str, actor: ActorDependency):
        return await app_service.get_run_result(actor, run_id)

    @app.get("/v1/runs/{run_id}/plans")
    async def run_plans(run_id: str, actor: ActorDependency):
        detail = await app_service.run_detail(actor, run_id)
        return {
            "candidates": detail["candidates"],
            "selection_reason": detail["selection_reason"],
        }

    @app.put("/v1/runs/{run_id}/plans")
    async def set_run_plans(run_id: str, payload: PlanViewUpdate, actor: ActorDependency):
        await app_service.set_plan_view(
            actor,
            run_id,
            candidates=payload.candidates,
            selection_reason=payload.selection_reason,
        )
        return {"status": "ok", "run_id": run_id}

    @app.post("/v1/runs/{run_id}/approvals", status_code=201)
    async def request_approval(run_id: str, payload: ApprovalCreate, actor: ActorDependency):
        return await app_service.request_approval(
            actor,
            run_id=run_id,
            step_id=payload.step_id,
            action=Action.model_validate(payload.action),
            preview=payload.preview,
            diff=payload.diff,
            page_revision=payload.page_revision,
            evidence_ids=payload.evidence_ids,
            object_scope=payload.object_scope,
            ttl=timedelta(seconds=payload.ttl_seconds),
        )

    @app.get("/v1/approvals")
    async def list_approvals(actor: ActorDependency):
        return await app_service.list_approvals(actor)

    @app.post("/v1/approvals/{approval_id}/approve")
    async def approve(approval_id: str, actor: ActorDependency):
        return await app_service.approve(actor, approval_id)

    @app.post("/v1/approvals/{approval_id}/reject")
    async def reject(approval_id: str, actor: ActorDependency):
        return await app_service.reject(actor, approval_id)

    @app.post("/v1/approvals/{approval_id}/revoke")
    async def revoke(approval_id: str, actor: ActorDependency):
        return await app_service.revoke_approval(actor, approval_id)

    @app.get("/v1/resources/{category}")
    async def list_resources(category: str, actor: ActorDependency):
        return await app_service.list_resources(actor, category)

    @app.put("/v1/resources/{category}")
    async def upsert_resource(category: str, payload: ResourceUpsert, actor: ActorDependency):
        await app_service.upsert_resource(actor, category, payload.id, payload.value)
        return {"status": "ok", "id": payload.id}

    for category in ("agents", "profiles", "artifacts"):

        def register_resource_alias(resource_category=category):
            @app.get(f"/v1/{resource_category}")
            async def list_alias(actor: ActorDependency):
                return await app_service.list_resources(actor, resource_category)

            @app.put(f"/v1/{resource_category}")
            async def upsert_alias(payload: ResourceUpsert, actor: ActorDependency):
                await app_service.upsert_resource(
                    actor, resource_category, payload.id, payload.value
                )
                return {"status": "ok", "id": payload.id}

            return list_alias, upsert_alias

        register_resource_alias()

    @app.get("/v1/events")
    async def events(actor: ActorDependency):
        subscription = app_service.events.subscribe(actor.tenant_id)

        async def stream():
            try:
                async for event in subscription:
                    payload = {
                        "tenant_id": event.tenant_id,
                        "kind": event.kind,
                        "payload": event.payload,
                        "occurred_at": event.occurred_at.isoformat(),
                    }
                    yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
            finally:
                await subscription.aclose()

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/v1/health")
    async def health():
        return {"status": "ok", "version": "3.0.0", "setup_complete": config_store.path.exists()}

    @app.get("/v1/settings")
    async def get_settings(_: None = Depends(require_setup_token)):
        return config_store.public()

    @app.get("/v1/settings/mcp-client-config")
    async def get_mcp_client_config(_: None = Depends(require_setup_token)):
        return build_mcp_client_config(config_store)

    @app.put("/v1/settings")
    async def update_settings(payload: SettingsUpdate, _: None = Depends(require_setup_token)):
        try:
            result = config_store.update(payload.settings, payload.secrets)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {**result, "restart_required": True}

    @app.post("/v1/settings/test")
    async def test_settings(_: None = Depends(require_setup_token)):
        return config_store.test_connections()

    @app.post("/v1/settings/prepare-local")
    async def prepare_local(_: None = Depends(require_setup_token)):
        return config_store.prepare_local()

    @app.get("/v1/settings/detect-browser")
    async def detect_browser(_: None = Depends(require_setup_token)):
        from webauto.runtime.browser import discover_browsers

        return discover_browsers()

    @app.post("/v1/settings/initialize-database")
    async def initialize_database(_: None = Depends(require_setup_token)):
        try:
            return await config_store.initialize_database()
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return app
