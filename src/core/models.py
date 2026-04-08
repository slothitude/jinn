from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class Event(str, Enum):
    """Typed event names for the EventBus."""
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    AGENT_START = "agent_start"
    AGENT_CHUNK = "agent_chunk"
    AGENT_END = "agent_end"
    KAIROS_INTERRUPT = "kairos_interrupt"
    MEMORY_UPDATE = "memory_update"
    TOOL_CALL_REQUEST = "tool_call_request"
    TOOL_CALL_RESULT = "tool_call_result"
    DELEGATION_START = "delegation_start"
    DELEGATION_END = "delegation_end"


@dataclass
class EventResult:
    """Result of an emit() call — delivery count, cancellation state, collected errors."""
    delivered: int
    cancelled: bool = False
    errors: List[Exception] = field(default_factory=list)


class EventCancelled(Exception):
    """Raise in a subscriber to cancel event propagation to lower-priority subscribers."""


class AgentRequest(BaseModel):
    session_id: str
    input_text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PlanNode(BaseModel):
    id: int
    action: str
    cost: str = "low"
    status: str = "pending"  # pending, in_progress, completed, failed
    tool: Optional[str] = None                # "bash", "read", "write"
    tool_args: Optional[Dict[str, Any]] = None  # {"command": "pytest"}

    @model_validator(mode="after")
    def _validate_tool_spec(self) -> "PlanNode":
        has_tool = self.tool is not None
        has_args = self.tool_args is not None
        if has_tool and not has_args:
            raise ValueError(f"PlanNode(id={self.id}): tool '{self.tool}' specified without tool_args")
        if has_args and not has_tool:
            raise ValueError(f"PlanNode(id={self.id}): tool_args specified without tool")
        return self


class PlanGraph(BaseModel):
    nodes: List[PlanNode]
    dependencies: List[List[int]] = Field(default_factory=list)
    fail_safe: str = ""


class AgentState(BaseModel):
    session_id: str
    turn_count: int = 0
    history: List[Dict[str, str]] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    execution_graph: Optional[PlanGraph] = None
    current_node_index: int = 0
    current_input: str = ""


class PolicyDecision(BaseModel):
    agent_id: str = "BUDDY"
    model_route: str = "sonnet"
    memory_strategy: str = "standard"
    provider_override: str | None = None
    model_override: str | None = None


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str


class ToolResult(BaseModel):
    tool_call_id: str
    name: str
    output: str
    success: bool = True


class AgentTier(str, Enum):
    ORCHESTRATOR = "orchestrator"
    SUPERVISOR = "supervisor"
    WORKER = "worker"


class DelegationContext(BaseModel):
    task_description: str
    constraints: str = ""
    tier: AgentTier = AgentTier.SUPERVISOR
    provider: str = "zhipu"


class DelegationResult(BaseModel):
    success: bool
    output: str = ""
    errors: list[str] = Field(default_factory=list)
