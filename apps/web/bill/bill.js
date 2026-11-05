"use strict";

// Everything shown here comes from documents users upload, so it is only ever written with textContent.
const params = new URLSearchParams(location.search);
const API_BASE = (params.get("api") || location.origin).replace(/\/+$/, "");
const MAX_PDF_BYTES = 5 * 1024 * 1024;
const MAX_HISTORY_BYTES = 256 * 1024;
const $ = (selector) => document.querySelector(selector);

const CHECK_TITLES = {
  arithmetic: "Charges do not match the tariff",
  estimated_readings: "Estimated meter readings",
  meter_sanity: "Meter readings do not add up",
  outage_consistency: "Billed use during a water outage",
  line_items: "Duplicate or unknown charge",
};

const STEPS = ["upload", "sandbox", "extract", "checks", "analyst", "letter", "done"];

// Event name -> [step, state]. "done" moves the next step to active.
const EVENT_STEPS = {
  job_queued: ["upload", "active"],
  bill_received: ["upload", "done"],
  container_started: ["sandbox", "active"],
  bill_parsed: ["sandbox", "done"],
  bill_parse_failed: ["sandbox", "failed"],
  timeout_kill: ["sandbox", "failed"],
  memory_kill: ["sandbox", "failed"],
  bill_extracted: ["extract", "done"],
  bill_unreadable: ["extract", "warn"],
  checks_completed: ["checks", "done"],
  analyst_completed: ["analyst", "done"],
  analyst_skipped: ["analyst", "warn"],
  letter_drafted: ["letter", "done"],
  job_completed: ["done", "done"],
};

const state = { current: null, stream: null, pdf: null, history: null, busy: false };

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

let toastTimer = null;
function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("show"), 2600);
}

function setFormMessage(message, isError = false) {
  const node = $("#form-msg");
  node.textContent = message;
  node.classList.toggle("error", isError);
}

function money(value) {
  if (value === null || value === undefined || value === "unreadable") return "–";
  const n = Number(value);
  return Number.isFinite(n) ? `R${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : String(value);
}

function amount(value, unit) {
  if (value === null || value === undefined) return "–";
  return unit === "R" ? money(value) : `${value} ${unit || ""}`.trim();
}

function bytes(n) {
  return n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 / 1024).toFixed(2)} MB`;
}

/* ---------- Progress stepper ---------- */

function stepNode(step) {
  return document.querySelector(`#stepper [data-step="${step}"]`);
}

function resetSteps() {
  for (const step of STEPS) {
    const node = stepNode(step);
    node.className = "";
    const note = node.querySelector(".step-note");
    if (note) note.remove();
  }
  $("#activity-log").replaceChildren();
  $("#log-count").textContent = "0";
  $("#job-id").textContent = "";
}

function setStep(step, status, note) {
  const index = STEPS.indexOf(step);
  STEPS.slice(0, index).forEach((earlier) => {
    const node = stepNode(earlier);
    if (!node.classList.contains("warn") && !node.classList.contains("failed")) node.className = "done";
  });
  const node = stepNode(step);
  node.className = status;
  if (note) addNote(step, note);
  if ((status === "done" || status === "warn") && STEPS[index + 1]) {
    const next = stepNode(STEPS[index + 1]);
    if (!next.className) next.className = "active";
  }
}

function completeAllSteps() {
  for (const step of STEPS) {
    const node = stepNode(step);
    if (!["warn", "failed"].includes(node.className)) node.className = "done";
  }
}

function failActiveStep(detail) {
  const active = STEPS.find((step) => stepNode(step).className === "active") || "upload";
  setStep(active, "failed", detail);
}

function logEvent(name, detail) {
  const item = el("li");
  const bad = /failed|kill|error/.test(name);
  item.append(el("span", name, bad ? "ev bad" : "ev"), document.createTextNode(detail ? ` ${detail}` : ""));
  const log = $("#activity-log");
  log.append(item);
  log.scrollTop = log.scrollHeight;
  $("#log-count").textContent = String(log.children.length);
}

