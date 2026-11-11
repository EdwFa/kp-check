"""JSON round-trip for tool I/O. Does not change in-memory dataclasses."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from kp_tz_check.dates import parse_date_string


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return to_jsonable(value.value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: to_jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    return str(value)


def from_jsonable(cls: type, data: Any) -> Any:
    if data is None:
        return None
    if cls is Any:
        return data
    origin = get_origin(cls)
    if origin is Union or origin is UnionType:
        args = [arg for arg in get_args(cls) if arg is not type(None)]
        if not args:
            return None
        if len(args) == 1:
            return from_jsonable(args[0], data)
        for arg in args:
            try:
                return from_jsonable(arg, data)
            except (TypeError, ValueError):
                continue
        raise ValueError(f"Cannot decode {data!r} as {cls}")
    if origin in (list, tuple):
        (inner,) = get_args(cls) or (Any,)
        return [from_jsonable(inner, item) for item in data]
    if origin is dict:
        args = get_args(cls) or (str, Any)
        key_type, val_type = args[0], args[1] if len(args) > 1 else Any
        return {from_jsonable(key_type, key): from_jsonable(val_type, item) for key, item in data.items()}
    if isinstance(cls, type) and issubclass(cls, Path):
        return Path(str(data))
    if isinstance(cls, type) and issubclass(cls, date) and cls is date:
        return _parse_date(data)
    if isinstance(cls, type) and issubclass(cls, Enum):
        return cls(data)
    if isinstance(cls, type) and is_dataclass(cls):
        if not isinstance(data, dict):
            raise TypeError(f"Expected object for {cls.__name__}, got {type(data).__name__}")
        hints = get_type_hints(cls)
        payload = {}
        for item in fields(cls):
            if item.name not in data:
                continue
            payload[item.name] = from_jsonable(hints.get(item.name, Any), data[item.name])
        return cls(**payload)
    if cls is str:
        return str(data)
    if cls is int:
        return int(data)
    if cls is float:
        return float(data)
    if cls is bool:
        return bool(data)
    return data


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        parsed = parse_date_string(text)
        if parsed is None:
            raise ValueError(f"Cannot parse date: {value!r}") from None
        return parsed
