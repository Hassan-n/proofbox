import hashlib
from contextlib import nullcontext
from datetime import date

import pytest
from fastapi import HTTPException, Response

import casefile
from casefile import (
    AttachEvidenceRequest,
    ConfirmReplyRequest,
    CreateCaseRequest,
    _bearer_token,
    _case_for_token,
    _rule_config,
)


def test_missing_case_token_is_not_found():
    with pytest.raises(HTTPException) as error:
        _bearer_token(None)
    assert error.value.status_code == 404


def test_bearer_token_is_parsed_without_changing_value():
    assert _bearer_token("Bearer long-random-token") == "long-random-token"


def test_rule_set_path_traversal_is_rejected():
    with pytest.raises(HTTPException) as error:
        _rule_config("../secrets")
    assert error.value.status_code == 422


def test_municipal_rules_are_explicitly_unverified():
    assert _rule_config("municipal_billing")["last_verified"] is None


def test_case_token_comparison_returns_same_not_found_for_mismatch():
    token = "valid-token"
    case = {"id": "case-1", "access_token_hash": hashlib.sha256(token.encode()).hexdigest()}

    class Connection:
        def execute(self, *_):
            return self

        def fetchone(self):
            return case

    assert _case_for_token(Connection(), "case-1", f"Bearer {token}") is case
    with pytest.raises(HTTPException) as error:
        _case_for_token(Connection(), "case-1", "Bearer wrong-token")
    assert error.value.status_code == 404


def test_create_case_stores_only_token_hash(monkeypatch):
    class Connection:
        statement = ""
        parameters = ()

        def execute(self, statement, parameters):
            self.statement = statement
            self.parameters = parameters

    connection = Connection()

    class Pool:
        def connection(self):
            return nullcontext(connection)

    monkeypatch.setattr(casefile, "_db_pool", lambda: Pool())
    http_response = Response()
    result = casefile.create_case(CreateCaseRequest(title="Water account"), http_response)
    assert result["expires_in_days"] == 7
    assert result["access_link"].endswith(
        f"#{result['case_id']}.{result['access_token']}"
    )
    assert "access_token_hash" in connection.statement
    assert "access_token," not in connection.statement
    assert connection.parameters[1] == hashlib.sha256(result["access_token"].encode()).hexdigest()
    assert http_response.headers["Cache-Control"] == "no-store"


def test_attaching_letter_creates_only_explicit_deadline_and_appointment_clocks(monkeypatch):
    token = "case-token"
    evidence = []
    clocks = []

    class Cursor:
        def __init__(self, row=None, rows=None):
            self.row, self.rows = row, rows or []

        def fetchone(self):
            return self.row

        def fetchall(self):
            return self.rows

    class Connection:
        def transaction(self):
            return nullcontext()

        def execute(self, statement, parameters=()):
            if "FROM cases WHERE id = %s AND expires_at > NOW()" in statement:
                return Cursor({
                    "id": "case-1",
                    "access_token_hash": hashlib.sha256(token.encode()).hexdigest(),
                    "rule_set": "grant_review",
                    "title": "Letter case",
                })
            if "FROM jobs" in statement and "status = 'completed'" in statement:
                return Cursor({
                    "id": "job-letter",
                    "lens": "letter",
                    "status": "completed",
                    "result_json": {
                        "summary": "Letter check complete.",
                        "derived_facts": {
                            "response_deadline": "2026-11-20",
                            "appointment_date": "2026-11-27",
                            "clocks": [
                                {"name": "Forged clock", "due_at": "2099-01-01", "rule_ref": "untrusted"},
                            ],
                        },
                    },
                })
            if "SELECT 1 FROM evidence_items" in statement:
                return Cursor()
            if "SELECT id FROM cases WHERE id = %s FOR UPDATE" in statement:
                return Cursor()
            if "COALESCE(MAX(seq), 0)" in statement:
                return Cursor({"max_seq": 0})
            if "INSERT INTO evidence_items" in statement:
                evidence.append(parameters)
                return Cursor()
            if "INSERT INTO clocks" in statement:
                clocks.append(parameters)
                return Cursor()
            if "FROM receipts" in statement:
                return Cursor(rows=[])
            return Cursor()

    connection = Connection()

    class Pool:
        def connection(self):
            return nullcontext(connection)

    monkeypatch.setattr(casefile, "_db_pool", lambda: Pool())
    response = Response()
    result = casefile.attach_evidence(
        "case-1",
        AttachEvidenceRequest(job_id="job-letter"),
        response,
        authorization=f"Bearer {token}",
    )

    assert result["kind"] == "letter"
    assert len(evidence) == 1
    assert [(clock[2], clock[3], clock[4]) for clock in clocks] == [
        ("Response deadline", date(2026, 11, 20), "grant_review.response_deadline"),
        ("Appointment", date(2026, 11, 27), "grant_review.appointment"),
    ]