function handleEvent(name, detail) {
  logEvent(name, detail);
  if (name === "instruction_ignored") return addNote("sandbox", "Hidden instruction found and removed");
  if (name === "history_missing") return addNote("extract", "No earlier bills supplied, so history checks will be skipped");
  if (name === "job_failed") return failActiveStep(detail || "The check failed");
  const mapped = EVENT_STEPS[name];
  if (!mapped) return;
  const [step, status] = mapped;
  const note = status === "warn" || status === "failed" ? detail : undefined;
  if (name === "job_completed") {
    if (!stepNode("letter").classList.contains("done")) addNote("letter", "Not needed: nothing to dispute");
    completeAllSteps();
  } else setStep(step, status, note);
}

function addNote(step, text) {
  const node = stepNode(step);
  let noteNode = node.querySelector(".step-note");
  if (!noteNode) {
    noteNode = el("span", "", "step-note");
    node.querySelector("div").append(noteNode);
  }
  noteNode.textContent = text;
}

/* ---------- Upload ---------- */

function setBusy(busy) {
  state.busy = busy;
  const button = $("#submit-btn");
  button.classList.toggle("busy", busy);
  button.querySelector(".btn-label").textContent = busy ? "Checking your bill…" : "Check my bill";
  updateSubmit();
}

function updateSubmit() {
  $("#submit-btn").disabled = state.busy || !state.pdf;
}

async function looksLikePdf(file) {
  const head = new Uint8Array(await file.slice(0, 5).arrayBuffer());
  return String.fromCharCode(...head) === "%PDF-";
}

async function choosePdf(file) {
  const zone = $("#dropzone");
  zone.classList.remove("has-file", "invalid");
  state.pdf = null;
  if (!file) {
    $("#drop-title").textContent = "Drop your bill PDF here";
    $("#drop-hint").textContent = "or browse your files · PDF up to 5 MB";
    updateSubmit();
    return;
  }
  let problem = "";
  if (file.size === 0) problem = "That file is empty.";
  else if (file.size > MAX_PDF_BYTES) problem = `That file is ${bytes(file.size)}. The limit is 5 MB.`;
  else if (!(await looksLikePdf(file))) problem = "That file is not a PDF.";
  $("#drop-title").textContent = file.name;
  if (problem) {
    zone.classList.add("invalid");
    $("#drop-hint").textContent = `${problem} Choose another file.`;
  } else {
    state.pdf = file;
    zone.classList.add("has-file");
    $("#drop-hint").textContent = `${bytes(file.size)} · ready to check · click to change`;
    setFormMessage("");
  }
  updateSubmit();
}

async function chooseHistory(file) {
  const line = $("#history-state");
  line.className = "file-state";
  state.history = null;
  if (!file) {
    line.textContent = "";
    return;
  }
  try {
    if (file.size > MAX_HISTORY_BYTES) throw new Error("it is larger than 256 KB");
    const data = JSON.parse(await file.text());
    if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("it must be a JSON object");
    for (const key of ["previous_bills", "outage_log"]) {
      if (key in data && !Array.isArray(data[key])) throw new Error(`"${key}" must be a list`);
    }
    state.history = data;
    const bills = (data.previous_bills || []).length;
    const outages = (data.outage_log || []).length;
    line.textContent = `${file.name}: ${bills} earlier bill${bills === 1 ? "" : "s"}, ${outages} outage${outages === 1 ? "" : "s"}.`;
    line.classList.add("ok");
  } catch (error) {
    line.textContent = `Could not use ${file.name}: ${error.message}.`;
    line.classList.add("error");
    $("#history-input").value = "";
  }
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(new Error("could not read the file"));
    reader.readAsDataURL(file);
  });
}

async function apiError(response) {
  try {
    const data = await response.json();
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map((item) => item.msg).join("; ");
  } catch {
    /* fall through */
  }
  return `HTTP ${response.status}`;
}

