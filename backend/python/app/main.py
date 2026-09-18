import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from uuid import uuid4

from fastapi import Depends, FastAPI, Query, Request
from pydantic import Field
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.auth import Actor, AuthorizationRepository, TokenVerifier
from app.config import Settings
from app.database import OracleDatabase
from app.errors import ServiceError
from app.contracts import Contract, CaptainDecision
from app.decisions import DecisionStore
from app.execution_store import ExecutionStore
from app.storage import load_policy
from app.policy_admin import PolicyAdminStore, UtilizationUpdate, active_policy_version
from app.assignments import AssignmentStore, CloseProject
from app.personas import PersonaRepository, PersonaSelection, constrain_actor, mint_session, require_management
from app.accounts import AccountStore, PasswordLogin
from app.selections import SelectionStore, SelectionUpdate
from app.manual_store import ManualStore, ManualPreviewInput, ManualDecisionInput
from datetime import date
from typing import Literal

log = logging.getLogger("staffing.backend")


class EnqueueExecution(Contract):
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")


def create_app(settings: Settings | None = None, database=None, verifier=None, authorization=None, executions=None, decisions=None, assignments=None, accounts=None, selections=None, manual=None) -> FastAPI:
    settings = settings or Settings()
    database = database or OracleDatabase(settings)
    verifier = verifier or TokenVerifier(settings)
    authorization = authorization or AuthorizationRepository(database)
    executions = executions or ExecutionStore(database, settings)
    decisions = decisions or DecisionStore(database, settings)
    assignments = assignments or AssignmentStore(database, settings)
    personas = PersonaRepository(database)
    policy_admin = PolicyAdminStore(database)
    accounts = accounts or AccountStore(database, settings)
    selections = selections or SelectionStore(database, settings)
    manual = manual or ManualStore(database, settings)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        database.close()

    app = FastAPI(title="AI POD Staffing Backend", version="0.5.0", lifespan=lifespan,
                  docs_url="/docs" if settings.backend_env != "production" else None,
                  redoc_url=None, openapi_url="/openapi.json" if settings.backend_env != "production" else None)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.correlation_id = uuid4().hex
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, error: ServiceError):
        headers = {"WWW-Authenticate": "Bearer"} if error.status == 401 else {}
        return JSONResponse({"error": {"code": error.code, "message": error.message},
                             "correlation_id": request.state.correlation_id}, status_code=error.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _error):
        # Pydantic's default HTTP error includes submitted values; do not echo employee text or tokens.
        return JSONResponse({"error": {"code": "INVALID_REQUEST", "message": "The request does not match the API contract."},
                             "correlation_id": request.state.correlation_id}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception):
        log.error("Backend request failed: type=%s correlation_id=%s", type(error).__name__, request.state.correlation_id)
        return JSONResponse({"error": {"code": "INTERNAL_ERROR", "message": "The operation could not be completed."},
                             "correlation_id": request.state.correlation_id}, status_code=500,
                            headers={"Cache-Control": "no-store"})

    def current_actor(request: Request) -> Actor:
        if settings.backend_auth_mode == "password":
            return authorization.resolve(accounts.subject(request.headers.get("authorization")))
        if settings.staffing_demo_personas_enabled:
            identity = verifier.persona(request.headers.get("authorization"))
            # Re-read active person/role mappings and permissions on every API
            # request. A signed persona chooses one role; it never grants it.
            return constrain_actor(authorization.resolve(identity.sub), identity)
        subject = verifier.subject(request.headers.get("authorization"))
        return authorization.resolve(subject)

    def local_persona_management(request: Request):
        require_management(settings, request.headers.get("authorization"),
                           request.client.host if request.client else None)

    @app.post("/v1/auth/password/login")
    def password_login(body: PasswordLogin):
        return accounts.login(body)

    @app.post("/v1/auth/password/logout")
    def password_logout(request: Request):
        return accounts.logout(request.headers.get("authorization"))

    @app.get("/v1/local-personas", dependencies=[Depends(local_persona_management)])
    def local_personas():
        return {"personas": personas.list()}

    @app.post("/v1/local-personas/session", dependencies=[Depends(local_persona_management)])
    def local_persona_session(body: PersonaSelection):
        personas.require_selection(body)
        return mint_session(body, settings)

    @app.get("/health/live")
    def live():
        return {"status": "ok", "service": "ai-pod-staffing-backend", "phase": 5}

    @app.get("/health/ready")
    def ready():
        database.ping()
        return {"status": "ok", "database": "reachable", "phase": 5}

    @app.get("/v1/me")
    def me(actor: Actor = Depends(current_actor)):
        return {"person_id": actor.person_id, "identity_subject": actor.subject, "roles": sorted(actor.roles),
                "full_name": actor.full_name,
                "permissions": [asdict(row) for row in actor.permissions]}

    @app.get("/v1/policy")
    def policy(actor: Actor = Depends(current_actor)):
        actor.require("AGENT_EXECUTION", "view")
        with database.read() as connection:
            return load_policy(connection, active_policy_version(connection))

    @app.get('/v1/admin/utilization')
    def utilization(actor: Actor = Depends(current_actor)):
        return policy_admin.get(actor)

    @app.post('/v1/admin/utilization')
    def update_utilization(body: UtilizationUpdate, actor: Actor = Depends(current_actor)):
        return policy_admin.update(actor, body)

    @app.post("/v1/requests/{request_id}/executions", status_code=202)
    def start_execution(request_id: str, body: EnqueueExecution, actor: Actor = Depends(current_actor)):
        actor.require("AGENT_EXECUTION", "create", "POD_CAPTAIN")
        return executions.enqueue(request_id, actor.subject, actor.person_id, body.idempotency_key)

    @app.get("/v1/executions/{execution_id}")
    def execution(execution_id: str, after: int = Query(default=0, ge=0), actor: Actor = Depends(current_actor)):
        actor.require("AGENT_EXECUTION", "view")
        return executions.get_execution(execution_id, actor, after)

    @app.get("/v1/proposals/{proposal_id}")
    def proposal(proposal_id: str, actor: Actor = Depends(current_actor)):
        actor.require("AGENT_EXECUTION", "view")
        return executions.get_proposal(proposal_id, actor)

    @app.get("/v1/requests")
    def requests(actor: Actor = Depends(current_actor)):
        return executions.visible_requests(actor)

    @app.get("/v1/requests/{request_id}/execution")
    def latest_execution(request_id: str, actor: Actor = Depends(current_actor)):
        return executions.latest(request_id, actor)

    @app.post("/v1/decisions")
    def decide(body: CaptainDecision, actor: Actor = Depends(current_actor)):
        return decisions.decide(actor, body)

    @app.post("/v1/proposals/{proposal_id}/selection")
    def update_selection(proposal_id: str, body: SelectionUpdate, actor: Actor = Depends(current_actor)):
        actor.require("AI_FITMENT", "approve", "POD_CAPTAIN")
        return selections.update(actor, proposal_id, body)

    @app.get('/v1/requests/{request_id}/proposal')
    def latest_proposal(request_id: str, actor: Actor = Depends(current_actor)):
        actor.require('AI_FITMENT', 'view')
        return executions.latest_proposal(request_id, actor)

    @app.get('/v1/requests/{request_id}/manual')
    def manual_state(request_id: str, actor: Actor = Depends(current_actor)):
        actor.require('AI_FITMENT', 'approve', 'POD_CAPTAIN')
        return manual.get(actor, request_id)

    @app.post('/v1/requests/{request_id}/manual-preview')
    def manual_preview(request_id: str, body: ManualPreviewInput, actor: Actor = Depends(current_actor)):
        actor.require('AI_FITMENT', 'approve', 'POD_CAPTAIN')
        return manual.preview(actor, request_id, body)

    @app.post('/v1/requests/{request_id}/manual-decision')
    def manual_decision(request_id: str, body: ManualDecisionInput, actor: Actor = Depends(current_actor)):
        actor.require('AI_FITMENT', 'approve', 'POD_CAPTAIN')
        return manual.decide(actor, request_id, body)

    @app.get("/v1/workspace")
    def workspace(week: date | None = None, resource: Literal["REQUESTS", "ALLOCATION_CALENDAR", "REPORTS", "TEAM_SKILLS", "MY_AVAILABILITY"] = "REQUESTS", actor: Actor = Depends(current_actor)):
        return assignments.workspace(actor, week, resource)

    @app.get('/v1/reports/export')
    def export_report(week: date | None = None, actor: Actor = Depends(current_actor)):
        actor.require('REPORTS', 'export')
        return assignments.workspace(actor, week, 'REPORTS')

    @app.post("/v1/requests/{request_id}/close")
    def close_project(request_id: str, body: CloseProject, actor: Actor = Depends(current_actor)):
        return assignments.close(actor, request_id, body)

    return app


app = create_app()
