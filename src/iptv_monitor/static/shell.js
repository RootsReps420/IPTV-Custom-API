/* Shared chrome for the console pages (/, /owner, /history, /key).
 * Overview: signed-in user + Sign out (/api/session, /logout; viewers lose [data-owner-only] links),
 * live clock, one hover/focus tooltip for any element with data-tip-title
 * (data-tip-body = extra lines, data-tip-key = colour key), and the sidebar status.
 * Pages without app.js (History, Info) set data-status-feed on <body>; shell.js then
 * polls /api/public for the sidebar status. app.js drives it on the Monitor page.
 * reliability(row, incidentDays(rows)) turns an /api/history row into an A–F grade
 * (shared by Monitor + History so both pages grade the same way).
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

  // ---------- Reliability grade ----------
  // From /api/history rows: share of the last 30 days on which a host had at least one outage.
  // Counting days (not outages) keeps one bad spike from sinking a host for a month, and days
  // when 75%+ of the pool failed at once are VPS-side incidents that count against nobody.
  const GRADE_WINDOW = 30;
  const INCIDENT_SHARE = 0.75;
  const GRADE_STEPS = [
    { grade: "A", maxShare: 2 / 30, text: "Very reliable" },
    { grade: "B", maxShare: 6 / 30, text: "Reliable" },
    { grade: "C", maxShare: 12 / 30, text: "Patchy" },
    { grade: "D", maxShare: 20 / 30, text: "Unreliable" },
  ];
  const GRADE_F = { grade: "F", text: "Avoid" };

  function lastDays(row) {
    return (row?.by_day || []).slice(-GRADE_WINDOW).map((n) => Number(n) || 0);
  }

  // Indexes (0 = oldest of the last 30 days) of VPS-wide incident days across the pool.
  function incidentDays(rows) {
    const pool = (rows || []).filter((row) => row.in_pool !== false);
    const skip = new Set();
    if (pool.length < 4) {
      return skip;
    }
    const failing = new Array(GRADE_WINDOW).fill(0);
    for (const row of pool) {
      lastDays(row).forEach((n, i) => {
        if (n > 0) {
          failing[i] += 1;
        }
      });
    }
    failing.forEach((n, i) => {
      if (n >= INCIDENT_SHARE * pool.length) {
        skip.add(i);
      }
    });
    return skip;
  }

  function reliability(row, skip = new Set()) {
    const days = lastDays(row);
    let counted = 0;
    let bad = 0;
    days.forEach((n, i) => {
      if (!skip.has(i)) {
        counted += 1;
        bad += n > 0 ? 1 : 0;
      }
    });
    const share = counted ? bad / counted : 0;
    const step = GRADE_STEPS.find((s) => share <= s.maxShare + 1e-9) || GRADE_F;
    return {
      grade: step.grade,
      text: step.text,
      bad,
      clean: counted - bad,
      span: counted,
      skipped: skip.size,
      skip,
      days,
      downs7: Number(row?.downs_7d) || 0,
    };
  }

  // Tooltip lines shared by cards, the signal map and History.
  function gradeTip(rel) {
    const lines = [`${rel.clean} of ${rel.span} days without an outage`];
    if (rel.skipped) {
      lines.push(`${rel.skipped} VPS-wide incident day${rel.skipped === 1 ? "" : "s"} not counted`);
    }
    lines.push(`${rel.downs7} outage${rel.downs7 === 1 ? "" : "s"} in the last 7 days`);
    return lines.join("\n");
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

  // ---------- Signed-in user ----------
  // Session gone (expired / signed out elsewhere): back to the sign-in page, then here again.
  function toSignIn() {
    location.href = `/?next=${encodeURIComponent(location.pathname + location.search)}`;
  }

  async function loadSession() {
    try {
      const response = await fetch("/api/session", { cache: "no-store" });
      if (response.status === 401) {
        toSignIn();
        return;
      }
      const data = await response.json();
      if (!data.username) {
        return;
      }
      // Viewers (Monitor + History only) do not see links the server would refuse.
      document.querySelectorAll("[data-owner-only]").forEach((el) => {
        el.hidden = data.role !== "owner";
      });
      const box = document.getElementById("side-user");
      if (box) {
        document.getElementById("side-user-name").textContent = data.username;
        document.getElementById("side-user-role").textContent = data.role === "owner" ? "Owner" : "Viewer";
        document.getElementById("side-avatar").textContent = data.username.slice(0, 1).toUpperCase();
        box.hidden = false;
      }
    } catch {
      // Offline: keep the page; the status poll reports it.
    }
  }

  document.getElementById("sign-out")?.addEventListener("click", async () => {
    try {
      await fetch("/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      location.href = "/";
    }
  });

  // ---------- Sidebar status for History / Info ----------
  async function pollStatus() {
    try {
      const response = await fetch("/api/public", { cache: "no-store" });
      if (response.status === 401) {
        toSignIn();
        return;
      }
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
  loadSession();
  if (document.body.hasAttribute("data-status-feed")) {
    pollStatus();
    setInterval(pollStatus, 15000);
  }

  window.consoleShell = { setStatus, overallState, reliability, incidentDays, gradeTip, toSignIn, hideTip: hide };
})();
