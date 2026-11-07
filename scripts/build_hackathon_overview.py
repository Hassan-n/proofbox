"""Build the seven-slide overview with original AI/cloud vector artwork."""

import math
from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "Proofbox_Overview.pdf"
DARK = (7, 13, 32)
PANEL = (16, 29, 53)
PAPER = (246, 247, 243)
WHITE = (255, 255, 255)
INK = (20, 38, 48)
GRAY = (82, 102, 113)
SOFT = (177, 198, 208)
MINT = (103, 232, 198)
TEAL = (17, 89, 112)
BLUE = (100, 175, 255)
VIOLET = (155, 130, 255)


class Overview(FPDF):
    def __init__(self) -> None:
        super().__init__(orientation="L", unit="pt", format=(720, 1280))
        self.set_auto_page_break(False)
        self.set_margins(0, 0, 0)
        fonts = Path(r"C:\Windows\Fonts")
        self.add_font("Deck", "", str(fonts / "calibri.ttf"))
        self.add_font("Deck", "B", str(fonts / "calibrib.ttf"))
        self.set_title("Proofbox | System Overview")
        self.set_author("Proofbox")
        self.set_subject("Vultr Agent Rush | Seven-slide product and architecture overview")
        self.dark = False

    def text(self, x, y, w, text, size=24, bold=False, color=None, bottom=657):
        self.set_font("Deck", "B" if bold else "", size)
        self.set_text_color(*(color or (WHITE if self.dark else INK)))
        self.set_xy(x, y)
        self.multi_cell(w, size * 1.18, text, align="L", padding=0)
        if self.get_y() > bottom:
            raise ValueError(f"Slide {self.page_no()}: overflowing text {text!r}")

    def box(self, x, y, w, h, color):
        self.set_fill_color(*color)
        self.set_draw_color(*((42, 65, 94) if self.dark else (218, 227, 222)))
        self.set_line_width(0.8)
        self.rect(x, y, w, h, style="DF", round_corners=True, corner_radius=14)

    def background(self):
        for y in range(0, 720, 4):
            t = y / 720
            self.set_fill_color(7 + int(5 * t), 13 + int(9 * t), 32 + int(15 * t))
            self.rect(0, y, 1280, 4, style="F")
        self.set_line_width(0.5)
        self.set_draw_color(22, 37, 64)
        for x in range(640, 1320, 64):
            self.line(x, 70, x - 160, 675)
        for y in range(80, 680, 56):
            self.line(620, y, 1280, y)
        nodes = [(831, 82), (975, 122), (1128, 85), (1216, 177),
                 (1088, 225), (1180, 620), (1014, 651), (866, 606)]
        self.set_draw_color(37, 64, 100)
        for a, b in zip(nodes, nodes[1:]):
            self.line(*a, *b)
        for x, y in nodes:
            self.set_fill_color(55, 93, 135)
            self.ellipse(x - 2.5, y - 2.5, 5, 5, style="F")
        self.set_fill_color(*BLUE)
        self.rect(0, 0, 1280, 4, style="F")
        self.set_fill_color(*MINT)
        self.rect(0, 0, 330, 4, style="F")

    def hero(self):
        """Original cloud-compute sculpture; not an official Vultr logo."""
        cx, cy = 1030, 341
        self.set_line_width(1)
        for radius in (160, 194):
            self.set_draw_color(39, 64, 103)
            self.ellipse(cx - radius, cy - radius, radius * 2, radius * 2)
        for degrees in (20, 85, 160, 220, 300):
            angle = math.radians(degrees)
            x, y = cx + 194 * math.cos(angle), cy + 194 * math.sin(angle)
            self.set_fill_color(*(MINT if degrees % 2 else BLUE))
            self.ellipse(x - 4, y - 4, 8, 8, style="F")
        for y in (404, 356, 308):
            self.set_fill_color(23, 48, 83)
            self.polygon([(895, y), (1030, y + 56), (1165, y),
                          (1165, y + 28), (1030, y + 84), (895, y + 28)], style="F")
            self.set_fill_color(29, 64, 107)
            self.set_draw_color(*BLUE)
            self.polygon([(895, y), (1030, y - 56), (1165, y), (1030, y + 56)], style="DF")
            self.set_draw_color(52, 98, 151)
            self.line(1030, y + 57, 1030, y + 81)
            for x in (1116, 1130, 1144):
                self.set_fill_color(*MINT)
                self.ellipse(x, y + 13 - (x - 1116) * 0.4, 4, 4, style="F")
        self.set_fill_color(15, 35, 63)
        self.set_draw_color(*MINT)
        self.set_line_width(2)
        self.polygon([(1030, 198), (1094, 221), (1086, 292),
                      (1066, 320), (1030, 342), (994, 320),
                      (974, 292), (966, 221)], style="DF")
        self.set_line_width(5)
        self.set_draw_color(*MINT)
        self.line(1002, 266, 1022, 287)
        self.line(1022, 287, 1059, 244)
        self.text(856, 559, 355, "AI + ISOLATED EXECUTION", 17, True, BLUE)

    def slide(self, section, title=None, subtitle=None, dark=False):
        self.add_page()
        self.dark = dark
        if dark:
            self.background()
        else:
            self.set_fill_color(*PAPER)
            self.rect(0, 0, 1280, 720, style="F")
        self.start_section(section)
        self.text(64, 33, 700, f"PROOFBOX  /  {section.upper()}", 13, True,
                  MINT if dark else TEAL)
        self.text(971, 33, 245, "VULTR AGENT RUSH / 2026", 13, color=SOFT if dark else GRAY)
        if title:
            self.text(64, 101, 1152, title, 46, True, bottom=161)
            self.set_fill_color(*(BLUE if dark else TEAL))
            self.rect(65, 157, 75, 3, style="F")
        if subtitle:
            self.text(64, 171, 1120, subtitle, 23, color=SOFT if dark else GRAY, bottom=230)
        self.set_draw_color(*(PANEL if dark else (218, 227, 222)))
        self.line(64, 678, 1216, 678)
        self.text(64, 692, 1000, "SYSTEM OVERVIEW  /  PROTOTYPE  /  NOT LEGAL ADVICE",
                  10, color=SOFT if dark else GRAY, bottom=717)
        self.text(1155, 689, 60, f"{self.page_no():02} / 07", 13,
                  color=SOFT if dark else GRAY, bottom=717)

    def card(self, x, tag, title, body, y=278, w=368, h=273):
        self.box(x, y, w, h, PANEL if self.dark else WHITE)
        accent = (BLUE if x < 400 else MINT if x < 800 else VIOLET) if self.dark else TEAL
        self.set_fill_color(*accent)
        self.rect(x + 25, y + 6, 52, 3, style="F")
        self.text(x + 25, y + 24, w - 50, tag, 15, True, accent)
        self.text(x + 25, y + 73, w - 50, title, 31, True, bottom=y + 125)
        self.text(x + 25, y + 131, w - 50, body, 23,
                  color=SOFT if self.dark else GRAY, bottom=y + h - 20)

    def arrow(self, x1, y1, x2, y2, color=MINT):
        self.set_line_width(2)
        self.set_draw_color(*color)
        self.line(x1, y1, x2, y2)
        self.set_fill_color(*color)
        if x1 == x2:
            self.polygon([(x2, y2), (x2 - 5, y2 - 9), (x2 + 5, y2 - 9)], style="F")
        else:
            self.polygon([(x2, y2), (x2 - 9, y2 - 5), (x2 - 9, y2 + 5)], style="F")


