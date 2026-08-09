from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NodePosition(BaseModel):
    x: float = 0
    y: float = 0


class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    type: str = Field(min_length=1, max_length=100)
    position: NodePosition = Field(default_factory=NodePosition)
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    id: str = Field(min_length=1, max_length=150)
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None


class WorkflowGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(default=2, ge=1, le=2)
    nodes: list[WorkflowNode] = Field(default_factory=list, max_length=500)
    edges: list[WorkflowEdge] = Field(default_factory=list, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    graph: WorkflowGraph = Field(default_factory=WorkflowGraph)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Project name cannot be blank")
        return value


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    graph: WorkflowGraph | None = None


class JobCreate(BaseModel):
    project_id: str | None = None
    graph: WorkflowGraph | None = None


class SettingsPatch(BaseModel):
    values: dict[str, Any]


class EngineTestRequest(BaseModel):
    engine_id: str


class ProviderTestRequest(BaseModel):
    provider_id: str = Field(min_length=1, max_length=100)


class ReferenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(min_length=1, max_length=100)
    role: Literal[
        "reference", "character", "style", "composition", "product", "environment",
        "start_frame", "end_frame", "mask", "front", "left", "right", "back", "top", "bottom",
    ] = "reference"
    weight: float = Field(default=1.0, ge=0.0, le=2.0)
    note: str = Field(default="", max_length=500)


class AgentPlanRequest(BaseModel):
    brief: str = Field(min_length=1, max_length=12000)
    target: Literal["image", "video", "film", "3d"] = "image"
    references: list[ReferenceSelection] = Field(default_factory=list, max_length=32)
    provider: str = Field(default="auto", max_length=100)
    model: str = Field(default="", max_length=240)
    local_first: bool = True
    aspect_ratio: str = Field(default="16:9", max_length=20)
    duration_seconds: int = Field(default=5, ge=1, le=600)
    output_resolution: Literal["preview", "1080p", "4k", "8k"] = "4k"
    create_project: bool = False
    project_name: str | None = Field(default=None, max_length=160)
    use_llm: bool = True
    planner_mode: Literal["auto", "rules", "llm"] = "auto"
    agent_model: str = Field(default="", max_length=240)

    @field_validator("brief")
    @classmethod
    def trim_brief(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Brief cannot be blank")
        return value


class AgentPlanResponse(BaseModel):
    graph: WorkflowGraph
    explanation: list[str]
    decisions: dict[str, Any]
    validation: dict[str, Any]
    project: dict[str, Any] | None = None


class BackupRequest(BaseModel):
    include_assets: bool = True
    include_outputs: bool = True


class RestoreRequest(BaseModel):
    backup_path: str
    replace_existing: bool = False


class GovernanceTaskPatch(BaseModel):
    status: Literal["PENDING", "DONE"]
    evidence: dict[str, Any] | None = None


class ProviderInvocationRequest(BaseModel):
    """Low-level provider diagnostic call. It is deliberately explicit and never used as a mock."""

    provider_id: str = Field(min_length=1, max_length=100)
    operation: Literal["enhance_prompt", "vision", "image", "image_edit", "video", "mesh"]
    prompt: str = Field(default="", max_length=12000)
    negative_prompt: str = Field(default="", max_length=4000)
    references: list[ReferenceSelection] = Field(default_factory=list, max_length=32)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_required_prompt_or_reference(self) -> "ProviderInvocationRequest":
        if not self.prompt.strip() and not self.references:
            raise ValueError("Provide a prompt or at least one reference")
        return self
