# Proofbox Frontend Audit (Step 0)

Date: 2026-11-06  
Auditor: Senior Front-End Designer-Engineer  
Scope: Entire Proofbox web frontend (`apps/web/`, sub-lenses, case timeline, styling, and JS interactions)

---

## 1. File and Folder Map

| Path | Screen / Role | Owning JS / Logic |
|---|---|---|
| `apps/web/index.html` | Chat Intake & Link Lens (Job View) | Inline `<script>` (~95 lines) + common modules |
| `apps/web/bill/index.html` | Bill Lens (Job View) | `apps/web/bill/bill.js` (~650 lines) |
| `apps/web/bill/bill.css` | Legacy Bill Lens CSS (258 lines) | To be replaced/migrated to central design system |
| `apps/web/bill/samples/*` | Sample fixtures (A5, A6, A7 JSON & PDF) | Consumed by `bill.js` |
| `apps/web/letter/index.html` | Letter Lens (Job View) | Inline `<script>` (~180 lines) |
| `apps/web/letter/samples/*` | Sample fixtures (A9 letter, A10 supporting PDFs) | Consumed by `letter/index.html` |
| `apps/web/case/index.html` | Case File Timeline, Pack Preview, Review | Inline `<script>` (~450 lines) |
| `apps/web/vultr.html` *(to add)* | How Proofbox Runs on Vultr (Judges Page) | New dedicated showcase screen |
| `apps/web/styleguide.html` *(to add)* | Design System Styleguide | Interactive review and component test bench |
| `apps/web/css/*` *(to add)* | Design tokens, base layout, reusable components | `tokens.css`, `base.css`, `components.css` |
| `apps/web/js/common.js` *(to add)* | Centralized safe utilities & focus management | Shared across all screens |

---

## 2. Inventory of JS Hooks to Preserve

All `id`, `data-*` attributes, classes, and SSE event handlers read or written by JavaScript must be preserved exactly or mapped without breaking functional behavior.

### A. Link Lens / Intake (`index.html`)
- **IDs**:
  - `#bill-link`: Link to Bill Lens with API param preserved
  - `#case-link`: Link to Case File with API param preserved
  - `#inspect-form`: Intake submission form
  - `#url`: URL/input field
  - `#submit`: Submission button
  - `#error`: Error banner (`role="alert"`)
  - `#activity-heading`: Accessible heading
  - `#job-state`: Live state label (Queuing, Inspecting, Complete, Failed, Connection lost)
  - `#events`: Event container (`aria-live="polite"`)
  - `#result-heading`: Result section heading
  - `#job-id`: Job ID display
  - `#result-empty`: Empty placeholder
  - `#verdict`: Verdict container (`aria-live="polite"`)
  - `#badge`: Verdict badge container
  - `#verdict-name`: Verdict name text
  - `#confidence`: Confidence level text
  - `#advice`: Primary actionable advice
  - `#reasons`: List of verdict explanation reasons
  - `#caveat`: "What this does not mean" caveat text
  - `#screenshot`: Sandbox page screenshot (`<img>`)
- **Dynamic classes**:
  - `.visible` (on `#verdict`, `#error`)
  - `.blocked` (on `.tag`)
  - `.badge.dangerous`, `.badge.suspicious`, `.badge.no_issue_found`, `.badge.could_not_check`
- **SSE Events**:
  - `job_completed`, `job_failed`, `network_blocked`, `download_quarantined`, `request_blocked`, `timeout_kill`, `memory_kill`

### B. Bill Lens (`bill/index.html` & `bill.js`)
- **IDs**:
  - Form & Upload: `#upload-form`, `#pdf-input`, `#dropzone`, `#drop-title`, `#drop-hint`, `#history-input`, `#history-state`, `#submit-btn`, `#form-msg`, `#result-input`
  - Stepper & Progress: `#job-id`, `#stepper`, `#activity-log`, `#log-count`
  - Verdict & Discrepancies: `#result`, `#verdict`, `#badge`, `#verdict-title`, `#meta`, `#billed-total`, `#recomputed-total`, `#total-diff`
  - Containment: `#containment`, `#containment-title`, `#containment-list`
  - Findings: `#checks-run`, `#no-findings`, `#findings`, `#analyst`, `#skipped-panel`, `#skipped-list`
  - Dispute Letter: `#letter-panel`, `#letter-title`, `#letter-source`, `#letter-text`, `#copy-letter`, `#download-letter`, `#print-letter`
  - Extracted Details: `#extracted-title`, `#unreadable`, `#extracted`, `#document-meta`
  - Footer & Actions: `#disclaimer`, `#save-result`, `#check-another`
  - Receipt Modal & Toast: `#receipt-dialog`, `#receipt-title`, `#receipt-meta`, `#receipt-content`, `#close-receipt`, `#toast`