async function submitBill(event) {
  event.preventDefault();
  if (!state.pdf || state.busy) return;
  setBusy(true);
  hideResult();
  resetSteps();
  setStep("upload", "active");
  setFormMessage("Uploading your bill…");
  try {
    const body = {
      filename: state.pdf.name,
      pdf_base64: await fileToBase64(state.pdf),
      history: state.history,
    };
    const response = await fetch(`${API_BASE}/api/bill/intake`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(await apiError(response));
    const { job_id: jobId } = await response.json();
    history.replaceState(null, "", `?${new URLSearchParams({ ...Object.fromEntries(params), job: jobId })}`);
    setFormMessage("Your bill is being checked. This usually takes under a minute.");
    await followJob(jobId);
  } catch (error) {
    failActiveStep(error.message);
    setFormMessage(`Upload failed: ${error.message}`, true);
    setBusy(false);
  }
}

/* ---------- Jobs ---------- */

async function fetchJob(jobId) {
  const response = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}`);
  if (!response.ok) throw new Error(response.status === 404 ? `Job ${jobId} was not found.` : await apiError(response));
  const data = await response.json();
  return { job: data.job || data, events: data.events || [] };
}

function resultOf(job) {
  if (!job.result_json) return null;
  return typeof job.result_json === "string" ? JSON.parse(job.result_json) : job.result_json;
}

async function showFinishedJob(jobId) {
  const { job } = await fetchJob(jobId);
  const result = resultOf(job);
  if (job.status === "failed" || !result) throw new Error((result && result.error) || "The check finished without a result.");
  render(result);
}

async function followJob(jobId) {
  $("#job-id").textContent = jobId;
  if (state.stream) state.stream.close();
  setBusy(true);
  const finish = (message, isError) => {
    setBusy(false);
    setFormMessage(message, isError);
  };

  let snapshot;
  try {
    snapshot = await fetchJob(jobId);
  } catch (error) {
    finish(error.message, true);
    return;
  }
  if (snapshot.job.status === "completed" || snapshot.job.status === "failed") {
    for (const row of snapshot.events) handleEvent(row.event_type, row.detail);
    try {
      await showFinishedJob(jobId);
      finish("");
    } catch (error) {
      failActiveStep(error.message);
      finish(error.message, true);
    }
    return;
  }

  const stream = new EventSource(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/events`);
  state.stream = stream;
  stream.onmessage = async (message) => {
    let item;
    try {
      item = JSON.parse(message.data);
    } catch {
      return;
    }
    handleEvent(item.event, item.detail);
    if (item.event !== "job_completed" && item.event !== "job_failed") return;
    stream.close();
    if (item.event === "job_failed") {
      finish(item.detail || "The check failed.", true);
      return;
    }
    try {
      await showFinishedJob(jobId);
      finish("Done. Your results are below.");
    } catch (error) {
      finish(error.message, true);
    }
  };
  stream.onerror = async () => {
    stream.close();
    // The server closes the stream once the job ends; fall back to the stored result.
    try {
      await showFinishedJob(jobId);
      completeAllSteps();
      finish("Done. Your results are below.");
    } catch {
      finish("Lost the live connection. Reload the page to check on this job.", true);
    }
  };
}

/* ---------- Result rendering ---------- */

function hideResult() {
  $("#result").hidden = true;
}

function render(result) {
  if (!result || result.lens !== "bill") throw new Error("This is not a Bill Lens result.");
  state.current = result;
  renderVerdict(result);
  renderContainment(result.events || []);
  renderFindings(result);
  renderSkipped(result.skipped_checks || []);
  renderLetter(result.dispute_letter);
  renderExtracted(result);
  $("#disclaimer").textContent = result.disclaimer || "This is not legal advice.";
  const section = $("#result");
  section.hidden = false;
  section.scrollIntoView({ behavior: "smooth", block: "start" });
  section.focus({ preventScroll: true });
}

function renderVerdict(result) {
  const summary = result.summary || {};
  const count = (result.findings || []).length;
  const badge = $("#badge");
  const verdict = $("#verdict");
  const billed = Number(summary.billed_total);
  const recomputed = Number(summary.recomputed_total);
  const comparable = summary.recomputed_total !== null && summary.recomputed_total !== undefined && Number.isFinite(billed) && Number.isFinite(recomputed);
  const diff = comparable ? billed - recomputed : 0;

  if (result.status !== "ok") {
    badge.textContent = "Could not read bill";
    badge.className = "badge unreadable";
    verdict.className = "verdict";
    $("#verdict-title").textContent = "We could not read enough of this bill to check it";
  } else if (count) {
    badge.textContent = `${count} finding${count === 1 ? "" : "s"}`;
    badge.className = "badge issues";
    verdict.className = "verdict issues";
    $("#verdict-title").textContent = diff >= 0.05
      ? `You may have been overcharged by ${money(diff)}`
      : `We found ${count} thing${count === 1 ? "" : "s"} worth querying`;
  } else {
    badge.textContent = "No discrepancies";
    badge.className = "badge ok";
    verdict.className = "verdict ok";
    $("#verdict-title").textContent = "This bill matches the published tariff";
  }

  $("#billed-total").textContent = money(summary.billed_total);
  $("#recomputed-total").textContent = money(summary.recomputed_total);
  const diffBox = $("#total-diff");
  diffBox.textContent = comparable ? `${diff > 0 ? "+" : diff < 0 ? "−" : ""}${money(Math.abs(diff))}` : "–";
  diffBox.parentElement.classList.toggle("over", comparable && Math.abs(diff) >= 0.05);

  const bill = result.extracted || {};
  const period = bill.billing_period || {};
  const parts = [bill.municipality, bill.account_number && `Account ${bill.account_number}`];
  if (period.start) parts.push(`${period.start} to ${period.end}`);
  if (result.tariff_id) parts.push(`Tariff ${result.tariff_id}`);
  if (result.sample) parts.push(`Sample ${result.sample.id}`);
  $("#meta").textContent = parts.filter((part) => part && part !== "unreadable").join(" · ");
}

