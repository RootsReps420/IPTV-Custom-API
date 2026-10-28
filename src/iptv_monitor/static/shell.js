/* Shared chrome for the console pages (/, /owner, /history, /key).
 * Overview: live clock, one hover/focus tooltip for any element with data-tip-title
 * (data-tip-body = extra lines, data-tip-key = colour key), and the sidebar status.
 * Pages without app.js (History, Info) set data-status-feed on <body>; shell.js then
 * polls /api/public for the sidebar status. app.js drives it on the Monitor page.
 * Tooltip text goes in with textContent only: hosts and names come from the API.
 */
(() => {
  const clock = document.getElementById("clock");
  const sideDot = document.getElementById("side-dot");
  const sideText = document.getElementById("side-status-text");
  const lastCycle = document.getElementById("last-cycle");

  function tickClock() {
    if (clock) {
      clock.textContent = new Date().toLocaleTimeString([], { hour12: false });
    }
  }

  // level: "good" | "warning" | "critical" | "" (unknown)
  function setStatus(level, text) {
    const dot = { good: "ok", warning: "warn", critical: "bad" }[level] || "";
    if (sideDot) {
      sideDot.className = `dot ${dot}`;
    }
    if (sideText) {
      sideText.textContent = text;
    }
  }

  // Shared with app.js so both pages word the overall state the same way.
  function overallState(counts) {
    const c = counts || {};
    const liveDown = (c.live_total ?? 0) - (c.live_up ?? 0);
    const standbyDown = (c.available_total ?? 0) - (c.available_up ?? 0);
    if (liveDown > 0) {
      return { level: "critical", short: "Live DNS down", headline: liveDown === 1 ? "Live DNS is down" : `${liveDown} live DNS hosts down` };
    }
    if (standbyDown > 0) {
      const hosts = `${standbyDown} standby host${standbyDown === 1 ? "" : "s"}`;
      return { level: "warning", short: `${hosts} down`, headline: `${hosts} down` };
    }
    return { level: "good", short: "All systems up", headline: "All systems operational" };
  }

  // ---------- Tooltip ----------
  const tip = document.createElement("div");
  tip.className = "tip";
  tip.setAttribute("role", "tooltip");
  tip.hidden = true;
  document.body.appendChild(tip);
  let anchor = null;

  function place(el) {
    const r = el.getBoundingClientRect();
    const t = tip.getBoundingClientRect();
    const left = Math.max(8, Math.min(r.left + r.width / 2 - t.width / 2, window.innerWidth - t.width - 8));
    let top = r.top - t.height - 10;
    if (top < 8) {
      top = r.bottom + 10;
    }
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  }

  function show(el) {
    anchor = el;
    tip.replaceChildren();
    const title = document.createElement("div");
    title.className = "tip-title";
    if (el.dataset.tipKey) {
      const key = document.createElement("i");
      key.className = `tip-key ${el.dataset.tipKey}`;
      title.appendChild(key);
    }
    title.appendChild(document.createTextNode(el.dataset.tipTitle || ""));
    tip.appendChild(title);
    for (const line of (el.dataset.tipBody || "").split("\n")) {
      if (line) {
        const row = document.createElement("div");
        row.className = "tip-line";
        row.textContent = line;
        tip.appendChild(row);
      }
    }
    tip.hidden = false;
    place(el);
  }

  function hide() {
    anchor = null;
    tip.hidden = true;
  }

  document.addEventListener("pointerover", (event) => {
    const el = event.target.closest?.("[data-tip-title]");
    if (el) {
      show(el);
    } else if (anchor) {
      hide();
    }
  });
  document.addEventListener("focusin", (event) => {
    const el = event.target.closest?.("[data-tip-title]");
    if (el) {
      show(el);
    }
  });
  document.addEventListener("focusout", hide);
  document.addEventListener("pointerleave", hide);
  window.addEventListener("scroll", hide, { passive: true });

  // ---------- Sidebar status for History / Info ----------
  async function pollStatus() {
    try {
      const response = await fetch("/api/public", { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      const state = overallState(data.counts);
      setStatus(state.level, state.short);
      if (lastCycle && data.last_cycle_at) {
        lastCycle.textContent = new Date(data.last_cycle_at).toLocaleTimeString([], { hour12: false });
      }
    } catch {
      setStatus("critical", "Monitor unreachable");
    }
  }

  tickClock();
  setInterval(tickClock, 1000);
  if (document.body.hasAttribute("data-status-feed")) {
    pollStatus();
    setInterval(pollStatus, 15000);
  }

  window.consoleShell = { setStatus, overallState, hideTip: hide };
})();
