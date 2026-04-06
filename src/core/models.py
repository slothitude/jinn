from typing import Any, Dict, List
from pydantic import BaseModel, Field


class AgentRequest(BaseModel):
    session_id: str
    input_text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentState(BaseModel):
    session_id: str
    turn_count: int = 0
    history: List[Dict[str, str]] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    agent_id: str = "BUDDY"
    model_route: str = "sonnet"
    memory_strategy: str = "standard"