function renderContainment(events) {
  const ignored = events.filter((event) => event.type === "instruction_ignored");
  $("#containment").hidden = ignored.length === 0;
  $("#containment-list").replaceChildren(...ignored.map((event) => el("li", (event.data && event.data.line) || event.message)));
}

function renderFindings(result) {
  const findings = result.findings || [];
  const ran = result.checks_run || [];
  $("#checks-run").textContent = ran.length ? `${ran.length} check${ran.length === 1 ? "" : "s"} run` : "";
  $("#no-findings").hidden = findings.length > 0 || result.status !== "ok";

  const cards = findings.map((finding, index) => {
    const card = el("article", undefined, "finding");
    const head = el("div", undefined, "finding-head");
    const title = el("h3");
    title.append(el("span", `${index + 1}.`, "finding-num"), document.createTextNode(CHECK_TITLES[finding.check] || finding.check));
    head.append(title);
    if (finding.difference) head.append(el("span", `+${amount(finding.difference, finding.unit)}`, "diff"));
    card.append(head, el("p", finding.explanation));

    if (finding.billed !== null && finding.billed !== undefined) {
      const figures = el("div", undefined, "finding-figures");
      const fig = (label, value) => {
        const span = el("span", `${label} `);
        span.append(el("b", value));
        return span;
      };
      figures.append(fig("Billed", amount(finding.billed, finding.unit)), fig("Should be", amount(finding.recomputed, finding.unit)));
      card.append(figures);
    }

    const receipts = el("div", undefined, "receipts");
    for (const id of finding.receipt_ids || []) {
      const meta = (result.receipts || {})[id] || {};
      const button = el("button", meta.label || id, "receipt-chip");
      button.type = "button";
      button.title = `Open receipt ${id}`;
      button.addEventListener("click", () => openReceipt(id));
      receipts.append(button);
    }
    card.append(receipts);
    return card;
  });
  $("#findings").replaceChildren(...cards);

  const analyst = result.analyst;
  const box = $("#analyst");
  box.hidden = !analyst;
  if (!analyst) return;
  box.className = `analyst ${analyst.status}`;
  if (analyst.status === "agreed") box.textContent = "Independent check passed: a separately written program recomputed the totals in the sandbox and got the same answer.";
  else if (analyst.status === "disagreed") box.textContent = "Independent check disagreed with the tariff engine, so it was not used as evidence. The findings above rely on the tariff engine only.";
  else box.textContent = "The independent check did not run, so only the tariff engine was used.";
}

function renderSkipped(skipped) {
  $("#skipped-panel").hidden = skipped.length === 0;
  $("#skipped-list").replaceChildren(...skipped.map((item) => el("li", item.reason || item.check)));
}

function renderLetter(letter) {
  $("#letter-panel").hidden = !letter;
  if (!letter) return;
  $("#letter-text").textContent = letter.text;
  $("#letter-source").textContent = letter.source === "writer" ? "Worded by AI · amounts verified by code" : "Standard template";
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
  const doc = result.document;
  $("#document-meta").textContent = doc
    ? `Document: ${doc.filename} · ${bytes(doc.bytes || 0)}${doc.pages ? ` · ${doc.pages} page(s)` : ""} · sha256 ${doc.sha256}`
    : "";
}