- **Data attributes**:
  - `data-step`: `upload`, `sandbox`, `extract`, `checks`, `analyst`, `letter`, `done`
  - `data-sample`: `A5`, `A6`, `A7`
- **Dynamic classes**:
  - Stepper state: `active`, `done`, `warn`, `failed`, `.step-note`
  - Dropzone: `has-file`, `invalid`, `dragging`
  - Button state: `busy` (on `#submit-btn`)
  - Status messages: `ok`, `error` (on `#history-state`, `#form-msg`)
  - Diff box: `.diff-box.over`
  - Badge & Verdict: `ok`, `issues`, `unreadable`
  - Analyst: `agreed`, `disagreed`
  - Findings: `finding`, `finding-head`, `finding-num`, `diff`, `finding-figures`, `receipts`, `receipt-chip`
  - Toast: `show`
- **SSE Events**:
  - `job_queued`, `bill_received`, `container_started`, `bill_parsed`, `bill_parse_failed`, `timeout_kill`, `memory_kill`, `bill_extracted`, `bill_unreadable`, `checks_completed`, `analyst_completed`, `analyst_skipped`, `letter_drafted`, `job_completed`, `job_failed`, `instruction_ignored`, `history_missing`

### C. Letter Lens (`letter/index.html`)
- **IDs**:
  - Form: `#upload-form`, `#letter-file`, `#supporting-files`, `#submit-button`, `#upload-message`
  - Progress: `#progress-panel`, `#job-status`, `#job-id`
  - Results: `#result-panel`, `#letter-fields`, `#checklist`
  - Actions: `#attach-button`, `#open-case`, `#copy-job`, `#attach-message`
- **Dynamic classes**:
  - `error-box` on messages
  - `check`, `status`, `status.have`, `status.missing`, `status.needs_fixing`

### D. Case File (`case/index.html`)
- **IDs**:
  - Global: `#page-title`, `#page-error`
  - Case Create: `#create-panel`, `#create-form`, `#case-title`, `#rule-set`, `#create-message`
  - Case View: `#case-view`, `#case-summary`, `#next-action`, `#clocks-title`, `#clocks`, `#rule-status`, `#timeline-title`, `#evidence`
  - Lens Links: `#link-lens`, `#bill-lens`, `#letter-lens`
  - Attach Form: `#attach-form`, `#job-id`, `#attach-message`
  - Sent Date Confirmation: `#sent-panel`, `#sent-form`, `#sent-evidence`, `#sent-date`, `#sent-message`
  - Reply Logging & Review: `#reply-form`, `#reply-text`, `#reply-message`, `#reply-proposals`
  - Pack Management: `#pack-title`, `#generate-pack`, `#pack-status`, `#pack-downloads`, `#download-pdf`, `#download-zip`, `#pack-preview`
  - Case Actions: `#delete-case`
  - Receipt Dialog: `#receipt-dialog`, `#receipt-title`, `#close-receipt`, `#receipt-hash`, `#receipt-content`
- **Dynamic classes**:
  - `clock`, `clock-head`, `state`, `state.overdue`, `state.due_soon`, `state.upcoming`, `state.met`, `state-icon`
  - `evidence`, `evidence-head`, `claim`, `receipts`
  - `proposal`, `claims`, `claim-link`
  - `button.secondary`, `button.danger`, `error-box`

---

## 3. Discovered Inconsistencies & Issues

1. **Fragmented Palettes**:
   - `index.html`, `bill.css`, `letter/index.html`, and `case/index.html` all define slight variations of greens (`#245c43`, `#1a4532`, `#245c43`), reds (`#9c2f27`), ambers (`#7a5417`), and surfaces (`#fffefa`, `#fafbf7`, `#ffffff`).
   - None of the screens use the unified brand teal (`--brand: #0F6B64`) or the specified chamber tokens (`--chamber-*`) for containment.
