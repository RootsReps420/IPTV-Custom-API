/* /watch player: Xtream catalogue + HLS/mpegts.js against same-origin /api/player.
 *
 * Site login cookie, then Live / Movies / Series lists from proxied player_api.
 * Playback: live is MPEG-TS (mpegts.js, low-latency). VOD tries the panel extension first.
 * for the 5-slot limiter. Panel user/pass never appear in this file.
 */

const loginPanel = document.getElementById("login-panel");
const appPanel = document.getElementById("app-panel");
const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const slotStat = document.getElementById("slot-stat");
const userStat = document.getElementById("user-stat");
const guideStat = document.getElementById("guide-stat");
const banner = document.getElementById("watch-banner");
const syncPanel = document.getElementById("watch-sync");
const syncLabel = document.getElementById("watch-sync-label");
const syncEta = document.getElementById("watch-sync-eta");
const syncFill = document.getElementById("watch-sync-fill");
const syncDetail = document.getElementById("watch-sync-detail");
const refreshPlaylistBtn = document.getElementById("refresh-playlist-btn");
const refreshEpgBtn = document.getElementById("refresh-epg-btn");
const video = document.getElementById("player");
const nowTitle = document.getElementById("now-title");
const nowEpg = document.getElementById("now-epg");
const nowNext = document.getElementById("now-next");
const nowClock = document.getElementById("now-clock");
const nowProgressWrap = document.getElementById("now-progress-wrap");
const nowProgress = document.getElementById("now-progress");
const categoryList = document.getElementById("category-list");
const itemList = document.getElementById("item-list");
const seriesPanel = document.getElementById("series-panel");
const searchEl = document.getElementById("watch-search");
const searchBtn = document.getElementById("search-btn");
const liveBadge = document.getElementById("live-badge");
const bufferRow = document.getElementById("buffer-row");
const watchSpinner = document.getElementById("watch-spinner");

/* Seconds of MPEG-TS to hold before/during play, like TiviMate Small/Medium/Large. */
const BUFFER_PROFILES = {
  small: { target: 2.5, low: 0.7, stash: 384 * 1024 },
  medium: { target: 6, low: 1.5, stash: 768 * 1024 },
  large: { target: 12, low: 3, stash: 1536 * 1024 },
};

function playId() {
  // One UUID per tab so two tabs from the same friend consume two panel slots.
  let id = sessionStorage.getItem("watch_play_id");
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem("watch_play_id", id);
  }
  return id;
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function apiError(data, fallback) {
  if (typeof data?.detail === "string") {
    return data.detail;
  }
  if (Array.isArray(data?.detail) && data.detail.length) {
    return data.detail.map((item) => item.msg || item).join("; ");
  }
  return fallback;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(apiError(data, `HTTP ${response.status}`));
    error.status = response.status;
    throw error;
  }
  return data;
}

const state = {
  user: null,
  configured: false,
  tab: "live",
  categories: [],
  categoryId: "",
  items: [],
  seriesDetail: null,
  playingLiveId: "",
  playingItem: null,
  wasSyncing: false,
  epgTries: 0,
  searchKind: "all",
  searchHits: { live: [], movies: [], series: [] },
  syncBusy: false,
};

let hls = null;
let tsPlayer = null;
let beatTimer = null;
let liveTimer = null;
let playing = false;
let playGen = 0;
let itemsGen = 0;
let searchGen = 0;
let searchTimer = null;
let liveHold = false;
let liveMpeg = false;
let vodRuntimeSec = null;

function bufferKey() {
  const key = localStorage.getItem("watch_buffer") || "medium";
  return BUFFER_PROFILES[key] ? key : "medium";
}

function bufferProfile() {
  return BUFFER_PROFILES[bufferKey()];
}

function paintBufferButtons() {
  if (!bufferRow) {
    return;
  }
  const key = bufferKey();
  bufferRow.querySelectorAll("[data-buf]").forEach((button) => {
    button.classList.toggle("is-here", button.getAttribute("data-buf") === key);
  });
}

function bufferedAhead() {
  if (!video.buffered.length) {
    return 0;
  }
  return Math.max(0, video.buffered.end(video.buffered.length - 1) - video.currentTime);
}

function showWatchSpinner(on) {
  if (!watchSpinner) {
    return;
  }
  watchSpinner.hidden = !on;
}

function stopLiveWatch() {
  liveHold = false;
  liveMpeg = false;
  showWatchSpinner(false);
  if (liveTimer) {
    clearInterval(liveTimer);
    liveTimer = null;
  }
}

function paintLiveBadge() {
  if (!liveBadge) {
    return;
  }
  if (!playing || !state.playingLiveId) {
    liveBadge.hidden = true;
    return;
  }
  liveBadge.hidden = false;
  if (liveHold || video.readyState < 2) {
    liveBadge.textContent = "BUFFERING";
    liveBadge.classList.add("is-behind");
    return;
  }
  liveBadge.textContent = "LIVE";
  liveBadge.classList.remove("is-behind");
}

function tickLiveBuffer() {
  if (!playing || !state.playingLiveId || !liveMpeg || !tsPlayer) {
    return;
  }
  if (video.seeking) {
    paintLiveBadge();
    return;
  }
  const { target, low } = bufferProfile();
  const ahead = bufferedAhead();
  const needFill = ahead < low || (liveHold && ahead < target);
  if (needFill) {
    liveHold = true;
    showWatchSpinner(true);
    if (!video.paused) {
      video.pause();
    }
    paintLiveBadge();
    return;
  }
  liveHold = false;
  showWatchSpinner(false);
  if (video.paused) {
    playNow();
  }
  paintLiveBadge();
}

function startLiveWatch() {
  stopLiveWatch();
  liveMpeg = true;
  liveHold = true;
  showWatchSpinner(true);
  paintLiveBadge();
  liveTimer = setInterval(tickLiveBuffer, 250);
  tickLiveBuffer();
}

