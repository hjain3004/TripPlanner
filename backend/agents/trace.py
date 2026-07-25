from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agents.models import TraceEvent


def artifact_hash(artifact: Any) -> str:
    if isinstance(artifact, BaseModel):
        payload = artifact.model_dump(mode="json")
    else:
        payload = artifact
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class TraceRecorder:
    def __init__(self, trace_id: str, trace_dir: Path | None = None) -> None:
        self.trace_id = trace_id
        self.trace_dir = trace_dir
        self.events: list[TraceEvent] = []

    def record(
        self,
        name: str,
        artifact: Any,
        *,
        model: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        event = TraceEvent.now(
            trace_id=self.trace_id,
            name=name,
            artifact_hash=artifact_hash(artifact),
            model=model,
            attributes=attributes,
        )
        self.events.append(event)
        self.flush()

    def flush(self) -> None:
        if self.trace_dir is None:
            return
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        path = self.trace_dir / f"{self.trace_id}.json"
        path.write_text(
            json.dumps(
                [event.model_dump(mode="json") for event in self.events],
                indent=2,
                sort_keys=True,
            )
        )
