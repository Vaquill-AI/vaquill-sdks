"""README snippets only name methods that exist."""

from __future__ import annotations

import re
from pathlib import Path

import vaquill
from vaquill import AsyncVaquill, Vaquill

README = (Path(__file__).resolve().parent.parent / "README.md").read_text()


def test_every_client_method_in_the_readme_exists() -> None:
    client = Vaquill(api_key="vq_key_readme_0123456789")  # pragma: allowlist secret
    aclient = AsyncVaquill(api_key="vq_key_readme_0123456789")  # pragma: allowlist secret
    calls = set(re.findall(r"client\.(\w+)\.(\w+)\(", README))
    assert ("statutes", "resolve") in calls and ("credits", "balance") in calls
    for namespace, method in calls:
        assert hasattr(getattr(client, namespace), method), (namespace, method)
        assert hasattr(getattr(aclient, namespace), method), (namespace, method)


def test_every_exception_in_the_readme_is_exported() -> None:
    for name in set(re.findall(r"vaquill\.(\w+Error)\b", README)):
        assert hasattr(vaquill, name), name
