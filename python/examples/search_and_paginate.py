"""Search, then page through results with a cost guard.

Every page of a charged endpoint spends credits, so always bound the iteration.

    VAQUILL_API_KEY=vq_key_... python examples/search_and_paginate.py
"""

from __future__ import annotations

from vaquill import Vaquill
from vaquill.types import StatuteResult


def main(client: Vaquill) -> list[StatuteResult]:
    first = client.statutes.search("statute of limitations for medical malpractice", state="ca")
    rows_on_page = len(first.results or [])
    print(f"{rows_on_page} rows on page one, cost {first.credits_consumed} credits")

    # 2 pages x 4 credits at most. `truncated` tells you more existed.
    pager = client.statutes.iter_search(
        "statute of limitations for medical malpractice", state="ca", limit=10, max_pages=2
    )
    rows = list(pager)
    print(f"read {len(rows)} rows, truncated={pager.truncated}, spent={client.credits_spent}")
    return rows


if __name__ == "__main__":
    main(Vaquill(max_credits=50))
