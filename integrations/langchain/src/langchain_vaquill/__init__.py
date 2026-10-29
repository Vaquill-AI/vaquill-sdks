"""LangChain integration for the Vaquill US primary law Data API."""

from ._client import ClientProvider, integration_user_agent
from ._version import __version__
from .retriever import VaquillRetriever
from .toolkit import VaquillToolkit
from .tools import READ_ONLY_TOOLS, WATCH_WRITE_TOOLS, VaquillTool

__all__ = [
    "READ_ONLY_TOOLS",
    "WATCH_WRITE_TOOLS",
    "ClientProvider",
    "VaquillRetriever",
    "VaquillTool",
    "VaquillToolkit",
    "__version__",
    "integration_user_agent",
]
