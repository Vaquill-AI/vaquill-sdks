"""Shared pieces of the ``vaquill`` command: exit codes, session, results, flag helpers."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from .. import Vaquill
from .._config import API_KEY_ENV, API_KEY_PREFIX
from ._render import UI

OK, GENERIC, USAGE, AUTH, CREDITS, RATE_LIMITED, NOT_FOUND, NETWORK = range(8)
KEY_PATTERN = re.compile(r"vq_key_[A-Za-z0-9_\-]+")

ClientFactory = Callable[..., Vaquill]


class CLIError(Exception):
    def __init__(self, message: str, code: int = GENERIC, payload: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.payload = payload


@dataclass
class Result:
    payload: Any
    human: Callable[[UI], str]
    charged: bool = False
    notice: str | None = None


def redact(text: str, key: str | None = None) -> str:
    text = KEY_PATTERN.sub("vq_key_[redacted]", text)
    return text.replace(key, "[redacted]") if key else text


def as_dict(value: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return cast("list[Any]", value) if isinstance(value, list) else []


def dump(model: Any) -> Any:
    return model.model_dump(mode="json", by_alias=True)


def more(payload: Any) -> bool:
    return any(as_dict(d).get("hasMore") is True for d in (payload, as_dict(payload).get("data")))


def more_notice(what: str, hint: str) -> str:
    return f"notice: more {what} exist; this command fetched one page. {hint}"


def json_text(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


class Session:
    """Holds the parsed options and builds the client on first use."""

    def __init__(self, args: argparse.Namespace, factory: ClientFactory) -> None:
        self.args = args
        self._factory = factory
        self._client: Vaquill | None = None

    @property
    def key(self) -> str | None:
        return self.args.api_key or os.environ.get(API_KEY_ENV) or None

    @property
    def client(self) -> Vaquill:
        if self._client is None:
            key = self.key
            if not key:
                raise CLIError(f"No API key. Set {API_KEY_ENV} or pass --api-key.", AUTH)
            if not key.startswith(API_KEY_PREFIX):
                raise CLIError(
                    f"Invalid API key: Vaquill keys start with '{API_KEY_PREFIX}'.", AUTH
                )
            self._client = self._factory(
                api_key=key,
                base_url=self.args.base_url,
                timeout=self.args.timeout,
                max_retries=self.args.max_retries,
                max_credits=self.args.max_credits,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


Handler = Callable[[Session], Result]


# ---- flags ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Flag:
    """One option, declared as data. ``kind``: s str, l repeatable str, i int, b on/off."""

    dest: str
    kind: str = "s"
    help: str = ""
    choices: tuple[str, ...] | None = None

    @property
    def option(self) -> str:
        return "--" + self.dest.replace("_", "-")


def declare(parser: argparse.ArgumentParser, flags: Iterable[Flag]) -> None:
    for f in flags:
        if f.kind == "b":
            parser.add_argument(
                f.option,
                dest=f.dest,
                action=argparse.BooleanOptionalAction,
                default=None,
                help=f.help,
            )
        elif f.kind == "l":
            parser.add_argument(
                f.option,
                dest=f.dest,
                action="append",
                metavar=f.dest.upper(),
                help=(f.help + " Repeatable.").strip(),
            )
        elif f.kind == "i":
            parser.add_argument(f.option, dest=f.dest, type=int, help=f.help)
        else:
            parser.add_argument(f.option, dest=f.dest, choices=f.choices, help=f.help)


def kw(args: argparse.Namespace, names: Iterable[str]) -> dict[str, Any]:
    """The named options that were given, as keyword arguments for an SDK method."""
    out: dict[str, Any] = {}
    for name in names:
        value = getattr(args, name, None)
        if value is not None:
            out[name] = value
    return out


def names(flags: Iterable[Flag]) -> list[str]:
    return [f.dest for f in flags]


def split_csv(values: Sequence[str] | None) -> list[str] | None:
    if values is None:
        return None
    return [part.strip() for v in values for part in v.split(",") if part.strip()]


def add_paging(parser: argparse.ArgumentParser, what: str) -> None:
    g = parser.add_argument_group("paging")
    g.add_argument("--all", action="store_true", help=f"Fetch every page of {what}.")
    g.add_argument("--max-pages", type=int, metavar="N", help="Stop after N pages (implies --all).")
    g.add_argument("--max-items", type=int, metavar="N", help="Stop after N items (implies --all).")


def wants_all(args: argparse.Namespace) -> bool:
    return bool(args.all) or args.max_pages is not None or args.max_items is not None


def paging_kw(args: argparse.Namespace) -> dict[str, Any]:
    return {"max_pages": args.max_pages, "max_items": args.max_items}


def forbid(args: argparse.Namespace, *dests: str) -> None:
    """Reject options that make no sense together with --all."""
    for dest in dests:
        if getattr(args, dest, None) is not None:
            flag = "--" + dest.replace("_", "-")
            raise CLIError(f"{flag} cannot be combined with --all.", USAGE)


def read_lines(path: str | None) -> list[str]:
    """Non-empty lines of a file, or of stdin for ``-``."""
    if path == "-":
        raw = sys.stdin.read()
    else:
        assert path is not None
        try:
            with open(path, encoding="utf-8") as handle:
                raw = handle.read()
        except OSError as exc:
            raise CLIError(f"Cannot read {path}: {exc.strerror}", USAGE) from exc
    return [line.strip() for line in raw.splitlines() if line.strip()]


def read_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        raise CLIError(f"Cannot read {path}: {exc.strerror}", USAGE) from exc


# ---- generic output -------------------------------------------------------------------

_SCALAR = (str, int, float, bool, type(None))


def _scalars(row: dict[str, Any]) -> list[tuple[str, Any]]:
    return [(k, v) for k, v in row.items() if isinstance(v, _SCALAR)]


def _first_table(data: dict[str, Any], list_key: str | None) -> list[Any]:
    for scope in (data, as_dict(data.get("data"))):
        if list_key and isinstance(scope.get(list_key), list):
            return as_list(scope[list_key])
    for scope in (data, as_dict(data.get("data"))):
        for value in scope.values():
            rows = as_list(value)
            if rows and all(isinstance(r, dict) for r in rows):
                return rows
    return []


def generic_human(
    data: Any, ui: UI, *, list_key: str | None = None, cols: Sequence[str] | None = None
) -> str:
    """Scalar fields as key/value lines, then the main list as a table."""
    body = as_dict(data)
    if not body:
        return json_text(data)
    envelope = as_dict(body.get("data")) or body
    head = ui.kv(_scalars(envelope))
    rows = _first_table(body, list_key)
    if not rows:
        return head or json_text(data)
    dicts = [as_dict(r) for r in rows]
    columns = list(cols) if cols else [k for k, _ in _scalars(dicts[0])][:5]
    if not columns:
        return head or json_text(data)
    table = ui.table(columns, [[r.get(c) for c in columns] for r in dicts])
    return (head + "\n\n" if head else "") + table


def paging_notice(
    data: Any, what: str, *, offset: bool = False, cursor: bool = False, all_flag: bool = True
) -> str | None:
    if (
        not more(data)
        and not as_dict(data).get("nextCursor")
        and not as_dict(as_dict(data).get("data")).get("nextCursor")
    ):
        return None
    body = as_dict(data)
    scope = body if "hasMore" in body or "nextCursor" in body else as_dict(body.get("data"))
    hints: list[str] = []
    if cursor and scope.get("nextCursor"):
        hints.append(f"Continue with --cursor {scope['nextCursor']}.")
    if offset and scope.get("nextOffset") is not None:
        hints.append(f"Continue with --offset {scope['nextOffset']}.")
    if all_flag:
        hints.append("Use --all to fetch every page (each page may be charged).")
    return more_notice(what, " ".join(hints))