async function openReceipt(id) {
  const meta = (state.current.receipts || {})[id] || {};
  $("#receipt-title").textContent = meta.label || "Receipt";
  $("#receipt-meta").textContent = [id, meta.kind, meta.sha256 && `sha256 ${meta.sha256}`].filter(Boolean).join(" · ");
  const content = $("#receipt-content");
  $("#receipt-dialog").showModal();
  if (meta.content !== undefined) {
    content.textContent = typeof meta.content === "string" ? meta.content : JSON.stringify(meta.content, null, 2);
    return;
  }
  content.textContent = "Loading receipt…";
  try {
    const response = await fetch(`${API_BASE}/api/bill/receipts/${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error(await apiError(response));
    const data = await response.json();
    const receipt = data.receipt || data;
    content.textContent = typeof receipt.content === "string" ? receipt.content : JSON.stringify(receipt.content ?? receipt, null, 2);
  } catch (error) {
    content.textContent = `Could not load receipt ${id} (${error.message}).`;
  }
}

/* ---------- Samples and saved results ---------- */

async function loadSample(name) {
  document.querySelectorAll("[data-sample]").forEach((button) => button.classList.toggle("active", button.dataset.sample === name));
  try {
    const response = await fetch(`samples/${encodeURIComponent(name)}.json`);
    if (!response.ok) throw new Error(`Sample ${name} is not available (HTTP ${response.status}).`);
    const result = await response.json();
    resetSteps();
    for (const event of result.events || []) handleEvent(event.type, event.message);
    if (result.dispute_letter) setStep("letter", "done");
    handleEvent("job_completed", "Prebuilt sample result");
    $("#job-id").textContent = `sample ${name}`;
    render(result);
    setFormMessage("");
  } catch (error) {
    setFormMessage(error.message, true);
  }
}

function downloadText(text, filename, type) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([text], { type }));
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function accountSlug() {
  const account = state.current && state.current.extracted && state.current.extracted.account_number;
  return String(account && account !== "unreadable" ? account : "bill").replace(/[^\w-]+/g, "_");
}

/* ---------- Wiring ---------- */

const zone = $("#dropzone");
$("#pdf-input").addEventListener("change", (event) => choosePdf(event.target.files[0]));
["dragenter", "dragover"].forEach((type) => zone.addEventListener(type, (event) => {
  event.preventDefault();
  zone.classList.add("dragging");
}));
["dragleave", "drop"].forEach((type) => zone.addEventListener(type, () => zone.classList.remove("dragging")));
zone.addEventListener("drop", (event) => {
  event.preventDefault();
  const file = event.dataTransfer.files[0];
  if (file) choosePdf(file);
});

$("#history-input").addEventListener("change", (event) => chooseHistory(event.target.files[0]));
$("#upload-form").addEventListener("submit", submitBill);

document.querySelectorAll("[data-sample]").forEach((button) => button.addEventListener("click", () => loadSample(button.dataset.sample)));

$("#result-input").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    const result = data.job ? resultOf(data.job) : data.result_json ? resultOf(data) : data;
    resetSteps();
    render(result);
    toast(`Opened ${file.name}`);
  } catch (error) {
    setFormMessage(`Could not open ${file.name}: ${error.message}`, true);
  }
  event.target.value = "";
});

$("#close-receipt").addEventListener("click", () => $("#receipt-dialog").close());
$("#receipt-dialog").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});

$("#copy-letter").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("#letter-text").textContent);
    toast("Letter copied");
  } catch {
    toast("Copy failed. Select the text and copy it manually.");
  }
});
$("#download-letter").addEventListener("click", () => {
  downloadText($("#letter-text").textContent, `dispute-letter-${accountSlug()}.txt`, "text/plain;charset=utf-8");
});
$("#print-letter").addEventListener("click", () => window.print());
$("#save-result").addEventListener("click", () => {
  downloadText(JSON.stringify(state.current, null, 2), `bill-result-${accountSlug()}.json`, "application/json");
});
$("#check-another").addEventListener("click", () => {
  hideResult();
  resetSteps();
  choosePdf(null);
  $("#pdf-input").value = "";
  history.replaceState(null, "", location.pathname + (params.get("api") ? `?api=${encodeURIComponent(params.get("api"))}` : ""));
  $("#upload-title").scrollIntoView({ behavior: "smooth" });
});

if (params.get("job")) followJob(params.get("job"));
else if (params.get("sample")) loadSample(params.get("sample"));
