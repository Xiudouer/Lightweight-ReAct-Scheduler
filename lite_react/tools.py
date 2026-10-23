"""Explicit tool registry and bounded, read-only local tools."""

import ast
import codecs
import copy
import json
import math
import operator
import os
import pathlib
import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable


_SCHEMA_KEYS = {"type", "description", "properties", "required", "additionalProperties",
                "items", "enum", "minimum", "maximum", "minLength", "maxLength",
                "minItems", "maxItems"}
_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}


def _check_schema(schema, depth=0):
    if depth > 12 or not isinstance(schema, dict) or schema.get("type") not in _TYPES:
        raise ValueError("Tools require an explicit, supported schema type (depth <= 12)")
    unknown = set(schema) - _SCHEMA_KEYS
    if unknown:
        raise ValueError("Unsupported schema keywords: " + ", ".join(sorted(unknown)))
    if schema["type"] == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if (not isinstance(properties, dict) or not isinstance(required, list)
                or any(not isinstance(key, str) or key not in properties for key in required)):
            raise ValueError("Invalid object properties/required")
        if schema.get("additionalProperties", False) is not False:
            raise ValueError("Tool object schemas must reject extra properties")
        for value in properties.values():
            _check_schema(value, depth + 1)
    if schema["type"] == "array":
        _check_schema(schema.get("items"), depth + 1)


def validate(value, schema, path="arguments", depth=0):
    if depth > 12:
        raise ValueError("Argument nesting exceeds 12 levels")
    typ = schema["type"]
    valid = {"object": isinstance(value, dict), "array": isinstance(value, list),
             "string": isinstance(value, str), "integer": type(value) is int,
             "number": type(value) in (int, float), "boolean": type(value) is bool,
             "null": value is None}[typ]
    if not valid:
        raise ValueError(f"{path} must have type {typ}")
    if typ in ("number", "integer"):
        if not math.isfinite(value):
            raise ValueError(f"{path} must be finite")
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{path} is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"{path} exceeds maximum")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not one of {schema['enum']}")
    if typ == "object":
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - set(value)
        if missing:
            raise ValueError(f"{path} missing required fields: {', '.join(sorted(missing))}")
        if set(value) - set(properties):
            raise ValueError(f"{path} has unknown fields")
        for key, item in value.items():
            validate(item, properties[key], f"{path}.{key}", depth + 1)
    if typ in ("string", "array"):
        low, high = ("minLength", "maxLength") if typ == "string" else ("minItems", "maxItems")
        if len(value) < schema.get(low, 0) or len(value) > schema.get(high, 1000000):
            raise ValueError(f"{path} length out of bounds")
    if typ == "array":
        for index, item in enumerate(value):
            validate(item, schema["items"], f"{path}[{index}]", depth + 1)


class ToolRegistry:
    def __init__(self, tools=()):
        self._tools = {}
        for tool in tools:
            self.add(tool)

    def add(self, tool):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", tool.name):
            raise ValueError("Invalid tool name")
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool: {tool.name}")
        if tool.parameters.get("type") != "object" or not callable(tool.handler):
            raise ValueError("A tool requires an object schema and callable handler")
        _check_schema(tool.parameters)
        # Do not let a caller mutate validation rules after registering a tool.
        self._tools[tool.name] = Tool(tool.name, tool.description, copy.deepcopy(tool.parameters), tool.handler)
        return tool

    def register(self, name, description, parameters):
        def decorator(fn):
            self.add(Tool(name, description, parameters, fn))
            return fn
        return decorator

    def schemas(self):
        return [{"type": "function", "function": dict(name=t.name, description=t.description,
                 parameters=copy.deepcopy(t.parameters))} for t in self._tools.values()]

    def execute(self, name, arguments, max_chars=6000):
        try:
            if name not in self._tools:
                raise ValueError(f"Unknown tool: {name}")
            tool = self._tools[name]
            validate(arguments, tool.parameters)
            result = tool.handler(**arguments)
            text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, allow_nan=False)
            truncated = len(text) > max_chars
            return dict(ok=True, output=text[:max_chars], truncated=truncated, original_chars=len(text))
        except Exception as exc:
            return dict(ok=False, error=f"{type(exc).__name__}: {exc}"[:1200], truncated=False)


