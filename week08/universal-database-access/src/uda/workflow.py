"""LangGraph workflow for one table: propose, validate, build a candidate.

The graph never contacts a database. Callers inject a LangChain chat model;
offline tests inject ``FakeListChatModel``. Model content is untrusted: it must
parse as ``ConceptProposal`` and pass physical-reference validation before any
candidate exists. Model transport errors propagate to the caller.
"""

from typing import Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict

from uda.candidate import build_candidate
from uda.models import Candidate, ConceptProposal, TableSchema
from uda.prompt import build_messages
from uda.validation import ValidationIssue, validate_proposal


class ProposalState(TypedDict, total=False):
    schema: TableSchema
    proposal: ConceptProposal | None
    issues: tuple[ValidationIssue, ...]
    candidate: Candidate | None
    error: str | None


class WorkflowResult(BaseModel):
    """Outcome of one proposal run.

    A candidate exists only when there is no error and no validation issue.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal: ConceptProposal | None = None
    issues: tuple[ValidationIssue, ...] = ()
    candidate: Candidate | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True only when a pending-review candidate was built."""
        return self.error is None and not self.issues and self.candidate is not None


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content

    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
    return "".join(parts)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[-1].strip().startswith("```"):
        lines = lines[1:-1]
    else:
        lines = lines[1:]
    return "\n".join(lines).strip()


def _first_line(exc: Exception) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else exc.__class__.__name__


def _compile(model: BaseChatModel):
    def propose_node(state: ProposalState) -> dict[str, Any]:
        response = model.invoke(build_messages(state["schema"]))
        text = _strip_code_fence(_message_text(response))
        try:
            proposal = ConceptProposal.model_validate_json(text)
        except ValueError as exc:
            return {
                "proposal": None,
                "error": f"LLM response is not a valid proposal: {_first_line(exc)}",
            }
        return {"proposal": proposal, "error": None}

    def validate_node(state: ProposalState) -> dict[str, Any]:
        proposal = state.get("proposal")
        if proposal is None:
            return {"issues": (), "error": "no proposal to validate"}

        issues = validate_proposal(state["schema"], proposal)
        return {"issues": issues, "error": None}

    def finalize_node(state: ProposalState) -> dict[str, Any]:
        proposal = state.get("proposal")
        if proposal is None:
            return {"candidate": None, "error": "no proposal to finalize"}

        return {"candidate": build_candidate(state["schema"], proposal)}

    def route_after_propose(state: ProposalState) -> str:
        return "validate" if state.get("error") is None else "end"

    def route_after_validate(state: ProposalState) -> str:
        if state.get("error") is not None or state.get("issues"):
            return "end"
        return "finalize"

    graph = StateGraph(ProposalState)
    graph.add_node("propose", propose_node)
    graph.add_node("validate", validate_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "propose")
    graph.add_conditional_edges(
        "propose",
        route_after_propose,
        {"validate": "validate", "end": END},
    )
    graph.add_conditional_edges(
        "validate",
        route_after_validate,
        {"finalize": "finalize", "end": END},
    )
    graph.add_edge("finalize", END)

    return graph.compile()


def run_workflow(schema: TableSchema, model: BaseChatModel) -> WorkflowResult:
    """Run one proposal through the graph. Fully offline when the model is local."""
    compiled = _compile(model)
    state: ProposalState = compiled.invoke({"schema": schema})
    return WorkflowResult(
        proposal=state.get("proposal"),
        issues=tuple(state.get("issues", ())),
        candidate=state.get("candidate"),
        error=state.get("error"),
    )