function applyBufferSize() {
  paintBufferButtons();
  if (!liveMpeg || !tsPlayer) {
    return;
  }
  const target = bufferProfile().target;
  const ahead = bufferedAhead();
  if (ahead > target + 1.5 && video.buffered.length) {
    const end = video.buffered.end(video.buffered.length - 1);
    try {
      video.currentTime = Math.max(0, end - target);
    } catch {
      /* ignore */
    }
  } else if (ahead < target) {
    liveHold = true;
  }
  tickLiveBuffer();
}

function formatClock() {
  return new Date().toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatTime(ts) {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) {
    return "";
  }
  return new Date(n * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function parseRuntime(value, { seconds } = {}) {
  if (value == null || value === "") {
    return null;
  }
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    if (seconds || value >= 1000) {
      return Math.round(value);
    }
    return Math.round(value * 60);
  }
  const text = String(value).trim();
  if (!text || text === "0" || text === "00:00" || text === "00:00:00") {
    return null;
  }
  if (/^\d+(\.\d+)?$/.test(text)) {
    const n = Number(text);
    if (!Number.isFinite(n) || n <= 0) {
      return null;
    }
    if (seconds || n >= 1000) {
      return Math.round(n);
    }
    return Math.round(n * 60);
  }
  const parts = text.split(":").map((part) => Number(part));
  if (parts.some((part) => !Number.isFinite(part) || part < 0)) {
    return null;
  }
  if (parts.length === 3) {
    return Math.round(parts[0] * 3600 + parts[1] * 60 + parts[2]);
  }
  if (parts.length === 2) {
    return Math.round(parts[0] * 60 + parts[1]);
  }
  return null;
}

function formatRuntime(seconds) {
  const n = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(n / 3600);
  const mins = Math.floor((n % 3600) / 60);
  const secs = n % 60;
  if (hours > 0) {
    return `${hours}:${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

function paintVodRuntime() {
  if (!vodRuntimeSec || state.playingLiveId) {
    return;
  }
  const played = Math.max(0, video.currentTime || 0);
  if (nowNext) {
    nowNext.textContent = `${formatRuntime(played)} / ${formatRuntime(vodRuntimeSec)}`;
  }
  if (nowProgressWrap && nowProgress) {
    nowProgressWrap.hidden = false;
    nowProgress.style.width = `${Math.min(100, (played / vodRuntimeSec) * 100)}%`;
  }
}

function setVodRuntime(seconds) {
  const n = Number(seconds);
  if (!Number.isFinite(n) || n <= 0) {
    return;
  }
  vodRuntimeSec = n;
  paintVodRuntime();
}

function clearVodRuntime() {
  vodRuntimeSec = null;
}

function progressPct(start, stop) {
  const a = Number(start);
  const b = Number(stop);
  if (!Number.isFinite(a) || !Number.isFinite(b) || b <= a) {
    return 0;
  }
  return Math.min(100, Math.max(0, ((Date.now() / 1000 - a) / (b - a)) * 100));
}

function setProgress(start, stop) {
  const pct = progressPct(start, stop);
  if (!nowProgressWrap || !nowProgress) {
    return;
  }
  if (pct <= 0) {
    nowProgressWrap.hidden = true;
    return;
  }
  nowProgressWrap.hidden = false;
  nowProgress.style.width = `${pct}%`;
}

function tickClock() {
  if (nowClock) {
    nowClock.textContent = formatClock();
  }
}

tickClock();
setInterval(tickClock, 15000);

function setPreview(item, extra) {
  const now = extra?.now || item?.now_title || "";
  const next = extra?.next || item?.next_title || "";
  const start = extra?.start || item?.now_start;
  const stop = extra?.stop || item?.now_stop;
  nowTitle.textContent = item?.name || extra?.title || "Select a channel";
  const times = [formatTime(start), formatTime(stop)].filter(Boolean).join(" – ");
  nowEpg.textContent = [now, times].filter(Boolean).join(" · ") || extra?.fallback || "";
  nowNext.textContent = next ? `Next: ${next}` : "";
  setProgress(start, stop);
}

function showBanner(text, kind) {
  if (!text) {
    banner.hidden = true;
    banner.textContent = "";
    banner.className = "watch-banner";
    return;
  }
  banner.hidden = false;
  banner.textContent = text;
  banner.className = `watch-banner ${kind || ""}`;
}

function formatEta(seconds) {
  const n = Number(seconds);
  if (!Number.isFinite(n) || n <= 0) {
    return "calculating…";
  }
  if (n < 75) {
    return `~${Math.max(10, Math.round(n / 5) * 5)}s left`;
  }
  if (n < 3600) {
    return `~${Math.round(n / 60)} min left`;
  }
  const hours = Math.floor(n / 3600);
  const mins = Math.round((n % 3600) / 60);
  return `~${hours}h ${mins}m left`;
}

function formatElapsed(seconds) {
  const n = Number(seconds);
  if (!Number.isFinite(n) || n < 0) {
    return "";
  }
  if (n < 60) {
    return `${n}s elapsed`;
  }
  return `${Math.floor(n / 60)}m ${String(n % 60).padStart(2, "0")}s elapsed`;
}

function phaseLabel(phase) {
  if (phase === "live") {
    return "Live groups";
  }
  if (phase === "epg") {
    return "EPG";
  }
  if (phase === "movies") {
    return "Movies";
  }
  if (phase === "series") {
    return "Shows";
  }
  return "Guide";
}

function renderSyncPanel(sync) {
  if (!syncPanel) {
    return;
  }
  if (sync?.running) {
    syncPanel.hidden = false;
    syncPanel.className = "watch-sync";
    const done = Number(sync.phase_done) || 0;
    const total = Number(sync.phase_total) || 0;
    const counts = total ? ` ${done}/${total}` : "";
    syncLabel.textContent = `Syncing ${phaseLabel(sync.phase)}${counts}`;
    const etaBits = [formatElapsed(sync.elapsed_seconds), formatEta(sync.eta_seconds)].filter(Boolean);
    syncEta.textContent = etaBits.join(" · ");
    const pct = Math.max(2, Math.min(100, Number(sync.percent) || 0));
    if (syncFill) {
      syncFill.style.width = `${pct}%`;
    }
    const inflight = Array.isArray(sync.inflight) ? sync.inflight.filter(Boolean) : [];
    if (sync.phase === "epg") {
      syncDetail.textContent = sync.progress || "Downloading XMLTV from the panel…";
    } else {
      const current = inflight.length ? inflight.join(" · ") : sync.phase_item || sync.progress || "";
      syncDetail.textContent = current
        ? `Now: ${current}`
        : "Working… programme titles appear when EPG finishes.";
    }
    return;
  }
  if (sync?.last_error && !(Number(sync.epg_channels) > 0)) {
    syncPanel.hidden = false;
    syncPanel.className = "watch-sync is-bad";
    syncLabel.textContent = "Guide sync issue";
    syncEta.textContent = "";
    if (syncFill) {
      syncFill.style.width = "100%";
    }
    syncDetail.textContent = sync.last_error;
    return;
  }
  syncPanel.hidden = true;
}

function setRefreshEnabled(enabled) {
  const on = !!enabled;
  if (refreshPlaylistBtn) {
    refreshPlaylistBtn.disabled = !on;
  }
  if (refreshEpgBtn) {
    refreshEpgBtn.disabled = !on;
  }
}

function setGuide(sync) {
  renderSyncPanel(sync);
  const canRefresh = state.configured && !state.syncBusy && !sync?.running;
  setRefreshEnabled(canRefresh);
  if (!guideStat) {
    return;
  }
  if (!sync) {
    guideStat.textContent = "—";
    return;
  }
  if (sync.running) {
    const eta = formatEta(sync.eta_seconds);
    const counts =
      sync.phase_total != null && Number(sync.phase_total) > 0
        ? `${sync.phase_done || 0}/${sync.phase_total}`
        : "";
    guideStat.textContent = [counts || "syncing", eta !== "calculating…" ? eta : ""].filter(Boolean).join(" · ");
    return;
  }
  if (!sync.ready) {
    guideStat.textContent = "not ready";
    return;
  }
  const age = Number(sync.age_seconds);
  let extra;
  if (!Number.isFinite(age)) {
    extra = `${sync.streams || 0} ch`;
  } else if (age < 120) {
    extra = "just now";
  } else if (age < 3600) {
    extra = `${Math.floor(age / 60)}m ago`;
  } else {
    extra = `${Math.floor(age / 3600)}h ago`;
  }
  const epg = Number(sync.epg_channels);
  const epgBit = Number.isFinite(epg) && epg > 0 ? ` · ${epg} EPG` : "";
  guideStat.textContent = `${extra}${epgBit}`;
}

let guideTimer = null;
let guidePollMs = 0;

async function tickGuide() {
  try {
    const me = await api("/api/watch/me");
    setSlots(me.slots);
    const running = !!me.sync?.running;
    if (running) {
      state.wasSyncing = true;
    }
    setGuide(me.sync);
    if (state.wasSyncing && me.sync?.ready && !running) {
      state.wasSyncing = false;
      showBanner("");
      await loadCategories();
      if (state.categoryId) {
        await loadItems();
      }
    }
    const want = running ? 2000 : 8000;
    if (want !== guidePollMs) {
      startGuidePoll(want);
    }
  } catch {
    /* ignore */
  }
}

function startGuidePoll(ms) {
  const interval = ms || 2000;
  if (guideTimer && guidePollMs === interval) {
    return;
  }
  if (guideTimer) {
    clearInterval(guideTimer);
  }
  guidePollMs = interval;
  guideTimer = setInterval(tickGuide, interval);
}

function setSlots(slots) {
  if (!slots) {
    slotStat.textContent = "—";
    return;
  }
  slotStat.textContent = `${slots.used}/${slots.max}`;
}

function showLogin() {
  loginPanel.hidden = false;
  appPanel.hidden = true;
}

function showApp() {
  loginPanel.hidden = true;
  appPanel.hidden = false;
}

function destroyPlayers() {
  if (hls) {
    hls.destroy();
    hls = null;
  }
  if (tsPlayer) {
    try {
      tsPlayer.pause();
      tsPlayer.unload();
      tsPlayer.detachMediaElement();
      tsPlayer.destroy();
    } catch {
      /* ignore */
    }
    tsPlayer = null;
  }
  video.pause();
  video.removeAttribute("src");
  video.load();
}

function stopPlayback() {
  playing = false;
  stopLiveWatch();
  showWatchSpinner(false);
  if (beatTimer) {
    clearInterval(beatTimer);
    beatTimer = null;
  }
  if (liveBadge) {
    liveBadge.hidden = true;
  }
  destroyPlayers();
}

async function releaseSlot() {
  try {
    const data = await api("/api/player/slot/release", {
      method: "POST",
      body: JSON.stringify({ play_id: playId() }),
    });
    setSlots(data.slots);
  } catch {
    /* ignore */
  }
}

async function heartbeat() {
  const data = await api("/api/player/slot/heartbeat", {
    method: "POST",
    body: JSON.stringify({ play_id: playId() }),
  });
  setSlots(data.slots);
}

function startHeartbeat() {
  if (beatTimer) {
    clearInterval(beatTimer);
  }
  beatTimer = setInterval(() => {
    heartbeat().catch((error) => {
      showBanner(error.message, "bad");
    });
  }, 20000);
}

function mediaUrl(kind, streamId, ext) {
  return `/api/player/media/${kind}/${encodeURIComponent(streamId)}.${ext}?sid=${encodeURIComponent(playId())}`;
}

function attachHls(url) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => done(false, new Error("HLS timeout")), 12000);
    const done = (ok, value) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      if (ok) {
        resolve(value);
      } else {
        reject(value);
      }
    };
    if (!window.Hls || !window.Hls.isSupported()) {
      if (video.canPlayType("application/vnd.apple.mpegurl")) {
        video.src = url;
        done(true, "native");
        return;
      }
      done(false, new Error("HLS is not supported in this browser."));
      return;
    }
    hls = new window.Hls({
      xhrSetup(xhr) {
        xhr.withCredentials = true;
      },
    });
    const onError = (_event, info) => {
      if (info?.fatal) {
        hls.off(window.Hls.Events.ERROR, onError);
        done(false, new Error("HLS failed"));
      }
    };
    hls.on(window.Hls.Events.ERROR, onError);
    hls.on(window.Hls.Events.MANIFEST_PARSED, () => done(true, "hls"));
    hls.loadSource(url);
    hls.attachMedia(video);
  });
}

function playNow() {
  video.muted = false;
  video.defaultMuted = false;
  if (!Number.isFinite(video.volume) || video.volume === 0) {
    video.volume = 1;
  }
  const p = video.play();
  if (p && typeof p.catch === "function") {
    p.catch((error) => {
      if (error && error.name === "AbortError") {
        return;
      }
    });
  }
}

function attachMpegTs(url, gen, live) {
  if (!window.mpegts || !window.mpegts.getFeatureList().mseLivePlayback) {
    throw new Error("MPEG-TS playback is not supported in this browser. Use Chrome or Edge.");
  }
  const buf = bufferProfile();
  tsPlayer = window.mpegts.createPlayer(
    {
      type: "mpegts",
      isLive: Boolean(live),
      hasAudio: true,
      hasVideo: true,
      url,
      withCredentials: true,
    },
    {
      enableWorker: false,
      enableStashBuffer: true,
      stashInitialSize: buf.stash,
      isLive: Boolean(live),
      liveBufferLatencyChasing: false,
      liveSync: false,
      autoCleanupSourceBuffer: true,
      autoCleanupMaxBackwardDuration: 90,
      autoCleanupMinBackwardDuration: 20,
      lazyLoad: false,
      deferLoadAfterSourceOpen: false,
      fixAudioTimestampGap: true,
    }
  );
  if (window.mpegts.Events) {
    tsPlayer.on(window.mpegts.Events.ERROR, (_type, detail) => {
      if (gen !== playGen) {
        return;
      }
      const raw = detail?.msg || detail?.code || "Stream error";
      const msg = String(raw);
      if (/network|http|status|eof|unrecoverable/i.test(msg)) {
        showBanner("Could not play this channel. If the portal is blocked, failover will pick a new DNS shortly.", "bad");
      } else {
        showBanner(msg, "bad");
      }
    });
  }
  tsPlayer.attachMediaElement(video);
  tsPlayer.load();
  playNow();
  if (live) {
    startLiveWatch();
  }
}

async function playSources(kind, streamId, extensions, gen) {
  // Start the player in this turn (keep the click's autoplay gesture). Heartbeat is not on the critical path.
  const keepItem = state.playingItem;
  const keepLive = state.playingLiveId;
  stopPlayback();
  state.playingItem = keepItem;
  state.playingLiveId = keepLive;
  if (gen != null && gen !== playGen) {
    return;
  }
  playing = true;
  startHeartbeat();
  heartbeat().catch((error) => {
    if (gen != null && gen !== playGen) {
      return;
    }
    showBanner(error.message, "bad");
  });
  let lastError = null;
  for (const ext of extensions) {
    if (gen != null && gen !== playGen) {
      return;
    }
    const url = mediaUrl(kind, streamId, ext);
    try {
      if (ext === "m3u8") {
        await attachHls(url);
        if (gen != null && gen !== playGen) {
          return;
        }
        playNow();
      } else if (ext === "ts") {
        attachMpegTs(url, gen, kind === "live");
        if (kind === "live") {
          return;
        }
        await video.play().catch((error) => {
          if (error && error.name === "AbortError") {
            return;
          }
          throw error;
        });
      } else {
        video.src = url;
        video.muted = false;
        video.defaultMuted = false;
        video.volume = 1;
        if (kind !== "live") {
          showWatchSpinner(true);
        }
        try {
          playNow();
          if (kind !== "live") {
            await video.play().catch((error) => {
              if (error && error.name === "AbortError") {
                return;
              }
              throw error;
            });
          }
        } finally {
          if (kind !== "live") {
            showWatchSpinner(false);
          }
        }
      }
      return;
    } catch (error) {
      lastError = error;
      destroyPlayers();
    }
  }
  if (gen != null && gen !== playGen) {
    return;
  }
  playing = false;
  if (beatTimer) {
    clearInterval(beatTimer);
    beatTimer = null;
  }
  await releaseSlot();
  throw lastError || new Error("Playback failed.");
}

function playLive(item) {
  const gen = ++playGen;
  clearVodRuntime();
  state.playingLiveId = String(item.stream_id);
  state.playingItem = item;
  setPreview(item, { fallback: "Starting…" });
  showBanner("");
  try {
    playSources("live", String(item.stream_id), ["ts"], gen).catch((error) => {
      if (gen !== playGen) {
        return;
      }
      showBanner(error.message, "bad");
    });
  } catch (error) {
    if (gen !== playGen) {
      return;
    }
    showBanner(error.message, "bad");
    return;
  }
  api(`/api/player/live/epg?stream_id=${encodeURIComponent(item.stream_id)}`)
    .then((data) => {
      if (gen !== playGen) {
        return;
      }
      const rows = data.epg || [];
      const current = rows[0] || {};
      const upcoming = rows[1] || {};
      const nowTitleText = current.title || item.now_title || "";
      const nextTitleText = upcoming.title || item.next_title || "";
      const start = current.start_timestamp || current.start || item.now_start;
      const stop = current.stop_timestamp || current.end || item.now_stop;
      setPreview(item, {
        now: nowTitleText,
        next: nextTitleText,
        start,
        stop,
        fallback: "No programme info",
      });
      const row = state.items.find((entry) => String(entry.stream_id) === String(item.stream_id));
      if (row && nowTitleText) {
        row.now_title = nowTitleText;
        row.next_title = nextTitleText;
        if (start) {
          row.now_start = start;
        }
        if (stop) {
          row.now_stop = stop;
        }
        renderItems();
      }
    })
    .catch(() => {
      /* keep now/next from the channel list */
    });
}

async function playVod(item) {
  const gen = ++playGen;
  state.playingLiveId = "";
  const ext = String(item.container_extension || "mp4").replace(/^\./, "");
  nowTitle.textContent = item.name || `Title ${item.stream_id}`;
  nowEpg.textContent = item.plot || "";
  setProgress(0, 0);
  setVodRuntime(parseRuntime(item.duration_secs, { seconds: true }) || parseRuntime(item.duration));
  if (!vodRuntimeSec && nowNext) {
    nowNext.textContent = "Runtime…";
  }
  showBanner("");
  api(`/api/player/vod/info?vod_id=${encodeURIComponent(item.stream_id)}`)
    .then((data) => {
      if (gen !== playGen) {
        return;
      }
      const info = data.info || {};
      if (!item.plot && info.plot) {
        nowEpg.textContent = info.plot;
      }
      setVodRuntime(parseRuntime(info.duration_secs, { seconds: true }) || parseRuntime(info.duration));
    })
    .catch(() => {});
  const order = [...new Set([ext, "mp4", "m3u8", "mkv", "ts"])];
  try {
    await playSources("movie", String(item.stream_id), order, gen);
  } catch (error) {
    if (gen !== playGen) {
      return;
    }
    showBanner(error.message, "bad");
  }
}

async function playEpisode(episode, seriesName) {
  const gen = ++playGen;
  state.playingLiveId = "";
  const ext = String(episode.container_extension || "mp4").replace(/^\./, "");
  nowTitle.textContent = `${seriesName || "Series"} · ${episode.title || `Episode ${episode.episode_num}`}`;
  nowEpg.textContent = episode.plot || episode.info?.plot || "";
  setProgress(0, 0);
  setVodRuntime(
    parseRuntime(episode.duration_secs || episode.info?.duration_secs, { seconds: true }) ||
      parseRuntime(episode.duration || episode.info?.duration)
  );
  if (!vodRuntimeSec && nowNext) {
    nowNext.textContent = "Runtime…";
  }
  showBanner("");
  const order = [...new Set([ext, "mp4", "m3u8", "mkv", "ts"])];
  try {
    await playSources("series", String(episode.id), order, gen);
  } catch (error) {
    if (gen !== playGen) {
      return;
    }
    showBanner(error.message, "bad");
  }
}

function visibleItems() {
  const query = (searchEl.value || "").trim().toLowerCase();
  let rows = state.items;
  if (query && state.tab !== "search") {
    const tokens = query.split(/\s+/).filter(Boolean);
    rows = rows.filter((item) => {
      const hay = `${item.name || ""} ${item.now_title || ""} ${item.next_title || ""} ${item.plot || ""} ${item.genre || ""}`.toLowerCase();
      const compact = hay.replace(/[^a-z0-9]+/g, "");
      const joined = query.replace(/\s+/g, "");
      if (joined.length >= 2 && compact.includes(joined)) {
        return true;
      }
      return tokens.every((token) => hay.includes(token));
    });
  }
  return rows.slice(0, 800);
}

function catMark(name) {
  const words = String(name || "")
    .replace(/[^a-zA-Z0-9| ]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!words.length) {
    return "·";
  }
  if (words.length === 1) {
    return words[0].slice(0, 2);
  }
  return `${words[0][0] || ""}${words[1][0] || ""}`;
}

function renderCategories() {
  categoryList.innerHTML = state.categories
    .map((cat) => {
      const id = String(cat.category_id ?? "");
      const name = cat.category_name || id;
      const here = id === String(state.categoryId) ? " is-here" : "";
      const count =
        cat.stream_count != null && cat.stream_count !== ""
          ? ` (${esc(cat.stream_count)})`
          : "";
      return `<button type="button" class="watch-cat${here}" data-cat="${esc(id)}"><span class="watch-cat-mark">${esc(catMark(name))}</span><span>${esc(name)}${count}</span></button>`;
    })
    .join("");
}

function renderItems() {
  const rows = visibleItems();
  if (!rows.length) {
    itemList.innerHTML = `<div class="empty-events">${
      state.categoryId ? "Nothing in this group." : "Pick a group to see channels."
    }</div>`;
    return;
  }
  if (state.tab === "live") {
    itemList.innerHTML = rows
      .map((item, index) => {
        const icon = item.stream_icon
          ? `<img src="${esc(item.stream_icon)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" />`
          : `<span></span>`;
        const now = item.now_title || "";
        const epg = now
          ? `<small class="watch-item-epg">${esc(now)}</small>`
          : `<small class="watch-item-epg is-empty">No programme info</small>`;
        const pct = progressPct(item.now_start, item.now_stop);
        const bar = pct > 0 ? `<span class="watch-item-bar"><i style="width:${pct}%"></i></span>` : "";
        const here = String(item.stream_id) === String(state.playingLiveId) ? " is-here" : "";
        const num = item.num || index + 1;
        return `<button type="button" class="watch-item${here}" data-live="${esc(item.stream_id)}"><span class="watch-num">${esc(num)}</span>${icon}<span class="watch-item-body"><span class="watch-item-name">${esc(item.name)}</span>${epg}${bar}</span></button>`;
      })
      .join("");
    return;
  }
  if (state.tab === "movies") {
    itemList.innerHTML = rows
      .map((item) => {
        const poster = item.stream_icon
          ? `<img src="${esc(item.stream_icon)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" />`
          : "";
        return `<button type="button" class="watch-item poster" data-vod="${esc(item.stream_id)}">${poster}<span class="watch-item-body"><span class="watch-item-name">${esc(item.name)}</span></span></button>`;
      })
      .join("");
    return;
  }
  itemList.innerHTML = rows
    .map((item) => {
      const poster = item.cover
        ? `<img src="${esc(item.cover)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" />`
        : "";
      return `<button type="button" class="watch-item poster" data-series="${esc(item.series_id)}">${poster}<span class="watch-item-body"><span class="watch-item-name">${esc(item.name)}</span></span></button>`;
    })
    .join("");
}

function renderSeries(detail, seriesName) {
  if (!detail) {
    seriesPanel.hidden = true;
    seriesPanel.innerHTML = "";
    return;
  }
  const episodes = detail.episodes || {};
  const seasons = Object.keys(episodes).sort((a, b) => Number(a) - Number(b));
  seriesPanel.hidden = false;
  seriesPanel.innerHTML = seasons
    .map((season) => {
      const list = (episodes[season] || [])
        .map((ep) => {
          return `<button type="button" class="watch-item" data-episode="${esc(ep.id)}" data-ext="${esc(ep.container_extension || "")}" data-title="${esc(ep.title || "")}" data-plot="${esc(ep.plot || ep.info?.plot || "")}" data-duration="${esc(ep.duration || ep.info?.duration || "")}" data-duration-secs="${esc(ep.duration_secs || ep.info?.duration_secs || "")}" data-series-name="${esc(seriesName)}">E${esc(ep.episode_num ?? ep.id)} ${esc(ep.title || "")}</button>`;
        })
        .join("");
      return `<div class="watch-season"><h3>Season ${esc(season)}</h3><div class="watch-season-eps">${list}</div></div>`;
    })
    .join("");
}

function searchCounts() {
  return {
    live: state.searchHits.live.length,
    movies: state.searchHits.movies.length,
    series: state.searchHits.series.length,
  };
}

function renderSearchNav() {
  const counts = searchCounts();
  const total = counts.live + counts.movies + counts.series;
  const rows = [
    ["all", "All", total],
    ["live", "TV", counts.live],
    ["movies", "Movies", counts.movies],
    ["series", "Shows", counts.series],
  ];
  categoryList.innerHTML = rows
    .map(([id, label, count]) => {
      const here = state.searchKind === id ? " is-here" : "";
      const extra = state.searchHits.live.length || state.searchHits.movies.length || state.searchHits.series.length
        ? ` (${esc(count)})`
        : "";
      return `<button type="button" class="watch-cat${here}" data-search-kind="${id}"><span class="watch-cat-mark">${esc(label.slice(0, 2))}</span><span>${esc(label)}${extra}</span></button>`;
    })
    .join("");
}

function searchRowLive(item, index) {
  const icon = item.stream_icon
    ? `<img src="${esc(item.stream_icon)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" />`
    : `<span></span>`;
  const now = item.now_title || "";
  const epg = now
    ? `<small class="watch-item-epg">${esc(now)}</small>`
    : `<small class="watch-item-epg">${esc(item.category_name || item.match || "Live")}</small>`;
  const here = String(item.stream_id) === String(state.playingLiveId) ? " is-here" : "";
  const num = item.num || index + 1;
  return `<button type="button" class="watch-item${here}" data-live="${esc(item.stream_id)}"><span class="watch-num">${esc(num)}</span>${icon}<span class="watch-item-body"><span class="watch-item-name">${esc(item.name)}</span>${epg}</span></button>`;
}

function searchRowMovie(item) {
  const poster = item.stream_icon
    ? `<img src="${esc(item.stream_icon)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" />`
    : "";
  const meta = item.match || item.category_name || item.genre || "Movie";
  return `<button type="button" class="watch-item poster" data-vod="${esc(item.stream_id)}">${poster}<span class="watch-item-body"><span class="watch-item-name">${esc(item.name)}</span><small class="watch-item-epg">${esc(meta)}</small></span></button>`;
}

function searchRowSeries(item) {
  const poster = item.cover
    ? `<img src="${esc(item.cover)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" />`
    : "";
  const meta = item.match || item.category_name || item.genre || "Show";
  return `<button type="button" class="watch-item poster" data-series="${esc(item.series_id)}">${poster}<span class="watch-item-body"><span class="watch-item-name">${esc(item.name)}</span><small class="watch-item-epg">${esc(meta)}</small></span></button>`;
}

function renderSearchResults() {
  const q = (searchEl.value || "").trim();
  if (q.length < 2) {
    itemList.innerHTML = `<div class="empty-events">Type at least two letters. Matches live channels, movies, and shows — names, what’s on now, plot, and genre.</div>`;
    renderSearchNav();
    return;
  }
  const kind = state.searchKind;
  const live = kind === "all" || kind === "live" ? state.searchHits.live : [];
  const movies = kind === "all" || kind === "movies" ? state.searchHits.movies : [];
  const series = kind === "all" || kind === "series" ? state.searchHits.series : [];
  if (!live.length && !movies.length && !series.length) {
    itemList.innerHTML = `<div class="empty-events">No matches for “${esc(q)}”.</div>`;
    renderSearchNav();
    return;
  }
  const parts = [];
  if (live.length) {
    parts.push(`<div class="watch-search-group"><strong>TV</strong><span>${esc(live.length)}</span></div>`);
    parts.push(live.map((item, index) => searchRowLive(item, index)).join(""));
  }
  if (movies.length) {
    parts.push(`<div class="watch-search-group"><strong>Movies</strong><span>${esc(movies.length)}</span></div>`);
    parts.push(movies.map((item) => searchRowMovie(item)).join(""));
  }
  if (series.length) {
    parts.push(`<div class="watch-search-group"><strong>Shows</strong><span>${esc(series.length)}</span></div>`);
    parts.push(series.map((item) => searchRowSeries(item)).join(""));
  }
  itemList.innerHTML = parts.join("");
  renderSearchNav();
}

async function runSearch() {
  if (state.tab !== "search") {
    return;
  }
  const q = (searchEl.value || "").trim();
  const gen = ++searchGen;
  seriesPanel.hidden = true;
  if (q.length < 2) {
    state.searchHits = { live: [], movies: [], series: [] };
    renderSearchResults();
    return;
  }
  itemList.innerHTML = `<div class="empty-events">Searching…</div>`;
  try {
    const data = await api(`/api/player/search?q=${encodeURIComponent(q)}`);
    if (gen !== searchGen || state.tab !== "search") {
      return;
    }
    state.searchHits = {
      live: data.live || [],
      movies: data.movies || [],
      series: data.series || [],
    };
    renderSearchResults();
  } catch (error) {
    if (gen !== searchGen) {
      return;
    }
    itemList.innerHTML = `<div class="empty-events">${esc(error.message)}</div>`;
  }
}

function queueSearch() {
  if (searchTimer) {
    clearTimeout(searchTimer);
  }
  searchTimer = setTimeout(() => {
    runSearch().catch(() => {});
  }, 220);
}

function findSearchItem(kind, id) {
  if (kind === "live") {
    return state.searchHits.live.find((row) => String(row.stream_id) === String(id));
  }
  if (kind === "movie") {
    return state.searchHits.movies.find((row) => String(row.stream_id) === String(id));
  }
  return state.searchHits.series.find((row) => String(row.series_id) === String(id));
}

async function loadCategories() {
  searchEl.placeholder = "Filter this group…";
  const kind = state.tab === "movies" ? "vod" : state.tab === "series" ? "series" : "live";
  const path =
    kind === "live"
      ? "/api/player/live/categories"
      : kind === "vod"
        ? "/api/player/vod/categories"
        : "/api/player/series/categories";
  categoryList.innerHTML = `<div class="empty-events">Loading categories…</div>`;
  itemList.innerHTML = `<div class="empty-events">Loading…</div>`;
  const data = await api(path);
  state.categories = data.categories || [];
  state.categoryId = "";
  renderCategories();
  if (!state.categories.length) {
    const me = await api("/api/watch/me").catch(() => ({}));
    setGuide(me.sync);
    if (me.sync?.running) {
      itemList.innerHTML = `<div class="empty-events">Downloading the full channel guide. This can take a few minutes, then every group is instant.</div>`;
    } else {
      itemList.innerHTML = `<div class="empty-events">No categories from the panel.</div>`;
    }
    return;
  }
  itemList.innerHTML = `<div class="empty-events">Pick a group. Channels and what's on now show in the list; click one for a live preview.</div>`;
}

async function loadItems(opts) {
  seriesPanel.hidden = true;
  const kind = state.tab;
  const refresh = !!opts?.epgRefresh;
  if (!refresh) {
    itemsGen += 1;
    state.epgTries = 0;
  }
  const gen = itemsGen;
  const categoryId = state.categoryId;
  if (kind === "live") {
    const data = await api(
      `/api/player/live/streams?category_id=${encodeURIComponent(categoryId)}`
    );
    if (gen !== itemsGen) {
      return;
    }
    state.items = data.streams || [];
  } else if (kind === "movies") {
    const data = await api(
      `/api/player/vod/streams?category_id=${encodeURIComponent(categoryId)}`
    );
    if (gen !== itemsGen) {
      return;
    }
    state.items = data.streams || [];
  } else {
    const data = await api(
      `/api/player/series/list?category_id=${encodeURIComponent(categoryId)}`
    );
    if (gen !== itemsGen) {
      return;
    }
    state.items = data.series || [];
  }
  renderItems();
  if (kind === "live") {
    const missing = state.items.filter((item) => !item.now_title).length;
    if (missing > 0 && (state.epgTries || 0) < 3) {
      state.epgTries = (state.epgTries || 0) + 1;
      window.setTimeout(() => {
        if (gen === itemsGen && state.tab === "live" && state.categoryId === categoryId) {
          loadItems({ epgRefresh: true }).catch(() => {});
        }
      }, 1800);
    }
  }
}

async function boot() {
  try {
    const me = await api("/api/watch/me");
    setSlots(me.slots);
    if (!me.username) {
      showLogin();
      return;
    }
    state.user = me.username;
    state.configured = me.configured;
    userStat.textContent = me.username;
    setGuide(me.sync);
    showApp();
    paintBufferButtons();
    if (!me.configured) {
      showBanner(
        "Watch is signed in, but config/player.yaml has no Xtream DNS / username / password yet.",
        "warn"
      );
      return;
    }
    if (me.sync?.running) {
      state.wasSyncing = true;
    }
    startGuidePoll(me.sync?.running ? 2000 : 8000);
    try {
      await loadCategories();
    } catch (error) {
      showBanner(error.message, "bad");
      itemList.innerHTML = `<div class="empty-events">${esc(error.message)}</div>`;
    }
  } catch (error) {
    showLogin();
    loginError.hidden = false;
    loginError.textContent = error.message;
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.hidden = true;
  try {
    await api("/api/watch/login", {
      method: "POST",
      body: JSON.stringify({
        username: document.getElementById("login-user").value,
        password: document.getElementById("login-pass").value,
      }),
    });
    await boot();
  } catch (error) {
    loginError.hidden = false;
    loginError.textContent = error.message;
  }
});

async function requestSync(kind) {
  if (state.syncBusy || !state.configured) {
    return;
  }
  state.syncBusy = true;
  setRefreshEnabled(false);
  try {
    await api("/api/player/sync", {
      method: "POST",
      body: JSON.stringify({ kind }),
    });
    state.wasSyncing = true;
    showBanner(kind === "epg" ? "EPG refresh queued…" : "Playlist refresh queued…");
    startGuidePoll(2000);
  } catch (error) {
    showBanner(error.message, "bad");
  } finally {
    state.syncBusy = false;
    await tickGuide();
  }
}

document.getElementById("logout-btn").addEventListener("click", async () => {
  state.playingItem = null;
  state.playingLiveId = "";
  stopPlayback();
  try {
    await api("/api/watch/logout", {
      method: "POST",
      body: JSON.stringify({ play_id: playId() }),
    });
  } catch {
    /* ignore */
  }
  showLogin();
});

if (refreshPlaylistBtn) {
  refreshPlaylistBtn.addEventListener("click", () => requestSync("playlist"));
}
if (refreshEpgBtn) {
  refreshEpgBtn.addEventListener("click", () => requestSync("epg"));
}

document.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", async () => {
    document.querySelectorAll("[data-tab]").forEach((item) => {
      item.classList.toggle("is-here", item === button);
    });
    state.tab = button.getAttribute("data-tab") || "live";
    showBanner("");
    seriesPanel.hidden = true;
    if (state.tab === "search") {
      searchEl.placeholder = "Search live, movies and shows…";
      renderSearchNav();
      renderSearchResults();
      searchEl.focus();
      if ((searchEl.value || "").trim().length >= 2) {
        await runSearch();
      }
      return;
    }
    try {
      await loadCategories();
    } catch (error) {
      showBanner(error.message, "bad");
    }
  });
});

