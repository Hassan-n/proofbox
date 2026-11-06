/**
 * Proofbox Central Design System · Shared Utilities
 * Single constant brand name, accessible dialog management, formatting & DOM helpers.
 */

export const PROOFBOX_NAME = "Proofbox";
export const BRAND_LINE = "Open nothing unsafely. Believe nothing unproven. Fight with receipts.";

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
 * Traps Tab key within dialog, closes on Esc, restores focus to trigger on close.
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
