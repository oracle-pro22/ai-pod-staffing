"""LangGraph orchestration with fenced Oracle stage checkpoints, not in-memory job durability."""
from typing import TypedDict

from app.agent_budget import remaining_model_calls
from app.agents.staffing import ANALYST_READS, Analysis, Selection, ToolSession, run_agent
from app.errors import ServiceError
from app.planning import SearchResult, find_options
from app.agents.supervisor import choose_transition, execution_status


class State(TypedDict):
    outcome: str
    route: str


class StaffingWorkflow:
    def __init__(self, store, job, model_factory):
        self.store, self.job, self.model_factory = store, job, model_factory
        self.model = None

    def save(self, stage, summary):
        self.store.save(self.job, stage, summary)

    def collect(self, _state):
        if self.job.evidence is None:
            self.job.evidence = self.store.load_evidence(self.job)
            self.store.save(self.job, "evidence", "Request, catalogue, role, skill and capacity evidence loaded.", bundle=self.job.evidence)
        return {"outcome": "RUNNING"}

    def agent(self, session, planner=False):
        stage = "planner" if planner else "analyst"
        remaining = remaining_model_calls(self.job.checkpoint, self.job.evidence.policy.maximum_agent_steps, stage)
        if not planner:
            reads = self.job.checkpoint.get("analysis_reads", [])
            if (not isinstance(reads, list) or any(not isinstance(name, str) for name in reads)
                or len(reads) != len(set(reads)) or not set(reads) <= ANALYST_READS):
                raise ServiceError("INVALID_CHECKPOINT", "Saved Analyst reads are invalid.", 409)
            session.seen.update(reads)

        def remember_analysis_read(name):
            self.job.checkpoint["analysis_reads"] = sorted(session.seen & ANALYST_READS)
            self.save("analyst", "Required request evidence read and checkpointed.")

        if self.model is None:
            self.model = self.model_factory()
        return run_agent(self.model, session,
            lambda: self.store.save(self.job, stage, "Model call budget reserved.", reserve="model_calls"),
            lambda _name: self.store.save(self.job, stage, "Allowlisted tool call budget reserved.", reserve="tool_calls"),
            planner, max_model_calls=remaining, after_analysis_read=None if planner else remember_analysis_read)

    def analyse(self, _state):
        if "analysis" not in self.job.checkpoint:
            analysis = self.agent(ToolSession(self.job.evidence))
            self.job.checkpoint["analysis"] = analysis.model_dump(mode="json")
            self.save("analysis", "Request and evidence analysis completed.")
        try:
            analysis = Analysis.model_validate(self.job.checkpoint["analysis"])
            ToolSession(self.job.evidence).validate_analysis(analysis)
        except ValueError as error:
            raise ServiceError("INVALID_CHECKPOINT", "Saved analysis does not match the request's business inputs.", 409) from error
        if analysis.clarification_questions and not _state.get("supervised"):
            self.store.finish(self.job, "NEEDS_INFORMATION", "BUSINESS_CLARIFICATION", "Captain clarification is required before a proposal can be prepared.")
            return {"outcome": "NEEDS_INFORMATION"}
        return {"outcome": "RUNNING"}

    def supervise(self, _state):
        # If a worker crashed after persisting a delegation, resume that exact
        # delegation without paying for another Supervisor choice.
        pending = self.job.checkpoint.get("supervisor_pending")
        routes = {"delegate_analysis": "analysis_delegate", "delegate_planning": "planning_delegate",
                  "finish_review": "publish", "request_clarification": "clarify"}
        completed = ((pending == "delegate_analysis" and "analysis" in self.job.checkpoint)
                     or (pending == "delegate_planning" and "selection" in self.job.checkpoint))
        if completed:
            self.job.checkpoint.pop("supervisor_pending", None)
            self.job.checkpoint.pop("delegate_inflight", None)
            self.save("supervisor", "Recovered a completed delegate checkpoint without repeating it.")
            pending = None
        if pending:
            if pending not in routes or execution_status(self.job.checkpoint)["next_action"] != pending:
                raise ServiceError("INVALID_CHECKPOINT", "Saved Supervisor transition is inconsistent.", 409)
            return {"outcome": "RUNNING", "route": routes[pending]}
        if self.model is None:
            self.model = self.model_factory()
        action = choose_transition(self.model, self.job.checkpoint,
            lambda: self.store.save(self.job, "supervisor", "Supervisor model call reserved.", reserve="model_calls"),
            lambda: self.store.save(self.job, "supervisor", "Supervisor tool call reserved.", reserve="tool_calls"))
        if action != "inspect_execution_status":
            self.job.checkpoint["supervisor_pending"] = action
        self.save("supervisor", {
            "delegate_analysis": "Supervisor delegated request evidence to the Analyst.",
            "delegate_planning": "Supervisor delegated validated team planning to the Planner.",
            "inspect_execution_status": "Supervisor inspected completed stages and remaining work.",
            "request_clarification": "Supervisor routed validated business questions to the Captain.",
            "finish_review": "Supervisor requested final validation and Captain review.",
        }[action])
        return {"outcome": "RUNNING", "route": routes.get(action, "supervise")}

    def delegate(self, stage, fn):
        attempts = self.job.checkpoint.setdefault("delegate_attempts", {})
        # Persist 'in flight' separately; dependency/worker restarts resume this
        # attempt. Only an explicit recoverable output error consumes a replan.
        if self.job.checkpoint.get("delegate_inflight") != stage:
            attempts[stage] = attempts.get(stage, 0) + 1
            if attempts[stage] > 2:
                raise ServiceError("DELEGATION_EXHAUSTED", "Delegate retry limit exceeded.", 409)
            self.job.checkpoint["delegate_inflight"] = stage
            self.save("supervisor", "Delegate attempt checkpointed.")
        try:
            result = fn({"supervised": True})
        except ServiceError as error:
            if error.code != "INVALID_AGENT_OUTPUT":
                raise
            self.job.checkpoint["delegate_error"] = {"stage": stage, "code": error.code}
            result = {"outcome": "RUNNING"}
        else:
            self.job.checkpoint.pop("delegate_error", None)
        self.job.checkpoint.pop("delegate_inflight", None)
        self.job.checkpoint.pop("supervisor_pending", None)
        if result["outcome"] == "RUNNING":
            self.save("supervisor", "Delegate returned; Supervisor will inspect the outcome.")
        return result

    def analysis_delegate(self, _state):
        return self.delegate("analysis", self.analyse)

    def planning_delegate(self, _state):
        return self.delegate("planning", self.plan)

    def clarify(self, _state):
        analysis = Analysis.model_validate(self.job.checkpoint["analysis"])
        ToolSession(self.job.evidence).validate_analysis(analysis)
        if not analysis.clarification_questions:
            raise ServiceError("INVALID_CHECKPOINT", "No validated clarification exists.", 409)
        self.store.finish(self.job, "NEEDS_INFORMATION", "BUSINESS_CLARIFICATION",
                          "Captain clarification is required before a proposal can be prepared.")
        return {"outcome": "NEEDS_INFORMATION"}

    def plan(self, _state):
        if "search" not in self.job.checkpoint:
            search = find_options(self.job.evidence, limit=self.store.settings.staffing_search_limit)
            self.job.checkpoint["search"] = search.model_dump(mode="json")
            self.save("rules", "Deterministic team, capacity and effort validation completed.")
        search = SearchResult.model_validate(self.job.checkpoint["search"])
        if not search.options:
            if not search.exhaustive:
                status, code = "FAILED", "SEARCH_LIMIT"
                summary = "Bounded search found no feasible option; this is not proof that none exists."
            elif any(value in ("CAPACITY_UNKNOWN", "CAPACITY_STALE") for value in search.exclusions.values()):
                status, code = "NEEDS_INFORMATION", "CAPACITY_INFORMATION"
                summary = "No feasible option with current evidence; some candidate capacity needs verification."
            else:
                status, code = "NO_FEASIBLE_POD", "NO_FEASIBLE_POD"
                summary = "No POD satisfies the current rules under the supported daily scheduling model."
            self.store.finish(self.job, status, code, summary)
            return {"outcome": status}
        if "selection" not in self.job.checkpoint:
            session = ToolSession(self.job.evidence, search, Analysis.model_validate(self.job.checkpoint["analysis"]))
            selection = self.agent(session, planner=True)
            self.job.checkpoint["selection"] = selection.model_dump(mode="json")
            self.save("planning", "Validated POD option selected and explained.")
        return {"outcome": "RUNNING"}

    def publish(self, _state):
        selection = Selection.model_validate(self.job.checkpoint["selection"])
        search = SearchResult.model_validate(self.job.checkpoint["search"])
        option = next((p for p in search.options if p.plan_id == selection.plan_id), None)
        if option is None:
            raise ServiceError("INVALID_CHECKPOINT", "Selected option is absent from the saved search.", 409)
        # Recheck references as well as the live Oracle invariants when resuming a checkpoint.
        session = ToolSession(self.job.evidence, search, Analysis.model_validate(self.job.checkpoint["analysis"]))
        session.seen.add("get_validated_options")
        session.complete_plan(**selection.model_dump())
        self.store.publish(self.job, option, selection)
        return {"outcome": "READY_FOR_REVIEW"}

    def graph(self):
        from langgraph.graph import END, START, StateGraph
        graph = StateGraph(State)
        for name in ("collect", "supervise", "analysis_delegate", "planning_delegate", "clarify", "publish"):
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "collect")
        graph.add_edge("collect", "supervise")
        graph.add_conditional_edges("supervise", lambda state: state["route"])
        for stage in ("analysis_delegate", "planning_delegate"):
            graph.add_conditional_edges(stage, lambda state: "supervise" if state["outcome"] == "RUNNING" else END)
        graph.add_edge("clarify", END)
        graph.add_edge("publish", END)
        return graph.compile()

    def run(self):
        return self.graph().invoke({"outcome": "RUNNING", "route": "collect"}, config={"recursion_limit": 20, "callbacks": []})