categoryList.addEventListener("click", async (event) => {
  const kindBtn = event.target.closest("[data-search-kind]");
  if (kindBtn) {
    state.searchKind = kindBtn.getAttribute("data-search-kind") || "all";
    renderSearchResults();
    return;
  }
  const button = event.target.closest("[data-cat]");
  if (!button) {
    return;
  }
  state.categoryId = button.getAttribute("data-cat") || "";
  renderCategories();
  try {
    await loadItems();
  } catch (error) {
    showBanner(error.message, "bad");
  }
});

itemList.addEventListener("click", async (event) => {
  const live = event.target.closest("[data-live]");
  if (live) {
    const id = live.getAttribute("data-live");
    const item = state.items.find((row) => String(row.stream_id) === String(id)) || findSearchItem("live", id);
    if (item) {
      localStorage.setItem("watch_last_live", String(id));
      state.playingLiveId = String(id);
      itemList.querySelectorAll(".watch-item[data-live]").forEach((el) => {
        el.classList.toggle("is-here", el.getAttribute("data-live") === String(id));
      });
      playLive(item);
    }
    return;
  }
  const vod = event.target.closest("[data-vod]");
  if (vod) {
    const id = vod.getAttribute("data-vod");
    const item = state.items.find((row) => String(row.stream_id) === String(id)) || findSearchItem("movie", id);
    if (item) {
      await playVod(item);
    }
    return;
  }
  const series = event.target.closest("[data-series]");
  if (series) {
    const id = series.getAttribute("data-series");
    const item = state.items.find((row) => String(row.series_id) === String(id)) || findSearchItem("series", id);
    try {
      const detail = await api(`/api/player/series/info?series_id=${encodeURIComponent(id)}`);
      renderSeries(detail, item?.name || "");
    } catch (error) {
      showBanner(error.message, "bad");
    }
  }
});

