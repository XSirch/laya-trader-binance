from __future__ import annotations

ACTION_KEYS = ("LONG", "SHORT", "FLAT")
EDGE_LEVELS = (
    "negative_or_failed",
    "no_meaningful_edge",
    "moderate_edge",
    "strong_edge",
    "exceptional_edge",
)


def trading_questions() -> dict[str, dict]:
    return {
        "action": {
            "type": "choice",
            "instructions": (
                "Choose the action with the best expected net value after trading costs for the "
                "configured horizon. Prefer FLAT when evidence is insufficient or expected edge "
                "does not compensate risk and costs."
            ),
            "criteria": {
                "LONG": "positive directional edge from entering a long position",
                "SHORT": "positive directional edge from entering a short position",
                "FLAT": "no trade; directional edge is insufficient or ambiguous",
            },
        },
        "tradeable": {
            "type": "noul",
            "instructions": (
                "Is there enough net directional edge in this market state to justify opening a trade?"
            ),
            "criteria": {
                "false": "remain flat because edge is insufficient",
                "true": "a directional trade has enough expected net edge",
            },
        },
        "edge_quality": {
            "type": "score",
            "instructions": "Rate the quality of the best available directional edge after costs.",
            "criteria": list(EDGE_LEVELS),
        },
    }