2. **Arbitrary Typography & Font Sizes**:
   - Headings range randomly across files (`56px/.98`, `40px`, `clamp(32px, 7vw, 52px)`, `clamp(2rem, 4.5vw, 2.9rem)`, `25px`, `22px`, `20px`, `19px`, `1.15rem`, `1.02rem`).
   - `index.html`, `letter`, and `case` put the entire body text in monospace (`--mono`), making body paragraphs, forms, and instructions look like raw terminals rather than a trustworthy civic instrument.
   - 35+ non-scale font sizes found (`10px`, `11px`, `12px`, `13px`, `14px`, `15px`, `18px`, `20px`, `22px`, `.75rem` through `1.35rem`).
3. **Inconsistent Button & Control Styling**:
   - Touch targets fall as low as 30 px or 34 px in some receipt buttons, violating the 48 px touch target requirement.
   - Radii differ randomly: 0 px, 2 px, 8 px, 10 px, 12 px, 14 px, 999 px.
   - Focus rings differ: outline colors include `#7bb98b`, `var(--green-bright)`, and standard browser defaults.
4. **Spacing off Scale**:
   - Margins and paddings use random pixel values (e.g., 7px, 9px, 11px, 13px, 14px, 18px, 19px, 22px, 26px, 30px, 34px, 44px) rather than multiples of the 4 px space scale (`--s1` through `--s7`).
5. **Accessibility Gaps**:
   - Status is frequently conveyed by background color alone or bare text without complementary icons.
   - Modals and dialogs (`#receipt-dialog`) lack a focus trap, do not consistently restore focus to the trigger upon exit, and do not trap Tab key navigation.
   - Missing explicit labels or helper texts on some file inputs and selectors.
   - Several foreground/background combinations (e.g., `#59665f` on `#f3f5ef`) hover near or below WCAG AA 4.5:1 contrast.
6. **Mandatory Wording Compliance**:
   - "No issue found" in some places was given a positive green treatment (`--green`), which misleads users into interpreting it as "safe". Must be changed to `--info` (blue tint) with the explicit statement: *"No issue found does not mean safe."*
7. **Containment Panel Under-designed**:
   - The sandbox activity in `index.html` and `bill/index.html` does not feature the hero dark chamber styling, wall-clock countdown, structured event row badges, or finish summaries required by Step 2.

---

## 4. Screens and States to Restyle

1. **App Shell & Global Elements**:
   - Header with brand mark, single constant "Proofbox", lens navigation, language selector, and persistent demo banner.
   - Footer with "Not legal advice" and synthetic data notice.
2. **Chat Intake Screen (`index.html`)**:
   - Inviting empty state with 3 example prompts (suspicious SMS, grant letter, water bill) as tappable chips.
   - Large input composer with file upload and language picker; sticky composer on mobile.
   - Router explanation bubble ("what I'm about to do").
3. **Job View Screens (`index.html`, `bill/index.html`, `letter/index.html`)**:
   - Two-zone layout (Hero Containment Panel + Verdict / Findings Report).
   - Compressed screenshot with explicit dimensions and trace link.
   - Link Lens verdict card, Bill Lens discrepancy table and dispute letter preview, Letter Lens checklist in consistent card design.
4. **Hero Containment Panel**:
   - Dark `--chamber-*` instrument interface with wall-clock countdown, live status indicator, and structured event badges.
   - Event categorization (`network_blocked`, `download_quarantined`, `instruction_ignored`, `canary_read`, `timeout_kill`, `memory_kill`, `container_destroyed`).
   - Summary statistics row upon completion.
   - Responsive collapse/expand for mobile viewports.
5. **Case Timeline Screen (`case/index.html`)**:
   - Case summary header with title, institution, status chip, and expiry notice.
   - Highlighted Next Action card.
   - Clocks grid with visual state chips and days remaining.
   - Evidence timeline with chronological nodes, badges, and receipt triggers.
   - Two-column Reply Review card (proposed changes vs. editable fields).
6. **Pack Preview Screen (`case/index.html`)**:
   - Clean printed document aesthetic with serif headings, numbered claims `[E1]`, `[E2]`, receipt chips, version label, and print styles (`@media print`).
7. **How Proofbox Runs on Vultr (`vultr.html`)**:
   - Dedicated judges page with clean inline SVG architecture diagram, Vultr service breakdowns, and animated live counters.
8. **Shared States across All Pages**:
   - Loading skeletons and progressive steps.
   - Empty states with plain-language explanations.
   - Error banners (`role="alert"`), offline indicators, and expired/deleted case notices.
9. **Component Styleguide (`styleguide.html`)**:
   - Comprehensive test bench exhibiting every token, component, button, badge, input, and state.
