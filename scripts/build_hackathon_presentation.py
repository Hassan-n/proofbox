"""Build the detailed, screenshot-free Proofbox system presentation.

Content is anchored to implementation and operational notes. Diagrams describe
system boundaries; they are not substitutes for live deployment test evidence.
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "Proofbox_Hackathon_Presentation.pdf"
WIDTH, HEIGHT, TOTAL = 1280, 720, 24
PAPER = (247, 245, 240)
WHITE = (255, 255, 255)
INK = (20, 32, 43)
MUTED = (78, 94, 108)
LINE = (216, 222, 218)
TEAL = (15, 107, 100)
MINT = (97, 222, 196)
BLUE = (72, 166, 230)
AMBER = (244, 188, 91)
DARK = (11, 22, 32)
PANEL = (20, 37, 49)
SOFT = (173, 194, 207)


class Deck(FPDF):
    def __init__(self) -> None:
        super().__init__(unit="pt", format=(HEIGHT, WIDTH), orientation="L")
        self.set_auto_page_break(False)
        self.set_margins(0, 0, 0)
        fonts = Path(r"C:\Windows\Fonts")
        self.add_font("Pitch", "", str(fonts / "calibri.ttf"))
        self.add_font("Pitch", "B", str(fonts / "calibrib.ttf"))
        self.set_title("Proofbox | Detailed System Presentation")
        self.set_author("Proofbox")
        self.set_subject("Vultr Agent Rush | Containment-first agents and evidence-backed workflows")
        self.dark = False

    def box(self, x: float, y: float, w: float, h: float, color: tuple) -> None:
        self.set_fill_color(*color)
        self.rect(x, y, w, h, style="F", round_corners=True, corner_radius=10)

    def text(self, x: float, y: float, w: float, value: str, size: float = 21,
             bold: bool = False, color: tuple | None = None,
             bottom: float = 656, leading: float | None = None) -> float:
        self.set_font("Pitch", "B" if bold else "", size)
        self.set_text_color(*(color or (WHITE if self.dark else INK)))
        self.set_xy(x, y)
        self.multi_cell(w, leading or size * 1.22, value, padding=0, align="L")
        end = self.get_y()
        if end > bottom:
            raise ValueError(f"Slide {self.page_no()}: text overflow: {value!r}")
        return end

    def label(self, x: float, y: float, value: str, w: float = 1152,
              color: tuple | None = None) -> None:
        self.text(x, y, w, value.upper(), 13, True, color or (MINT if self.dark else TEAL))

    def slide(self, section: str, title: str, subtitle: str, dark: bool = False) -> None:
        self.add_page()
        self.dark = dark
        self.set_fill_color(*(DARK if dark else PAPER))
        self.rect(0, 0, WIDTH, HEIGHT, style="F")
        self.start_section(title)
        self.label(64, 34, f"PROOFBOX / {section}", 820)
        self.text(963, 34, 253, "VULTR AGENT RUSH / 2026", 13, color=SOFT if dark else MUTED)
        self.text(64, 89, 1152, title, 40, True, bottom=144)
        self.text(64, 151, 1152, subtitle, 20, color=SOFT if dark else MUTED, bottom=211)
        self.set_draw_color(*(PANEL if dark else LINE))
        self.line(64, 678, 1216, 678)
        self.text(64, 692, 960, "SYSTEM PRESENTATION / PROTOTYPE / NOT LEGAL OR ELIGIBILITY ADVICE", 10,
                  color=SOFT if dark else MUTED, bottom=718)
        self.text(1143, 687, 73, f"{self.page_no():02d} / {TOTAL}", 14,
                  color=SOFT if dark else MUTED, bottom=718)

    def note(self, value: str) -> None:
        self.box(64, 603, 1152, 54, PANEL if self.dark else (226, 239, 234))
        self.text(84, 616, 1112, value, 19, True, MINT if self.dark else TEAL, bottom=653)

    def columns(self, left: tuple[str, list[tuple[str, str]]],
                right: tuple[str, list[tuple[str, str]]]) -> None:
        for x, (tag, blocks) in zip((64, 656), (left, right)):
            self.box(x, 230, 560, 363, PANEL if self.dark else WHITE)
            self.label(x + 24, 250, tag, 512)
            y = 280.0
            for heading, body in blocks:
                y = self.text(x + 24, y, 512, heading, 22, True, bottom=580) + 5
                y = self.text(x + 24, y, 512, body, 19, color=SOFT if self.dark else MUTED,
                              bottom=580) + 12

    def table(self, headers: list[str], rows: list[list[str]],
              widths: list[int], row_height: int = 64, size: int = 19) -> None:
        self.box(64, 230, 1152, 46 + len(rows) * row_height, PANEL if self.dark else WHITE)
        x = 80
        for header, width in zip(headers, widths):
            self.label(x, 244, header, width - 24)
            x += width
        for i, row in enumerate(rows):
            y = 281 + i * row_height
            x = 80
            for j, (value, width) in enumerate(zip(row, widths)):
                self.text(x, y, width - 24, value, size, j == 0,
                          color=None if j == 0 else (SOFT if self.dark else MUTED),
                          bottom=y + row_height - 9)
                x += width
            if i < len(rows) - 1:
                self.set_draw_color(*(DARK if self.dark else LINE))
                self.line(80, y + row_height - 15, 1198, y + row_height - 15)

    def node(self, x: float, y: float, w: float, h: float,
             label: str, body: str, accent: tuple = MINT) -> None:
        self.box(x, y, w, h, PANEL if self.dark else WHITE)
        self.label(x + 20, y + 20, label, w - 40, accent if self.dark else TEAL)
        if body:
            self.text(x + 20, y + 55, w - 40, body, 22, bottom=y + h - 16)

    def arrow(self, x1: float, y1: float, x2: float, y2: float,
              color: tuple = MINT) -> None:
        self.set_draw_color(*color)
        self.set_line_width(2)
        self.line(x1, y1, x2, y2)
        self.set_fill_color(*color)
        if x1 == x2:
            d = 1 if y2 > y1 else -1
            self.polygon([(x2, y2), (x2 - 5, y2 - 9 * d), (x2 + 5, y2 - 9 * d)], style="F")
        else:
            d = 1 if x2 > x1 else -1
            self.polygon([(x2, y2), (x2 - 9 * d, y2 - 5), (x2 - 9 * d, y2 + 5)], style="F")


def build() -> Path:
    p = Deck()

    p.slide("01 / Executive overview", "Proofbox", "Containment-first agent execution. Evidence-backed action.", True)
    p.text(64, 236, 1110, "Open nothing unsafely.\nBelieve nothing unproven.", 53, True, leading=64)
    p.text(65, 400, 1080,
           "Proofbox inspects suspicious links, verifies bills, and checks letter requirements "
           "using isolated execution, deterministic checks, and a private evidence ledger.", 27, color=SOFT)
    p.node(65, 523, 350, 68, "INSPECT", "", MINT)
    p.node(465, 523, 350, 68, "VERIFY", "", BLUE)
    p.node(865, 523, 350, 68, "PRESERVE", "", AMBER)
    p.arrow(416, 558, 464, 558)
    p.arrow(816, 558, 864, 558)
    p.note("Built for Vultr Agent Rush / Blast Radius Zero. The separate demo shows the product in use.")

    p.slide("02 / Problem and users", "The problem is not a lack of answers. It is a lack of proof.",
            "People must assess risky inputs and consequential paperwork without exposing themselves or losing context.")
    p.columns(
        ("WHAT PEOPLE FACE", [
            ("Suspicious links", "Messages can lead to credential requests, misleading pages, redirects, or unwanted downloads."),
            ("Disputed bills and official letters", "Charges, readings, requirements, and response dates need checking against explicit rules."),
            ("Scattered evidence", "Documents, findings, replies, and deadlines are hard to assemble into one reviewable record."),
        ]),
        ("WHO THE SYSTEM SERVES", [
            ("Citizens", "A guided way to understand findings and retain the artifacts behind them."),
            ("Support and advice teams", "A consistent case file for reviewing work without reconstructing a conversation."),
            ("Service operators", "A reusable pattern for controlled intake and evidence-backed workflow automation."),
        ]))
    p.note("Target value: clearer decisions, less repeated checking, and a reliable handoff between people.")

    p.slide("03 / Product scope", "Three inspection lenses. One private case file.",
            "Each lens has a bounded task and an explicit output; the case file connects them.")
    p.table(["Surface", "Input and processing", "Output"], [
        ["Link Lens", "HTTP(S) URL; isolated browser observation and static indicators.", "Verdict, reasons, trace artifacts, and containment events."],
        ["Bill Lens", "Bill PDF; optional reading history and outage context; tariff recomputation.", "Findings, calculation receipts, and a draft dispute letter."],
        ["Letter Lens", "Official letter plus supporting PDFs; requirement extraction and layout checks.", "Checklist findings, explicit dates, and derived check facts."],
        ["Case File", "Attached findings, confirmed dates, reply proposals, and case-owned receipts.", "Evidence ledger, clocks, actions, and versioned PDF / ZIP packs."],
    ], [192, 484, 460], 76, 19)
    p.note("Scope is inspection and preparation, not automatic form submission or legal representation.")

    p.slide("04 / End-to-end journey", "From untrusted input to a reviewable outcome.",
            "The workflow separates interpretation, execution, verification, and user-controlled state changes.", True)
    nodes = [
        ("01 / INTAKE", "Validate the input.\nCreate a job and\npreserve its context."),
        ("02 / EXECUTE", "Run a browser or\nPDF/code task in\nthe worker sandbox."),
        ("03 / VERIFY", "Apply static checks,\narithmetic, schemas,\nand domain rules."),
        ("04 / EXPLAIN", "Return findings,\ncaveats, and\nreceipt references."),
        ("05 / PRESERVE", "Attach to a case.\nConfirm dates.\nExport the record."),
    ]
    for i, (tag, body) in enumerate(nodes):
        x = 64 + i * 234
        p.node(x, 268, 215, 232, tag, body)
        if i < 4:
            p.arrow(x + 216, 380, x + 233, 380)
    p.text(65, 533, 1130, "Job events describe execution; the case ledger preserves selected evidence and confirmed actions.", 22, color=SOFT)
    p.note("An interpretation is not proof. A completed job is not automatically a confirmed case action.")

    p.slide("05 / Link Lens", "Observe a page without becoming its next victim.",
            "The browser gathers behavior and artifacts; the person does not need to interact with the inspected page.")
    p.columns(
        ("INSPECTION PIPELINE", [
            ("Validate the URL", "Accept absolute HTTP(S) URLs. Reject embedded credentials, local hosts, private IP literals, and invalid ports."),
            ("Run the browser in isolation", "Playwright records redirects, visible text, form fields, requests, downloads, and an inspection image."),
            ("Collect behavioral evidence", "Blocked requests and quarantined downloads become job events; artifacts return to the control plane."),
        ]),
        ("DECISION LOGIC", [
            ("Static indicators", "Check domain/brand mismatch, sensitive inputs, redirect chains, punycode, raw IPs, and risk indicators."),
            ("Visual and trace interpretation", "A vision-role model interprets the captured page alongside the trace. Deterministic danger rules override its result."),
            ("Explicit uncertainty", "Results distinguish dangerous, suspicious, no issue found, and could not check. No issue found does not mean safe."),
        ]))
    p.note("The browser observes; it does not fill or submit forms. Private-network protection also depends on egress policy.")

    p.slide("06 / Bill Lens", "Use language models for extraction, not arithmetic authority.",
            "A billing finding must be traceable to the source fields, the rule used, and the calculation.")
    p.columns(
        ("FROM PDF TO CHECKABLE FACTS", [
            ("Isolated parsing", "The uploaded bill is text-extracted in the worker sandbox. Preserve its filename, size, page count, and hash."),
            ("Structured extraction", "The extractor produces typed bill fields. Unreadable inputs do not silently become successful checks."),
            ("Deterministic tariff checks", "Decimal arithmetic recomputes charges. Reading history and outage context support additional checks when supplied."),
        ]),
        ("FROM FINDING TO ACTION", [
            ("Independent code path", "An analyst-generated program executes in the no-network sandbox; its output is data to verify, not trusted control events."),
            ("Receipt-backed findings", "Store billed, recomputed, and difference values with explanations and calculation artifacts."),
            ("Draft, not automatic dispute", "Generate a reviewable dispute letter. Attaching a draft alone must not start a statutory response clock."),
        ]))
    p.note("Municipal tariff and escalation rules remain unverified. Missing history means the related checks are skipped.")

    p.slide("07 / Verification explained", "A correct calculation still needs a correct rule.",
            "Illustrative arithmetic only: these values are not a product test result or an official tariff.")
    p.table(["Layer", "Illustrative example", "What it establishes"], [
        ["Extracted facts", "Usage: 12 units. Reported usage charge: R 220.00.", "The fields to examine; extraction may still need correction."],
        ["Assumed rule", "First 6 units at R 10.00; next 6 units at R 20.00.", "The basis of recomputation, subject to source verification."],
        ["Recomputation", "(6 x R 10.00) + (6 x R 20.00) = R 180.00.", "A deterministic result under the stated assumptions."],
        ["Difference", "R 220.00 - R 180.00 = R 40.00.", "A discrepancy to review, not proof of unlawful billing."],
    ], [206, 478, 452], 75)
    p.note("The receipt must preserve the rule and inputs. Reproducible arithmetic cannot validate an unofficial rule.")

    p.slide("08 / Letter Lens", "Translate correspondence into requirements and check facts.",
            "The official letter is interpreted; supporting documents are checked inside the isolated worker.")
    p.columns(
        ("PROCESSING", [
            ("Letter and supporting PDFs", "Accept one official letter and up to four supporting PDFs, within the documented upload limits."),
            ("Parse before interpreting", "Extract text inside the no-network sandbox. The model extracts requirements and explicit dates from the official letter."),
            ("Checklist execution", "Layout-specific code checks supporting documents. Derived facts summarize presence, dates, and checklist outcomes."),
        ]),
        ("PRIVACY AND LIMITS", [
            ("Minimize model exposure", "The supporting-document privacy boundary sends derived check facts rather than full supporting text or raw identity numbers."),
            ("Retain useful context", "Requirement findings and explicit response or appointment dates can be attached to a private case."),
            ("Do not imply authentication", "Checks are layout-based, not authenticity or identity verification. Scanned/image-only PDFs are unsupported."),
        ]))
    p.note("The grant-review checklist is unverified. An extracted requirement is not an eligibility determination.")

    p.slide("09 / Case file", "Preserve a ledger, not just a conversation.",
            "The case file brings evidence, receipt ownership, deadlines, and correspondence into one workflow.")
    p.columns(
        ("EVIDENCE LIFECYCLE", [
            ("Attach completed findings", "Link and document outcomes become evidence entries with case-specific sequence numbers and derived facts."),
            ("Stable references", "Sequence allocation locks the case row; evidence numbers cannot be reassigned. Claims can refer to entries such as [E1]."),
            ("Case-owned receipts", "Receipt copies belong to the case. Deletion removes these copies rather than leaving orphaned case artifacts."),
        ]),
        ("CONTROLLED CASE ACTIONS", [
            ("Start clocks deliberately", "A person confirms when a dispute was sent. Merely drafting or attaching correspondence is not enough."),
            ("Review replies before applying them", "Model extraction creates a separate proposal. Confirmation is required before updating case state."),
            ("Export a dated snapshot", "Pack generation preserves the selected evidence, claims, clock state, and receipt hashes in immutable versions."),
        ]))
    p.note("Private access is possession-based: anyone with the exact token link can view the case. Share it with care.")

    p.slide("10 / System architecture", "Keep the authority outside the execution boundary.",
            "Vultr hosts separated control-plane and sandbox tiers; model calls originate from the control plane.", True)
    p.node(64, 251, 180, 156, "PERSON", "Web interface\nHTTPS + SSE", BLUE)
    p.node(303, 231, 359, 246, "CONTROL-PLANE VM",
           "Web + FastAPI\nJob orchestration\nPostgreSQL + case engine\nModel gateway")
    p.node(733, 231, 483, 246, "SANDBOX-HOST VM",
           "Private authenticated worker\nDocker + gVisor / runsc\nBrowser and PDF/code tasks\nNo inference key", AMBER)
    p.arrow(245, 335, 302, 335, BLUE)
    p.arrow(663, 335, 732, 335)
    p.text(665, 305, 70, "Private", 13, color=MINT)
    p.node(303, 528, 359, 126, "VULTR SERVERLESS INFERENCE", "OpenAI-compatible model API")
    p.node(733, 528, 483, 126, "CASE PACK STORAGE", "Durable private storage;\nconfigured separately")
    p.arrow(482, 478, 482, 527)
    p.set_draw_color(*MINT)
    p.line(640, 477, 640, 504)
    p.line(640, 504, 974, 504)
    p.arrow(974, 504, 974, 527)
    p.text(65, 535, 192, "Architecture contract.\nDeployed end-to-end\nverification pending.", 17, color=SOFT)

    p.slide("11 / Service responsibilities", "Small, explicit responsibilities across the stack.",
            "The implementation separates public orchestration, untrusted execution, model interpretation, and evidence export.")
    p.table(["Component", "Responsibility", "Key boundary"], [
        ["Web application", "Link, bill, letter, and case interfaces; displays streamed progress and findings.", "No untrusted browser/code execution on the user's device."],
        ["FastAPI control plane", "Validate intake, claim jobs, call the worker, evaluate results, and expose case APIs.", "Owns inference access and consequential case-state changes."],
        ["Worker and sandbox", "Run browser, parse_bill, parse_document, and code modes; collect output and lifecycle events.", "Private API; per-task resource and execution restrictions."],
        ["PostgreSQL + pack builder", "Persist jobs, events, model-call records, receipts, case state, and pack snapshots.", "Integrity checks before export; durable pack storage required."],
    ], [215, 495, 426], 76)
    p.note("The model proposes or interprets. The API, deterministic logic, and user confirmation govern the workflow.")

    p.slide("12 / Agent and model roles", "Assign models to bounded jobs, not unrestricted authority.",
            "Current role mappings are visible in the gateway and configuration; no model quality ranking is claimed.")
    p.table(["Role", "Configured model", "Responsibility"], [
        ["Router", "deepseek-v4.1-flash-1017", "Role mapping for classification and routing."],
        ["Extractor", "qwen3.8-27b", "Structured extraction from permitted source text."],
        ["Analyst / coder", "deepseek-v4.1-flash-1017", "Generate a program for isolated verification."],
        ["Writer", "glm-5.3", "Plain-language advice and reviewable draft letters."],
        ["Vision verifier", "mimo-v2.6-pro", "Interpret Link Lens page capture and trace."],
    ], [215, 430, 491], 59)
    p.note("Fallback models and translation are listed in YAML; gateway failover/translation must not be assumed implemented.")

    p.slide("13 / Gateway controls", "Treat external content as data, including model inputs.",
            "The control plane centralizes model access, structured validation, privacy checks, and call accounting.")
    p.columns(
        ("REQUEST AND RESPONSE", [
            ("Delimit untrusted content", "Serialize input as JSON and escape angle brackets before enclosing it in an untrusted-data boundary."),
            ("Validate structured output", "A Pydantic schema validates JSON responses where a schema is required. The gateway strips code fences before validation."),
            ("Bound the retry loop", "At most three attempts. Validation errors inform the next attempt; exhausted attempts return an explicit error payload."),
        ]),
        ("CONTROL AND VISIBILITY", [
            ("Centralize inference credentials", "The Vultr inference key remains in the control-plane environment, not the browser or worker."),
            ("Apply the privacy gate", "Check outgoing textual prompt content for identity-number patterns before submitting the request."),
            ("Record each call", "Persist role, model, token counts, latency, and outcome. These support later operational measurement, not invented benchmarks."),
        ]))
    p.note("Prompt boundaries reduce instruction confusion; they do not replace sandboxing, validation, or data-access policy.")

    p.slide("14 / Threat model", "Different threats need different enforcement layers.",
            "Containment is a defense-in-depth design, not a claim that every possible escape has been eliminated.", True)
    p.table(["Threat", "Intended enforcement", "Residual boundary"], [
        ["Hostile page or PDF", "Separate worker; disposable execution; restricted container permissions.", "Escape resistance must be tested on the deployed runtime."],
        ["Private-network access", "No-network code mode; browser egress proxy and destination policy.", "Validate DNS, redirects, metadata targets, and direct egress."],
        ["Prompt injection", "Trusted parsing events, untrusted-data delimiters, schemas, and deterministic checks.", "Not a proof of complete prompt-injection resistance."],
        ["Sensitive-data leakage", "Prompt privacy gate, private case access, export exclusions, and integrity checks.", "Pattern detection is not comprehensive personal-data detection."],
    ], [222, 482, 432], 77, 19)
    p.note("Blast Radius Zero is the challenge objective. The presentation does not assert certified zero risk.")

    p.slide("15 / Sandbox profiles", "Enforce limits where the work actually executes.",
            "The following values are current worker settings, not a measured throughput or performance guarantee.", True)
    p.table(["Control", "Browser / Link Lens", "Bill / document / code"], [
        ["Runtime and network", "gVisor / runsc; internal network with proxy.", "gVisor / runsc by default; network none."],
        ["Memory / CPU / processes", "1 GB; 1 CPU; 128 process limit.", "512 MB; 0.5 CPU; 64 process limit."],
        ["Filesystem / privilege", "Read-only root; dropped capabilities; no new privileges.", "Read-only root and inputs; dropped capabilities; no new privileges."],
        ["Wall-clock limit", "25 seconds for the browser worker task.", "20 seconds by default; configurable."],
        ["Temporary data", "Ephemeral output and download quarantine.", "64 MB /tmp; isolated input directory."],
    ], [257, 443, 436], 60, 18)
    p.note("Production must preserve these restrictions, confirm teardown, and never weaken runsc silently to make a task pass.")

    p.slide("16 / Execution events and failures", "Show what happened, and what could not be established.",
            "Job state and trusted worker events make execution inspectable without elevating model output into control signals.")
    p.columns(
        ("LIFECYCLE AND DATA", [
            ("Execution events", "Record container start, artifact collection, prohibited requests, quarantined downloads, resource termination, and completion."),
            ("Worker-to-API streaming", "Worker responses use NDJSON event records. The control plane persists job events and exposes SSE to the web interface."),
            ("Separate data from authority", "Model-written code output is returned as data. Only trusted parser instruction_ignored records are forwarded as events."),
        ]),
        ("FAILURE SEMANTICS", [
            ("Unreadable or unavailable input", "Parsing and inspection errors must be distinct from successful checks. Link Lens includes a could_not_check outcome."),
            ("Incomplete context", "Missing bill history skips history-based checks instead of fabricating earlier readings."),
            ("Operational visibility", "Failed jobs and model-call outcomes retain diagnostic context. A teardown event alone is not independent proof of cleanup."),
        ]))
    p.note("Do not interpret a quiet trace, a reassuring summary, or a lifecycle label as proof that all checks passed.")

    p.slide("17 / Evidence integrity", "Connect each claim to its inputs and artifacts.",
            "The pack builder enforces reference validity and receipt integrity before producing the export.", True)
    for i, (tag, body) in enumerate([
        ("01 / SOURCE", "Preserve the input\nand its fingerprint."),
        ("02 / FINDING", "Store derived facts\nand receipt references."),
        ("03 / LEDGER", "Allocate stable\ncase evidence numbers."),
        ("04 / EXPORT", "Resolve claims and\nvalidate receipt hashes."),
    ]):
        x = 64 + i * 294
        p.node(x, 253, 270, 194, tag, body)
        if i < 3:
            p.arrow(x + 271, 349, x + 293, 349)
    p.text(65, 486, 1120,
           "Claims such as [E1] must resolve to evidence in the pack. Receipt bytes are checked "
           "against recorded SHA-256 values. Invalid references or mismatched hashes stop pack generation.",
           24, color=SOFT)
    p.note("A hash detects a content mismatch. It is not a digital signature, proof of authenticity, or proof of truth.")

    p.slide("18 / Export contract", "Deliver an evidence package another person can inspect.",
            "The export is a versioned snapshot, not an automatically updated live document.")
    p.columns(
        ("PDF EVIDENCE PACK", [
            ("Case and version context", "Identify the case, pack version, generation time, and applicable rule caveats."),
            ("Numbered claims and clocks", "Link numbered claims to evidence sections; include due dates and clock state from the snapshot."),
            ("Evidence and drafted correspondence", "List evidence entries and receipt hashes; include relevant draft dispute-letter content."),
        ]),
        ("ZIP RECEIPT ARCHIVE", [
            ("Reviewable artifacts", "Package permitted receipt artifacts associated with the versioned evidence snapshot."),
            ("Supporting-document exclusion", "Replace Letter Lens supporting PDFs with placeholders containing the source hash and privacy-protected metadata."),
            ("Integrity and privacy gates", "Reject mismatched hashes and detected 13-digit identifiers. Store immutable PDF/ZIP versions under CASE_STORAGE_DIR."),
        ]))
    p.note("Pack files need durable, private storage and consistent backup. Temporary container storage is insufficient.")

    p.slide("19 / Privacy and access", "Minimize exposure throughout the case lifecycle.",
            "Controls reduce specific risks; they do not establish full POPIA compliance or comprehensive data-loss prevention.")
    p.table(["Boundary", "Current mechanism", "Important qualification"], [
        ["Case access", "Random token in URL fragment; API bearer header; database stores its SHA-256 hash.", "Anyone possessing the link has access; sharing is a security decision."],
        ["Model prompts", "Supporting-document check facts; textual identity-number pattern gate.", "Pattern matching does not detect every sensitive field or image."],
        ["Evidence export", "Supporting PDFs replaced with hash-bearing placeholders; ID-number gate.", "Primary source and derived facts still require appropriate handling."],
        ["Retention and deletion", "Case-owned receipts, expiry cleanup, and deletion workflow.", "Verify deployed cleanup, backup retention, logs, and access policy."],
    ], [192, 500, 444], 76, 19)
    p.note("Use synthetic data for the hackathon. Real-record handling requires a privacy and operational review.")

    p.slide("20 / Clocks and human confirmation", "Suggestions must not silently become consequential actions.",
            "Explicit confirmation connects the case record to what a person actually did.")
    p.columns(
        ("DEADLINE RULES", [
            ("Anchor to a confirmed event", "Municipal dispute clocks begin from the confirmed sent date, not the document-generation date."),
            ("Count business days in code", "Counting starts on the next business day after the sent date; non-business days are skipped."),
            ("Expose rule uncertainty", "Holiday dates, response periods, and escalation routes require verification against official sources."),
        ]),
        ("REPLY PROPOSALS", [
            ("Extract into a separate proposal", "A reply can suggest changes without writing new evidence, clocks, or actions immediately."),
            ("Apply only after confirmation", "The person reviews the proposal before the case state changes; attaching a draft does not start a dispute clock."),
            ("Discard deliberately", "Discarding a proposal clears its raw reply text and extracted proposal. Reminders are derived from due dates."),
        ]))
    p.note("A code-derived deadline is only as reliable as its anchor date, rule source, and holiday calendar.")

    p.slide("21 / Operations and deployment", "Production readiness is an operational gate, not a slide claim.",
            "Deploy the release in a controlled order and verify each boundary against the actual environment.")
    p.columns(
        ("RELEASE PREPARATION", [
            ("Pin and review the release", "Record the intended commit and images. Review existing host changes and establish a maintenance and rollback owner."),
            ("Back up before migration", "Back up PostgreSQL and pack storage consistently. Test restoration and review startup migrations on a database copy."),
            ("Rebuild sandbox images first", "Ensure both bill and document parsers exist under runsc before updating the worker, API, and web services."),
        ]),
        ("DEPLOYMENT CHECKS", [
            ("Protect the private worker", "Restrict network access and use a unique worker token. Do not expose the worker or Docker socket publicly."),
            ("Provision durable pack storage", "Configure writable CASE_STORAGE_DIR, permissions, backup, and a consistent shared path if multiple API instances are used."),
            ("Verify the full workflow", "Check all lenses, event streaming, case access, confirmation, pack downloads, privacy gates, and expiry cleanup."),
        ]))
    p.note("An application-image rollback does not undo schema changes. Restore and migration procedures must be tested.")

    p.slide("22 / Readiness and roadmap", "Useful implementation. Clearly defined remaining work.",
            "Current source and deployment notes support workflow claims, not certified production or security outcomes.")
    p.table(["Status", "Scope", "Next acceptance evidence"], [
        ["Implemented", "Three lenses; case API; clocks; reply confirmation; pack export; receipt and prompt privacy gates.", "Release-specific regression and end-to-end results."],
        ["Unverified", "Live deployment behavior, sandbox escape resistance, domain rules, holidays, and grant checklist.", "Recorded deployment tests; official sources; adversarial test results."],
        ["Known limitations", "Text PDFs only; layout-specific letter checks; possession-based case access.", "Broader-format evaluation and a privacy/access review."],
        ["Next / proposed", "Pilot workflow, measured accuracy and review effort, stronger operational observability.", "Documented quality, cost, latency, and privacy acceptance thresholds."],
    ], [192, 532, 412], 76)
    p.note("No user-adoption, accuracy, cost-saving, latency, or escape-test numbers are claimed in this presentation.")

    p.slide("23 / Why this system matters", "Useful agent work, bounded execution, reviewable evidence.",
            "The differentiator is the combination: interpretation alone cannot provide containment or a durable handoff.", True)
    p.columns(
        ("WHAT MAKES THE SYSTEM DISTINCT", [
            ("Execution-aware inspection", "The link is observed in an isolated runtime rather than merely described from its URL."),
            ("Verification-aware interpretation", "Models help read and explain; rules and deterministic calculations keep critical conclusions checkable."),
            ("Evidence-aware workflow", "Findings survive as receipt-linked case entries and versioned exports, with human confirmation at consequential steps."),
        ]),
        ("HOW VALUE SHOULD BE MEASURED", [
            ("Review efficiency", "Measure case preparation and reviewer reconstruction time against a manual baseline."),
            ("Finding quality", "Evaluate extraction accuracy, false positives, missed findings, and agreement with verified domain rules."),
            ("Operational fitness", "Measure task reliability, per-case inference cost, latency, cleanup success, and privacy-control outcomes."),
        ]))
    p.note("Proofbox's promise: inspect the input, verify the claim, preserve the evidence, and keep the person in control.")

    p.slide("24 / Technical source anchors", "A system presentation grounded in inspectable implementation.",
            "Source paths are relative to sandbox-spike. Separate product demonstration is submitted alongside this document.")
    p.table(["Claim area", "Implementation / documentation anchor"], [
        ["Orchestration and jobs", "apps/api/main.py; apps/api/link_lens.py; apps/api/lenses/bill/job.py"],
        ["Document workflows", "apps/api/lenses/bill/pipeline.py; apps/api/lenses/letter_job.py"],
        ["Inference and sandbox controls", "apps/api/gateway.py; config/models.yaml; apps/worker/main.py; apps/worker/bill_modes.py"],
        ["Case, integrity, and privacy", "apps/api/casefile.py; apps/api/pack_builder.py; docs/decisions.md"],
        ["Deployment and limitations", "docs/deployment-guide.md; docs/decisions.md; apps/web/vultr.html"],
    ], [322, 814], 60, 19)
    p.note("Open nothing unsafely. Believe nothing unproven. Preserve evidence that can be reviewed.")

    if p.page_no() != TOTAL:
        raise ValueError(f"Expected {TOTAL} slides, got {p.page_no()}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    p.output(str(OUTPUT))
    return OUTPUT


if __name__ == "__main__":
    print(build())