def build() -> Path:
    p = Overview()

    p.slide("The promise", dark=True)
    p.text(64, 111, 750, "Proofbox", 80, True)
    p.text(67, 239, 715, "From untrusted inputs\nto evidence-backed action.", 45, True)
    p.text(67, 387, 650, "Inspect links. Verify paperwork.\nKeep the proof.", 29, color=SOFT)
    p.hero()
    for x, label, color in [(67, "INSPECT", BLUE), (249, "VERIFY", MINT),
                            (431, "PRESERVE", VIOLET)]:
        p.box(x, 503, 163, 43, PANEL)
        p.text(x + 20, 515, 139, label, 16, True, color)
    p.text(67, 592, 1100, "Containment-first agents, built on Vultr.", 25, True, MINT)

    p.slide("The problem", "An answer is not enough.",
            "Risky links and consequential paperwork need more than a convincing summary.", dark=True)
    p.card(64, "01 / RISK", "Can I open it?", "Suspicious pages can request credentials, trigger downloads, or reach prohibited destinations.")
    p.card(456, "02 / UNCERTAINTY", "Is it correct?", "Bills and official letters need explicit checks of numbers, requirements, and dates.")
    p.card(848, "03 / FRAGMENTATION", "Where is the proof?", "Findings, documents, and replies get scattered when there is no shared evidence trail.")
    p.text(65, 607, 1140, "Proofbox connects safe inspection, verification, and a reviewable record.", 26, True, MINT)

    p.slide("The product", "Three lenses. One case file.",
            "Purpose-built workflows for suspicious links, billing questions, and official correspondence.", dark=True)
    p.card(64, "LINK LENS", "Inspect behavior", "Observe a page in an isolated browser. Preserve findings and execution artifacts.", y=265, h=254)
    p.card(456, "BILL LENS", "Recompute charges", "Extract the bill, check arithmetic in code, and draft a receipt-backed dispute.", y=265, h=254)
    p.card(848, "LETTER LENS", "Check requirements", "Extract dates and requirements. Run layout-based checks on supporting PDFs.", y=265, h=254)
    p.box(64, 551, 1152, 95, TEAL)
    p.text(89, 574, 270, "PRIVATE CASE FILE", 23, True, WHITE)
    p.text(391, 568, 789, "Evidence + confirmed dates + replies\nExport a versioned PDF / ZIP pack.", 24, color=WHITE)

    p.slide("How it works", "Inspect. Verify. Explain. Preserve.",
            "Models interpret. Code checks. People confirm consequential actions.", dark=True)
    for i, (title, body) in enumerate([
        ("Inspect", "Run the browser or document task in an isolated worker."),
        ("Verify", "Apply static checks, deterministic calculations, and schemas."),
        ("Explain", "Return findings, caveats, and the receipts behind the result."),
        ("Preserve", "Attach to a case, confirm dates, and export the evidence."),
    ]):
        x = 64 + i * 294
        p.card(x, f"0{i + 1}", title, body, y=280, w=270, h=280)
        if i < 3:
            p.arrow(x + 272, 418, x + 291, 418)
    p.text(65, 608, 1140, "The output is a reviewable handoff, not just another chat response.", 26, True, MINT)

    p.slide("Vultr architecture", "Separate authority from execution.",
            "A control-plane VM orchestrates work; a separate sandbox-host VM runs untrusted tasks.", dark=True)
    p.box(64, 284, 190, 166, PANEL)
    p.text(86, 307, 150, "PERSON", 15, True, BLUE)
    p.text(86, 355, 150, "Web app\nHTTPS + SSE", 25)
    p.box(311, 261, 405, 224, PANEL)
    p.text(336, 286, 355, "VULTR / CONTROL PLANE", 15, True, MINT)
    p.text(336, 334, 355, "API + job orchestration\nCase data + model gateway\nInference key stays here", 26)
    p.box(782, 261, 434, 224, PANEL)
    p.text(807, 286, 384, "VULTR / SANDBOX HOST", 15, True, BLUE)
    p.text(807, 334, 384, "Private worker API\nDocker + gVisor / runsc\nDisposable browser and code", 26)
    p.arrow(255, 367, 309, 367, BLUE)
    p.arrow(717, 367, 781, 367)
    p.text(723, 338, 65, "Private", 12, color=MINT)
    p.box(311, 539, 405, 94, TEAL)
    p.text(336, 556, 355, "Vultr Serverless Inference\nOpenAI-compatible model API", 23, color=WHITE)
    p.arrow(513, 486, 513, 538)
    p.text(806, 552, 387, "Code mode: no network\nBrowser mode: controlled egress", 23, color=SOFT)
    p.text(65, 551, 198, "Architecture overview.\nLive validation pending.", 16, color=SOFT)

    p.slide("Trust by design", "Bound the work. Keep the evidence.",
            "Safety comes from system boundaries, not instructions to the model alone.", dark=True)
    p.card(64, "EXECUTION", "Contain", "Isolated tasks, resource limits, restricted network access, and temporary execution environments.")
    p.card(456, "CORRECTNESS", "Verify", "Deterministic calculations and structured checks keep critical findings reviewable.")
    p.card(848, "ACCOUNTABILITY", "Preserve", "Receipt hashes, stable evidence references, versioned exports, and human confirmation.")
    p.text(65, 607, 1140, "Integrity is not authenticity. A reproducible check still needs a verified domain rule.", 24, True, MINT)

    p.slide("The value", "Less guesswork. More evidence.",
            "For citizens and the teams who help them.", dark=True)
    p.box(64, 275, 555, 244, PANEL)
    p.text(90, 300, 503, "THE OUTCOME", 15, True, MINT)
    p.text(90, 349, 503, "Understand the finding.\nReview the receipt.\nAct with context.", 34, True)
    p.box(651, 275, 565, 244, PANEL)
    p.text(677, 300, 513, "THE NEXT GATE", 15, True, BLUE)
    p.text(677, 349, 513, "Verify live containment and domain rules, then measure quality, review time, and cost per case.", 28, color=SOFT)
    p.text(65, 557, 1138, "Text PDFs only. Letter checks do not authenticate documents. Production verification remains outstanding.",
           19, color=SOFT)
    p.text(65, 614, 1148, "Open nothing unsafely. Believe nothing unproven.", 31, True, MINT)

    assert p.page_no() == 7
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    p.output(str(OUTPUT))
    return OUTPUT


if __name__ == "__main__":
    print(build())
