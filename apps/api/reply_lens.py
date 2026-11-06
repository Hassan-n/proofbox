"""Reply text screening, extraction schema, and deterministic clock proposals."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?previous\s+instructions\b", re.IGNORECASE),
    re.compile(r"\b(?:system|developer)\s+prompt\b", re.IGNORECASE),
    re.compile(r"\bmark\s+(?:this\s+)?case\s+(?:as\s+)?resolved\b", re.IGNORECASE),
    re.compile(r"\b(?:reveal|print|expose)\s+(?:the\s+)?(?:secret|api key|system prompt)\b", re.IGNORECASE),
    re.compile(r"\bdisregard\s+(?:all\s+)?(?:rules|instructions)\b", re.IGNORECASE),
)

UNREADABLE = "unreadable"
REPLY_TYPES = (
    "acknowledgement",
    "substantive_answer",
    "request_for_information",
    "refusal",
    "other",
    UNREADABLE,
)


class ReplyExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender: str = Field(default=UNREADABLE, max_length=200)
    date_received: str = Field(default=UNREADABLE, max_length=40)
    reply_type: str = Field(default=UNREADABLE, max_length=40)
    reference_number: str = Field(default=UNREADABLE, max_length=200)
    documents_requested: list[str] = Field(default_factory=list, max_length=20)
    new_deadline: str = Field(default=UNREADABLE, max_length=40)
    summary: str = Field(default=UNREADABLE, max_length=1000)


def scan_instructions(text: str) -> list[str]:
    return [pattern.pattern for pattern in INJECTION_PATTERNS if pattern.search(text)]


def normalize_extraction(value: dict[str, Any]) -> dict[str, Any]:
    result = ReplyExtraction.model_validate(value).model_dump()
    if result["reply_type"] not in REPLY_TYPES:
        result["reply_type"] = UNREADABLE
    for field in ("sender", "date_received", "reference_number", "new_deadline", "summary"):
        text = result[field].strip()
        result[field] = text if text else UNREADABLE
    if result["date_received"] != UNREADABLE:
        try:
            result["date_received"] = date.fromisoformat(result["date_received"]).isoformat()
        except ValueError:
            result["date_received"] = UNREADABLE
    if result["new_deadline"] != UNREADABLE:
        try:
            result["new_deadline"] = date.fromisoformat(result["new_deadline"]).isoformat()
        except ValueError:
            result["new_deadline"] = UNREADABLE
    result["documents_requested"] = [
        item.strip() for item in result["documents_requested"] if item.strip()
    ]
    summary = result["summary"]
    if summary != UNREADABLE:
        sentences = re.split(r"(?<=[.!?])\s+", summary)
        result["summary"] = " ".join(sentences[:3])
    return result


def propose_reply_effect(
    extracted: dict[str, Any],
    open_clocks: list[dict[str, Any]],
) -> dict[str, Any]:
    reply_type = extracted["reply_type"]
    effects: list[dict[str, Any]] = []
    selected_clock = None
    response_clocks = [
        clock
        for clock in open_clocks
        if not clock.get("met_at") and clock.get("state") != "met"
        if "response" in clock["name"].lower() or "reply" in clock["name"].lower()
    ]

    if reply_type == "substantive_answer" and response_clocks:
        selected_clock = response_clocks[0]
        effects.append(
            {
                "type": "mark_clock_met",
                "clock_id": selected_clock["id"],
                "clock_name": selected_clock["name"],
                "text": f"Mark '{selected_clock['name']}' as met",
            }
        )
    elif reply_type == "acknowledgement":
        effects.append({"type": "leave_clocks_open", "text": "Leave all clocks open"})

    if extracted["new_deadline"] != UNREADABLE:
        effects.append(
            {
                "type": "add_clock",
                "due_at": extracted["new_deadline"],
                "text": f"Add a new follow-up clock due {extracted['new_deadline']}",
            }
        )

    return {
        "reply_type": reply_type,
        "date_received": extracted["date_received"],
        "reference_number": extracted["reference_number"],
        "new_deadline": extracted["new_deadline"],
        "clock_choice": selected_clock["id"] if selected_clock else None,
        "effects": effects,
        "proposed_changes": [effect["text"] for effect in effects],
    }


def parse_confirmed_date(value: str) -> date:
    if value == UNREADABLE:
        raise ValueError("A readable reply date is required before confirmation.")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Reply date must use YYYY-MM-DD.") from error
