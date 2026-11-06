/**
 * Proofbox Containment Panel Controller (Hero Component)
 * Manages the dark instrument chamber UI, event mapping, summary counts,
 * wall-clock countdown, auto-scrolling with scroll-up detection, and mobile collapse.
 */

import { el } from "./common.js";

export class ContainmentPanel {
  constructor({
    rootElement,
    jobId = "",
    wallClockSeconds = 40,
    onBreakIt = null,
  }) {
    this.root = rootElement;
    this.jobId = jobId;
    this.wallClockSeconds = wallClockSeconds;
    this.timeRemaining = wallClockSeconds;
    this.onBreakIt = onBreakIt;
    this.isFinished = false;
    this.counts = { blocked: 0, quarantined: 0, ignored: 0 };
    this.userHasScrolledUp = false;
    this.timerInterval = null;

    this.renderShell();
    this.startCountdown();
  }

  renderShell() {
    this.root.className = "containment-panel";
    this.root.setAttribute("data-state", "running");

    const shortId = this.jobId ? (this.jobId.length > 14 ? `${this.jobId.slice(0, 14)}…` : this.jobId) : "initializing";

    this.header = el("div", { className: "containment-header" },
      el("div", { className: "containment-title-group" },
        el("span", { className: "containment-badge" }, "Sandbox"),
        el("span", { className: "font-mono text-xs text-muted", id: "chamber-job-id" }, shortId)
      ),
      el("div", { className: "flex-row" },
        el("span", { className: "containment-live-pill", id: "chamber-status-pill" },
          el("span", { className: "containment-live-dot", "aria-hidden": "true" }),
          el("span", { id: "chamber-live-state" }, "RUNNING")
        ),
        el("span", { className: "containment-timer", id: "chamber-timer" }, `${this.timeRemaining}s limit`)
      )
    );

    this.summaryRow = el("div", { className: "containment-summary", hidden: true, id: "chamber-summary" },
      el("div", { className: "containment-summary-item" },
        el("span", { text: "Blocked:" }),
        el("span", { className: "containment-summary-count", id: "count-blocked" }, "0")
      ),
      el("div", { className: "containment-summary-item" },
        el("span", { text: "Quarantined:" }),
        el("span", { className: "containment-summary-count", id: "count-quarantined" }, "0")
      ),
      el("div", { className: "containment-summary-item" },
        el("span", { text: "Ignored:" }),
        el("span", { className: "containment-summary-count", id: "count-ignored" }, "0")
      )
    );

    this.eventList = el("ol", {
      className: "containment-events",
      id: "chamber-events-list",
      role: "log",
      "aria-live": "polite"
    });

    // Detect user scroll-up to pause auto-scroll
    this.eventList.addEventListener("scroll", () => {
      const atBottom = this.eventList.scrollHeight - this.eventList.scrollTop - this.eventList.clientHeight < 30;
      this.userHasScrolledUp = !atBottom;
    });

    this.root.replaceChildren(this.header, this.summaryRow, this.eventList);

    if (this.onBreakIt) {
      const redTeamBar = el("div", { style: "padding: var(--s2) var(--s3); background: var(--chamber-surface); border-top: 1px solid var(--chamber-line); text-align: right;" },
        el("button", {
          type: "button",
          className: "btn btn-redteam",
          title: "Safe simulated attack demonstration in isolated container",
          onClick: this.onBreakIt
        }, "Try to break it (Safe test)")
      );
      this.root.appendChild(redTeamBar);
    }
  }

  setJobId(jobId) {
    this.jobId = jobId;
    const shortId = jobId ? (jobId.length > 14 ? `${jobId.slice(0, 14)}…` : jobId) : "";
    const node = this.root.querySelector("#chamber-job-id");
    if (node) node.textContent = shortId;
  }

  startCountdown() {
    clearInterval(this.timerInterval);
    this.timerInterval = setInterval(() => {
      if (this.isFinished) {
        clearInterval(this.timerInterval);
        return;
      }
      this.timeRemaining = Math.max(0, this.timeRemaining - 1);
      const timerNode = this.root.querySelector("#chamber-timer");
      if (timerNode) {
        timerNode.textContent = `${this.timeRemaining}s remaining`;
      }
      if (this.timeRemaining === 0) {
        clearInterval(this.timerInterval);
      }
    }, 1000);
  }

