/**
 * Proofbox Central Design System · Shared Utilities
 * Single constant brand name, accessible dialog management, SVG icon creator,
 * formatting & DOM helpers.
 */

export const PROOFBOX_NAME = "Proofbox";
export const BRAND_LINE = "Open nothing unsafely. Believe nothing unproven. Fight with receipts.";
export const DEPLOYED_API_URL = "http://zzarudpebhfzoohnpppp0snw.64.177.59.98.sslip.io";

/**
 * Resolves the API base URL.
 * Defaults to the production API backend when accessed on the deployed domain,
 * while honoring ?api= overrides or falling back to location.origin for local development.
 */
export function getApiBase() {
  const params = new URLSearchParams(window.location.search);
  const paramApi = params.get("api");
  if (paramApi) {
    return paramApi.replace(/\/+$/, "");
  }
  if (
    window.location.hostname.includes("4kcvz2ocaby56a8gdp4cdvvk") ||
    window.location.hostname.includes("64.177.59.98")
  ) {
    return DEPLOYED_API_URL;
  }
  return window.location.origin.replace(/\/+$/, "");
}

/**
 * Lightweight safe DOM creator
 */
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [key, val] of Object.entries(attrs)) {
      if (val === undefined || val === null) continue;
      if (key === "className" || key === "class") {
        node.className = String(val);
      } else if (key === "textContent" || key === "text") {
        node.textContent = String(val);
      } else if (key.startsWith("on") && typeof val === "function") {
        node.addEventListener(key.slice(2).toLowerCase(), val);
      } else if (key === "hidden") {
        node.hidden = Boolean(val);
      } else if (key.startsWith("data-") || key.startsWith("aria-") || ["id", "href", "src", "type", "name", "for", "role", "title", "alt", "value", "placeholder"].includes(key)) {
        node.setAttribute(key, String(val));
      } else {
        node[key] = val;
      }
    }
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null) continue;
    if (typeof child === "string" || typeof child === "number") {
      node.appendChild(document.createTextNode(String(child)));
    } else if (child instanceof Node) {
      node.appendChild(child);
    }
  }
  return node;
}

/**
 * Clean SVG icon creator (Heroicons/Lucide inspired)
 */
export function createSvgIcon(type, className = "chip-icon", size = 16) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  if (className) svg.setAttribute("class", className);

  const paths = {
    check: '<polyline points="20 6 9 17 4 12"></polyline>',
    cross: '<line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>',
    alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line>',
    info: '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline>',
    water: '<path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"></path>',
    phone: '<rect width="14" height="20" x="5" y="2" rx="2" ry="2"></rect><line x1="12" y1="18" x2="12.01" y2="18"></line>',
    arrowRight: '<line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline>',
    copy: '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path>',
    clock: '<circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline>'
  };

  svg.innerHTML = paths[type] || paths.info;
  return svg;
}

/**
 * Format bytes into human-readable string (e.g. 1.2 MB)
 */
export function formatBytes(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

/**
 * Format currency in South African Rands (fictional metro context)
 */
export function formatMoney(value) {
  if (value === null || value === undefined || value === "unreadable") return "–";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return `R${n.toLocaleString("en-ZA", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/**
 * Format ISO date string into readable date
 */
export function formatDate(value) {
  if (!value) return "Date unavailable";
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return String(value);
  }
}

/**
 * Copy text to clipboard with toast notification feedback
 */
export async function copyToClipboard(text, successMessage = "Copied to clipboard") {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      showToast(successMessage);
      return true;
    }
    // Fallback
    const input = document.createElement("textarea");
    input.value = text;
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.appendChild(input);
    input.focus();
    input.select();
    document.execCommand("copy");
    document.body.removeChild(input);
    showToast(successMessage);
    return true;
  } catch (error) {
    showToast("Could not copy automatically. Select text manually.");
    return false;
  }
}

let toastTimer = null;
/**
 * Show a floating status toast
 */
export function showToast(message) {
  let toastNode = document.querySelector("#toast");
  if (!toastNode) {
    toastNode = el("div", { id: "toast", className: "toast", role: "status", "aria-live": "polite" });
    document.body.appendChild(toastNode);
  }
  toastNode.textContent = message;
  toastNode.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastNode.classList.remove("show");
  }, 2800);
}

/**
 * Accessible Dialog Trap & Manager
 */
export function setupAccessibleDialog(dialog, triggerElement = null) {
  if (!dialog) return;

  let lastActive = triggerElement || document.activeElement;

  function handleKeyDown(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      dialog.close();
      return;
    }
    if (event.key !== "Tab") return;

    const focusables = dialog.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    if (!focusables.length) return;

    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  dialog.addEventListener("keydown", handleKeyDown);

  dialog.addEventListener("close", () => {
    if (lastActive && typeof lastActive.focus === "function") {
      lastActive.focus();
    }
  });

  return {
    open(newTrigger) {
      if (newTrigger) lastActive = newTrigger;
      else lastActive = document.activeElement;
      if (typeof dialog.showModal === "function") {
        dialog.showModal();
      } else {
        dialog.setAttribute("open", "");
      }
      const initialFocus = dialog.querySelector("button, input, [tabindex]") || dialog;
      initialFocus.focus();
    },
    close() {
      dialog.close();
    }
  };
}
