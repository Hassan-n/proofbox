# Implementation decisions

- Business-day counting starts on the next business day after the confirmed sent date; a non-business sent date starts at the next business day.
- Reminders are calendar days before a due date and are derived, not stored as separate clocks.
- The confirmed sent date, rather than the generated document date, starts a clock.
- Municipal response and escalation rules remain unverified. `last_verified` is `null`, and the escalation route remains `to be filled from official sources`.
- The calendar includes the planned 2026-2027 South African public-holiday dates, but they must be checked against an official source before rules are represented as verified.
- Case links carry the random token in the URL fragment; API access uses a bearer header, and the database stores only its SHA-256 hash.
- Evidence sequence numbers are allocated while locking the case row and cannot be reassigned; receipt copies are case-owned so deleting a case removes those copies.
- Starting municipal dispute clocks requires the person to confirm the sent date; merely attaching a drafted letter does not start them.
- Reply proposals are stored separately and do not write evidence, clocks, or actions until confirmation. Discarding a proposal clears its raw text and extracted proposal.
- Pack generation uses ReportLab in the API process, keeps immutable versioned PDF/ZIP files under `CASE_STORAGE_DIR`, and rejects mismatched hashes or detected 13-digit identifiers. Configure `CASE_STORAGE_DIR` to durable storage for deployments.

The case API, mobile timeline, clock calculator, reply proposal/confirmation, evidence pack export/preview, receipt protection, expiry cleanup, model prompt privacy gate, and initial Letter Lens flow are implemented. Letter Lens extracts only from the official letter; uploaded PDFs are text-extracted and checklist-checked in the no-network worker sandbox, and explicit response/appointment dates become case clocks only after the user attaches the result. Supporting PDFs are replaced by hash-bearing placeholders in evidence-pack ZIPs to avoid exporting identity numbers. The checklist is layout-specific and does not authenticate documents.

Municipal rules and the grant-review checklist are unverified, deployed end-to-end testing remains outstanding, and text extraction does not support scanned/image-only PDFs. Generate synthetic Letter Lens samples with `python scripts/generate_letter_fixtures.py`; the A10 ID number is fictitious and should not be used as real identity data.
