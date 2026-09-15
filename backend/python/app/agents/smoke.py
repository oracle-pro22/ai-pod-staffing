from decimal import Decimal
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from pydantic import Field

from app.contracts import Contract


class CapacityArguments(Contract):
    committed_hours: float = Field(ge=0, le=80, allow_inf_nan=False)
    available_hours: float = Field(gt=0, le=80, allow_inf_nan=False)


@tool(args_schema=CapacityArguments)
def calculate_weekly_percentage(committed_hours: float, available_hours: float) -> dict:
    """Calculate committed hours divided by available hours times 100. Reads no database and writes nothing."""
    result = Decimal(str(committed_hours)) / Decimal(str(available_hours)) * 100
    return {"allocation_pct": float(result.quantize(Decimal("0.01")))}


class SmokeState(TypedDict, total=False):
    messages: list
    tool_result: dict
    final_received: bool


def build_smoke_graph(model):
    """Bounded integration proof, NOT the staffing graph. One model-request/tool/model-response cycle."""
    bound = model.bind_tools([calculate_weekly_percentage])

    def ask(state):
        response = bound.invoke(state["messages"], config={"callbacks": []})
        calls = response.tool_calls
        if len(calls) != 1 or calls[0]["name"] != calculate_weekly_percentage.name:
            raise ValueError("Model did not return exactly the expected tool call")
        arguments = CapacityArguments.model_validate(calls[0]["args"])
        if arguments.committed_hours != 16 or arguments.available_hours != 40:
            raise ValueError("Model changed the fixed smoke-test inputs")
        return {"messages": [*state["messages"], response]}

    def execute(state):
        call = state["messages"][-1].tool_calls[0]
        result = calculate_weekly_percentage.invoke(call["args"])
        return {"tool_result": result, "messages": [*state["messages"],
            ToolMessage(content=str(result), tool_call_id=call["id"])]}

    def finish(state):
        response = bound.invoke(state["messages"], config={"callbacks": []})
        if response.tool_calls or not response.content:
            raise ValueError("Model did not finish after receiving the tool result")
        return {"final_received": True}

    graph = StateGraph(SmokeState)
    graph.add_node("request_tool", ask)
    graph.add_node("execute_tool", execute)
    graph.add_node("consume_result", finish)
    graph.add_edge(START, "request_tool")
    graph.add_edge("request_tool", "execute_tool")
    graph.add_edge("execute_tool", "consume_result")
    graph.add_edge("consume_result", END)
    return graph.compile()  # Deliberately no in-memory persistence claim; durable saver comes later.


def run_smoke(model):
    return build_smoke_graph(model).invoke({"messages": [
        SystemMessage(content="You are testing tool interoperability. Call calculate_weekly_percentage exactly once using committed_hours=16 and available_hours=40. After the tool result, state the percentage and do not call another tool."),
        HumanMessage(content="Use the calculation tool to find the allocation for 16 committed hours out of 40 available hours."),
    ]}, config={"recursion_limit": 6, "callbacks": []})