def test_confirming_reply_uses_stored_proposal_clock_choice(monkeypatch):
    token = "case-token"
    met_updates = []
    evidence = []
    reply_updates = []

    class Cursor:
        def __init__(self, row=None, rows=None):
            self.row, self.rows = row, rows or []

        def fetchone(self):
            return self.row

        def fetchall(self):
            return self.rows

    response_clock = {"id": "clock-1", "name": "Response due", "due_at": date(2026, 1, 20)}
    # Shaped like the real SELECT row: the proposal lives in `proposal_json`.
    reply_row = {
        "id": "reply-1",
        "status": "proposed",
        "raw_text": "Synthetic substantive answer.",
        "extraction_json": {
            "sender": "Karoo Bay Metro",
            "date_received": "2026-01-15",
            "reply_type": "substantive_answer",
            "reference_number": "KBM-1",
            "documents_requested": [],
            "new_deadline": "unreadable",
            "summary": "The account was corrected.",
        },
        "proposal_json": {"clock_choice": "clock-1", "effects": []},
        "confirmation_json": None,
        "evidence_id": None,
    }

    class Connection:
        def transaction(self):
            return nullcontext()

        def execute(self, statement, parameters=()):
            if "FROM cases WHERE id = %s AND expires_at > NOW()" in statement:
                return Cursor({
                    "id": "case-1",
                    "access_token_hash": hashlib.sha256(token.encode()).hexdigest(),
                    "rule_set": "municipal_billing",
                    "title": "Water account",
                })
            if "FROM replies WHERE id = %s" in statement:
                return Cursor(reply_row)
            if "FROM clocks" in statement and "state <> 'met'" in statement:
                return Cursor(rows=[response_clock])
            if "FROM clocks" in statement and "WHERE id = %s" in statement:
                return Cursor(response_clock)
            if statement.lstrip().startswith("UPDATE clocks SET state = 'met'"):
                met_updates.append(parameters)
            elif "COALESCE(MAX(seq), 0)" in statement:
                return Cursor({"max_seq": 2})
            elif "INSERT INTO evidence_items" in statement:
                evidence.append(parameters)
            elif statement.lstrip().startswith("UPDATE replies"):
                reply_updates.append(statement)
            return Cursor()

    connection = Connection()

    class Pool:
        def connection(self):
            return nullcontext(connection)

    monkeypatch.setattr(casefile, "_db_pool", lambda: Pool())
    result = casefile.confirm_reply(
        "case-1",
        "reply-1",
        ConfirmReplyRequest(),
        Response(),
        authorization=f"Bearer {token}",
    )

    assert result["status"] == "confirmed"
    assert result["seq"] == 3
    assert len(met_updates) == 1
    assert met_updates[0][1] is False
    assert met_updates[0][2] == "clock-1"
    assert len(evidence) == 1
    assert len(reply_updates) == 1 and "raw_text = ''" in reply_updates[0]
