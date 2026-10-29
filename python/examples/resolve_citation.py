"""Resolve a citation to its section, then read the section text.

VAQUILL_API_KEY=vq_key_... python examples/resolve_citation.py
"""

from __future__ import annotations

from vaquill import InsufficientCreditsError, Vaquill
from vaquill.types import StatuteResolveResponse


def main(client: Vaquill, cite: str = "42 U.S.C. 1983") -> StatuteResolveResponse | None:
    try:
        result = client.statutes.resolve(cite)  # 2 credits, even when it does not resolve
    except InsufficientCreditsError:
        print("Out of credits. Top up in the developer dashboard.")
        return None
    print(f"{cite}: resolved={result.resolved} charged={result.credits_consumed} credits")
    if result.resolved and result.section is not None and result.section.act_id:
        body = client.statutes.get_section_body(result.section.act_id)  # 6 credits
        print((body.plain or body.content or "")[:200])
    return result


if __name__ == "__main__":
    main(Vaquill(max_credits=20))
