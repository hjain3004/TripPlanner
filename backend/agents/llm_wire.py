"""JSON Schema for provider-constrained output, and the way back to the Pydantic model.

Anthropic's structured outputs accept a subset of JSON Schema. The model classes the pipeline
already uses (TripSpec, DraftItinerary, CriticVerdict, ExplainerOutput) are richer than that, so
the wire schema is derived from them rather than hand-maintained:

* numeric and length constraints, defaults and other unsupported keywords are dropped (the
  response is still validated against the real Pydantic class client-side);
* every object gets ``additionalProperties: false``;
* a ``dict[str, X]`` field cannot be expressed (open objects are unsupported), so it travels as
  an array of ``{key, value}`` pairs and is folded back into a dict before validation.

Nothing here talks to a provider. ``find_wire_problems`` lets the offline check refuse a schema
the documented limits would reject, instead of discovering it with a paid request.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agents.discovery.contracts import SearchIntent
from core.trip_models import DraftItinerary

# Documented limits of structured outputs (platform.claude.com, structured outputs).
MAX_OPTIONAL_PARAMETERS = 24
MAX_ANYOF = 16

_DROPPED_KEYWORDS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "default",
        "examples",
    }
)
_SUPPORTED_FORMATS = frozenset(
    {"date-time", "time", "date", "duration", "email", "hostname", "uri", "ipv4", "ipv6", "uuid"}
)
_KEY = "key"
_VALUE = "value"


def _transform(node: Any) -> Any:
    if isinstance(node, list):
        return [_transform(item) for item in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for name, value in node.items():
        if name in _DROPPED_KEYWORDS:
            continue
        if name == "minItems" and value not in (0, 1):
            continue
        if name == "format" and value not in _SUPPORTED_FORMATS:
            continue
        if name in ("properties", "$defs", "definitions") and isinstance(value, dict):
            out[name] = {key: _transform(sub) for key, sub in value.items()}
        elif name == "additionalProperties":
            continue  # re-derived below
        else:
            out[name] = _transform(value)
    extra = node.get("additionalProperties")
    if node.get("type") == "object" and "properties" not in node and isinstance(extra, dict):
        # An open map: send it as a list of key/value pairs.
        return {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {_KEY: {"type": "string"}, _VALUE: _transform(extra)},
                "required": [_KEY, _VALUE],
                "additionalProperties": False,
            },
            **({"description": node["description"]} if "description" in node else {}),
        }
    if out.get("type") == "object" or "properties" in out:
        out["additionalProperties"] = False
    return out


class WireItineraryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    poi_id: str
    start_hint: str | None = None
    meal_slots: list[str] = Field(default_factory=list)


class WireItineraryDay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: date
    items: list[WireItineraryItem] = Field(default_factory=list)
    unmet_needs: list[str] = Field(default_factory=list)


class WireDraftItinerary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hotel_area_id: str
    days: list[WireItineraryDay] = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)
    unverified_suggestions: list[str] = Field(default_factory=list)


class PlannerTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["itinerary", "search"]
    itinerary: DraftItinerary | None = None
    search_intent: SearchIntent | None = None

    @model_validator(mode="after")
    def _check_pairing(self) -> Self:
        if self.kind == "itinerary":
            if self.itinerary is None:
                raise ValueError("kind is 'itinerary' but itinerary is None")
            if self.search_intent is not None:
                raise ValueError("kind is 'itinerary' but search_intent is populated")
        elif self.kind == "search":
            if self.search_intent is None:
                raise ValueError("kind is 'search' but search_intent is None")
            if self.itinerary is not None:
                raise ValueError("kind is 'search' but itinerary is populated")
        return self


class WirePlannerTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["itinerary", "search"]
    itinerary: WireDraftItinerary | None = None
    search_intent: SearchIntent | None = None


def to_wire_schema(model: type[BaseModel]) -> dict[str, Any]:
    if issubclass(model, DraftItinerary):
        target_model: type[BaseModel] = WireDraftItinerary
    elif model is PlannerTurn:
        target_model = WirePlannerTurn
    else:
        target_model = model
    return dict(_transform(target_model.model_json_schema()))


def wire_schema_json(model: type[BaseModel]) -> str:
    return json.dumps(to_wire_schema(model), sort_keys=True, separators=(",", ":"))


def _resolve(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        target = defs.get(ref.rsplit("/", 1)[1])
        if isinstance(target, dict):
            return target
    return node


def _fold(data: Any, node: dict[str, Any], defs: dict[str, Any]) -> Any:
    """Undo the pair-list encoding of maps, guided by the model's own schema."""
    node = _resolve(node, defs)
    if data is None:
        return None
    extra = node.get("additionalProperties")
    if node.get("type") == "object" and "properties" not in node and isinstance(extra, dict):
        if not isinstance(data, list):
            return data
        folded: dict[str, Any] = {}
        for pair in data:
            if isinstance(pair, dict) and _KEY in pair and _VALUE in pair:
                folded[str(pair[_KEY])] = _fold(pair[_VALUE], extra, defs)
        return folded
    if isinstance(data, dict) and isinstance(node.get("properties"), dict):
        return {
            key: _fold(value, node["properties"][key], defs) if key in node["properties"] else value
            for key, value in data.items()
        }
    if isinstance(data, list) and isinstance(node.get("items"), dict):
        return [_fold(item, node["items"], defs) for item in data]
    for alternative in node.get("anyOf", []):
        if isinstance(alternative, dict) and _resolve(alternative, defs).get("type") != "null":
            return _fold(data, alternative, defs)
    return data


def from_wire(data: Any, model: type[BaseModel]) -> Any:
    schema = model.model_json_schema()
    return _fold(data, schema, schema.get("$defs", {}))


def find_wire_problems(wire: dict[str, Any]) -> list[str]:
    """Reasons the documented limits would reject this wire schema (empty when it fits)."""
    problems: list[str] = []
    optional = 0
    any_of = 0

    def walk(node: Any, path: str) -> None:
        nonlocal optional, any_of
        if isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")
            return
        if not isinstance(node, dict):
            return
        properties = node.get("properties")
        if isinstance(properties, dict):
            required = set(node.get("required", []))
            optional += len([name for name in properties if name not in required])
            if node.get("additionalProperties") is not False:
                problems.append(f"{path or '$'}: object without additionalProperties=false")
        if isinstance(node.get("anyOf"), list):
            any_of += len(node["anyOf"])
        for name, value in node.items():
            walk(value, f"{path}/{name}")

    walk(wire, "")
    if optional > MAX_OPTIONAL_PARAMETERS:
        problems.append(
            f"{optional} optional parameters exceed the limit of {MAX_OPTIONAL_PARAMETERS}"
        )
    if any_of > MAX_ANYOF:
        problems.append(f"{any_of} anyOf alternatives exceed the limit of {MAX_ANYOF}")
    return problems