def object_schema(properties, required):
    return dict(type="object", properties=properties, required=required, additionalProperties=False)


def _calculate(expression):
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 100:
        raise ValueError("Expression too complex")
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
           ast.Pow: operator.pow}

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = node.value
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in ops:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise ValueError("Exponent must be between -12 and 12")
            value = ops[type(node.op)](left, right)
        else:
            raise ValueError("Only numbers, parentheses and + - * / // % ** are allowed")
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e100:
            raise ValueError("Numeric result is not finite or exceeds 1e100")
        return value

    return dict(value=visit(tree.body))


def builtin_tools(workspace):
    """Read-only bounded file tools. workspace is explicitly supplied by the host."""
    root = pathlib.Path(workspace).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("workspace must be a directory")

    def resolve(path):
        result = (root / path).resolve(strict=True)
        if not result.is_relative_to(root):
            raise ValueError("Path is outside the selected workspace")
        return result

    def files():
        count = 0
        for directory, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not d.startswith('.')
                             and not pathlib.Path(directory, d).is_symlink()
                             and not getattr(os.path, "isjunction", lambda p: False)(os.path.join(directory, d))
                             and pathlib.Path(directory, d).resolve().is_relative_to(root))
            for name in sorted(names):
                candidate = pathlib.Path(directory, name)
                if not candidate.is_symlink() and candidate.resolve().is_relative_to(root):
                    yield candidate
                    count += 1
                    if count >= 500:
                        return

    def read_file(path, start_line=1, max_lines=80):
        target = resolve(path)
        if not target.is_file():
            raise ValueError("Not a regular file")
        with target.open("rb") as handle:
            raw = handle.read(262145)
        text = codecs.getincrementaldecoder("utf-8-sig")().decode(raw[:262144], final=len(raw) <= 262144)
        lines = text.splitlines()
        return dict(path=target.relative_to(root).as_posix(), start_line=start_line,
                    content="\n".join(f"{i + 1}: {line}" for i, line in
                                      enumerate(lines) if start_line - 1 <= i < start_line - 1 + max_lines),
                    truncated=len(raw) > 262144 or start_line - 1 + max_lines < len(lines))

    def list_files():
        found = list(files())
        return dict(files=[p.relative_to(root).as_posix() for p in found],
                    limit_reached=len(found) >= 500, scope="At most 500 files; hidden directories and links excluded")

    def search_files(query):
        matches, scanned, skipped = [], 0, 0
        for target in files():
            scanned += 1
            try:
                with target.open("rb") as handle:
                    raw = handle.read(131073)
                if len(raw) > 131072 or b"\0" in raw:
                    skipped += 1
                    continue
                lines = raw.decode("utf-8-sig").splitlines()
            except (OSError, UnicodeError):
                skipped += 1
                continue
            for number, line in enumerate(lines, 1):
                if query.casefold() in line.casefold():
                    matches.append(dict(path=target.relative_to(root).as_posix(), line=number, text=line[:300]))
                    if len(matches) >= 30:
                        return dict(matches=matches, files_scanned=scanned, files_skipped=skipped, truncated=True)
        return dict(matches=matches, files_scanned=scanned, files_skipped=skipped,
                    truncated=scanned >= 500, scope="UTF-8 files <=128 KiB, first 500 regular files")

    registry = ToolRegistry()
    registry.add(Tool("calculate", "Compute a numeric arithmetic expression; use this for precise calculations.",
                      object_schema({"expression": dict(type="string", minLength=1, maxLength=400)}, ["expression"]), _calculate))
    registry.add(Tool("list_files", "List up to 500 files in the chosen workspace (no arguments).",
                      object_schema({}, []), list_files))
    registry.add(Tool("read_file", "Read a bounded page from one UTF-8 file within the chosen workspace.",
                      object_schema({"path": dict(type="string", minLength=1, maxLength=512),
                                     "start_line": dict(type="integer", minimum=1, maximum=1000000),
                                     "max_lines": dict(type="integer", minimum=1, maximum=200)}, ["path"]), read_file))
    registry.add(Tool("search_files", "Find a literal substring in bounded UTF-8 files in the chosen workspace.",
                      object_schema({"query": dict(type="string", minLength=1, maxLength=200)}, ["query"]), search_files))
    return registry
