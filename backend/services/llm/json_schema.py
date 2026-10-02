"""JSON Schema in the plain dialect the non-Anthropic tool APIs document.

Gemini's tool parameters are "a select subset" of JSON Schema and it "may
reject very large or deeply nested schemas"; Nova's docs list no `$ref` or
`anyOf` at all. `inline_schema` rewrites a Pydantic / strict schema into the
lowest common form: every `$ref` inlined (no `$defs`), `anyOf [X, null]`
folded into a type list, and the given keys dropped. Whatever the model then
sends back is still validated against the original Pydantic model, so this
only changes how the shape is described, never what is accepted."""

from __future__ import annotations

from typing import Any


def inline_schema(schema: dict, *, drop: tuple[str, ...] = ("title", "default")) -> dict:
    schema = dict(schema)
    defs = schema.pop("$defs", {})

    def clean(node: Any) -> Any:
        if isinstance(node, list):
            return [clean(n) for n in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return clean(defs[node["$ref"].split("/")[-1]])
        options = node.get("anyOf")
        if options and len(options) == 2 and {"type": "null"} in options:
            other = clean(next(o for o in options if o != {"type": "null"}))
            if isinstance(other.get("type"), str):
                folded = {**other, "type": [other["type"], "null"]}
                if "enum" in folded:
                    folded["enum"] = [*folded["enum"], None]
                rest = {k: clean(v) for k, v in node.items() if k != "anyOf" and k not in drop}
                return {**folded, **rest}
        return {k: clean(v) for k, v in node.items() if k not in drop}

    return clean(schema)


NOVA_DROP = ("title", "default", "additionalProperties")


def nova_schema(schema: dict) -> dict:
    """Nova's tool docs show only type/properties/required on objects;
    unknown arguments are rejected by our own validation instead."""
    return inline_schema(schema, drop=NOVA_DROP)
