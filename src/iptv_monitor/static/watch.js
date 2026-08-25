/* /watch player: Xtream catalogue + HLS/mpegts.js against same-origin /api/player.
 *
 * Site login cookie, then Live / Movies / Series lists from proxied player_api.
 * Playback tries .m3u8 (hls.js) then .ts (mpegts.js). sid is a per-tab play_id
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
const video = document.getElementById("player");
const nowTitle = document.getElementById("now-title");
const nowEpg = document.getElementById("now-epg");
const categoryList = document.getElementById("category-list");
const itemList = document.getElementById("item-list");
const seriesPanel = document.getElementById("series-panel");
const searchEl = document.getElementById("watch-search");

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
};

let hls = null;
let tsPlayer = null;
let beatTimer = null;
let playing = false;

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

function setGuide(sync) {
  if (!guideStat) {
    return;
  }
  if (!sync) {
    guideStat.textContent = "—";
    return;
  }
  if (sync.running) {
    guideStat.textContent = sync.progress || "Updating…";
    return;
  }
  if (!sync.ready) {
    guideStat.textContent = "not ready";
    return;
  }
  const age = Number(sync.age_seconds);
  if (!Number.isFinite(age)) {
    guideStat.textContent = `${sync.streams || 0} ch`;
    return;
  }
  if (age < 120) {
    guideStat.textContent = "just now";
    return;
  }
  if (age < 3600) {
    guideStat.textContent = `${Math.floor(age / 60)}m ago`;
    return;
  }
  guideStat.textContent = `${Math.floor(age / 3600)}h ago`;
}

let guideTimer = null;

function startGuidePoll() {
  if (guideTimer) {
    return;
  }
  guideTimer = setInterval(async () => {
    try {
      const me = await api("/api/watch/me");
      setGuide(me.sync);
      if (me.sync && !me.sync.running) {
        clearInterval(guideTimer);
        guideTimer = null;
        if (me.sync.ready && state.tab === "live") {
          await loadCategories();
          showBanner("");
        }
      }
    } catch {
      /* ignore */
    }
  }, 4000);
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
  if (beatTimer) {
    clearInterval(beatTimer);
    beatTimer = null;
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

function attachMpegTs(url) {
  if (!window.mpegts || !window.mpegts.getFeatureList().mseLivePlayback) {
    throw new Error("MPEG-TS playback is not supported in this browser. Use Chrome or Edge.");
  }
  tsPlayer = window.mpegts.createPlayer(
    { type: "mse", isLive: true, url, withCredentials: true },
    { enableWorker: true, liveBufferLatencyChasing: true }
  );
  tsPlayer.attachMediaElement(video);
  tsPlayer.load();
}

async function playSources(kind, streamId, extensions) {
  // Try each container in order. Keep the slot across retries; release only if all fail.
  stopPlayback();
  await heartbeat();
  playing = true;
  startHeartbeat();
  let lastError = null;
  for (const ext of extensions) {
    const url = mediaUrl(kind, streamId, ext);
    try {
      if (ext === "m3u8") {
        await attachHls(url);
      } else if (ext === "ts") {
        attachMpegTs(url);
      } else {
        video.src = url;
      }
      await video.play();
      return;
    } catch (error) {
      lastError = error;
      destroyPlayers();
    }
  }
  playing = false;
  if (beatTimer) {
    clearInterval(beatTimer);
    beatTimer = null;
  }
  await releaseSlot();
  throw lastError || new Error("Playback failed.");
}

async function playLive(item) {
  nowTitle.textContent = item.name || `Channel ${item.stream_id}`;
  nowEpg.textContent =
    [item.now_title, item.next_title].filter(Boolean).join(" → ") || "Loading guide…";
  showBanner("");
  try {
    await playSources("live", String(item.stream_id), ["m3u8", "ts"]);
    startHeartbeat();
    playing = true;
  } catch (error) {
    showBanner(error.message, "bad");
    nowEpg.textContent = "";
    return;
  }
  try {
    const data = await api(`/api/player/live/epg?stream_id=${encodeURIComponent(item.stream_id)}`);
    const rows = data.epg || [];
    nowEpg.textContent = rows
      .slice(0, 2)
      .map((row) => row.title || "Programme")
      .join(" → ") || nowEpg.textContent || "No EPG";
  } catch {
    /* keep now/next from the channel list */
  }
}

async function playVod(item) {
  const ext = String(item.container_extension || "mp4").replace(/^\./, "");
  nowTitle.textContent = item.name || `Title ${item.stream_id}`;
  nowEpg.textContent = item.plot || "";
  showBanner("");
  const order = [...new Set([ext, "mp4", "m3u8", "mkv", "ts"])];
  try {
    await playSources("movie", String(item.stream_id), order);
    startHeartbeat();
    playing = true;
  } catch (error) {
    showBanner(error.message, "bad");
  }
}

async function playEpisode(episode, seriesName) {
  const ext = String(episode.container_extension || "mp4").replace(/^\./, "");
  nowTitle.textContent = `${seriesName || "Series"} · ${episode.title || `Episode ${episode.episode_num}`}`;
  nowEpg.textContent = episode.plot || episode.info?.plot || "";
  showBanner("");
  const order = [...new Set([ext, "mp4", "m3u8", "mkv", "ts"])];
  try {
    await playSources("series", String(episode.id), order);
    startHeartbeat();
    playing = true;
  } catch (error) {
    showBanner(error.message, "bad");
  }
}

function visibleItems() {
  const query = (searchEl.value || "").trim().toLowerCase();
  let rows = state.items;
  if (query) {
    rows = rows.filter((item) => {
      const hay = `${item.name || ""} ${item.now_title || ""} ${item.next_title || ""}`.toLowerCase();
      return hay.includes(query);
    });
  }
  return rows.slice(0, 800);
}

function renderCategories() {
  categoryList.innerHTML = state.categories
    .map((cat) => {
      const id = String(cat.category_id ?? "");
      const here = id === String(state.categoryId) ? " is-here" : "";
      const count =
        cat.stream_count != null && cat.stream_count !== ""
          ? ` (${esc(cat.stream_count)})`
          : "";
      return `<button type="button" class="watch-cat${here}" data-cat="${esc(id)}">${esc(cat.category_name || id)}${count}</button>`;
    })
    .join("");
}

function renderItems() {
  const rows = visibleItems();
  if (!rows.length) {
    itemList.innerHTML = `<div class="empty-events">Nothing in this category.</div>`;
    return;
  }
  if (state.tab === "live") {
    itemList.innerHTML = rows
      .map((item) => {
        const icon = item.stream_icon
          ? `<img src="${esc(item.stream_icon)}" alt="" referrerpolicy="no-referrer" />`
          : "";
        const epg = item.now_title
          ? `<small>${esc(item.now_title)}</small>`
          : item.title
            ? `<small>${esc(item.title)}</small>`
            : "";
        return `<button type="button" class="watch-item" data-live="${esc(item.stream_id)}">${icon}<span>${esc(item.name)}${epg}</span></button>`;
      })
      .join("");
    return;
  }
  if (state.tab === "movies") {
    itemList.innerHTML = rows
      .map((item) => {
        const poster = item.stream_icon
          ? `<img src="${esc(item.stream_icon)}" alt="" referrerpolicy="no-referrer" />`
          : "";
        return `<button type="button" class="watch-item poster" data-vod="${esc(item.stream_id)}">${poster}<span>${esc(item.name)}</span></button>`;
      })
      .join("");
    return;
  }
  itemList.innerHTML = rows
    .map((item) => {
      const poster = item.cover
        ? `<img src="${esc(item.cover)}" alt="" referrerpolicy="no-referrer" />`
        : "";
      return `<button type="button" class="watch-item poster" data-series="${esc(item.series_id)}">${poster}<span>${esc(item.name)}</span></button>`;
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
          return `<button type="button" class="watch-item" data-episode="${esc(ep.id)}" data-ext="${esc(ep.container_extension || "")}" data-title="${esc(ep.title || "")}" data-plot="${esc(ep.plot || ep.info?.plot || "")}" data-series-name="${esc(seriesName)}">E${esc(ep.episode_num ?? ep.id)} ${esc(ep.title || "")}</button>`;
        })
        .join("");
      return `<div class="watch-season"><h3>Season ${esc(season)}</h3><div class="watch-season-eps">${list}</div></div>`;
    })
    .join("");
}

