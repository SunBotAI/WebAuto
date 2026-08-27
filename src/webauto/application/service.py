"""Single application-service boundary for every product entry point."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from webauto.agent import GoalCompiler
from webauto.domain import (
    Action,
    Approval,
    ApprovalState,
    ButlerConversation,
    ConversationMessage,
    ConversationRole,
    GoalContract,
    Placement,
    RiskBudget,
    Run,
    RunState,
)
from webauto.runtime.reliability import (
    ApprovalService,
    action_digest,
    approval_binding_digest,
)

from .state import ApplicationStateStore


class Role(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    APPROVER = "approver"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: str
    tenant_id: str
    roles: set[Role]


class PermissionDenied(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AuditEntry:
    actor_id: str
    tenant_id: str
    action: str
    resource_type: str
    resource_id: str
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ApplicationEvent:
    tenant_id: str
    kind: str
    payload: dict[str, Any]
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class _Subscription:
    def __init__(self, broker: EventBroker, tenant_id: str) -> None:
        self._broker = broker
        self.tenant_id = tenant_id
        self.queue: asyncio.Queue[ApplicationEvent] = asyncio.Queue()
        self._closed = False

    def __aiter__(self) -> _Subscription:
        return self

    async def __anext__(self) -> ApplicationEvent:
        if self._closed:
            raise StopAsyncIteration
        return await self.queue.get()

    async def aclose(self) -> None:
        self._closed = True
        self._broker._remove(self)


class EventBroker:
    def __init__(self) -> None:
        self._subscriptions: dict[str, list[_Subscription]] = {}

    def subscribe(self, tenant_id: str) -> _Subscription:
        subscription = _Subscription(self, tenant_id)
        self._subscriptions.setdefault(tenant_id, []).append(subscription)
        return subscription

    async def publish(self, tenant_id: str, kind: str, payload: dict[str, Any]) -> None:
        event = ApplicationEvent(tenant_id, kind, payload)
        for subscription in tuple(self._subscriptions.get(tenant_id, [])):
            await subscription.queue.put(event)

    def _remove(self, subscription: _Subscription) -> None:
        subscriptions = self._subscriptions.get(subscription.tenant_id, [])
        if subscription in subscriptions:
            subscriptions.remove(subscription)


@dataclass(frozen=True, slots=True)
class _TenantGoal:
    tenant_id: str
    goal: GoalContract


@dataclass(frozen=True, slots=True)
class _TenantRun:
    tenant_id: str
    run: Run


@dataclass(frozen=True, slots=True)
class _TenantConversation:
    tenant_id: str
    conversation: ButlerConversation


class ApplicationService:
    def __init__(
        self,
        *,
        events: EventBroker | None = None,
        state_store: ApplicationStateStore | None = None,
    ) -> None:
        self.events = events or EventBroker()
        self._state_store = state_store
        self._loaded = state_store is None
        self._goals: dict[str, _TenantGoal] = {}
        self._runs: dict[str, _TenantRun] = {}
        self._audit: list[AuditEntry] = []
        self._approval_service = ApprovalService()
        self._approval_tenants: dict[str, str] = {}
        self._approval_execution_claims: dict[str, str] = {}
        self._plan_views: dict[str, dict[str, Any]] = {}
        self._conversations: dict[str, _TenantConversation] = {}
        self._run_results: dict[str, dict[str, Any]] = {}
        self._resources: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        self._lock = asyncio.Lock()
        self._persist_lock = asyncio.Lock()

    @property
    def audit_log(self) -> tuple[AuditEntry, ...]:
        return tuple(self._audit)

    async def create_goal(
        self,
        actor: Actor,
        *,
        objective: str,
        success_criteria: list[str],
        risk_budget: RiskBudget | None = None,
        constraints: dict[str, Any] | None = None,
    ) -> GoalContract:
        await self._ensure_loaded()
        self._require(actor, Role.OPERATOR)
        compiled = GoalCompiler().compile(
            objective,
            success_criteria=success_criteria,
            risk_budget=risk_budget,
            constraints=constraints,
        )
        if compiled.goal is None:
            raise ValueError("; ".join(compiled.clarifications))
        async with self._lock:
            self._goals[compiled.goal.id] = _TenantGoal(actor.tenant_id, compiled.goal)
        await self._record(actor, "goal.create", "goal", compiled.goal.id)
        return compiled.goal

    async def create_run(
        self,
        actor: Actor,
        *,
        goal_id: str,
        plan_id: str,
        placement: Placement | None = None,
        profile_id: str | None = None,
    ) -> Run:
        await self._ensure_loaded()
        self._require(actor, Role.OPERATOR)
        self._goal_for(actor, goal_id)
        run = Run(
            goal_id=goal_id,
            plan_id=plan_id,
            placement=placement,
            profile_id=profile_id,
            state=RunState.READY,
        )
        async with self._lock:
            self._runs[run.id] = _TenantRun(actor.tenant_id, run)
        await self._record(actor, "run.create", "run", run.id)
        return run

    async def get_run(self, actor: Actor, run_id: str) -> Run:
        await self._ensure_loaded()
        self._require_any(actor, {Role.VIEWER, Role.OPERATOR, Role.APPROVER, Role.ADMIN})
        return self._run_for(actor, run_id)

    async def start_run(self, actor: Actor, run_id: str) -> Run:
        return await self._transition(
            actor, run_id, {RunState.READY, RunState.PAUSED}, RunState.RUNNING, "run.start"
        )

    async def pause_run(self, actor: Actor, run_id: str) -> Run:
        return await self._transition(
            actor, run_id, {RunState.RUNNING}, RunState.PAUSED, "run.pause"
        )

    async def resume_run(self, actor: Actor, run_id: str) -> Run:
        return await self._transition(
            actor, run_id, {RunState.PAUSED}, RunState.RUNNING, "run.resume"
        )

    async def cancel_run(self, actor: Actor, run_id: str) -> Run:
        return await self._transition(
            actor,
            run_id,
            {
                RunState.READY,
                RunState.RUNNING,
                RunState.PAUSED,
                RunState.WAITING_APPROVAL,
                RunState.WAITING_HUMAN,
            },
            RunState.CANCELLED,
            "run.cancel",
        )

    async def takeover(self, actor: Actor, run_id: str) -> Run:
        return await self._transition(
            actor,
            run_id,
            {RunState.RUNNING, RunState.PAUSED},
            RunState.WAITING_HUMAN,
            "run.takeover",
        )

    async def return_control(self, actor: Actor, run_id: str) -> Run:
        return await self._transition(
            actor, run_id, {RunState.WAITING_HUMAN}, RunState.RUNNING, "run.return_control"
        )

    async def wait_for_approval(self, actor: Actor, run_id: str) -> Run:
        return await self._transition(
            actor,
            run_id,
            {RunState.RUNNING},
            RunState.WAITING_APPROVAL,
            "run.waiting_approval",
        )

    async def continue_after_approval(self, actor: Actor, run_id: str) -> Run:
        """Resume only after the bound approval has been consumed exactly once."""
        return await self._transition(
            actor,
            run_id,
            {RunState.WAITING_APPROVAL},
            RunState.RUNNING,
            "run.approval_consumed",
        )

    async def finish_run(self, actor: Actor, run_id: str, *, succeeded: bool) -> Run:
        return await self._transition(
            actor,
            run_id,
            {RunState.RUNNING},
            RunState.SUCCEEDED if succeeded else RunState.FAILED,
            "run.succeed" if succeeded else "run.fail",
        )

    async def request_approval(
        self,
        actor: Actor,
        *,
        run_id: str,
        step_id: str | None,
        action: Action,
        preview: dict[str, Any],
        diff: dict[str, Any],
        page_revision: str,
        evidence_ids: list[str],
        object_scope: dict[str, Any],
        ttl: timedelta,
    ) -> Approval:
        await self._ensure_loaded()
        self._require(actor, Role.OPERATOR)
        run = self._run_for(actor, run_id)
        if run.profile_id is None or run.placement is None:
            raise ValueError("approval requires a bound profile and placement")
        approval = self._approval_service.request(
            run_id=run_id,
            step_id=step_id,
            action=action,
            profile_id=run.profile_id,
            placement=run.placement,
            preview=preview,
            diff=diff,
            page_revision=page_revision,
            evidence_ids=evidence_ids,
            object_scope=object_scope,
            ttl=ttl,
        )
        self._approval_tenants[approval.id] = actor.tenant_id
        await self._record(actor, "approval.request", "approval", approval.id)
        return approval

    async def approve(self, actor: Actor, approval_id: str) -> Approval:
        await self._ensure_loaded()
        self._require(actor, Role.APPROVER)
        self._approval_for(actor, approval_id)
        approval = self._approval_service.approve(approval_id, actor.user_id)
        await self._record(actor, "approval.approve", "approval", approval_id)
        return approval

    async def reject(self, actor: Actor, approval_id: str) -> Approval:
        await self._ensure_loaded()
        self._require(actor, Role.APPROVER)
        self._approval_for(actor, approval_id)
        approval = self._approval_service.reject(approval_id, actor.user_id)
        await self._record(actor, "approval.reject", "approval", approval_id)
        return approval

    async def revoke_approval(self, actor: Actor, approval_id: str) -> Approval:
        await self._ensure_loaded()
        self._require(actor, Role.APPROVER)
        self._approval_for(actor, approval_id)
        approval = self._approval_service.revoke(approval_id, actor.user_id)
        await self._record(actor, "approval.revoke", "approval", approval_id)
        return approval

    async def consume_approval(
        self,
        actor: Actor,
        approval_id: str,
        *,
        action: Action,
        page_revision: str,
        evidence_ids: list[str],
        object_scope: dict[str, Any],
    ) -> Approval:
        await self._ensure_loaded()
        self._require(actor, Role.OPERATOR)
        approval = self._approval_for(actor, approval_id)
        run = self._run_for(actor, approval.run_id)
        if run.profile_id is None or run.placement is None:
            raise ValueError("approval consumption requires a bound profile and placement")
        consumed = self._approval_service.consume(
            approval_id,
            action,
            profile_id=run.profile_id,
            placement=run.placement,
            page_revision=page_revision,
            evidence_ids=evidence_ids,
            object_scope=object_scope,
        )
        await self._record(actor, "approval.consume", "approval", approval_id)
        return consumed

    async def claim_consumed_approval_execution(
        self,
        actor: Actor,
        approval_id: str,
        *,
        action: Action,
        operation: str,
        object_scope: dict[str, Any],
    ) -> Approval:
        """Atomically claim a consumed approval for one external execution."""
        await self._ensure_loaded()
        self._require(actor, Role.OPERATOR)
        approval = self._approval_for(actor, approval_id)
        self._run_for(actor, approval.run_id)
        if approval.state != ApprovalState.CONSUMED:
            raise RuntimeError("approval must be consumed before browser execution")
        if approval.action_hash != action_digest(action):
            raise RuntimeError("consumed approval action binding does not match")
        if action.target.get("operation") != operation:
            raise RuntimeError("consumed approval operation binding does not match")
        if object_scope.get("operation") != operation:
            raise RuntimeError("consumed approval object operation does not match")
        if approval.object_digest != approval_binding_digest(object_scope):
            raise RuntimeError("consumed approval object binding does not match")
        async with self._lock:
            if approval_id in self._approval_execution_claims:
                raise RuntimeError("consumed approval execution was already claimed")
            self._approval_execution_claims[approval_id] = utc = datetime.now(
                timezone.utc
            ).isoformat()
        await self._record(
            actor,
            "approval.execution_claim",
            "approval",
            approval_id,
            {"claimed_at": utc},
        )
        return approval

    async def list_approvals(self, actor: Actor) -> tuple[Approval, ...]:
        await self._ensure_loaded()
        self._require_any(actor, {Role.VIEWER, Role.OPERATOR, Role.APPROVER, Role.ADMIN})
        return tuple(
            self._approval_service.get(approval_id)
            for approval_id, tenant_id in self._approval_tenants.items()
            if tenant_id == actor.tenant_id
        )

    async def set_plan_view(
        self,
        actor: Actor,
        run_id: str,
        *,
        candidates: list[dict[str, Any]],
        selection_reason: str,
    ) -> None:
        await self._ensure_loaded()
        self._require(actor, Role.OPERATOR)
        self._run_for(actor, run_id)
        self._plan_views[run_id] = {
            "candidates": list(candidates),
            "selection_reason": selection_reason,
        }
        await self._record(actor, "run.plan_view", "run", run_id)

    async def run_detail(self, actor: Actor, run_id: str) -> dict[str, Any]:
        run = await self.get_run(actor, run_id)
        goal = self._goal_for(actor, run.goal_id)
        plan_view = self._plan_views.get(run_id, {"candidates": [], "selection_reason": ""})
        timeline = tuple(
            item
            for item in self._audit
            if item.tenant_id == actor.tenant_id and item.resource_id in {run.id, goal.id}
        )
        return {
            "run": run,
            "goal": goal,
            "timeline": timeline,
            "result": self._run_results.get(run_id),
            **plan_view,
        }

    async def create_conversation(
        self,
        actor: Actor,
        *,
        title: str,
    ) -> ButlerConversation:
        await self._ensure_loaded()
        self._require(actor, Role.OPERATOR)
        normalized = " ".join(title.split())[:160] or "新会话"
        conversation = ButlerConversation(title=normalized)
        async with self._lock:
            self._conversations[conversation.id] = _TenantConversation(
                actor.tenant_id, conversation
            )
        await self._record(actor, "conversation.create", "conversation", conversation.id)
        return conversation

    async def get_conversation(
        self,
        actor: Actor,
        conversation_id: str,
    ) -> ButlerConversation:
        await self._ensure_loaded()
        self._require_any(actor, {Role.VIEWER, Role.OPERATOR, Role.APPROVER, Role.ADMIN})
        return self._conversation_for(actor, conversation_id)

    async def list_conversations(
        self,
        actor: Actor,
        *,
        limit: int = 50,
    ) -> tuple[ButlerConversation, ...]:
        await self._ensure_loaded()
        self._require_any(actor, {Role.VIEWER, Role.OPERATOR, Role.APPROVER, Role.ADMIN})
        if not 1 <= limit <= 200:
            raise ValueError("conversation limit must be between 1 and 200")
        own = [
            item.conversation
            for item in self._conversations.values()
            if item.tenant_id == actor.tenant_id
        ]
        return tuple(sorted(own, key=lambda item: item.updated_at, reverse=True)[:limit])

    async def append_conversation_message(
        self,
        actor: Actor,
        conversation_id: str,
        *,
        role: ConversationRole,
        content: str,
        kind: str | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ButlerConversation:
        await self._ensure_loaded()
        self._require(actor, Role.OPERATOR)
        current = self._conversation_for(actor, conversation_id)
        if run_id is not None:
            self._run_for(actor, run_id)
        message = ConversationMessage(
            role=role,
            content=content.strip(),
            kind=kind,
            run_id=run_id,
            metadata=metadata or {},
        )
        updated = current.model_copy(
            update={
                "messages": (*current.messages[-199:], message),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        async with self._lock:
            self._conversations[conversation_id] = _TenantConversation(actor.tenant_id, updated)
        await self._record(
            actor,
            "conversation.message",
            "conversation",
            conversation_id,
            {"role": role.value, "kind": kind, "run_id": run_id},
        )
        return updated

    async def update_conversation_context(
        self,
        actor: Actor,
        conversation_id: str,
        *,
        last_intent: str,
        context: dict[str, Any],
    ) -> ButlerConversation:
        await self._ensure_loaded()
        self._require(actor, Role.OPERATOR)
        current = self._conversation_for(actor, conversation_id)
        updated = current.model_copy(
            update={
                "last_intent": last_intent,
                "context": dict(context),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        async with self._lock:
            self._conversations[conversation_id] = _TenantConversation(actor.tenant_id, updated)
        await self._record(
            actor,
            "conversation.context",
            "conversation",
            conversation_id,
            {"last_intent": last_intent},
        )
        return updated

    async def list_runs(
        self,
        actor: Actor,
        *,
        states: list[str] | None = None,
        limit: int = 100,
    ) -> tuple[Run, ...]:
        await self._ensure_loaded()
        self._require_any(actor, {Role.VIEWER, Role.OPERATOR, Role.APPROVER, Role.ADMIN})
        if not 1 <= limit <= 500:
            raise ValueError("run limit must be between 1 and 500")
        allowed_states = {RunState(value) for value in states} if states else None
        own = [
            item.run
            for item in self._runs.values()
            if item.tenant_id == actor.tenant_id
            and (allowed_states is None or item.run.state in allowed_states)
        ]
        return tuple(sorted(own, key=lambda item: item.created_at, reverse=True)[:limit])

    async def set_run_result(
        self,
        actor: Actor,
        run_id: str,
        result: dict[str, Any],
    ) -> None:
        await self._ensure_loaded()
        self._require(actor, Role.OPERATOR)
        self._run_for(actor, run_id)
        self._run_results[run_id] = dict(result)
        await self._record(actor, "run.result", "run", run_id)

    async def get_run_result(
        self,
        actor: Actor,
        run_id: str,
    ) -> dict[str, Any] | None:
        await self.get_run(actor, run_id)
        result = self._run_results.get(run_id)
        return dict(result) if result is not None else None

    async def upsert_resource(
        self,
        actor: Actor,
        category: str,
        resource_id: str,
        value: dict[str, Any],
    ) -> None:
        await self._ensure_loaded()
        self._require(actor, Role.OPERATOR)
        if category not in {
            "agents",
            "profiles",
            "nodes",
            "policies",
            "artifacts",
            "memories",
            "shopping_workspaces",
            "xianyu_buy_workspaces",
            "xianyu_listing_workspaces",
            "xianyu_store_workspaces",
            "action_previews",
        }:
            raise ValueError("unsupported resource category")
        tenant = self._resources.setdefault(actor.tenant_id, {})
        tenant.setdefault(category, {})[resource_id] = dict(value)
        await self._record(actor, f"{category}.upsert", category, resource_id)

    async def list_resources(
        self,
        actor: Actor,
        category: str,
        *,
        resource_ids: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        await self._ensure_loaded()
        self._require_any(actor, {Role.VIEWER, Role.OPERATOR, Role.ADMIN})
        own = self._resources.get(actor.tenant_id, {}).get(category, {})
        if resource_ids is None:
            return dict(own)
        for resource_id in resource_ids:
            if resource_id not in own and any(
                resource_id in tenant.get(category, {})
                for tenant_id, tenant in self._resources.items()
                if tenant_id != actor.tenant_id
            ):
                raise PermissionDenied("resource is outside actor tenant")
        return {resource_id: own[resource_id] for resource_id in resource_ids if resource_id in own}

    def _approval_for(self, actor: Actor, approval_id: str) -> Approval:
        if self._approval_tenants.get(approval_id) != actor.tenant_id:
            raise PermissionDenied("approval is outside actor tenant")
        return self._approval_service.get(approval_id)

    async def _transition(
        self, actor: Actor, run_id: str, allowed: set[RunState], target: RunState, action: str
    ) -> Run:
        await self._ensure_loaded()
        self._require(actor, Role.OPERATOR)
        current = self._run_for(actor, run_id)
        if current.state not in allowed:
            raise RuntimeError(f"cannot {action} from {current.state.value}")
        updates: dict[str, Any] = {"state": target}
        if target == RunState.RUNNING and current.started_at is None:
            updates["started_at"] = datetime.now(timezone.utc)
        if target in {RunState.CANCELLED, RunState.SUCCEEDED, RunState.FAILED}:
            updates["finished_at"] = datetime.now(timezone.utc)
        updated = current.model_copy(update=updates)
        async with self._lock:
            self._runs[run_id] = _TenantRun(actor.tenant_id, updated)
        await self._record(actor, action, "run", run_id, {"state": target.value})
        return updated

    async def _record(
        self,
        actor: Actor,
        action: str,
        resource_type: str,
        resource_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._audit.append(
            AuditEntry(
                actor.user_id,
                actor.tenant_id,
                action,
                resource_type,
                resource_id,
                details=details or {},
            )
        )
        await self._persist()
        await self.events.publish(
            actor.tenant_id, action, {"resource_id": resource_id, **(details or {})}
        )

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        async with self._lock:
            if self._loaded:
                return
            assert self._state_store is not None
            state = await self._state_store.load()
            if state is not None:
                self._restore(state)
            self._loaded = True

    async def _persist(self) -> None:
        if self._state_store is not None:
            async with self._persist_lock:
                await self._state_store.save(self._snapshot())

    def _snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "goals": [
                {"tenant_id": value.tenant_id, "goal": value.goal.model_dump(mode="json")}
                for value in self._goals.values()
            ],
            "runs": [
                {"tenant_id": value.tenant_id, "run": value.run.model_dump(mode="json")}
                for value in self._runs.values()
            ],
            "audit": [
                {
                    "actor_id": item.actor_id,
                    "tenant_id": item.tenant_id,
                    "action": item.action,
                    "resource_type": item.resource_type,
                    "resource_id": item.resource_id,
                    "occurred_at": item.occurred_at.isoformat(),
                    "details": item.details,
                }
                for item in self._audit
            ],
            "approvals": self._approval_service.snapshot(),
            "approval_tenants": dict(self._approval_tenants),
            "approval_execution_claims": dict(self._approval_execution_claims),
            "plan_views": self._plan_views,
            "conversations": [
                {
                    "tenant_id": value.tenant_id,
                    "conversation": value.conversation.model_dump(mode="json"),
                }
                for value in self._conversations.values()
            ],
            "run_results": self._run_results,
            "resources": self._resources,
        }

    def _restore(self, state: dict[str, Any]) -> None:
        if state.get("schema_version") != "1":
            raise RuntimeError("unsupported application-state schema")
        self._goals = {
            item["goal"]["id"]: _TenantGoal(
                item["tenant_id"], GoalContract.model_validate(item["goal"])
            )
            for item in state.get("goals", [])
        }
        self._runs = {
            item["run"]["id"]: _TenantRun(item["tenant_id"], Run.model_validate(item["run"]))
            for item in state.get("runs", [])
        }
        self._audit = [
            AuditEntry(
                actor_id=item["actor_id"],
                tenant_id=item["tenant_id"],
                action=item["action"],
                resource_type=item["resource_type"],
                resource_id=item["resource_id"],
                occurred_at=datetime.fromisoformat(item["occurred_at"]),
                details=item.get("details", {}),
            )
            for item in state.get("audit", [])
        ]
        self._approval_service.restore(state.get("approvals", {}))
        self._approval_tenants = dict(state.get("approval_tenants", {}))
        self._approval_execution_claims = dict(state.get("approval_execution_claims", {}))
        self._plan_views = dict(state.get("plan_views", {}))
        self._conversations = {
            item["conversation"]["id"]: _TenantConversation(
                item["tenant_id"],
                ButlerConversation.model_validate(item["conversation"]),
            )
            for item in state.get("conversations", [])
        }
        self._run_results = {
            run_id: dict(result) for run_id, result in state.get("run_results", {}).items()
        }
        self._resources = dict(state.get("resources", {}))

    def _conversation_for(
        self,
        actor: Actor,
        conversation_id: str,
    ) -> ButlerConversation:
        record = self._conversations.get(conversation_id)
        if record is None or record.tenant_id != actor.tenant_id:
            raise PermissionDenied("conversation is outside actor tenant")
        return record.conversation

    def _goal_for(self, actor: Actor, goal_id: str) -> GoalContract:
        record = self._goals.get(goal_id)
        if record is None or record.tenant_id != actor.tenant_id:
            raise PermissionDenied("goal is outside actor tenant")
        return record.goal

    def _run_for(self, actor: Actor, run_id: str) -> Run:
        record = self._runs.get(run_id)
        if record is None or record.tenant_id != actor.tenant_id:
            raise PermissionDenied("run is outside actor tenant")
        return record.run

    @staticmethod
    def _require(actor: Actor, role: Role) -> None:
        if Role.ADMIN not in actor.roles and role not in actor.roles:
            raise PermissionDenied(f"role {role.value} is required")

    @staticmethod
    def _require_any(actor: Actor, roles: set[Role]) -> None:
        if Role.ADMIN not in actor.roles and actor.roles.isdisjoint(roles):
            raise PermissionDenied("actor has no permitted role")
