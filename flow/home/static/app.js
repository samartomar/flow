/* Flow Home. One page, six views, no build step and no dependencies.
 *
 * The server hands this window a token once, in the URL fragment (which never reaches a
 * server); it is kept in sessionStorage and sent on every call as X-Flow-Token. Views
 * are rendered from the API's JSON with every value escaped. The server's content
 * security policy allows no inline style, so the few dynamic sizes — a progress bar, a
 * level meter — are set through the DOM after each render (`sizes`).
 */
"use strict";

(() => {
  // ------------------------------------------------------------------ token, routes
  const PAGES = ["home", "history", "voice", "ask", "models", "settings", "start"];
  const start = new URLSearchParams(location.hash.slice(1));
  if (start.get("token")) {
    try { sessionStorage.setItem("flow-token", start.get("token")); } catch (_) { /* private */ }
    history.replaceState(null, "", "#/" + (PAGES.includes(start.get("page")) ? start.get("page") : "home"));
  }
  let TOKEN = "";
  try { TOKEN = sessionStorage.getItem("flow-token") || start.get("token") || ""; } catch (_) { TOKEN = start.get("token") || ""; }

  const current = () => {
    const m = location.hash.match(/^#\/([a-z]+)/);
    return m && PAGES.includes(m[1]) ? m[1] : "home";
  };

  // ------------------------------------------------------------------ the API
  class Gone extends Error {}

  async function api(path, body) {
    let res;
    try {
      res = await fetch("/api/" + path, {
        method: body === undefined ? "GET" : "POST",
        headers: { "X-Flow-Token": TOKEN, "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: "no-store",
      });
    } catch (_) {
      throw new Gone("Flow is not running. Start it, then open Flow Home from the pill's menu.");
    }
    let payload = {};
    try { payload = await res.json(); } catch (_) { payload = {}; }
    if (res.status === 401) throw new Gone(payload.error || "This window belongs to a Flow that has quit.");
    if (!res.ok) throw new Error(payload.error || "That did not work.");
    return payload;
  }

  // ------------------------------------------------------------------ small html
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const C = {
    text: "#E6E8ED", muted: "#A0A6B2", dim: "#656B78", soft: "#8A909C", code: "#C7CBD4",
    green: "#3ECF8E", blue: "#7AA2F7", red: "#F2584A", amber: "#E8A33D",
    type: "#E6E8ED", refine: "#E1B75C", ask: "#B48EF5",
  };
  const PATHS = {
    home: '<path d="M4 10.5 12 4l8 6.5v9a1 1 0 0 1-1 1h-4.5v-6h-5v6H5a1 1 0 0 1-1-1z"/>',
    history: '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4.5v3.2h3.2"/><path d="M12 8.2v4.3l2.8 1.8"/>',
    wave: '<path d="M4 10.5v3M8 7.5v9M12 4.5v15M16 8.5v7M20 10.5v3"/>',
    chat: '<path d="M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-7l-4.5 3.5V16H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z"/>',
    layers: '<path d="M12 3.5 20 8l-8 4.5L4 8z"/><path d="M4 12.2 12 16.7l8-4.5"/><path d="M4 16.2 12 20.7l8-4.5"/>',
    sliders: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    folder: '<path d="M3.5 7A1.5 1.5 0 0 1 5 5.5h4l2 2h8A1.5 1.5 0 0 1 20.5 9v8.5A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/>',
    terminal: '<rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="m7.5 10 2.5 2-2.5 2M12.5 15h4"/>',
    download: '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19.5h14"/>',
    trash: '<path d="M5 7h14M10 7V5h4v2M7 7l1 12.5h8L17 7"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    x: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    play: '<path d="M8 5.5v13l10.5-6.5z"/>',
    chip: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9.5 9.5h5v5h-5z"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>',
    shield: '<path d="M12 3.5 19 6v5.5c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9V6z"/>',
    lock: '<rect x="5.5" y="10.5" width="13" height="9.5" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
    warn: '<path d="M12 4.5 20.5 19h-17z"/><path d="M12 10v4M12 16.5v.01"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    open: '<path d="M14 5h5v5M19 5l-8 8"/><path d="M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',
    circle: '<circle cx="12" cy="12" r="8"/>',
    circlecheck: '<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.3 2.4 2.4 4.6-4.9"/>',
    refresh: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v3.2h-3.2"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0"/><path d="M12 17.5V21"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>',
    pencil: '<path d="M4.5 19.5l1-4L15.8 5.2a2 2 0 0 1 2.8 0l.2.2a2 2 0 0 1 0 2.8L8.5 18.5z"/><path d="M13.5 7.5l3 3"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/>',
    pause: '<path d="M9 6v12M15 6v12"/>',
    bookmark: '<path d="M7 4.5h10a1 1 0 0 1 1 1V20l-6-4-6 4V5.5a1 1 0 0 1 1-1z"/>',
    speaker: '<path d="M4.5 9.5h3l4.5-4v13l-4.5-4h-3z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
    stop: '<rect x="7" y="7" width="10" height="10" rx="1.5"/>',
    aside: '<path d="M4 6h16l-6 7.5V19l-4-2v-3.5z"/>',
    send: '<path d="M4.5 12 20 4.5 13.5 20l-2-6.5z"/>',
  };
  const icon = (name, color = C.muted, size = 18, sw = 1.6) =>
    `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PATHS[name]}</svg>`;
  // The pill's own mic glyph (design/compact/gen.py), so Home and the pill draw one mark.
  const glyph = (color, k = 1) =>
    `<svg width="${14 * k}" height="${18 * k}" viewBox="0 0 14 18" fill="none" stroke="${color}" stroke-width="1.4" stroke-linecap="round" aria-hidden="true"><rect x="4.3" y="1.2" width="5.4" height="9.6" rx="2.7"/><path d="M1.8 8.4a5.2 5.2 0 0 0 10.4 0"/><path d="M7 13.6V16.4"/></svg>`;
  const keys = (combo) => {
    if (!combo) return "";
    const parts = String(combo).split("+").map((k) => k.trim()).filter(Boolean)
      .map((k) => `<span class="kbd">${esc(k.length === 1 ? k.toUpperCase() : k[0].toUpperCase() + k.slice(1))}</span>`);
    return `<span class="keys">${parts.join('<span class="plus">+</span>')}</span>`;
  };
  const sw = (on, act, label, extra = "") =>
    `<button type="button" class="switch" role="switch" aria-checked="${on ? "true" : "false"}" aria-label="${esc(label)}" data-act="${act}" ${extra}><span></span></button>`;
  const seg = (options, value, act, label) =>
    `<div class="seg" role="group" aria-label="${esc(label)}">${options.map((o) => {
      const [v, text] = Array.isArray(o) ? o : [o, o];
      return `<button type="button" aria-pressed="${v === value ? "true" : "false"}" data-act="${act}" data-value="${esc(v)}">${esc(text)}</button>`;
    }).join("")}</div>`;
  const bars = (n = 12, cls = "") => `<span class="meter ${cls}" data-meter="${n}">${"<i></i>".repeat(n)}</span>`;
  const human = (bytes) => bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : `${Math.round(bytes / 1024 ** 2)} MB`;
  const SIDE_TINT = { dictate: C.type, refine: C.refine, ask: C.ask };
  const MODE_WORD = { dictate: "Dictate", refine: "Refine", ask: "Ask" };

  // ------------------------------------------------------------------ the rail
  const NAV = [
    { id: "home", label: "Home", icon: "home" },
    { group: "Dictate" },
    { id: "history", label: "History", icon: "history", tint: C.type },
    { id: "voice", label: "Voice", icon: "wave", tint: C.type },
    { group: "Ask" },
    { id: "ask", label: "Conversations", icon: "chat", tint: C.ask },
    { group: "Setup" },
    { id: "models", label: "Models", icon: "layers" },
    { id: "settings", label: "Settings", icon: "sliders" },
  ];

  function renderNav() {
    const here = current();
    document.getElementById("nav").innerHTML = NAV.map((n) => {
      if (n.group) return `<div class="label">${esc(n.group)}</div>`;
      const on = n.id === here;
      const tint = on ? (n.tint || C.text) : C.muted;
      return `<a href="#/${n.id}" ${on ? 'aria-current="page"' : ""} title="${esc(n.label)}">${icon(n.icon, tint)}<span class="nav-text">${esc(n.label)}</span></a>`;
    }).join("");
  }

  let live = null;

  function renderStatus() {
    const el = document.getElementById("status");
    if (!live) { el.innerHTML = '<span class="fine">connecting to Flow</span>'; return; }
    const heard = live.capturing ? C.green : C.muted;
    const model = live.loading ? "loading the speech model"
      : live.models ? `${live.models[1]} for your words` : "speech model not loaded yet";
    el.innerHTML = `
      <div class="row">${icon("mic", heard, 15)}<span class="grow ellipsis">${esc(live.mic || "no microphone")}</span>${bars(6, live.capturing ? "live" : "")}</div>
      <div class="row">${icon("layers", C.muted, 15)}<span class="grow ellipsis">${esc(model)}</span></div>
      <div class="row">${icon("terminal", C.muted, 15)}<span class="grow ellipsis">${esc(live.cli || "no agent CLI")}</span></div>
      <hr class="rule">
      <div class="row">${glyph(SIDE_TINT[live.mode] || C.type, 0.8)}<span class="mode grow">${esc(MODE_WORD[live.mode] || "Dictate")}</span><span class="fine">${esc(live.activity || "")}</span></div>
      ${live.lent ? `<div class="row">${icon("wave", C.amber, 15)}<span class="fine grow">${esc(live.lent)}; the pill waits</span></div>` : ""}`;
    level(el, live.capturing ? live.level_db : -90);
  }

  // Heights for a meter from a level in dB: the same -60..-10 window the pill reads.
  function level(root, db) {
    const norm = Math.max(0, Math.min(1, (db + 60) / 50));
    root.querySelectorAll("[data-meter]").forEach((m) => {
      const n = m.children.length;
      [...m.children].forEach((bar, i) => {
        const shape = 0.45 + 0.55 * Math.sin(((i + 1) / (n + 1)) * Math.PI);
        bar.style.height = `${Math.max(3, Math.round(3 + 15 * norm * shape))}px`;
      });
    });
  }

  function sizes(root) {
    if (data && data.mic && data.mic.listen && data.tune) {
      level(root, data.mic.listen.state === "listening" ? data.mic.listen.level_db
        : data.tune.state === "listening" ? data.tune.level_db : -90);
    }
    root.querySelectorAll("[data-w]").forEach((el) => { el.style.width = `${el.dataset.w}%`; });
    root.querySelectorAll("[data-x]").forEach((el) => { el.style.left = `${el.dataset.x}%`; });
    // A live level on the page belongs to whichever voice task is listening.
    if (data && data.tune && data.check && root.querySelector(".card [data-meter]")) {
      const t = data.tune, c = data.check;
      level(root, t.state === "listening" ? t.level_db : c.state === "recording" ? c.level_db : -90);
    }
  }

  // ------------------------------------------------------------------ toast, gone
  let toastTimer = 0;
  function toast(text, bad = false) {
    const el = document.getElementById("toast");
    el.textContent = text;
    el.classList.toggle("bad", bad);
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, bad ? 6000 : 3000);
  }
  function gone(why) {
    document.getElementById("gone-why").textContent = why;
    document.getElementById("gone").hidden = false;
  }

  // ------------------------------------------------------------------ Home
  function renderHome(d) {
    const s = d.stats || {};
    const sc = d.shortcuts || {};
    const hist = d.history || {};
    const done = d.setup.filter((i) => i.done).length;
    const gesture = sc.gesture === "toggle" ? "press, talk, press again" : "hold, talk, let go";
    const askHow = sc.mode
      ? `Tap the pill until its mic is violet, or press ${keys(sc.mode)}, then hold to talk.`
      : "Tap the pill until its mic is violet, then hold to talk.";
    const recent = (d.recent || []).map((r) => `
      <div class="recent">${glyph(r.side === "ask" ? C.ask : C.type, 0.8)}
        <span class="kind">${esc(r.kind === "said" ? "Said" : r.kind === "asked" ? "Asked" : "Answer")}</span>
        <span class="text">${esc(r.text)}</span></div>`).join("");
    return `
      <div class="page-head"><div class="grow"><h1>Home</h1><p class="sub">Two things Flow does. Hold a key, talk, let go.</p></div></div>
      <div class="split stretch">
        <section class="card side-card">
          <div class="row"><span class="disc">${glyph(C.type, 1.15)}</span><h2 class="grow">Dictate</h2>${keys(sc.dictate)}<span class="fine">${esc(sc.dictate ? gesture : "")}</span></div>
          <p class="lead">Talk into any window. Let go and it pastes where you were, accurate in your accent.</p>
          <div class="stats">
            <div class="stat"><b>${Number(s.today_words || 0).toLocaleString()}</b><span>words ${s.since ? "since " + esc(s.since) : "today"}</span></div>
            <div class="stat"><b>${s.saved_minutes ? "&asymp; " + s.saved_minutes + " min" : "&ndash;"}</b><span>saved vs typing at ${esc(s.typing_wpm)} wpm</span></div>
            ${s.all_words != null ? `<div class="stat"><b>${Number(s.all_words).toLocaleString()}</b><span>words all time</span></div>` : ""}
          </div>
          <hr class="rule">
          <div class="row">${glyph(C.refine, 0.8)}<p class="note">Tap the pill to gold for <b class="warn">Refine</b>: shaped for your project before you send it.</p></div>
          ${sc.paste_last ? `<div class="row">${icon("copy", C.soft, 15)}<p class="note grow">Pasted in the wrong window? <b>Paste last</b> puts it in the one in front.</p>${keys(sc.paste_last)}</div>` : ""}
        </section>
        <section class="card side-card">
          <div class="row"><span class="disc">${glyph(C.ask, 1.15)}</span><h2 class="grow">Ask</h2>${d.mode === "ask" ? '<span class="badge violet">the pill is on Ask</span>' : ""}</div>
          <p class="lead">Ask anything, like ChatGPT. With a workspace set, the answer knows your code.</p>
          <p class="note">${askHow}</p>
          <hr class="rule">
          <div class="row">${icon("folder", d.workspace ? C.green : C.soft, 16)}<span class="mono grow ellipsis">${esc(d.workspace || "no workspace - answers are about anything")}</span><a class="btn ghost sm" href="#/settings">Change</a></div>
          <div class="row">${icon("terminal", C.muted, 16)}<span class="note grow">${d.cli ? `${esc(d.cli)} answers, with the words you say and the workspace path.` : "No agent CLI found. Install claude or codex to ask."}</span></div>
        </section>
      </div>
      <div class="split stretch">
        <section class="card">
          <div class="row"><h2 class="grow">Finish setting up</h2><span class="note">${done} of ${d.setup.length}</span></div>
          <div class="progress green"><div data-w="${Math.round((done / d.setup.length) * 100)}"></div></div>
          <div class="col">${d.setup.map((i) => `
            <div class="check ${i.done ? "done" : ""}">${icon(i.done ? "circlecheck" : "circle", i.done ? C.green : C.dim, 20)}
              <div class="text"><b>${esc(i.title)}</b><span class="note ellipsis">${esc(i.detail)}</span></div>
              ${i.done ? "" : `<a class="btn sm" href="#/${esc(i.page)}">Open</a>`}</div>`).join("")}</div>
        </section>
        <section class="card">
          <div class="row"><h2 class="grow">This session</h2></div>
          <div class="col">${recent || '<p class="note">Nothing yet. What you say and ask shows up here.</p>'}</div>
          <div class="row">${icon("lock", C.soft, 14)}<p class="fine">${hist.keeping
            ? `In memory, and kept in <a href="#/history">History</a> for ${esc(hist.days)} days on this PC.`
            : hist.choice === "off" ? "In memory only - gone when Flow quits. History is off, so nothing is written to disk."
              : `In memory only - gone when Flow quits. <a href="#/history">History</a> can keep it, if you choose to.`}</p></div>
        </section>
      </div>`;
  }

  // ------------------------------------------------------------------ Models
  function modelActions(m, busy) {
    if (!m.catalog) return "";
    const dl = m.download;
    if (dl && dl.state === "running") {
      const total = dl.total || 0;
      const pct = total ? Math.min(100, Math.round((dl.done / total) * 100))
        : dl.files_total ? Math.round((dl.files_done / dl.files_total) * 100) : 0;
      const said = total ? `${human(dl.done)} of ${human(total)}` : "starting";
      return `<div class="col"><div class="progress ${pct ? "" : "busy"}"><div data-w="${pct}"></div></div>
        <div class="row"><span class="note">Downloading - ${esc(said)}</span><button type="button" class="btn ghost sm" data-act="cancel" data-name="${esc(m.name)}">Cancel</button></div></div>`;
    }
    const failed = dl && dl.state === "failed"
      ? `<span class="note warn ellipsis" title="${esc(dl.error)}">${esc(dl.error)}</span>` : "";
    if (m.installed) {
      const using = m.in_use.length > 0;
      return `${failed}<span class="note">on this PC</span>
        <button type="button" class="icon-btn" aria-label="Delete ${esc(m.name)}" title="${using ? "In use - choose another model first" : "Delete"}" data-act="delete" data-name="${esc(m.name)}" ${using || busy ? "disabled" : ""}>${icon("trash", using ? C.dim : C.soft, 16)}</button>`;
    }
    return `${failed}<button type="button" class="btn sm" data-act="download" data-name="${esc(m.name)}">${icon("download", C.text, 15)}${failed ? "Retry" : "Download"}</button>`;
  }

  function renderModels(d) {
    const sp = d.speech;
    const ag = d.agent;
    const vo = d.voice;
    const gpu = sp.gpu;
    const onGpu = sp.device === "cuda";
    const catalog = sp.models.filter((m) => m.catalog);
    const option = (tier, chosen, auto) => [`<option value="" ${chosen ? "" : "selected"}>Automatic (${esc(auto)})</option>`]
      .concat(catalog.map((m) => `<option value="${esc(m.name)}" ${m.name === chosen ? "selected" : ""}>${esc(m.name)}${m.installed ? "" : " - downloads first"}${m.blind ? " - invents words in silence" : ""}</option>`))
      .join("");
    const now = sp.models.filter((m) => m.in_use.length);
    const finalNow = (now.find((m) => m.in_use.includes("final")) || {}).name || sp.automatic.final;
    const partialNow = (now.find((m) => m.in_use.includes("partial")) || {}).name || sp.automatic.partial;
    const rows = sp.models.map((m) => {
      const tags = [];
      if (m.in_use.includes("final")) tags.push('<span class="badge green">your words</span>');
      if (m.in_use.includes("partial")) tags.push('<span class="badge green">live preview</span>');
      if (m.name === sp.automatic.final && !m.in_use.includes("final")) tags.push('<span class="badge">recommended here</span>');
      if (m.blind) tags.push(`<span class="badge amber">${icon("warn", C.amber, 12)}invents words in silence</span>`);
      return `<div class="tr ${m.in_use.length ? "using" : ""}" role="row">
        <div class="col" role="cell"><div class="name"><span class="mono">${esc(m.name)}</span>${tags.join("")}</div>${m.note ? `<span class="fine">${esc(m.note)}</span>` : ""}</div>
        <div role="cell" class="note">${esc(m.size_text)}</div>
        <div role="cell">${m.errors != null ? `<span class="${m.name === "large-v3" ? "good" : ""}">${m.errors.toFixed(1)}</span>` : '<span class="fine">&ndash;</span>'}</div>
        <div role="cell" class="note">${m.speed != null ? m.speed + "&times;" : "&ndash;"}</div>
        <div role="cell" class="acts">${modelActions(m, sp.loading)}</div></div>`;
    }).join("");
    const clis = ag.available.length
      ? [["auto", "Automatic"]].concat(ag.available.map((n) => [n, n])).map(([v, t]) => `
          <label class="row"><input type="radio" name="cli" value="${esc(v)}" data-change="cli" ${(ag.pinned || "auto") === v ? "checked" : ""}>${esc(t)}</label>`).join("")
      : "";
    const groups = {};
    (vo.voices || []).forEach((v) => { (groups[v.group] = groups[v.group] || []).push(v); });
    const voiceOptions = [`<option value="" ${vo.current ? "" : "selected"}>The engine's default</option>`]
      .concat(Object.entries(groups).map(([g, vs]) => `<optgroup label="${esc(g)}">${vs.map((v) =>
        `<option value="${esc(v.name)}" ${v.name === vo.current ? "selected" : ""}>${esc(v.label)}</option>`).join("")}</optgroup>`)).join("");
    return `
      <div class="page-head"><div class="grow"><h1>Models</h1><p class="sub">What hears you, what answers you, and what talks back.</p></div></div>
      <section class="card tight"><div class="row wrap pc">
        ${icon("chip", onGpu ? C.green : C.muted, 22)}
        <div class="col grow">
          <div class="row wrap"><b>${esc(gpu ? gpu.name : "No NVIDIA GPU found")}</b>${gpu && gpu.memory_mb ? `<span class="note">${Math.round(gpu.memory_mb / 1024)} GB</span>` : ""}
            <span class="badge ${onGpu ? "green" : ""}">${onGpu ? '<span class="dot green"></span>speech runs on the GPU' : "speech runs on the CPU"}</span>
            ${sp.compute_types.includes("int8") && onGpu && !sp.compute_types.includes("float16") ? '<span class="badge">int8</span>' : ""}</div>
          <p class="note">${onGpu ? (sp.compute_types.includes("float16") ? "This card has fast half-precision; Flow runs int8 on it." : "This card has no fast half-precision, so int8 is its fast path. Flow picks it for you.")
            : esc(sp.why_cpu || "The CPU runs the smaller models in time; the large ones need a GPU.")}</p>
        </div>
        <div class="col"><b>${esc(sp.cache.text)}</b><span class="fine">of speech models on disk</span></div>
        <button type="button" class="btn" data-act="open" data-what="models">${icon("folder", C.text, 15)}Open folder</button>
      </div></section>
      <section class="card">
        <div class="row"><h2 class="grow">Speech recognition</h2>${sp.loading ? '<span class="badge"><span class="dot blue"></span>loading a model</span>' : ""}</div>
        <p class="note">Now: <span class="mono">${esc(finalNow)}</span> for the words that get pasted, <span class="mono">${esc(partialNow)}</span> for the live preview.</p>
        ${sp.swappable ? `<div class="choose">
          <label>Words that get pasted<select id="final-model">${option("final", sp.chosen.final, sp.automatic.final)}</select></label>
          <label>Live preview<select id="partial-model">${option("partial", sp.chosen.partial, sp.automatic.partial)}</select></label>
          <label>Run speech on<select id="decode-device">${[["", "Automatic"], ["cuda", "The GPU"], ["cpu", "The CPU"]].map(([v, t]) =>
            `<option value="${v}" ${(sp.device_asked === v || (!v && sp.device_asked === "auto")) ? "selected" : ""}>${t}</option>`).join("")}</select></label>
        </div>
        <div class="row"><button type="button" class="btn primary" data-act="use-models">Use these</button><p class="note">Applies now. A model that is not on this PC downloads first, then takes over.</p></div>`
        : '<p class="note">This speech engine has no models to choose between.</p>'}
        <div class="table" role="table" aria-label="Speech models">
          <div class="tr head" role="row"><span class="label" role="columnheader">Model</span><span class="label" role="columnheader">Size</span><span class="label" role="columnheader">Errors / 100 words</span><span class="label" role="columnheader">Speed</span><span role="columnheader"></span></div>
          ${rows}
        </div>
        <p class="fine">Errors per 100 words and speed were measured on ${esc(sp.measured_on)}; speed is how many times faster than you talk. They compare the models - your own voice is its own measurement. The marked models skip the silence signal Flow's filter relies on, so they hear &ldquo;thank you&rdquo; in an empty room.</p>
      </section>
      <div class="split">
        <section class="card">
          <div class="row"><h2 class="grow">Ask and Refine</h2><span class="note">${ag.available.length ? "found on this PC" : ""}</span></div>
          <p class="note">The agent CLI you already use does the answering. Flow never holds a key.</p>
          ${ag.available.length ? `<div class="row wrap">${clis}</div>
          <div class="row"><label class="note" for="cli-model">Model</label><input id="cli-model" class="input grow" list="cli-models" value="${esc(ag.model)}" placeholder="the CLI's own default" maxlength="120"><datalist id="cli-models">${ag.models.map((m) => `<option value="${esc(m)}"></option>`).join("")}</datalist><button type="button" class="btn sm" data-act="cli-model">Save</button></div>
          <div class="row"><span class="note">Effort</span>${seg(ag.efforts, ag.effort, "effort", "How hard the CLI may think")}</div>
          <div class="row"><label class="note" for="cli-timeout">Wait up to</label><input id="cli-timeout" class="input" type="number" min="1" max="600" step="1" value="${Math.round(ag.timeout)}"><span class="note grow">seconds</span><button type="button" class="btn sm" data-act="cli-timeout">Save</button></div>`
          : '<p class="note">None found. Install <span class="mono">claude</span> or <span class="mono">codex</span> and sign in to it - Flow finds it on your PATH.</p>'}
        </section>
        <section class="card">
          <div class="row"><h2 class="grow">Spoken replies</h2>${vo.available ? sw(!vo.muted, "mute", "Read answers aloud") : ""}</div>
          ${vo.available ? `<p class="note">Answers from Ask can be read aloud. Flow never listens while it talks.</p>
          <div class="row"><select id="voice" class="grow" data-change="voice" aria-label="Voice">${voiceOptions}</select><button type="button" class="btn" data-act="preview">${icon("play", C.text, 14)}Preview</button></div>
          <div class="row top">${icon("shield", C.soft, 14)}<p class="fine">Natural voices send the answer's text to Microsoft to be spoken. Windows and Piper voices stay on this PC.</p></div>`
          : '<p class="note">No speech engine answered on this PC, so answers are shown and not read.</p>'}
        </section>
      </div>`;
  }

  // ------------------------------------------------------------------ Settings
  function renderSettings(d) {
    const mic = d.mic;
    const sh = d.shortcuts;
    const devices = [`<option value="" ${mic.chosen ? "" : "selected"}>The system default${!mic.chosen && mic.current ? " (" + esc(mic.current) + ")" : ""}</option>`]
      .concat(mic.devices.map((dev) => `<option value="${esc(dev.name)}" ${dev.name === mic.chosen ? "selected" : ""}>${esc(dev.name)}</option>`)).join("");
    const hot = sh.available ? `
      <div class="hotkey"><span class="what">Talk</span>${keys(sh.chord.describe) || '<span class="note">off</span>'}<span class="grow"></span>${seg([["hold", "Hold"], ["toggle", "Toggle"]], sh.chord.gesture, "gesture", "How the talk keys work")}</div>
      <div class="hotkey"><label class="what" for="chord-keys">Talk keys</label><input id="chord-keys" class="input mono grow" value="${esc(sh.chord.keys)}" placeholder="ctrl+win - empty turns it off"><button type="button" class="btn sm" data-act="chord">Save</button></div>
      ${sh.hotkeys.map((h) => `
      <div class="hotkey"><span class="what">${esc(h.label)}</span>${h.combo ? keys(h.combo) : '<span class="note">not registered</span>'}<span class="grow"></span>
        <input class="input mono" data-hotkey="${esc(h.action)}" value="${esc(h.override)}" placeholder="ctrl+alt+..." aria-label="New keys for ${esc(h.label)}">
        <button type="button" class="btn sm" data-act="hotkey" data-action="${esc(h.action)}">Save</button></div>`).join("")}
      <p class="fine">Hold and Toggle change now. New keys take effect the next time Flow starts.</p>`
      : `<p class="note">${sh.lite ? "No global shortcuts in Lite: hold the pill to talk. Nothing to grant but the microphone." : "Global shortcuts are off for this launch."}</p>`;
    const ws = d.workspaces;
    const wsRows = ws.recent.map((p) => `
      <div class="ws"><label><input type="radio" name="ws" value="${esc(p)}" data-change="ws" ${p === ws.current ? "checked" : ""}>${icon("folder", C.green, 16)}<span class="mono ellipsis">${esc(p)}</span></label>
        <button type="button" class="icon-btn" aria-label="Forget ${esc(p)}" data-act="ws-forget" data-path="${esc(p)}">${icon("x", C.soft, 14)}</button></div>`).join("");
    const apps = d.apps.map((a) => `
      <div class="app-row"><span class="mono ellipsis">${esc(a.exe)}</span><span class="note ellipsis" title="${esc(a.instruction)}">${esc(a.instruction)}</span>
        <button type="button" class="icon-btn" aria-label="Remove ${esc(a.exe)}" data-act="app-remove" data-exe="${esc(a.exe)}">${icon("x", C.soft, 14)}</button></div>`).join("");
    return `
      <div class="page-head"><div class="grow"><h1>Settings</h1><p class="sub">Everything Flow remembers about how you like it. The pill never grows one of these.</p></div></div>
      ${d.profile ? "" : '<section class="card tight"><p class="note warn">Flow was started with --no-profile: changes here last until it quits.</p></section>'}
      <div class="split">
        <div class="col">
          <section class="card">
            <h2>Microphone</h2>
            <div class="row"><select id="mic" class="grow" data-change="mic" aria-label="Microphone">${devices}</select>${bars(12)}</div>
            <p class="note">${mic.flag ? "Chosen by --device for this launch. " : ""}${mic.chosen || mic.flag
              ? "If it goes away, Flow keeps trying this one and tells you - it never switches to another on its own."
              : "Follows the one Windows uses, and moves with it when you plug something in."} The level moves while Flow is listening.</p>
          </section>
          <section class="card"><h2>Shortcuts</h2>${hot}</section>
          <section class="card">
            <h2>Saying send</h2>
            <div class="row"><select id="send" data-change="send" aria-label="Send word">${d.send.presets.concat(d.send.presets.includes(d.send.word) ? [] : [d.send.word]).map((w) =>
              `<option value="${esc(w)}" ${w === d.send.word ? "selected" : ""}>${esc(w)}</option>`).join("")}</select>
              <p class="note grow">Say &ldquo;${esc(d.send.word)}&rdquo; on its own to send${d.send.pastes ? `, or &ldquo;${esc(d.send.enter_word)}&rdquo; to send and press Enter` : ""}.</p></div>
            <p class="fine">Each word here was tested against hundreds of real recordings so it does not fire by accident.</p>
          </section>
          <section class="card">
            <h2>Start and update</h2>
            <div class="setting"><div class="text"><b>Load the speech model when Flow starts</b><span class="note">The first words come faster; starting takes a moment longer.</span></div>${sw(d.startup.warm, "warm", "Load the model at startup")}</div>
            <div class="setting"><div class="text"><b>Flow ${esc(d.version)}</b><span class="note" id="update-line">Flow asks for updates only when you press this.</span></div><button type="button" class="btn" data-act="update">${icon("refresh", C.text, 15)}Check for updates</button></div>
          </section>
        </div>
        <div class="col">
          <section class="card">
            <div class="row"><h2 class="grow">Workspaces</h2><button type="button" class="btn" data-act="ws-add">${icon("plus", C.text, 15)}Add a folder</button></div>
            <p class="note">The project folder Ask and Refine answer about. Kept notes are written there.</p>
            <div class="col">${wsRows}
              <div class="ws"><label><input type="radio" name="ws" value="" data-change="ws" ${ws.current ? "" : "checked"}>${icon("chat", C.soft, 16)}<span class="note">No workspace: just talk</span></label></div>
            </div>
            <div class="row"><input id="ws-path" class="input mono grow" placeholder="or paste a folder path" aria-label="Folder path"><button type="button" class="btn sm" data-act="ws-add-path">Add</button></div>
          </section>
          <section class="card">
            <h2>Ask</h2>
            <div class="setting"><div class="text"><b>Ask after a pause</b><span class="note">In Ask, a few quiet seconds send the question. Off: send it yourself.</span></div>${sw(d.ask.auto_ask, "auto-ask", "Ask after a pause")}</div>
          </section>
          <section class="card">
            <h2>The pill</h2>
            <div class="setting"><div class="text"><b>Design</b><span class="note">Switches now, keeping what you were saying.</span></div>${seg(d.design.options.map((o) => [o.name, o.label]), d.design.current, "design", "Pill design")}</div>
            <div class="setting"><div class="text"><b>Classic panel</b><span class="note">Width and place of the Classic pill's panel, from its next start.</span></div>
              <select data-change="panel" aria-label="Panel width">${d.classic.panels.map((p) => `<option ${p === d.classic.panel ? "selected" : ""}>${esc(p)}</option>`).join("")}</select>
              <select data-change="place" aria-label="Where the pill sits">${d.classic.places.map((p) => `<option ${p === d.classic.place ? "selected" : ""}>${esc(p)}</option>`).join("")}</select></div>
          </section>
          <section class="card">
            <h2>Refine, per app</h2>
            <p class="note">An extra instruction for Refine when a program is in front - say, &ldquo;keep it to one line&rdquo; for a chat app.</p>
            <div class="col">${apps || '<p class="fine">None yet.</p>'}</div>
            <div class="app-row"><input id="app-exe" class="input mono" placeholder="slack.exe" aria-label="Program"><input id="app-text" class="input" placeholder="the instruction" aria-label="Instruction" maxlength="400"><button type="button" class="btn sm" data-act="app-add">Add</button></div>
          </section>
          <section class="card">
            <h2>What leaves this PC</h2>
            <div class="privacy">${icon("circlecheck", C.green, 18)}<div class="col"><b>Your voice never does</b><span class="note">Speech is recognised here. No account, no key.</span></div></div>
            <div class="privacy">${icon("terminal", C.blue, 18)}<div class="col"><b>Ask and Refine send text to your agent CLI</b><span class="note">The words, and the workspace path when one is set.</span></div></div>
            <div class="privacy">${icon("lock", C.soft, 18)}<div class="col"><b>The trace keeps timings and counts, never words</b><span class="note">Flow's own diagnostics, on this PC.</span></div></div>
            <div class="privacy">${icon("history", d.history && d.history.keeping ? C.green : C.soft, 18)}<div class="col"><b>${d.history && d.history.keeping
              ? `History keeps your words for ${esc(d.history.days)} days`
              : d.history && d.history.choice === "off" ? "History is off: your words are not kept" : "History keeps nothing until you choose"}</b><span class="note">On this PC only. <a href="#/history">History</a> changes it.</span></div></div>
            <div class="row wrap"><button type="button" class="btn sm" data-act="open" data-what="settings">${icon("folder", C.text, 14)}Settings folder</button><button type="button" class="btn sm" data-act="open" data-what="trace">${icon("folder", C.text, 14)}Trace folder</button></div>
          </section>
        </div>
      </div>`;
  }

  // ------------------------------------------------------------------ Voice
  // A sentence as Flow heard it: missed words struck, extra words marked.
  function diff(steps) {
    return steps.map((s) => s.op === "ok" ? esc(s.said)
      : s.op === "sub" ? `<del>${esc(s.said)}</del> <ins>${esc(s.heard)}</ins>`
        : s.op === "del" ? `<del>${esc(s.said)}</del>` : `<ins>${esc(s.heard)}</ins>`).join(" ");
  }

  // Where a level sits on the -90..-10 dB scale the tuning card draws.
  const onScale = (db) => Math.max(0, Math.min(100, ((db + 90) / 80) * 100)).toFixed(1);

  function tuneCard(t) {
    const last = t.last;
    if (t.state === "listening" || t.state === "measuring") {
      const pct = Math.min(100, Math.round((t.elapsed / t.seconds) * 100));
      return `
        <section class="card">
          <div class="row"><h2 class="grow">Read this aloud</h2><span class="note">${Math.round(t.elapsed)} s of ${Math.round(t.seconds)}</span></div>
          <p class="passage">${esc(t.passage)}</p>
          <div class="progress green"><div data-w="${pct}"></div></div>
          ${t.state === "measuring"
            ? '<div class="row"><span class="badge"><span class="dot blue"></span>measuring what you read</span></div>'
            : `<div class="row">${bars(14, "live")}<span class="note grow">${t.enough ? "That is enough to measure - finish now, or read to the end." : "Read at your normal pace, with your normal pauses."}</span>
                 <button type="button" class="btn primary" data-act="tune-finish" ${t.enough ? "" : "disabled"}>Done reading</button>
                 <button type="button" class="btn ghost" data-act="tune-cancel">Cancel</button></div>`}
        </section>`;
    }
    const gap = last ? last.gap_db : null;
    const verdict = gap == null ? "" : gap >= 20 ? "apart: easy to tell apart" : gap >= 12 ? "apart: fine" : "apart: close - speak up, or move the microphone nearer";
    return `
      <section class="card">
        <div class="row"><h2 class="grow">Your room and your voice</h2><span class="note">${last ? `tuned ${esc(last.at)}${last.device ? ", " + esc(last.device) : ""}` : "not tuned yet"}</span></div>
        ${last ? `
        <div class="stats">
          <div class="stat"><b>${last.floor_db} dB</b><span>room, between sentences</span></div>
          <div class="stat"><b>${last.speech_db} dB</b><span>your voice</span></div>
          <div class="stat"><b>${gap} dB</b><span>${esc(verdict)}</span></div>
        </div>
        <div class="scale" aria-hidden="true"><span class="band" data-x="${onScale(last.floor_db)}" data-w="${(onScale(last.speech_db) - onScale(last.floor_db)).toFixed(1)}"></span>
          <span class="mark room" data-x="${onScale(last.floor_db)}"></span><span class="mark you" data-x="${onScale(last.speech_db)}"></span></div>`
          : '<p class="note">Flow is using settings measured on someone else\'s microphone. One minute of reading measures yours: how quiet your room is, how loud you speak, and how clearly Flow hears you.</p>'}
        ${t.state === "done" ? '<p class="note good">Saved. Flow is listening with these now.</p>' : ""}
        ${t.state === "failed" ? `<p class="note warn">${esc(t.error)}</p>` : ""}
        <div class="row"><button type="button" class="btn ${last ? "" : "primary"}" data-act="tune-start" ${t.profile ? "" : "disabled"}>${icon("mic", last ? C.text : "#15171C", 15)}${last ? "Tune again" : "Tune Flow to your voice"}</button>
          <p class="note">${t.profile ? "Read one paragraph aloud, about 45 seconds. Nothing leaves this PC." : "Started with --no-profile: a tuning has nowhere to be saved."}</p></div>
      </section>`;
  }

  function checkCard(c, dict) {
    const addWord = (w) => `<button type="button" class="badge red" data-act="dict-add" data-term="${esc(w)}" title="Add ${esc(w)} to the dictionary">${icon("plus", C.red, 12)}${esc(w)}</button>`;
    if (c.state === "ready" || c.state === "recording" || c.state === "decoding") {
      const last = c.scores.length ? c.scores[c.scores.length - 1] : null;
      return `
        <section class="card">
          <div class="row"><h2 class="grow">How well Flow hears you</h2><span class="note">sentence ${c.index + 1} of ${c.total}</span></div>
          <p class="sentence">${esc(c.sentence)}</p>
          ${c.state === "recording"
            ? `<div class="row">${bars(14, "live")}<span class="note grow">Listening - it stops when you do.</span><button type="button" class="btn" data-act="check-stop">Stop</button></div>`
            : c.state === "decoding"
              ? '<div class="row"><span class="badge"><span class="dot blue"></span>checking what Flow heard</span></div>'
              : `<div class="row"><button type="button" class="btn primary" data-act="check-record">${icon("mic", "#15171C", 15)}Read it</button><span class="note grow">${esc(c.note || "Press, read the sentence as you normally would, then pause.")}</span><button type="button" class="btn ghost" data-act="check-cancel">Cancel</button></div>`}
          ${last ? `<p class="heard"><span class="label">last one</span> ${diff(last.steps)}</p>` : ""}
        </section>`;
    }
    const done = c.state === "done" && c.per_hundred != null;
    return `
      <section class="card">
        <div class="row"><h2 class="grow">How well Flow hears you</h2>${done ? '<span class="note">checked just now</span>' : ""}</div>
        ${done ? `
          <div class="row top"><span class="big">${c.per_hundred}</span><div class="col"><b>errors in 100 words, your voice</b><span class="note">The Models page's numbers are other people's voices. This one is yours.</span></div></div>
          ${c.offers.length ? `<div class="row wrap"><span class="note">Missed</span>${c.offers.map(addWord).join("")}<span class="fine">add a name to the dictionary so Flow listens for it</span></div>` : '<p class="note good">No names or terms missed.</p>'}
          <details><summary class="note">What it heard, sentence by sentence</summary>
            <div class="col">${c.scores.map((s) => `<p class="heard">${diff(s.steps)}</p>`).join("")}</div></details>`
          : '<p class="note">Read five short sentences. Flow shows exactly which words it got wrong, and offers the names it missed for the dictionary.</p>'}
        ${c.state === "failed" ? `<p class="note warn">${esc(c.error)}</p>` : ""}
        <div class="row"><button type="button" class="btn ${done ? "" : "primary"}" data-act="check-start">${icon("refresh", done ? C.text : "#15171C", 15)}${done ? "Check again" : "Start the check"}</button>
          <p class="note">About a minute. The pill waits until it is done.</p></div>
      </section>`;
  }

  function dictionaryCard(d) {
    if (!d.enabled) {
      return `<section class="card"><h2>Dictionary</h2><p class="note">Off for this launch: Flow was started with --no-lexicon.</p></section>`;
    }
    const learned = d.learned.map((l) => `
      <div class="pair">
        <span class="mono wrong">${esc(l.wrong)}</span>${icon("arrow", C.soft, 14)}<span class="mono right">${esc(l.right)}</span>
        <span class="note grow">you fixed this ${l.times} times</span>
        ${l.status === "offer" ? `<button type="button" class="btn sm" data-act="learned" data-action="fix" data-wrong="${esc(l.wrong)}" data-right="${esc(l.right)}">${icon("check", C.text, 14)}Always fix</button>
          <button type="button" class="btn ghost sm" data-act="learned" data-action="never" data-wrong="${esc(l.wrong)}" data-right="${esc(l.right)}">Never</button>`
          : l.status === "fixed" ? '<span class="badge green">fixed every time</span>' : '<span class="badge">listened for, not fixed</span>'}
        <button type="button" class="icon-btn" aria-label="Forget ${esc(l.wrong)} to ${esc(l.right)}" title="Forget it: Flow stops listening for it" data-act="learned" data-action="forget" data-wrong="${esc(l.wrong)}" data-right="${esc(l.right)}">${icon("x", C.soft, 14)}</button>
      </div>`).join("");
    const corrections = d.corrections.map((c) => `
      <div class="pair"><span class="mono wrong">${esc(c.wrong)}</span>${icon("arrow", C.soft, 14)}<span class="mono right">${esc(c.right)}</span><span class="grow"></span>
        <button type="button" class="icon-btn" aria-label="Remove the correction for ${esc(c.wrong)}" data-act="correction-remove" data-wrong="${esc(c.wrong)}">${icon("trash", C.soft, 14)}</button></div>`).join("");
    const words = d.terms.map((t) => `<span class="badge word">${esc(t)}<button type="button" class="chip-x" aria-label="Remove ${esc(t)}" data-act="word-remove" data-term="${esc(t)}">${icon("x", C.soft, 11)}</button></span>`).join("");
    return `
      <section class="card">
        <div class="row"><h2 class="grow">Dictionary</h2><span class="note">${d.used} of ${d.cap} lines</span>
          <button type="button" class="btn ghost sm" data-act="open" data-what="lexicon">${icon("folder", C.muted, 14)}The file</button></div>
        <div class="col">
          <div class="row"><span class="dot amber"></span><span class="label amber">Learned from your fixes</span></div>
          ${learned || '<p class="fine">When you correct the same word twice, it shows up here, and Flow starts listening for the right spelling.</p>'}
        </div>
        <hr class="rule">
        <div class="col">
          <div class="row"><span class="label">Corrections</span><span class="note">when Flow hears the left, it writes the right</span></div>
          ${corrections || '<p class="fine">None yet.</p>'}
          <div class="row"><input id="fix-wrong" class="input mono" placeholder="what Flow writes" aria-label="What Flow writes" maxlength="40">${icon("arrow", C.soft, 14)}
            <input id="fix-right" class="input mono" placeholder="what it should" aria-label="What it should write" maxlength="40"><button type="button" class="btn sm" data-act="correction-add">Add</button></div>
        </div>
        <hr class="rule">
        <div class="col">
          <span class="label">Words to listen for</span>
          <div class="row wrap">${words || '<span class="fine">None yet.</span>'}</div>
          <div class="row"><input id="word-new" class="input grow" placeholder="a name, a tool, a repo" aria-label="New word" maxlength="40"><button type="button" class="btn sm" data-act="word-add">Add</button></div>
          <p class="fine">Each word helps when you say it and costs a little accuracy when you don't. Add the ones you say often.</p>
        </div>
      </section>`;
  }

  function renderVoice(d) {
    const send = d.send;
    return `
      <div class="page-head"><div class="grow"><h1>Voice</h1><p class="sub">Teach Flow how you speak. Everything on this page stays on this PC.</p></div></div>
      <div class="split stretch">${tuneCard(d.tune)}${checkCard(d.check, d.dictionary)}</div>
      <div class="split">
        ${dictionaryCard(d.dictionary)}
        <section class="card">
          <h2>Things you can say</h2>
          <div class="col says">${d.commands.map((c) => `<div class="say"><span class="mono">&ldquo;${esc(c.say)}&rdquo;</span><span class="note">${esc(c.does)}</span></div>`).join("")}
            <div class="say"><span class="mono">&ldquo;${esc(send.word)}&rdquo;</span><span class="note">send, on its own</span></div>
            ${send.pastes ? `<div class="say"><span class="mono">&ldquo;${esc(send.enter_word)}&rdquo;</span><span class="note">send, then press Enter</span></div>` : ""}
          </div>
          <p class="fine">A correction counts only when the words it names are in your draft. The send word is on <a href="#/settings">Settings</a>.</p>
        </section>
      </div>`;
  }

  // ------------------------------------------------------------------ History
  // What the page is filtered to, and the fix a person has open. Kept here rather than
  // read back off the page, because the page is re-drawn under them every few seconds.
  const historyView = { kind: "all", query: "" };
  let fixing = null; // { id, wrong, right }

  function keepChoice(d) {
    const days = d.days || 30;
    return `
      <section class="card choose-history">
        <h2>Keep a history?</h2>
        <p class="note">Nothing is chosen for you, and until you choose, Flow keeps nothing. You can change it here at any time.</p>
        <div class="choice-grid">
          <button type="button" class="choice" data-act="history-keep" ${d.profile ? "" : "disabled"}>${icon("history", C.green, 20)}
            <b>Keep what I dictate and ask for ${esc(days)} days</b>
            <span class="note">On this PC only. Find it, copy it again, fix words Flow got wrong. Conversations are kept too, so you can carry them on.</span></button>
          <button type="button" class="choice" data-act="history-decline" ${d.profile ? "" : "disabled"}>${icon("lock", C.soft, 20)}
            <b>Don't keep it</b>
            <span class="note">Flow keeps times and word counts, never the words. What you said this session stays on Home until Flow quits.</span></button>
        </div>
        ${d.profile ? `<p class="fine">Kept in <span class="mono">${esc(d.path)}</span>, a plain file you can open. Choosing "Don't keep it" later deletes it.</p>`
          : '<p class="note warn">Flow was started with --no-profile, so there is nowhere to keep a history this launch.</p>'}
      </section>`;
  }

  function entryMeta(e) {
    if (e.kind === "set_aside") {
      return `<span class="where">${icon("aside", C.amber, 14)}Set aside, not pasted</span>`;
    }
    const where = e.app ? `<span class="where">${icon("terminal", C.muted, 14)}${esc(e.app)}</span>` : "";
    const parts = [];
    if (e.kind === "refined") parts.push(`refined by ${esc(e.cli || "the CLI")}${e.secs != null ? ` in ${esc(e.secs)} s` : ""}`);
    else if (e.words) parts.push(`${esc(e.words)} word${e.words === 1 ? "" : "s"}`);
    const how = e.how === "not pasted" || e.how === "not copied"
      ? `<span class="bad" title="${esc(e.note || "")}">${esc(e.how)}</span>` : esc(e.how || "");
    if (how) parts.push(how);
    return `${where}<span class="fine">${parts.join(" &middot; ")}</span>${e.fixed ? '<span class="badge">fixed here</span>' : ""}`;
  }

  function fixForm(e, lexicon) {
    const f = fixing;
    return `
      <div class="fixer">
        <label class="note" for="fix-was">Flow wrote</label><input id="fix-was" class="input mono" value="${esc(f.wrong)}" maxlength="40" aria-label="What Flow wrote" data-fix="wrong">
        ${icon("arrow", C.soft, 14)}
        <label class="note" for="fix-said">you said</label><input id="fix-said" class="input mono" value="${esc(f.right)}" maxlength="40" aria-label="What you said" data-fix="right">
        <button type="button" class="btn sm" data-act="history-fix-here" data-id="${esc(e.id)}">Fix it here</button>
        ${lexicon ? `<button type="button" class="btn sm primary" data-act="history-fix-always" data-id="${esc(e.id)}">${icon("check", "#15171C", 14)}Always fix it</button>` : ""}
        <button type="button" class="btn ghost sm" data-act="history-fix-cancel">Cancel</button>
        <p class="fine grow-line">${lexicon ? "Always fix it adds a correction to Voice, so it stops coming out wrong." : "The dictionary is off this launch, so the fix stays in this entry."}</p>
      </div>`;
  }

  function historyEntry(e, lexicon) {
    const acts = `
      <button type="button" class="icon-btn" aria-label="Copy" title="Copy" data-act="history-copy" data-id="${esc(e.id)}">${icon("copy", C.soft, 15)}</button>
      ${e.kind === "set_aside" ? "" : `<button type="button" class="icon-btn" aria-label="Fix a word" title="Fix a word Flow got wrong" data-act="history-fix" data-id="${esc(e.id)}">${icon("pencil", C.soft, 15)}</button>`}
      <button type="button" class="icon-btn" aria-label="Delete" title="Delete" data-act="history-delete" data-id="${esc(e.id)}">${icon("x", C.soft, 14)}</button>`;
    const body = e.kind === "refined" && e.heard
      ? `<div class="was"><span class="label">heard</span><p>${esc(e.heard)}</p></div>
         <div class="sent"><span class="label">sent</span><p class="body" data-text="${esc(e.id)}">${esc(e.text)}</p></div>`
      : `<p class="body" data-text="${esc(e.id)}">${esc(e.text)}</p>`;
    return `
      <article class="entry ${e.kind === "set_aside" ? "aside" : ""}">
        <div class="meta"><span class="time">${esc(e.time)}</span>${entryMeta(e)}<span class="acts">${acts}</span></div>
        ${body}
        ${e.kind === "set_aside" ? `<p class="fine">Sounded like ${esc(e.why || "noise")}. Flow sets aside what might be the room rather than your words, and keeps it here so you can have it back.</p>` : ""}
        ${fixing && fixing.id === e.id ? fixForm(e, lexicon) : ""}
      </article>`;
  }

  function renderHistory(d) {
    const head = (actions) => `
      <div class="page-head"><div class="grow"><h1>History</h1><p class="sub">What you dictated, where it went, and anything Flow set aside.</p></div>${actions || ""}</div>`;
    if (d.choice === "") return head() + keepChoice(d);
    if (d.choice === "off") {
      return head() + `
        <section class="card">
          <div class="row">${icon("lock", C.soft, 18)}<h2 class="grow">History is off</h2><button type="button" class="btn" data-act="history-keep" ${d.profile ? "" : "disabled"}>Keep a history</button></div>
          <p class="note">Flow keeps times and word counts, never the words. Today: ${Number(d.today.words || 0).toLocaleString()} words.</p>
          <p class="fine">Home lists what you said this session, in memory only.</p>
        </section>`;
    }
    const actions = `
      <div class="row">
        <select data-change="history-days" aria-label="How long history is kept">${d.day_choices.map((n) =>
          `<option value="${n}" ${n === d.days ? "selected" : ""}>Keep ${n} days</option>`).join("")}</select>
        <button type="button" class="btn" data-act="${d.paused ? "history-resume" : "history-pause"}">${icon(d.paused ? "play" : "pause", C.text, 14)}${d.paused ? "Resume" : "Pause"}</button>
      </div>`;
    const filters = [["all", "All"], ["dictated", "Dictated"], ["refined", "Refined"], ["set_aside", "Set aside"]];
    let lastDay = "";
    const list = d.entries.map((e) => {
      const heading = e.day !== lastDay ? `<h3 class="day">${esc(e.day)}</h3>` : "";
      lastDay = e.day;
      return heading + historyEntry(e, d.lexicon);
    }).join("");
    const empty = d.query
      ? `<p class="note">Nothing kept matches &ldquo;${esc(d.query)}&rdquo;.</p>`
      : d.counts.all ? '<p class="note">Nothing of this kind is kept yet.</p>'
        : '<p class="note">Nothing kept yet. Dictate something, and it shows up here the moment it is pasted.</p>';
    return head(actions) + `
      ${d.paused ? `<section class="card tight banner"><div class="row">${icon("pause", C.amber, 16)}<p class="note grow">Paused: nothing you say is kept until you resume, or until Flow restarts.</p><button type="button" class="btn sm" data-act="history-resume">Resume</button></div></section>` : ""}
      ${d.error ? `<section class="card tight banner bad"><div class="row">${icon("warn", C.red, 16)}<p class="note grow">${esc(d.error)}</p></div></section>` : ""}
      <div class="toolbar">
        <label class="search">${icon("search", C.soft, 16)}<input id="history-q" type="search" value="${esc(historyView.query)}" placeholder="Search what you said" aria-label="Search history"></label>
        <div class="seg" role="group" aria-label="Show">${filters.map(([k, t]) =>
          `<button type="button" aria-pressed="${d.kind === k ? "true" : "false"}" data-act="history-kind" data-value="${k}">${t}<span class="count">${esc(d.counts[k] || 0)}</span></button>`).join("")}</div>
        <span class="note grow right">Today: ${Number(d.today.words || 0).toLocaleString()} words, ${esc(d.today.pastes)} ${d.today.pastes === 1 ? "paste" : "pastes"}</span>
      </div>
      <div class="entries">${list || empty}</div>
      ${d.more ? `<p class="note">${esc(d.more)} older ${d.more === 1 ? "entry is" : "entries are"} not shown - search to find ${d.more === 1 ? "it" : "them"}.</p>` : ""}
      <hr class="rule">
      <div class="row wrap">${icon("lock", C.soft, 14)}<p class="fine grow">Stored only on this PC, in <span class="mono">${esc(d.path)}</span>, and deleted after ${esc(d.days)} days.${d.paste_last ? ` Paste last (${esc(d.paste_last)}) pastes the newest one again.` : ""}</p>
        <button type="button" class="btn ghost sm" data-act="history-clear" ${d.counts.all ? "" : "disabled"}>Clear dictation history</button>
        <button type="button" class="btn ghost sm danger" data-act="history-off">Stop keeping</button></div>`;
  }

  // ------------------------------------------------------------------ Conversations
  // Which kept conversation is open instead of the live one ("" for the live one), and
  // the question being typed — held here so a re-draw never takes it from under a hand.
  const askView = { conv: "" };
  let askDraft = "";
  let wrapped = null;

  // An answer's text as a page: fenced code as code, `inline code` and **bold** in the
  // prose, everything escaped first so nothing in an answer can become markup.
  function rich(text) {
    const inline = (t) => esc(t).replace(/`([^`\n]+)`/g, "<code>$1</code>").replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>");
    return String(text).split("```").map((part, i) => {
      if (i % 2 === 1) {
        const nl = part.indexOf("\n");
        const lang = nl > 0 ? part.slice(0, nl).trim() : "";
        const code = (nl >= 0 ? part.slice(nl + 1) : part).replace(/\n$/, "");
        return `<pre class="code">${lang && lang.length < 20 ? `<span class="lang">${esc(lang)}</span>` : ""}<code>${esc(code)}</code></pre>`;
      }
      const prose = part.replace(/^\n+|\n+$/g, "");
      return prose ? `<div class="prose">${inline(prose)}</div>` : "";
    }).join("");
  }

  function turn(e, live, cli) {
    if (e.kind === "asked") {
      return `<div class="turn you"><span class="who">${icon(e.via === "typed" ? "pencil" : "mic", C.soft, 13)}you ${e.via === "typed" ? "typed" : "said"} &middot; ${esc(e.time)}</span><p class="said">${esc(e.text)}</p></div>`;
    }
    if (e.failed) {
      return `<div class="turn cli"><div class="answer failed"><span class="who">${icon("warn", C.red, 13)}no answer</span><p class="note">${esc(e.failed)}</p></div></div>`;
    }
    const conv = live ? "" : askView.conv;
    return `
      <div class="turn cli"><div class="answer">
        <span class="who">${glyph(C.ask, 0.62)}${esc(e.cli || cli || "the CLI")}${e.secs != null ? ` &middot; ${esc(e.secs)} s` : ""}</span>
        ${rich(e.text)}
        <div class="row wrap acts">
          <button type="button" class="btn ghost sm" data-act="answer-copy" data-id="${esc(e.id)}">${icon("copy", C.muted, 14)}Copy</button>
          <button type="button" class="btn ghost sm" data-act="answer-note" data-id="${esc(e.id)}" data-conv="${esc(conv)}">${icon("bookmark", C.muted, 14)}Keep note</button>
          <button type="button" class="btn ghost sm" data-act="answer-say" data-id="${esc(e.id)}" data-conv="${esc(conv)}">${icon("speaker", C.muted, 14)}Read aloud</button>
        </div>
      </div></div>`;
  }

  function convoList(d) {
    const cur = d.current;
    const now = `
      <button type="button" class="item" data-act="conv-open" data-conv="" aria-current="${askView.conv ? "false" : "true"}">
        <span class="t">${esc(cur.title || "New conversation")}</span>
        <span class="w">${cur.asking ? "asking now" : cur.exchanges.length ? "now" : "nothing asked yet"}</span></button>`;
    const groups = {};
    d.past.forEach((c) => { (groups[c.ws_leaf || ""] = groups[c.ws_leaf || ""] || []).push(c); });
    const past = Object.entries(groups).map(([leaf, items]) => `
      <div class="label group">${icon(leaf ? "folder" : "chat", C.soft, 13)}${esc(leaf || "No workspace")}</div>
      ${items.map((c) => `<button type="button" class="item" data-act="conv-open" data-conv="${esc(c.conv)}" aria-current="${askView.conv === c.conv ? "true" : "false"}">
        <span class="t">${esc(c.title || "(no question)")}</span><span class="w">${esc(c.when)}</span></button>`).join("")}`).join("");
    const kept = d.keeping ? (past || '<p class="fine pad">Earlier conversations show up here.</p>')
      : `<p class="fine pad">${d.choice === "off" ? "History is off, so a conversation lasts until Flow quits." : "Conversations last until Flow quits."} <a href="#/history">${d.choice === "off" ? "Turn history on" : "Keep a history"}</a> to find them later.</p>`;
    return `<aside class="convo-list" aria-label="Conversations">${now}${kept}</aside>`;
  }

  function renderAsk(d) {
    const cur = d.current;
    const v = d.viewing;
    const shown = v || cur;
    const ws = v ? v.ws : cur.workspace;
    const context = `
      <div class="row wrap context">${icon("folder", ws ? C.green : C.soft, 15)}<span class="mono ellipsis">${esc(ws || "no workspace - answers are about anything")}</span>
        ${v ? "" : `<span class="fine">&middot; ${esc(cur.cli || "no agent CLI")}${cur.effort ? ` &middot; ${esc(cur.effort)} effort` : ""}</span>`}
        ${!v && cur.notes ? `<span class="badge violet">${icon("bookmark", C.ask, 12)}${cur.notes} note${cur.notes === 1 ? "" : "s"} kept</span>
          <button type="button" class="btn sm" data-act="ask-wrap" title="${cur.workspace ? "Writes them to flow-notes in the workspace" : "No workspace: the notes stay on screen"}">Wrap up</button>` : ""}</div>`;
    const turns = shown.exchanges.map((e) => turn(e, !v, cur.cli)).join("");
    const waiting = !v && cur.asking ? `
      <div class="turn cli"><div class="answer pending"><span class="who">${glyph(C.ask, 0.62)}${esc(cur.cli || "the CLI")}</span>
        <div class="thinking"><span class="dot blue"></span>thinking<span class="fine" id="ask-elapsed"></span></div></div></div>` : "";
    const empty = !shown.exchanges.length ? `
      <div class="empty-ask">${glyph(C.ask, 1.6)}<p class="note">Ask anything, like ChatGPT. ${cur.workspace ? `Answers know the code in <span class="mono">${esc(cur.workspace_leaf)}</span>.` : "Set a workspace on Settings and answers know your code."}</p></div>` : "";
    const composer = v ? `
      <section class="card tight banner violet"><div class="row wrap">${icon("history", C.ask, 16)}<p class="note grow">From ${esc(v.when)}. Carrying it on makes it the conversation the pill asks into too${cur.workspace !== v.ws ? `, grounded in ${esc(cur.workspace_leaf || "no workspace")}` : ""}.</p>
        <button type="button" class="btn violet sm" data-act="conv-continue" data-conv="${esc(v.conv)}">Carry on this conversation</button>
        <button type="button" class="btn ghost sm danger" data-act="conv-delete" data-conv="${esc(v.conv)}">Delete</button></div></section>`
      : `
      <div class="composer">
        <textarea id="ask-text" rows="3" placeholder="${shown.exchanges.length ? "Ask a follow-up" : "Ask anything"}" aria-label="Your question" ${cur.cli ? "" : "disabled"}>${esc(askDraft)}</textarea>
        <div class="row wrap"><span class="fine grow">Enter asks, Shift+Enter starts a new line. Or hold the talk keys and dictate into the box.</span>
          <button type="button" class="btn violet" data-act="ask" ${cur.cli && !cur.asking ? "" : "disabled"}>${icon("send", C.ask, 15)}Ask</button></div>
      </div>
      <div class="row">${icon("shield", C.soft, 14)}<p class="fine">${cur.cli ? `Your question${cur.workspace ? ` and the path <span class="mono">${esc(cur.workspace)}</span> go` : " goes"} to ${esc(cur.cli)}. Audio never leaves this PC.` : "No agent CLI found. Install claude or codex and sign in to it to ask."}</p></div>`;
    const wrap = wrapped ? `
      <section class="card">
        <div class="row">${icon("bookmark", C.ask, 16)}<h2 class="grow">Wrapped up ${esc(wrapped.count)} note${wrapped.count === 1 ? "" : "s"}</h2>
          <button type="button" class="btn sm" data-act="wrapped-copy">${icon("copy", C.text, 14)}Copy</button><button type="button" class="icon-btn" aria-label="Close" data-act="wrapped-close">${icon("x", C.soft, 14)}</button></div>
        <p class="note">${wrapped.path ? `Written to <span class="mono">${esc(wrapped.path)}</span>.` : "No workspace is set, so they stay here: copy them."}</p>
        <pre class="code doc"><code>${esc(wrapped.doc)}</code></pre>
      </section>` : "";
    return `
      <div class="page-head"><div class="grow"><h1>Conversations</h1><p class="sub">Ask like ChatGPT, about your code or about anything. Type here, or talk to the pill.</p></div>
        <button type="button" class="btn" data-act="ask-new">${icon("plus", C.text, 15)}New conversation</button></div>
      <div class="convo">
        ${convoList(d)}
        <section class="thread">
          <div class="col"><h2 class="ellipsis">${esc(shown.title || "New conversation")}</h2>${context}</div>
          ${wrap}${empty}${turns}${waiting}${composer}
        </section>
      </div>`;
  }

  // ------------------------------------------------------------------ the first run
  // Five steps, no terminal (the canvas's FirstRun artboard): the two sides, the
  // microphone, the speech model, tuning, and the history question with a box to try it
  // in. The step lives here; everything a step shows comes from /api/start.
  let startStep = 1;
  let tryText = "";
  const STEPS = 5;

  // "ctrl+win" as the keys the page draws, or the pill when there are none this launch.
  const holdKeys = (k) => (k.dictate ? keys(k.dictate) : "<b>the pill</b>");

  function stepWelcome(d) {
    const k = d.keys || {};
    const gesture = k.gesture === "toggle" ? "press, speak, press again" : "hold, speak, let go";
    return `
      <h1 class="fr-title">Talk, and Flow types it. Ask, and it answers.</h1>
      <p class="sub">Two things, one pill. ${esc(gesture[0].toUpperCase() + gesture.slice(1))}.</p>
      <div class="fr-sides">
        <div class="fr-side">${glyph(C.type, 1.3)}<b>Dictate</b><span class="row"><span class="note">hold</span>${holdKeys(k)}</span>
          <span class="note">pastes into the window you were in</span></div>
        <div class="fr-side">${glyph(C.ask, 1.3)}<b>Ask</b><span class="row">${k.mode ? keys(k.mode) : ""}<span class="note">${k.mode ? "then hold" : "tap the pill to violet, then hold"}</span></span>
          <span class="note">the answer rises above the pill, like ChatGPT</span></div>
      </div>
      <p class="fine">${icon("shield", C.soft, 13)} Speech is recognised on this PC. No account, no API key.</p>`;
  }

  function stepMic(d) {
    const m = d.mic;
    const l = m.listen;
    const options = [["", `Windows default${!m.chosen && m.current ? ": " + m.current : ""}`]]
      .concat(m.devices.map((dev) => [dev.name, dev.name]));
    const chosen = m.chosen || "";
    const status = l.state === "failed" ? `<span class="warn">${esc(l.error)}</span>`
      : l.heard ? `<span class="good">${icon("circlecheck", C.green, 15)} Hearing you clearly.</span>`
        : l.state === "listening" ? "Listening - say a few words."
          : m.lent && !l.state.startsWith("listen") ? esc(m.lent) : "";
    return `
      <h1 class="fr-title">Which microphone?</h1>
      <p class="sub">Say something. The bar beside the one you are using should move.</p>
      <div class="fr-list" role="radiogroup" aria-label="Microphone">${options.map(([value, label]) => `
        <label class="fr-option ${value === chosen ? "on" : ""}"><input type="radio" name="fr-mic" value="${esc(value)}" data-change="fr-mic" ${value === chosen ? "checked" : ""}>
          <span class="grow ellipsis">${esc(label)}</span>${value === chosen ? bars(14, l.state === "listening" ? "live" : "") : ""}</label>`).join("")}</div>
      <p class="note fr-status">${status}</p>
      ${l.state !== "listening" ? '<button type="button" class="btn sm" data-act="fr-listen">Listen again</button>' : ""}`;
  }

  function modelLine(t, role) {
    const dl = t.download;
    if (t.installed) return `<div class="fr-model">${icon("circlecheck", C.green, 18)}<span class="mono">${esc(t.name)}</span><span class="note grow">${role}</span><span class="note">on this PC</span></div>`;
    if (dl && dl.state === "running") {
      const pct = dl.total ? Math.min(100, Math.round((dl.done / dl.total) * 100)) : 0;
      return `<div class="fr-model col"><div class="row">${icon("download", C.blue, 18)}<span class="mono">${esc(t.name)}</span><span class="note grow">${role}</span>
        <span class="note">${dl.total ? `${human(dl.done)} of ${human(dl.total)}` : "starting"}</span></div>
        <div class="progress ${pct ? "" : "busy"}"><div data-w="${pct}"></div></div></div>`;
    }
    return `<div class="fr-model">${icon("circle", C.dim, 18)}<span class="mono">${esc(t.name)}</span><span class="note grow">${role}</span>
      ${dl && dl.state === "failed" ? `<span class="note warn ellipsis" title="${esc(dl.error)}">${esc(dl.error)}</span>` : ""}<span class="note">${esc(t.size_text)}</span></div>`;
  }

  function stepModel(d) {
    const m = d.model;
    const gpu = m.gpu && m.gpu.name ? m.gpu.name.replace(/^NVIDIA\s+(GeForce\s+)?/i, "") : "";
    const measuredHere = gpu && m.measured_on.includes(gpu);
    const speed = m.final.speed ? Math.round(m.final.speed) : 0;
    const why = m.device === "cuda" && speed
      ? (measuredHere ? `Your ${esc(gpu)} runs it about ${speed} times faster than you talk.`
        : `On a GTX 1070 it runs about ${speed} times faster than speech; ${esc(gpu || "your card")} is likely no slower.`)
      : m.device === "cuda" ? "It runs on your graphics card." : "It runs on this PC's processor.";
    const action = m.ready
      ? `<p class="note good">${icon("circlecheck", C.green, 15)} ${m.loaded ? "Ready." : m.loading ? "On this PC - loading it now." : "On this PC."}</p>`
      : m.downloading
        ? '<div class="row"><p class="note grow">You can keep going while it downloads. Models in Flow Home can swap it later.</p><button type="button" class="btn ghost sm" data-act="fr-models" data-value="cancel">Cancel</button></div>'
        : `<div class="row"><button type="button" class="btn primary" data-act="fr-models" data-value="download">${icon("download", "#15171C", 15)}Download</button><p class="note grow">You can keep going while it downloads.</p></div>`;
    return `
      <h1 class="fr-title">Getting the speech model</h1>
      <p class="sub">Recommended for this PC: <b>${esc(m.final.name)}</b>. ${why}</p>
      <div class="col">${modelLine(m.final, "writes the words that get pasted")}${modelLine(m.partial, "draws the live preview")}</div>
      ${action}
      ${m.alternative && !m.ready ? `<p class="note">Short on space or time? <button type="button" class="linkish" data-act="fr-models" data-value="smaller">Use ${esc(m.alternative.final)} instead${m.alternative.size_text ? " - " + esc(m.alternative.size_text) : ""}</button></p>` : ""}`;
  }

  function stepTune(d) {
    const t = d.tune;
    const ready = d.model.ready;
    if (t.state === "listening" || t.state === "measuring") {
      const pct = Math.min(100, Math.round((t.elapsed / t.seconds) * 100));
      return `
        <h1 class="fr-title">Let Flow hear you</h1>
        <p class="passage">${esc(t.passage)}</p>
        <div class="progress green"><div data-w="${pct}"></div></div>
        ${t.state === "measuring" ? '<p class="note"><span class="dot blue"></span> Measuring what you read.</p>'
          : `<div class="row">${bars(14, "live")}<span class="note grow">Listening - ${Math.round(t.elapsed)} s. ${t.enough ? "That is enough - finish now, or read to the end." : "Read at your normal pace."}</span>
            <button type="button" class="btn primary" data-act="tune-finish" ${t.enough ? "" : "disabled"}>Done reading</button>
            <button type="button" class="btn ghost" data-act="tune-cancel">Cancel</button></div>`}`;
    }
    const last = t.last;
    return `
      <h1 class="fr-title">Let Flow hear you</h1>
      <p class="sub">Read one paragraph aloud at your normal pace. About 45 seconds; it tunes Flow to your room and your voice.</p>
      ${t.state === "done" ? `<p class="note good">${icon("circlecheck", C.green, 15)} Saved. Flow is listening with these now.</p>` : ""}
      ${t.state === "failed" ? `<p class="note warn">${esc(t.error)}</p>` : ""}
      ${last && t.state !== "done" ? `<p class="note">Already tuned: the room at ${esc(last.floor_db)} dB, your voice at ${esc(last.speech_db)} dB.</p>` : ""}
      ${ready ? `<div class="row"><button type="button" class="btn ${last ? "" : "primary"}" data-act="tune-start" ${t.profile ? "" : "disabled"}>${icon("mic", last ? C.text : "#15171C", 15)}${last || t.state === "done" ? "Tune again" : "Start reading"}</button>
          <span class="note">Nothing leaves this PC. Or skip it - Voice in Flow Home does it any time.</span></div>`
        : `<p class="note">${icon("download", C.soft, 14)} Tuning listens through the speech model, which is still ${d.model.downloading ? "downloading" : "not on this PC"}. Skip it for now - Voice in Flow Home does it any time.</p>`}`;
  }

  function stepFinish(d) {
    const h = d.history;
    const k = d.keys || {};
    const choice = (value, title, note) => `
      <button type="button" class="choice ${h.choice === value ? "picked" : ""}" aria-pressed="${h.choice === value ? "true" : "false"}" data-act="fr-history" data-value="${value}" ${d.profile ? "" : "disabled"}>
        ${icon(value === "keep" ? "history" : "lock", value === "keep" ? C.green : C.soft, 20)}<b>${title}</b><span class="note">${note}</span></button>`;
    const blocked = d.mode !== "dictate"
      ? `<p class="note warn">The pill is on ${esc(MODE_WORD[d.mode] || d.mode)} - tap it until its mic is white, then try this.</p>`
      : !d.model.ready ? '<p class="note warn">The speech model is not on this PC yet - try this once its download finishes.</p>' : "";
    return `
      <h1 class="fr-title">Last thing: keep a history?</h1>
      <p class="sub">Nothing is chosen for you. Pick one; History in Flow Home changes it later.</p>
      <div class="choice-grid">
        ${choice("keep", `Keep what I dictate and ask for ${esc(h.days || 30)} days`, "On this PC only. Find it, copy it again, fix words Flow got wrong.")}
        ${choice("off", "Don't keep it", "Flow keeps times and word counts, never the words.")}
      </div>
      <hr class="rule">
      <h2>Try it</h2>
      <p class="note">${d.lite
        ? `Click in the box, hold the pill, say &ldquo;Flow is ready&rdquo;, let go - then press Ctrl+V in the box: Lite copies instead of pasting.`
        : `Click in the box, hold ${holdKeys(k)}, say &ldquo;Flow is ready&rdquo;, let go.`}</p>
      ${blocked}
      <textarea id="fr-try" class="input fr-try" rows="2" placeholder="Try it here" aria-label="Try it here">${esc(tryText)}</textarea>
      ${tryText.trim() ? `<p class="note good">${icon("circlecheck", C.green, 15)} It works. That is all there is to it.</p>` : ""}`;
  }

  function renderStart(d) {
    const body = [stepWelcome, stepMic, stepModel, stepTune, stepFinish][startStep - 1](d);
    const dots = Array.from({ length: STEPS }, (_, i) => `<span class="fr-dot ${i + 1 === startStep ? "on" : i + 1 < startStep ? "done" : ""}"></span>`).join("");
    const next = startStep === 1 ? "Get started" : startStep === STEPS ? "Open Flow" : "Next";
    const busy = d.tune.state === "listening" || d.tune.state === "measuring";
    return `
      <div class="fr">
        <div class="fr-head"><span class="fr-brand"><span class="brand-mark" aria-hidden="true"></span>Flow</span>
          <span class="fr-dots" aria-hidden="true">${dots}</span><span class="note grow">Step ${startStep} of ${STEPS}</span>
          <button type="button" class="btn ghost sm" data-act="fr-skip">Skip setup</button></div>
        <section class="fr-body">${body}</section>
        <div class="fr-foot">${startStep > 1 ? '<button type="button" class="btn ghost" data-act="fr-back">Back</button>' : ""}<span class="grow"></span>
          <button type="button" class="btn primary" data-act="fr-next" ${busy ? "disabled" : ""}>${next}</button></div>
      </div>`;
  }

  // Leaving a step stops what it left listening: the microphone test is a meter, and a
  // tuning half read is not a tuning.
  async function goStep(n) {
    const from = startStep;
    startStep = Math.max(1, Math.min(STEPS, n));
    if (from === 2 && startStep !== 2) { try { await api("start/listen", { action: "stop" }); } catch (_) { /* gone */ } }
    if (startStep === 2) {
      try { data = await api("start/listen", { action: "start" }); } catch (e) { toast(e.message, true); }
    }
    show(true);
  }

  async function finishStart() {
    try {
      await api("start/done", {});
    } catch (e) {
      if (e instanceof Gone) { gone(e.message); return; }
      toast(e.message, true);
      return;
    }
    location.hash = "#/home";
  }

  // ------------------------------------------------------------------ showing a page
  const LOAD = { home: "home", history: "history", voice: "voice", ask: "ask", models: "models", settings: "settings", start: "start" };
  const DRAW = { home: renderHome, history: renderHistory, voice: renderVoice, ask: renderAsk, models: renderModels, settings: renderSettings, start: renderStart };
  let data = null;
  let shown = "";

  // A page's data as its view stands: History under its filter, Conversations on the
  // kept conversation that is open.
  function fetchPage(name) {
    if (name === "history") return api("history/list", { kind: historyView.kind, query: historyView.query });
    if (name === "ask" && askView.conv) return api("ask/view", { conv: askView.conv });
    return api(LOAD[name]);
  }

  async function show(force = false) {
    const name = current();
    document.body.classList.toggle("first", name === "start");
    renderNav();
    try {
      const fresh = await fetchPage(name);
      if (current() !== name) return;
      data = fresh;
      draw(name, force || shown !== name);
      shown = name;
    } catch (e) {
      if (e instanceof Gone) gone(e.message); else toast(e.message, true);
    }
  }

  // How to find the focused control again after a re-draw replaced it: by id, or by the
  // data attributes that say what it does. Keyboard users keep their place.
  function focusKey(el) {
    if (!el || el === document.body) return "";
    if (el.id) return `#${CSS.escape(el.id)}`;
    const attrs = ["act", "change", "value", "name", "action", "what", "path", "exe", "hotkey",
      "term", "wrong", "right", "id", "conv"]
      .filter((k) => el.dataset && el.dataset[k] !== undefined)
      .map((k) => `[data-${k}="${CSS.escape(el.dataset[k])}"]`);
    return attrs.length ? attrs.join("") : "";
  }

  // The fields a re-draw may happen under: their words live in this script, not in the
  // page, so an answer arriving while somebody types the next question lands without
  // taking the question away.
  const HELD = new Set(["ask-text", "history-q", "fix-was", "fix-said", "fr-try"]);

  // A poll never re-draws under somebody typing; an action they took always re-draws.
  function draw(name, fresh, force = false) {
    const pageEl = document.getElementById("page");
    const active = document.activeElement;
    const typing = active && pageEl.contains(active) && /^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName)
      && !HELD.has(active.id);
    // Nor under somebody selecting words: a poll that re-draws takes the selection with
    // it, and a selection is how a word to fix or to copy gets picked.
    const sel = window.getSelection ? window.getSelection() : null;
    const selecting = sel && !sel.isCollapsed && sel.anchorNode && pageEl.contains(sel.anchorNode);
    if ((typing || selecting) && !fresh && !force) return;
    const key = pageEl.contains(active) ? focusKey(active) : "";
    const caret = active && HELD.has(active.id) ? [active.selectionStart, active.selectionEnd] : null;
    const top = pageEl.scrollTop;
    const bottom = pageEl.scrollHeight - pageEl.clientHeight - top < 40;
    pageEl.innerHTML = DRAW[name](data);
    sizes(pageEl);
    // A conversation reads downward: a page that was at its end stays at its end when an
    // answer lands, so the answer is what is on screen.
    pageEl.scrollTop = fresh ? (name === "ask" ? pageEl.scrollHeight : 0)
      : name === "ask" && bottom ? pageEl.scrollHeight : top;
    if (fresh && name !== "ask") {
      pageEl.focus({ preventScroll: true });
    } else if (key) {
      const again = pageEl.querySelector(key);
      if (again) {
        again.focus({ preventScroll: true });
        if (caret && typeof again.setSelectionRange === "function") {
          try { again.setSelectionRange(caret[0], caret[1]); } catch (_) { /* not a text field */ }
        }
      }
    }
    elapsed();
  }

  // The seconds an answer has been coming, beside "thinking".
  function elapsed() {
    const el = document.getElementById("ask-elapsed");
    if (!el || !data || !data.current) return;
    const asked = [...data.current.exchanges].reverse().find((e) => e.kind === "asked");
    if (asked && asked.at) el.textContent = ` ${Math.max(0, Math.round(Date.now() / 1000 - asked.at))} s`;
  }

  function redrawWith(payload) {
    data = payload;
    draw(current(), false, true);
  }

  // ------------------------------------------------------------------ actions
  const value = (id) => (document.getElementById(id) || {}).value;
  async function run(fn, done) {
    try {
      const out = await fn();
      if (out && typeof out === "object" && !Array.isArray(out) && LOAD[current()]) redrawWith(out);
      if (done) toast(done);
    } catch (e) {
      if (e instanceof Gone) gone(e.message); else toast(e.message, true);
    }
  }
  const redraw = () => { if (data) draw(current(), false, true); };
  const refresh = () => run(() => fetchPage(current()));

  // The clipboard, from the page: a loopback origin is a secure context, and every call
  // here follows a click, which is the permission the browser asks for.
  async function copy(text, said = "Copied") {
    try {
      await navigator.clipboard.writeText(text);
      toast(said);
    } catch (_) {
      toast("Could not copy - select the text and press Ctrl+C", true);
    }
  }

  function findEntry(id) {
    if (!data) return null;
    const pool = data.entries || [].concat((data.current && data.current.exchanges) || [],
      (data.viewing && data.viewing.exchanges) || []);
    return pool.find((e) => e.id === id) || null;
  }

  // The words last selected inside an entry, so "Fix a word" can start from them. Kept
  // on every change rather than read at the click, because the click itself can collapse
  // the selection before the handler runs.
  let lastPick = { id: "", text: "" };
  document.addEventListener("selectionchange", () => {
    const sel = window.getSelection();
    const text = sel ? sel.toString().trim() : "";
    if (!text) return;
    const node = sel.anchorNode;
    const host = node && (node.nodeType === 1 ? node : node.parentElement);
    const el = host && host.closest ? host.closest("[data-text]") : null;
    lastPick = el && text.length <= 40 ? { id: el.dataset.text, text } : { id: "", text: "" };
  });

  function fixEntry(id, always) {
    const wrong = ((fixing && fixing.wrong) || "").trim();
    const right = ((fixing && fixing.right) || "").trim();
    if (!wrong || !right) { toast("Say what Flow wrote, and what you said", true); return; }
    run(async () => {
      const out = await api("history/fix", { id, wrong, right, always, ...historyView });
      fixing = null;
      return out;
    }, always ? `${wrong} becomes ${right} from now on` : "Fixed in this entry");
  }

  async function sendQuestion() {
    const text = askDraft.trim();
    if (!text) return;
    try {
      const out = await api("ask/question", { text });
      askDraft = "";
      askView.conv = "";
      data = out;
      draw("ask", false, true);
      const box = document.getElementById("ask-text");
      if (box) box.focus({ preventScroll: true });
    } catch (e) {
      if (e instanceof Gone) gone(e.message); else toast(e.message, true);
    }
  }

  const ACT = {
    download: (el) => run(() => api("models/download", { name: el.dataset.name }), `Downloading ${el.dataset.name}`),
    cancel: (el) => run(() => api("models/cancel", { name: el.dataset.name }), "Cancelled"),
    delete: (el) => {
      if (!confirm(`Delete ${el.dataset.name} from this PC? You can download it again.`)) return;
      run(() => api("models/delete", { name: el.dataset.name }), `Deleted ${el.dataset.name}`);
    },
    "use-models": () => run(() => api("models/use", {
      final: value("final-model") || null, partial: value("partial-model") || null,
      device: value("decode-device") || "auto",
    }), "Switching models - the pill shows the load"),
    "cli-model": () => run(() => api("agent", { model: value("cli-model") || "" }), "Saved"),
    "cli-timeout": () => run(() => api("agent", { timeout: Number(value("cli-timeout")) }), "Saved"),
    effort: (el) => run(() => api("agent", { effort: el.dataset.value }), `Effort: ${el.dataset.value}`),
    mute: (el) => run(() => api("replies", { muted: el.getAttribute("aria-checked") === "true" })),
    preview: () => run(() => api("replies/preview", {})),
    "tune-start": () => run(() => here(api("voice/tune", { action: "start" }))),
    "tune-finish": () => run(() => here(api("voice/tune", { action: "finish" }))),
    "tune-cancel": () => run(() => here(api("voice/tune", { action: "cancel" })), "Cancelled - nothing was saved"),
    "fr-next": () => (startStep === STEPS ? finishStart() : goStep(startStep + 1)),
    "fr-back": () => goStep(startStep - 1),
    "fr-skip": () => finishStart(),
    "fr-listen": () => run(() => api("start/listen", { action: "start" })),
    "fr-models": (el) => run(() => api("start/models", { action: el.dataset.value }),
      el.dataset.value === "download" ? "Downloading - you can keep going"
        : el.dataset.value === "smaller" ? `Switching to the smaller models` : "Cancelled"),
    "fr-history": (el) => run(() => here(api("history/choice", { choice: el.dataset.value })),
      el.dataset.value === "keep" ? "History is on, on this PC only" : "Nothing you say will be kept"),
    "check-start": () => run(() => api("voice/check", { action: "start" })),
    "check-record": () => run(() => api("voice/check", { action: "record" })),
    "check-stop": () => run(() => api("voice/check", { action: "stop" })),
    "check-cancel": () => run(() => api("voice/check", { action: "cancel" })),
    "history-keep": () => run(() => api("history/choice", { choice: "keep" }), "History is on, on this PC only"),
    "history-decline": () => run(() => api("history/choice", { choice: "off" }), "Nothing you say will be kept"),
    "history-off": () => {
      if (!confirm("Stop keeping history? This deletes everything kept so far - dictation and conversations.")) return;
      run(() => api("history/choice", { choice: "off" }), "History is off, and what was kept is deleted");
    },
    "history-kind": (el) => { historyView.kind = el.dataset.value; fixing = null; refresh(); },
    "history-pause": () => run(() => api("history/pause", { paused: true, ...historyView }), "Paused - nothing is kept until you resume"),
    "history-resume": () => run(() => api("history/pause", { paused: false, ...historyView }), "Keeping again"),
    "history-copy": (el) => { const e = findEntry(el.dataset.id); if (e) copy(e.text); },
    "history-fix": (el) => {
      const id = el.dataset.id;
      fixing = { id, wrong: lastPick.id === id ? lastPick.text : "", right: "" };
      lastPick = { id: "", text: "" };
      redraw();
      const field = document.getElementById(fixing.wrong ? "fix-said" : "fix-was");
      if (field) field.focus();
    },
    "history-fix-cancel": () => { fixing = null; redraw(); },
    "history-fix-here": (el) => fixEntry(el.dataset.id, false),
    "history-fix-always": (el) => fixEntry(el.dataset.id, true),
    "history-delete": (el) => run(() => api("history/delete", { id: el.dataset.id, ...historyView }), "Deleted"),
    "history-clear": () => {
      if (!confirm("Delete every dictation entry kept so far? Conversations stay.")) return;
      run(() => api("history/clear", historyView), "Cleared");
    },
    ask: () => sendQuestion(),
    "ask-new": () => { askView.conv = ""; wrapped = null; run(() => api("ask/new", {})); },
    "conv-open": (el) => { askView.conv = el.dataset.conv || ""; wrapped = null; show(true); },
    "conv-continue": (el) => run(async () => {
      const out = await api("ask/continue", { conv: el.dataset.conv });
      askView.conv = "";
      return out;
    }, "Carried on - ask the next question here or on the pill"),
    "conv-delete": (el) => {
      if (!confirm("Delete this conversation from History?")) return;
      run(async () => {
        const out = await api("ask/delete", { conv: el.dataset.conv });
        askView.conv = "";
        return out;
      }, "Deleted");
    },
    "answer-copy": (el) => { const e = findEntry(el.dataset.id); if (e) copy(e.text); },
    "answer-note": (el) => run(() => api("ask/note", { id: el.dataset.id, conv: el.dataset.conv }), "Kept as a note - Wrap up puts them in one file"),
    "answer-say": (el) => run(() => api("ask/say", { id: el.dataset.id, conv: el.dataset.conv })),
    "ask-wrap": () => run(async () => {
      const out = await api("ask/wrap", { conv: askView.conv });
      wrapped = out.wrapped || null;
      return out;
    }),
    "wrapped-copy": () => { if (wrapped) copy(wrapped.doc); },
    "wrapped-close": () => { wrapped = null; redraw(); },
    "dict-add": (el) => run(() => api("voice/word", { term: el.dataset.term }), `Flow listens for ${el.dataset.term} now`),
    "word-add": () => {
      const term = (value("word-new") || "").trim();
      if (term) run(() => api("voice/word", { term }), `Flow listens for ${term} now`);
    },
    "word-remove": (el) => run(() => api("voice/word/remove", { term: el.dataset.term }), "Removed"),
    "correction-add": () => {
      const wrong = (value("fix-wrong") || "").trim(), right = (value("fix-right") || "").trim();
      if (wrong && right) run(() => api("voice/correction", { wrong, right }), `${wrong} becomes ${right} from now on`);
    },
    "correction-remove": (el) => run(() => api("voice/correction/remove", { wrong: el.dataset.wrong }), "Removed"),
    learned: (el) => run(() => api("voice/learned", { wrong: el.dataset.wrong, right: el.dataset.right, action: el.dataset.action }),
      el.dataset.action === "fix" ? "Fixed every time from now on" : el.dataset.action === "never" ? "Flow will not ask again" : "Forgotten"),
    gesture: (el) => run(() => api("settings/gesture", { gesture: el.dataset.value }), "Changed"),
    chord: () => run(() => api("settings/chord", { keys: value("chord-keys") || "" }), "Saved - applies when Flow next starts"),
    hotkey: (el) => {
      const input = document.querySelector(`[data-hotkey="${el.dataset.action}"]`);
      run(() => api("settings/hotkey", { action: el.dataset.action, combo: input ? input.value : "" }),
        "Saved - applies when Flow next starts");
    },
    "ws-add": () => run(() => api("settings/workspace/add", {})),
    "ws-add-path": () => {
      const path = (value("ws-path") || "").trim();
      if (path) run(() => api("settings/workspace/add", { path }), "Workspace added");
    },
    "ws-forget": (el) => run(() => api("settings/workspace/forget", { path: el.dataset.path })),
    "auto-ask": (el) => run(() => api("settings/auto_ask", { on: el.getAttribute("aria-checked") !== "true" })),
    warm: (el) => run(() => api("settings/warm", { on: el.getAttribute("aria-checked") !== "true" }), "Saved"),
    design: (el) => run(() => api("settings/design", { name: el.dataset.value }), "Switching the pill"),
    "app-add": () => {
      const exe = (value("app-exe") || "").trim(), instruction = (value("app-text") || "").trim();
      if (exe && instruction) run(() => api("settings/apps", { exe, instruction }), "Saved");
    },
    "app-remove": (el) => run(() => api("settings/apps", { exe: el.dataset.exe, instruction: "" })),
    open: (el) => run(() => api("open", { what: el.dataset.what })),
    update: async () => {
      const line = document.getElementById("update-line");
      if (line) line.textContent = "Asking GitHub...";
      try {
        const out = await api("update", {});
        if (line) line.textContent = out.line;
      } catch (e) {
        if (e instanceof Gone) gone(e.message); else if (line) line.textContent = e.message;
      }
    },
  };
  const CHANGE = {
    cli: (el) => run(() => api("agent", { cli: el.value }), el.value === "auto" ? "Automatic" : `Pinned to ${el.value}`),
    voice: (el) => run(() => api("replies", { voice: el.value || null }), "Voice changed"),
    mic: (el) => run(() => api("settings/mic", { name: el.value || null }), "Microphone changed"),
    send: (el) => run(() => api("settings/send", { word: el.value }), `Say "${el.value}" to send`),
    ws: (el) => run(() => api("settings/workspace", { path: el.value || null }), "Workspace changed"),
    panel: (el) => run(() => api("settings/classic", { panel: el.value }), "Saved"),
    place: (el) => run(() => api("settings/classic", { place: el.value }), "Saved"),
    "history-days": (el) => run(() => api("history/days", { days: Number(el.value), ...historyView }), `Kept for ${el.value} days`),
    "fr-mic": (el) => run(() => api("start/mic", { name: el.value || null }), "Microphone changed"),
  };

  // Words being typed into a field a re-draw can happen under are kept here as they
  // are typed, and the search asks again a moment after the typing stops.
  let searchTimer = 0;
  document.addEventListener("input", (ev) => {
    const el = ev.target;
    if (el.id === "fr-try") {
      const had = tryText.trim();
      tryText = el.value;
      if (!had !== !tryText.trim()) redraw();
    } else if (el.id === "ask-text") askDraft = el.value;
    else if (el.dataset && el.dataset.fix && fixing) fixing[el.dataset.fix] = el.value;
    else if (el.id === "history-q") {
      historyView.query = el.value;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(refresh, 250);
    }
  });

  document.addEventListener("click", (ev) => {
    const el = ev.target.closest("[data-act]");
    if (!el || el.disabled) return;
    const fn = ACT[el.dataset.act];
    if (fn) { ev.preventDefault(); fn(el); }
  });
  document.addEventListener("change", (ev) => {
    const el = ev.target.closest("[data-change]");
    if (!el) return;
    const fn = CHANGE[el.dataset.change];
    if (fn) fn(el);
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter" && ev.keyCode !== 13) return;
    const el = ev.target;
    if (el.id === "ask-text") {
      // Enter asks; Shift+Enter is a new line, and an IME still composing owns the key.
      if (!ev.shiftKey && !ev.isComposing) { ev.preventDefault(); sendQuestion(); }
      return;
    }
    if (el.id === "fix-was" || el.id === "fix-said") {
      ev.preventDefault();
      const b = document.querySelector('[data-act="history-fix-always"]') || document.querySelector('[data-act="history-fix-here"]');
      if (b) ACT[b.dataset.act](b);
      return;
    }
    if (el.id === "ws-path") ACT["ws-add-path"]();
    else if (el.id === "cli-model") ACT["cli-model"]();
    else if (el.id === "chord-keys") ACT.chord();
    else if (el.id === "word-new") ACT["word-add"]();
    else if (el.id === "fix-right") ACT["correction-add"]();
  });
  window.addEventListener("hashchange", () => show(true));

  // ------------------------------------------------------------------ the poll
  let polls = 0;
  async function poll() {
    try {
      live = await api("state");
      renderStatus();
      if (live.navigate && live.navigate !== current()) location.hash = "#/" + live.navigate;
      const name = current();
      if (name === "settings") level(document.getElementById("page"), live.capturing ? live.level_db : -90);
      polls += 1;
      // Models refreshes while something is moving on it; Voice while it is listening;
      // Home every few seconds.
      const moving = name === "models" && data && data.speech
        && (data.speech.loading || data.speech.models.some((m) => m.download && m.download.state === "running"));
      const listening = voiceBusy(name);
      // Conversations re-reads when the live conversation moved under it: an answer on
      // its way, a question asked from the pill, a new conversation started there.
      const cur = name === "ask" && data && data.current;
      const talked = cur && (live.asking || cur.asking || live.conversation !== cur.conv
        || live.exchanges !== cur.exchanges.length);
      if (moving || listening || talked || ((name === "home" || name === "history") && polls % 5 === 0)) {
        const fresh = await fetchPage(name);
        if (current() === name) { data = fresh; draw(name, false); }
      }
      if (name === "ask") elapsed();
      // The first run re-reads while something on it is moving: the microphone test,
      // a download, a tuning. Otherwise every two seconds, for the model to finish
      // loading and the pill's mode to come back to Dictate.
      if (name === "start" && data && data.mic) {
        const moving = data.mic.listen.state === "listening" || data.model.downloading
          || ["listening", "measuring"].includes(data.tune.state) || data.model.loading;
        if (moving || polls % 2 === 0) {
          const fresh = await api("start");
          if (current() === "start") { data = fresh; draw("start", false); }
        }
      }
    } catch (e) {
      if (e instanceof Gone) { gone(e.message); return; }
    }
    setTimeout(poll, current() === "settings" || voiceBusy(current()) || startBusy() ? 250 : 1000);
  }

  function startBusy() {
    return current() === "start" && data && data.mic
      && (data.mic.listen.state === "listening" || data.tune.state === "listening");
  }

  // A page reached from the first run gets the first run back, not the page its route
  // was written for: the tuning and history routes answer with Voice and History.
  const here = (promise) => promise.then((out) => (current() === "start" ? api("start") : out));

  function voiceBusy(name) {
    if (name !== "voice" || !data || !data.tune || !data.check) return false;
    return ["listening", "measuring"].includes(data.tune.state)
      || ["recording", "decoding"].includes(data.check.state);
  }

  renderNav();
  renderStatus();
  show(true);
  poll();
})();
