"""Explicit binding from retained document snapshots to FI2 extraction.

This module deliberately does not fetch documents or select an LLM provider.  The
acquisition workflow supplies an immutable :class:`SnapshotBundle` after it has
persisted the provider capture.  The caller must also name the extraction mode;
there is no environment-driven fallback from a scripted acceptance run to a
hosted model.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from agents.llm import LLMCallError, LLMClient, ScriptedLLMClient
from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import SnapshotBundle
from ingestion.diff import SnapshotDiff, diff_text
from ingestion.extraction import ExtractionOutcome, FinancialExtractor
from ingestion.storage import FinancialIngestionStore


class ExtractionMode(StrEnum):
    """The origin of an extraction response, kept visible through orchestration."""

    SCRIPTED_REPLAY = "scripted_replay"
    CURATOR_AUTHORED = "curator_authored"
    AUTHORIZED_CLIENT = "authorized_client"
    DISABLED = "disabled"


class ExtractionRuntimeError(ValueError):
    """Raised for an impossible or ambiguous extraction-runtime configuration."""


@dataclass(frozen=True)
class ExtractionRuntimeConfig:
    """A deliberately small, explicit extraction-client configuration.

    ``responses`` is accepted only for offline replay modes.  A real client is
    never constructed from environment variables here: enabling one requires a
    caller to inject an already-authorized ``LLMClient``.
    """

    mode: ExtractionMode
    responses: Sequence[object] = ()
    client: LLMClient | None = None
    extractor_version: str = "firecrawl-fi2-extractor-v1"

    def __post_init__(self) -> None:
        if not self.extractor_version.strip():
            raise ExtractionRuntimeError("extractor_version must not be blank")
        if self.mode in {ExtractionMode.SCRIPTED_REPLAY, ExtractionMode.CURATOR_AUTHORED}:
            if self.client is not None:
                raise ExtractionRuntimeError("replay modes cannot also receive a live client")
            if not self.responses:
                raise ExtractionRuntimeError("replay modes require an explicit scripted response")
        elif self.mode is ExtractionMode.AUTHORIZED_CLIENT:
            if self.client is None:
                raise ExtractionRuntimeError("authorized_client mode requires an injected client")
            if self.responses:
                raise ExtractionRuntimeError(
                    "authorized_client mode cannot contain scripted responses"
                )
        elif self.mode is ExtractionMode.DISABLED and (self.client is not None or self.responses):
            raise ExtractionRuntimeError(
                "disabled mode cannot contain a client or scripted response"
            )


class _OneAttemptClient:
    """Prevent a caller from making the FI2 extractor silently retry its client."""

    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner
        self.calls = 0

    def complete_json(
        self,
        *,
        node: str,
        system: str,
        user: str,
        schema: type[Any],
        temperature: float = 0.0,
        max_tokens: int = 2048,
        timeout_s: int = 20,
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        if node != "financial_extractor":
            raise LLMCallError("extraction runtime permits only financial_extractor")
        if self.calls >= 1:
            raise LLMCallError("extraction runtime allows one semantic invocation")
        self.calls += 1
        return self._inner.complete_json(
            node=node,
            system=system,
            user=user,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            tools=tools,
        )


def build_financial_extraction_client(config: ExtractionRuntimeConfig) -> LLMClient:
    """Return the one explicit client selected by ``config``.

    ``DISABLED`` intentionally has no client.  Callers should return a typed,
    zero-call outcome instead of treating disabled extraction as a failed model
    invocation.
    """

    if config.mode is ExtractionMode.DISABLED:
        raise ExtractionRuntimeError("disabled extraction has no client")
    if config.mode in {ExtractionMode.SCRIPTED_REPLAY, ExtractionMode.CURATOR_AUTHORED}:
        return _OneAttemptClient(
            ScriptedLLMClient({"financial_extractor": list(config.responses)})
        )
    assert config.client is not None
    return _OneAttemptClient(config.client)


@dataclass(frozen=True)
class ExtractionRuntimeOutcome:
    """The FI2 result plus an honest label for how its response was obtained."""

    mode: ExtractionMode
    outcome: ExtractionOutcome
    diff: SnapshotDiff


class FinancialExtractionRuntime:
    """Run the existing FI2 extractor against one already-retained snapshot."""

    def __init__(
        self,
        *,
        config: ExtractionRuntimeConfig,
        store: FinancialIngestionStore,
        artifacts: ContentAddressedStore,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.artifacts = artifacts
        self.now = now or (lambda: datetime.now(UTC))

    def extract_snapshot(
        self,
        *,
        target_table: str,
        target_id: str,
        current_row: dict[str, Any],
        current_row_hash: str | None,
        snapshot: SnapshotBundle,
        previous_snapshot: SnapshotBundle | None,
        client_event_id: str,
        manual_capture: bool = False,
    ) -> ExtractionRuntimeOutcome:
        """Extract at most once; unchanged snapshots and disabled mode call no model."""

        diff = diff_text(
            None if previous_snapshot is None else previous_snapshot.canonical_markdown,
            snapshot.canonical_markdown,
        )
        if self.config.mode is ExtractionMode.DISABLED:
            return ExtractionRuntimeOutcome(
                mode=self.config.mode,
                diff=diff,
                outcome=ExtractionOutcome(
                    status="extraction_failed",
                    calls=0,
                    diagnostic="financial extraction is explicitly disabled",
                ),
            )
        client = build_financial_extraction_client(self.config)
        outcome = FinancialExtractor(
            client=client,
            store=self.store,
            artifacts=self.artifacts,
            now=self.now,
            extractor_version=self.config.extractor_version,
        ).extract(
            target_table=target_table,
            target_id=target_id,
            current_row=current_row,
            current_row_hash=current_row_hash,
            snapshot=snapshot,
            diff=diff,
            client_event_id=client_event_id,
            manual_capture=manual_capture,
        )
        return ExtractionRuntimeOutcome(mode=self.config.mode, outcome=outcome, diff=diff)
