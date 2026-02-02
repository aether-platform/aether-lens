import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass
class PipelineEvent:
    """Base class for all pipeline events."""

    type: str
    timestamp: float

    def to_json(self) -> str:
        return json.dumps(asdict(self))


@dataclass
class TestStartedEvent(PipelineEvent):
    label: str
    test_type: str
    strategy: str


@dataclass
class TestProgressEvent(PipelineEvent):
    label: str
    status_text: str


@dataclass
class TestFinishedEvent(PipelineEvent):
    label: str
    status: str  # PASSED, FAILED, SKIPPED
    error: Optional[str] = None
    artifact: Optional[str] = None
    baseline: Optional[str] = None


@dataclass
class PipelineLogEvent(PipelineEvent):
    message: str
    level: str = "INFO"


@dataclass
class PipelineResultEvent(PipelineEvent):
    results: List[Dict[str, Any]]


@dataclass
class TestCase:
    id: str
    type: str
    label: str
    command: str
    description: Optional[str] = None
    execution_env: Optional[str] = None
    tags: List[str] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
