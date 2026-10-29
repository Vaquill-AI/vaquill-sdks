"""Resource namespaces attached to the clients (``client.statutes`` and friends)."""

from ._async.boards import AsyncBoards
from ._async.credits import AsyncCredits
from ._async.pricing import AsyncPricing
from ._async.session_laws import AsyncSessionLaws
from ._async.statutes import AsyncStatutes
from ._async.watches import AsyncWatches
from .boards import SyncBoards
from .credits import SyncCredits
from .pricing import SyncPricing
from .session_laws import SyncSessionLaws
from .statutes import SyncStatutes
from .watches import SyncWatches

__all__ = [
    "AsyncBoards",
    "AsyncCredits",
    "AsyncPricing",
    "AsyncSessionLaws",
    "AsyncStatutes",
    "AsyncWatches",
    "SyncBoards",
    "SyncCredits",
    "SyncPricing",
    "SyncSessionLaws",
    "SyncStatutes",
    "SyncWatches",
]