seriesPanel.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-episode]");
  if (!button) {
    return;
  }
  await playEpisode(
    {
      id: button.getAttribute("data-episode"),
      title: button.getAttribute("data-title"),
      container_extension: button.getAttribute("data-ext"),
      plot: button.getAttribute("data-plot"),
      duration: button.getAttribute("data-duration"),
      duration_secs: button.getAttribute("data-duration-secs"),
    },
    button.getAttribute("data-series-name")
  );
});

searchEl.addEventListener("input", () => {
  if (state.tab === "search") {
    queueSearch();
    return;
  }
  renderItems();
});

searchEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && state.tab === "search") {
    event.preventDefault();
    if (searchTimer) {
      clearTimeout(searchTimer);
    }
    runSearch().catch(() => {});
  }
});

if (bufferRow) {
  bufferRow.addEventListener("click", (event) => {
    const button = event.target.closest("[data-buf]");
    if (!button) {
      return;
    }
    const key = button.getAttribute("data-buf");
    if (!BUFFER_PROFILES[key]) {
      return;
    }
    localStorage.setItem("watch_buffer", key);
    applyBufferSize();
  });
}

video.addEventListener("timeupdate", paintVodRuntime);
video.addEventListener("play", tickLiveBuffer);
video.addEventListener("playing", () => {
  if (!liveMpeg) {
    showWatchSpinner(false);
  }
  tickLiveBuffer();
});
video.addEventListener("pause", paintLiveBadge);
video.addEventListener("waiting", () => {
  if (!liveMpeg || !playing || !state.playingLiveId) {
    return;
  }
  liveHold = true;
  showWatchSpinner(true);
  paintLiveBadge();
});
video.addEventListener("ended", () => {
  if (!liveMpeg || !playing || !state.playingLiveId) {
    return;
  }
  liveHold = true;
  showWatchSpinner(true);
  paintLiveBadge();
  tickLiveBuffer();
});

window.addEventListener("pagehide", () => {
  if (playing) {
    navigator.sendBeacon?.(
      "/api/player/slot/release",
      new Blob([JSON.stringify({ play_id: playId() })], { type: "application/json" })
    );
  }
});

boot();
