from types import SimpleNamespace

import pytest

from privacy import PrivacyBlockedError, ensure_no_id_number
from lenses.bill.model_caller import make_caller


def test_privacy_guard_blocks_thirteen_digits_and_emits_only_safe_detail():
    events = []
    with pytest.raises(PrivacyBlockedError):
        ensure_no_id_number(
            ["person number 8101011234567"],
            "job-1",
            lambda *event: events.append(event),
        )
    assert events == [
        ("job-1", "pii_blocked", "Blocked a model prompt containing a 13-digit identifier")
    ]


def test_privacy_guard_allows_shorter_values():
    ensure_no_id_number(["reference 810101123456"], None)


def test_bill_model_caller_does_not_send_blocked_prompt():
    calls = []
    emitted = []
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: calls.append(kwargs))
        )
    )
    caller = make_caller(
        client,
        {"extractor": "model"},
        {},
        lambda *args: None,
        emit=lambda *event: emitted.append(event),
    )

    with pytest.raises(PrivacyBlockedError):
        caller("extractor", "job-2", "Extract fields", "number 8101011234567")

    assert calls == []
    assert emitted[0][1] == "pii_blocked"


def test_shared_model_gateway_does_not_send_blocked_prompt(monkeypatch):
    import gateway

    calls = []
    events = []
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: calls.append(kwargs))
        )
    )
    monkeypatch.setattr(gateway, "client", client)
    monkeypatch.setattr(gateway, "add_event", lambda *event: events.append(event))

    with pytest.raises(PrivacyBlockedError):
        gateway.call_model(
            "extractor", "job-3", "Extract fields", "number 8101011234567"
        )

    assert calls == []
    assert events[0][1] == "pii_blocked"