  addEvent(type, detail = "") {
    const timestamp = new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false
    }).format(new Date());

    let tagText = "INFO";
    let tagClass = "";
    let borderColor = "var(--chamber-cyan)"; // default info cyan
    let plainDescription = detail || type;

    // Map according to Step 2 specifications:
    if (type === "network_blocked" || type === "request_blocked") {
      this.counts.blocked++;
      tagText = "BLOCKED";
      tagClass = "tag-blocked";
      borderColor = "var(--chamber-red)"; // Red
      plainDescription = detail ? `Blocked: tried to reach ${detail}` : "Blocked outbound network connection";
    } else if (type === "canary_read") {
      this.counts.blocked++;
      tagText = "CANARY TOUCHED";
      tagClass = "tag-blocked";
      borderColor = "var(--chamber-red)";
      plainDescription = `Fake secret touched: ${detail || "canary credential read attempt"}`;
    } else if (type === "download_quarantined") {
      this.counts.quarantined++;
      tagText = "QUARANTINED";
      tagClass = "tag-quarantined";
      borderColor = "var(--chamber-amber)"; // Amber
      plainDescription = `Quarantined payload: ${detail || "unknown file"} (never opened)`;
    } else if (type === "instruction_ignored") {
      this.counts.ignored++;
      tagText = "IGNORED";
      tagClass = "tag-ignored";
      borderColor = "var(--chamber-blue)"; // Blue
      plainDescription = detail ? `Ignored prompt instruction: "${detail}" (did not change the result)` : "Ignored untrusted document instruction";
    } else if (type === "timeout_kill" || type === "memory_kill") {
      this.counts.blocked++;
      tagText = "LIMIT KILLED";
      tagClass = "tag-blocked";
      borderColor = "var(--chamber-red)";
      plainDescription = `${type === "timeout_kill" ? "Timeout kill" : "Memory limit kill"}: ${detail || "Process terminated"}`;
    } else if (type === "output_truncated") {
      tagText = "TRUNCATED";
      borderColor = "var(--chamber-amber)";
      plainDescription = `Output size truncated: ${detail || "exceeded safe buffer limit"}`;
    } else if (type === "container_destroyed") {
      tagText = "DESTROYED";
      tagClass = "tag-destroyed";
      borderColor = "var(--chamber-green)"; // Green
      plainDescription = `Container destroyed. Job ${this.jobId || "closed"}.`;
    } else if (type === "job_completed") {
      tagText = "COMPLETE";
      tagClass = "tag-destroyed";
      borderColor = "var(--chamber-green)";
      plainDescription = detail || "Inspection complete. Finding verified.";
    } else if (type === "job_failed") {
      tagText = "FAILED";
      tagClass = "tag-blocked";
      borderColor = "var(--chamber-red)";
      plainDescription = detail || "Inspection failed.";
    }

    const row = el("li", {
      className: "containment-event-row",
      style: `border-left-color: ${borderColor};`
    },
      el("span", { className: "containment-event-time" }, timestamp),
      el("div", { className: "containment-event-body" },
        el("div", { className: "flex-row", style: "gap: 6px;" },
          el("span", { className: `containment-event-tag ${tagClass}` }, tagText),
          el("span", { text: plainDescription })
        )
      )
    );

    // If timeout or memory kill, append small limit bar
    if (type === "timeout_kill" || type === "memory_kill") {
      const bar = el("div", { className: "containment-kill-bar" },
        el("div", { className: "containment-kill-bar-fill", style: "width: 100%;" })
      );
      row.querySelector(".containment-event-body").appendChild(bar);
    }

    this.eventList.appendChild(row);

    // Auto-scroll unless user scrolled up
    if (!this.userHasScrolledUp) {
      this.eventList.scrollTop = this.eventList.scrollHeight;
    }

    this.updateSummary();
  }

  updateSummary() {
    const blockedNode = this.root.querySelector("#count-blocked");
    const quarNode = this.root.querySelector("#count-quarantined");
    const ignNode = this.root.querySelector("#count-ignored");
    if (blockedNode) blockedNode.textContent = String(this.counts.blocked);
    if (quarNode) quarNode.textContent = String(this.counts.quarantined);
    if (ignNode) ignNode.textContent = String(this.counts.ignored);
  }

  finish(status = "DESTROYED") {
    this.isFinished = true;
    clearInterval(this.timerInterval);

    this.root.setAttribute("data-state", "finished");

    const liveDot = this.root.querySelector(".containment-live-dot");
    if (liveDot) {
      liveDot.style.animation = "none";
      liveDot.style.backgroundColor = status === "FAILED" ? "var(--chamber-red)" : "var(--chamber-green)";
      liveDot.style.boxShadow = "none";
    }

    const liveText = this.root.querySelector("#chamber-live-state");
    if (liveText) {
      liveText.textContent = status;
      liveText.style.color = status === "FAILED" ? "var(--chamber-red)" : "var(--chamber-green)";
    }

    const timer = this.root.querySelector("#chamber-timer");
    if (timer) {
      timer.textContent = "Destroyed";
    }

    // Show summary row
    this.summaryRow.hidden = false;

    // Mobile collapsible behavior:
    // On mobile screens (< 760px), collapse after completion while keeping 1 tap to expand
    if (window.innerWidth <= 760) {
      this.eventList.style.maxHeight = "160px";
    }
  }

  clear() {
    this.eventList.replaceChildren();
    this.counts = { blocked: 0, quarantined: 0, ignored: 0 };
    this.summaryRow.hidden = true;
    this.timeRemaining = this.wallClockSeconds;
    this.isFinished = false;
    this.userHasScrolledUp = false;
    this.startCountdown();
  }
}
