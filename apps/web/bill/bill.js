"use strict";

// Result data comes from documents users upload, so it is only ever written with textContent.
const params = new URLSearchParams(location.search);
const API_BASE = params.get("api") || location.origin;
const $ = (selector) => document.querySelector(selector);

const CHECK_TITLES = {
  arithmetic: "Charges do not match the tariff",
  estimated_readings: "Estimated meter readings",
  meter_sanity: "Meter readings do not add up",
  outage_consistency: "Billed use during a water outage",
  line_items: "Duplicate or unknown charge",
};

let current = null;
let stream = null;

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function setStatus(message, isError = false) {
  const line = $("#status-line");
  line.textContent = message;
  line.classList.toggle("error", isError);
}

function money(value) {
  if (value === null || value === undefined || value === "unreadable") return "–";
  const n = Number(value);
  return Number.isFinite(n) ? `R${n.toFixed(2)}` : String(value);
}

function amount(value, unit) {
  if (value === null || value === undefined) return "–";
  return unit === "R" ? money(value) : `${value} ${unit || ""}`.trim();
}

function render(result) {
  if (!result || result.lens !== "bill") throw new Error("This is not a Bill Lens result.");
  current = result;
  $("#result").hidden = false;
  renderSummary(result);
  renderContainment(result.events || []);
  renderFindings(result);
  renderSkipped(result.skipped_checks || []);
  renderLetter(result.dispute_letter);
  renderExtracted(result);
  $("#disclaimer").textContent = result.disclaimer || "This is not legal advice.";
}

function renderSummary(result) {
  const summary = result.summary || {};
  const count = (result.findings || []).length;
  const badge = $("#badge");
  if (result.status !== "ok") {
    badge.textContent = "Could not read bill";
    badge.className = "badge unreadable";
  } else if (count) {
    badge.textContent = `${count} finding${count === 1 ? "" : "s"}`;
    badge.className = "badge issues";
  } else {
    badge.textContent = "No discrepancies";
    badge.className = "badge ok";
  }
  $("#billed-total").textContent = money(summary.billed_total);
  $("#recomputed-total").textContent = money(summary.recomputed_total);
  const diffNode = $("#total-diff");
  const billed = Number(summary.billed_total);
  const recomputed = Number(summary.recomputed_total);
  if (Number.isFinite(billed) && Number.isFinite(recomputed) && summary.recomputed_total !== null) {
    const diff = billed - recomputed;
    diffNode.textContent = `${diff > 0 ? "+" : diff < 0 ? "−" : ""}R${Math.abs(diff).toFixed(2)}`;
    diffNode.classList.toggle("over", Math.abs(diff) >= 0.05);
  } else {
    diffNode.textContent = "–";
    diffNode.classList.remove("over");
  }
  const bill = result.extracted || {};
  const period = bill.billing_period || {};
  const parts = [bill.municipality, bill.account_number && `Account ${bill.account_number}`];
  if (period.start) parts.push(`${period.start} to ${period.end}`);
  if (result.tariff_id) parts.push(`Tariff ${result.tariff_id}`);
  if (result.sample) parts.push(`Sample ${result.sample.id} (${result.sample.mode})`);
  $("#meta").textContent = parts.filter(Boolean).join(" · ");
}

function renderContainment(events) {
  const ignored = events.filter((event) => event.type === "instruction_ignored");
  $("#containment").hidden = ignored.length === 0;
  const list = $("#containment-list");
  list.replaceChildren(...ignored.map((event) => el("li", (event.data && event.data.line) || event.message)));
}

function renderFindings(result) {
  const findings = result.findings || [];
  $("#no-findings").hidden = findings.length > 0 || result.status !== "ok";
  $("#findings-wrap").hidden = findings.length === 0;
  const rows = findings.map((finding, index) => {
    const row = document.createElement("tr");
    row.append(el("td", index + 1));
    const check = el("td");
    check.append(el("div", CHECK_TITLES[finding.check] || finding.check, "check-title"), el("div", finding.explanation, "explanation"));
    row.append(check);
    row.append(el("td", amount(finding.billed, finding.unit), "num"));
    row.append(el("td", amount(finding.recomputed, finding.unit), "num"));
    const diff = el("td", finding.difference ? `+${amount(finding.difference, finding.unit)}` : "–", "num");
    if (finding.difference) diff.classList.add("diff");
    row.append(diff);
    const receipts = el("td");
    const box = el("div", undefined, "receipts");
    for (const id of finding.receipt_ids || []) {
      const meta = (result.receipts || {})[id] || {};
      const button = el("button", meta.label || id);
      button.type = "button";
      button.title = `Open receipt ${id}`;
      button.addEventListener("click", () => openReceipt(id));
      box.append(button);
    }
    receipts.append(box);
    row.append(receipts);
    return row;
  });
  $("#findings-body").replaceChildren(...rows);

  const analyst = result.analyst;
  let text = "";
  if (analyst) {
    if (analyst.status === "agreed") text = "Independent check: a separately generated program recomputed the totals in a sandbox and agreed with the tariff engine.";
    else if (analyst.status === "disagreed") text = "Independent check: the sandbox recomputation disagreed with the tariff engine, so it was not used as evidence.";
    else text = "Independent check: the sandbox recomputation did not run, so only the tariff engine was used.";
  }
  $("#analyst").textContent = text;
}