async function loadCategories() {
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
  itemList.innerHTML = `<div class="empty-events">Pick a category. Channels and what's on now load from the local guide.</div>`;
}

async function loadItems() {
  seriesPanel.hidden = true;
  const kind = state.tab;
  if (kind === "live") {
    const data = await api(
      `/api/player/live/streams?category_id=${encodeURIComponent(state.categoryId)}`
    );
    state.items = data.streams || [];
  } else if (kind === "movies") {
    const data = await api(
      `/api/player/vod/streams?category_id=${encodeURIComponent(state.categoryId)}`
    );
    state.items = data.streams || [];
  } else {
    const data = await api(
      `/api/player/series/list?category_id=${encodeURIComponent(state.categoryId)}`
    );
    state.items = data.series || [];
  }
  renderItems();
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
    if (!me.configured) {
      showBanner(
        "Watch is signed in, but config/player.yaml has no Xtream DNS / username / password yet.",
        "warn"
      );
      return;
    }
    if (me.sync?.running && !me.sync?.ready) {
      showBanner(
        me.sync.progress ||
          "Downloading the full channel list and EPG. This can take a few minutes; after that, groups are instant for everyone.",
        "warn"
      );
      startGuidePoll();
    }
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

document.getElementById("logout-btn").addEventListener("click", async () => {
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

document.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", async () => {
    document.querySelectorAll("[data-tab]").forEach((item) => {
      item.classList.toggle("is-here", item === button);
    });
    state.tab = button.getAttribute("data-tab") || "live";
    showBanner("");
    try {
      await loadCategories();
    } catch (error) {
      showBanner(error.message, "bad");
    }
  });
});

categoryList.addEventListener("click", async (event) => {
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
    const item = state.items.find((row) => String(row.stream_id) === String(id));
    if (item) {
      localStorage.setItem("watch_last_live", String(id));
      await playLive(item);
    }
    return;
  }
  const vod = event.target.closest("[data-vod]");
  if (vod) {
    const id = vod.getAttribute("data-vod");
    const item = state.items.find((row) => String(row.stream_id) === String(id));
    if (item) {
      await playVod(item);
    }
    return;
  }
  const series = event.target.closest("[data-series]");
  if (series) {
    const id = series.getAttribute("data-series");
    const item = state.items.find((row) => String(row.series_id) === String(id));
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
    },
    button.getAttribute("data-series-name")
  );
});

searchEl.addEventListener("input", renderItems);

window.addEventListener("pagehide", () => {
  if (playing) {
    navigator.sendBeacon?.(
      "/api/player/slot/release",
      new Blob([JSON.stringify({ play_id: playId() })], { type: "application/json" })
    );
  }
});

boot();
