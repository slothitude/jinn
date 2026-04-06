from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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


class PolicyDecision(BaseModel):
    agent_id: str = "BUDDY"
    model_route: str = "sonnet"
    memory_strategy: str = "standard"


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str


class ToolResult(BaseModel):
    tool_call_id: str
    name: str
    output: str
    success: bool = True
