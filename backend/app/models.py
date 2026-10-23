from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_BYTES = 15_000_000
MAX_ROWS = 20_000
MAX_COLUMNS = 40
MAX_FILES = 5


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message = message
        self.status = status
        super().__init__(message)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CsvFile(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=MAX_BYTES)


class StackPreparation(StrictModel):
    kind: Literal["stack"]
    fileIds: list[str] = Field(min_length=2, max_length=5)


class JoinPreparation(StrictModel):
    kind: Literal["join"]
    leftId: str = Field(min_length=1)
    rightId: str = Field(min_length=1)
    leftKey: str = Field(min_length=1)
    rightKey: str = Field(min_length=1)
    joinType: Literal["inner", "left"]


Operation = Annotated[StackPreparation | JoinPreparation, Field(discriminator="kind")]


class CanvasPoint(StrictModel):
    x: float = Field(ge=0, le=6000, allow_inf_nan=False)
    y: float = Field(ge=0, le=6000, allow_inf_nan=False)


class DerivedTable(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    operation: Operation


class TableGraph(StrictModel):
    kind: Literal["graph"] = "graph"
    operations: list[DerivedTable] = Field(default_factory=list, max_length=8)
    positions: dict[str, CanvasPoint] = Field(default_factory=dict, max_length=13)


class WorkspaceAction(StrictModel):
    action: Literal[
        "list",
        "create",
        "load",
        "delete",
        "patch",
        "removeFile",
        "renameTable",
        "canvas",
        "tablePreview",
        "pin",
        "exportDataset",
        "exportResult",
        "exportReport",
    ]
    workspaceId: str | None = None
    revision: int | None = Field(default=None, ge=0)
    title: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    question: str | None = Field(default=None, max_length=1000)
    fileId: str | None = None
    canvas: TableGraph | None = None
    tableId: str | None = Field(default=None, min_length=1, max_length=80)
    analysisId: str | None = None
    pinned: bool | None = None


class AnalysisRequest(StrictModel):
    workspaceId: str
    question: str = Field(min_length=1, max_length=1000)
    requestId: str
    dataVersion: int = Field(ge=0)
    tableId: str | None = Field(default=None, min_length=1, max_length=80)


Cell = str | int | float | None
Row = dict[str, Cell]
Json = dict[str, Any]


class UploadRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    bytes: int = Field(ge=1, le=MAX_BYTES)
    contentType: str = Field(default="text/csv", max_length=100)


class ChartConfig(StrictModel):
    type: Literal["bar", "line", "pie", "scatter", "none"] = "none"
    x_key: str = Field(default="", max_length=120)
    y_key: str = Field(default="", max_length=120)
    title: str = Field(default="Analysis", max_length=150)


class SqlPlan(StrictModel):
    sql_query: str = Field(default="", max_length=8000)
    chart_config: ChartConfig = Field(default_factory=ChartConfig)
    reasoning: str = Field(default="", max_length=1000)
    clarification: str = Field(default="", max_length=500)


class WorkspaceQuery(StrictModel):
    table_ids: list[str] = Field(min_length=1, max_length=13)
    plan: SqlPlan


class WorkspacePlan(StrictModel):
    title: str = Field(default="Workspace analysis", max_length=150)
    reasoning: str = Field(default="", max_length=1000)
    queries: list[WorkspaceQuery] = Field(default_factory=list, max_length=3)
    clarification: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def valid_outcome(self):
        if bool(self.queries) == bool(self.clarification):
            raise ValueError("Return queries or a clarification, exclusively.")
        return self


class DashboardCard(StrictModel):
    table_id: str = Field(max_length=80)
    plan: SqlPlan


class DashboardPlan(StrictModel):
    cards: list[DashboardCard] = Field(min_length=1, max_length=7)


class DashboardRequest(StrictModel):
    tableIds: list[str] = Field(default_factory=list, max_length=13)
    requestId: str = Field(min_length=36, max_length=36)
