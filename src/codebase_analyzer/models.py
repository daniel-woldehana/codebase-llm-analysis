from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParameterInfo(StrictModel):
    name: str
    type: str


class EndpointInfo(StrictModel):
    http_methods: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)


class MethodInfo(StrictModel):
    name: str
    signature: str
    return_type: str | None = None
    parameters: list[ParameterInfo] = Field(default_factory=list)
    modifiers: list[str] = Field(default_factory=list)
    annotations: list[str] = Field(default_factory=list)
    start_line: int
    end_line: int
    lines_of_code: int
    cyclomatic_complexity: int = Field(ge=1)
    endpoint: EndpointInfo | None = None
    description: str = ""
    noteworthy_aspects: list[str] = Field(default_factory=list)


class ClassInfo(StrictModel):
    name: str
    kind: Literal["class", "interface", "enum", "record", "annotation"]
    package: str | None = None
    modifiers: list[str] = Field(default_factory=list)
    annotations: list[str] = Field(default_factory=list)
    extends: list[str] = Field(default_factory=list)
    implements: list[str] = Field(default_factory=list)
    methods: list[MethodInfo] = Field(default_factory=list)
    description: str = ""


class FileMetrics(StrictModel):
    lines: int
    source_lines: int
    comment_lines: int
    blank_lines: int
    class_count: int
    method_count: int
    aggregate_cyclomatic_complexity: int
    max_method_complexity: int


class FileAnalysis(StrictModel):
    path: str
    language: str
    sha256: str
    size_bytes: int
    purpose: str = ""
    imports: list[str] = Field(default_factory=list)
    classes: list[ClassInfo] = Field(default_factory=list)
    metrics: FileMetrics
    dependencies: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    noteworthy_aspects: list[str] = Field(default_factory=list)
    llm_enriched: bool = False


class ProjectSource(StrictModel):
    repository_url: str | None = None
    local_path: str | None = None
    branch_or_ref: str | None = None
    commit: str | None = None


class ExecutionInfo(StrictModel):
    mode: Literal["llm", "offline"]
    provider: str
    model: str
    max_input_tokens: int
    reserved_output_tokens: int
    analyzed_file_count: int
    skipped_file_count: int
    cache_hits: int = 0
    warnings: list[str] = Field(default_factory=list)


class ProjectOverview(StrictModel):
    name: str
    purpose: str
    functionality: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    frameworks_and_libraries: list[str] = Field(default_factory=list)
    architecture_style: str = ""


class ArchitectureInfo(StrictModel):
    summary: str
    layers: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    data_flow: list[str] = Field(default_factory=list)


class RepositoryStatistics(StrictModel):
    total_files: int
    analyzed_files: int
    total_lines: int
    source_lines: int
    class_count: int
    method_count: int
    aggregate_cyclomatic_complexity: int
    average_method_complexity: float


class MethodReference(StrictModel):
    file: str
    class_name: str
    name: str
    signature: str
    cyclomatic_complexity: int
    description: str


class AnalysisReport(StrictModel):
    schema_version: str = "1.0"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: ProjectSource
    execution: ExecutionInfo
    project: ProjectOverview
    architecture: ArchitectureInfo
    statistics: RepositoryStatistics
    files: list[FileAnalysis]
    key_methods: list[MethodReference] = Field(default_factory=list)
    complexity_hotspots: list[MethodReference] = Field(default_factory=list)
    noteworthy_aspects: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


# Smaller schemas returned directly by the LLM.
# Keep these schemas compatible with strict structured-output providers:
# all fields are required, and open-ended dictionaries are avoided.
class LLMClassInsight(StrictModel):
    class_name: str
    description: str


class LLMMethodInsight(StrictModel):
    class_name: str
    method_name: str
    description: str
    noteworthy_aspects: list[str]


class LLMFileInsight(StrictModel):
    purpose: str
    class_insights: list[LLMClassInsight]
    method_insights: list[LLMMethodInsight]
    dependencies: list[str]
    risks: list[str]
    noteworthy_aspects: list[str]


class LLMRepositoryInsight(StrictModel):
    project_name: str
    purpose: str
    functionality: list[str]
    frameworks_and_libraries: list[str]
    architecture_style: str
    architecture_summary: str
    layers: list[str]
    patterns: list[str]
    data_flow: list[str]
    noteworthy_aspects: list[str]
    assumptions: list[str]
    limitations: list[str]