function renderSkipped(skipped) {
  $("#skipped-panel").hidden = skipped.length === 0;
  $("#skipped-list").replaceChildren(...skipped.map((item) => el("li", item.reason || item.check)));
}

function renderLetter(letter) {
  $("#letter-panel").hidden = !letter;
  if (!letter) return;
  $("#letter-text").textContent = letter.text;
  $("#letter-source").textContent = letter.source === "writer" ? "Worded by the writer model, checked by code" : "Standard template";
}

function renderExtracted(result) {
  const unreadable = result.unreadable_fields || [];
  $("#unreadable").textContent = unreadable.length
    ? `Could not read: ${unreadable.join(", ")}.`
    : result.status === "ok" ? "Every field was found in the document text." : (result.notes || []).join(" ");
  const list = $("#extracted");
  list.replaceChildren();
  const bill = result.extracted || {};
  const add = (label, value) => {
    const dd = el("dd", value === undefined || value === null ? "–" : value);
    if (value === "unreadable") dd.className = "unreadable";
    list.append(el("dt", label), dd);
  };
  for (const [key, value] of Object.entries(bill)) {
    if (value === null || typeof value !== "object") add(key.replaceAll("_", " "), value);
  }
  if (bill.billing_period) add("billing period", `${bill.billing_period.start} to ${bill.billing_period.end}`);
  for (const reading of bill.meter_readings || []) add(`reading ${reading.date}`, `${reading.reading_kl} kl (${reading.type})`);
  for (const line of bill.tariff_lines || []) add(line.description, `${line.quantity_kl} kl × R${line.rate_per_kl} = R${line.amount}`);
  for (const charge of bill.fixed_charges || []) add(charge.description, `R${charge.amount}`);
}

async function openReceipt(id) {
  const meta = (current.receipts || {})[id] || {};
  $("#receipt-title").textContent = meta.label || "Receipt";
  $("#receipt-meta").textContent = [id, meta.kind, meta.sha256 && `sha256 ${meta.sha256}`].filter(Boolean).join(" · ");
  const content = $("#receipt-content");
  $("#receipt-dialog").showModal();
  if (meta.content !== undefined) {
    content.textContent = meta.content;
    return;
  }
  content.textContent = "Loading receipt…";
  try {
    const response = await fetch(`${API_BASE}/api/receipts/${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const receipt = data.receipt || data;
    content.textContent = typeof receipt.content === "string" ? receipt.content : JSON.stringify(receipt, null, 2);
  } catch (error) {
    content.textContent = `Could not load receipt ${id} (${error.message}).`;
  }
}

function parseResult(raw) {
  return typeof raw === "string" ? JSON.parse(raw) : raw;
}

async function loadSample(name) {
  document.querySelectorAll("[data-sample]").forEach((button) => button.classList.toggle("active", button.dataset.sample === name));
  setStatus(`Loading sample ${name}…`);
  try {
    const response = await fetch(`samples/${encodeURIComponent(name)}.json`);
    if (!response.ok) throw new Error(`sample ${name} not found (HTTP ${response.status}). Run scripts/build_bill_samples.py.`);
    render(await response.json());
    setStatus(`Showing sample ${name}.`);
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function showJob(jobId) {
  const response = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}`);
  if (!response.ok) throw new Error(`Could not load job ${jobId} (HTTP ${response.status}).`);
  const data = await response.json();
  const job = data.job || data;
  if (job.result_json) {
    render(parseResult(job.result_json));
    setStatus(`Showing job ${jobId}.`);
    return true;
  }
  return false;
}

async function loadJob(jobId) {
  setStatus(`Loading job ${jobId}…`);
  try {
    if (await showJob(jobId)) return;
    setStatus(`Job ${jobId} is still running…`);
    if (stream) stream.close();
    stream = new EventSource(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/events`);
    stream.onmessage = async (message) => {
      const item = JSON.parse(message.data);
      setStatus(`${item.event}${item.detail ? `: ${item.detail}` : ""}`);
      if (item.event === "job_completed" || item.event === "job_failed") {
        stream.close();
        if (item.event === "job_failed" || !(await showJob(jobId))) setStatus(item.detail || `Job ${jobId} finished without a result.`, true);
      }
    };
    stream.onerror = () => {
      stream.close();
      setStatus("The live event connection ended before a result arrived.", true);
    };
  } catch (error) {
    setStatus(error.message, true);
  }
}

document.querySelectorAll("[data-sample]").forEach((button) => button.addEventListener("click", () => loadSample(button.dataset.sample)));

$("#file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    render(parseResult(data.job ? data.job.result_json : data.result_json || data));
    setStatus(`Showing ${file.name}.`);
  } catch (error) {
    setStatus(`Could not open ${file.name}: ${error.message}`, true);
  }
  event.target.value = "";
});

$("#close-receipt").addEventListener("click", () => $("#receipt-dialog").close());

$("#copy-letter").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("#letter-text").textContent);
    setStatus("Letter copied to the clipboard.");
  } catch {
    setStatus("Copy failed. Select the letter text and copy it manually.", true);
  }
});

$("#download-letter").addEventListener("click", () => {
  const blob = new Blob([$("#letter-text").textContent], { type: "text/plain;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  const account = ((current && current.extracted && current.extracted.account_number) || "account").replace(/[^\w-]+/g, "_");
  link.download = `dispute-letter-${account}.txt`;
  link.click();
  URL.revokeObjectURL(link.href);
});

if (params.get("job")) loadJob(params.get("job"));
else loadSample(params.get("sample") || "A6");
