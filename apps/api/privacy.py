"""Shared privacy checks for model-bound prompt text."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

ID_NUMBER_PATTERN = re.compile(r"\d{13}")


class PrivacyBlockedError(ValueError):
    """Raised when an outbound model prompt contains a 13-digit identifier."""


def ensure_no_id_number(
    prompt_parts: Iterable[str],
    job_id: str | None,
    emit: Callable[[str, str, str], None] | None = None,
) -> None:
    if not any(ID_NUMBER_PATTERN.search(part) for part in prompt_parts):
        return
    if job_id:
        if emit is None:
            from db import add_event

            emit = add_event
        emit(job_id, "pii_blocked", "Blocked a model prompt containing a 13-digit identifier")
    raise PrivacyBlockedError("Model call blocked by the privacy guard.")
