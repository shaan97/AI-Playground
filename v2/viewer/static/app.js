"use strict";
/* Universe control-plane SPA: a runs index, a live/history graph view, an
   Antigravity-style trajectory (whole-run transcript), and an experiment
   launcher. Hash router: #/ = index, #/run/<id> = graph, #/run/<id>/trajectory. */
const $ = (id) => document.getElementById(id);
const LIVE = new Set(["queued", "running", "paused"]);

/* ------------------------------------------------------------------ API */
const API = {
  async listRuns() { return (await fetch("/api/runs")).json(); },
  async meta(id) { return (await fetch(`/api/runs/${enc(id)}/meta`)).json(); },
  async history(id) { return (await fetch(`/api/runs/${enc(id)}/history`)).json(); },
  async trace(id, step, agent) { return (await fetch(`/api/runs/${enc(id)}/trace/${step}/${enc(agent)}`)).json(); },
  async conversation(id, agent) { return (await fetch(`/api/runs/${enc(id)}/conversation/${enc(agent)}`)).json(); },
  async kernels(id) { return (await fetch(`/api/runs/${enc(id)}/kernels`)).json(); },
  async launch(spec) {
    const r = await fetch("/api/runs", { method: "POST", body: JSON.stringify(spec) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `HTTP ${r.status}`);
    return r.json();
  },
  async control(id, action) {
    const r = await fetch(`/api/runs/${enc(id)}/control/${action}`, { method: "POST" });
    return r.json();
  },
};
function enc(s) { return encodeURIComponent(s); }
function esc(s) { return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

/* ------------------------------------------------------------------ router */
window.addEventListener("hashchange", route);
function route() {
  const h = location.hash.replace(/^#/, "") || "/";
  const m = h.match(/^\/run\/([^/]+)(\/trajectory)?$/);
  if (m) { showRun(decodeURIComponent(m[1]), !!m[2]); }
  else { showIndex(); }
}

/* ------------------------------------------------------------------ index */
async function showIndex() {
  Run.teardown();
  $("indexBar").style.display = "";
  $("index").style.display = "";
  $("runView").classList.remove("show");
  const el = $("index");
  el.innerHTML = `<div class="empty-note">loading runs…</div>`;
  let runs = [];
  try { runs = await API.listRuns(); } catch (e) { el.innerHTML = `<div class="empty-note">could not load runs</div>`; return; }
  if (!runs.length) {
    el.innerHTML = `<div class="empty-note">No runs yet.<br/>Tap <b>＋ New experiment</b> to launch one.</div>`;
    return;
  }
  const grid = document.createElement("div");
  grid.className = "grid";
  runs.forEach((r) => grid.appendChild(runCard(r)));
  el.innerHTML = "";
  el.appendChild(grid);
}

function runCard(r) {
  const c = document.createElement("div");
  c.className = "card";
  const cfg = r.config || {};
  const cfgBits = [];
  if (cfg.kind) cfgBits.push(cfg.kind);
  if (cfg.model) cfgBits.push(cfg.model);
  if (cfg.level !== undefined && cfg.level !== null) cfgBits.push("L" + cfg.level);
  const agents = (r.agents || []).map((a) => `<span class="tagchip">${esc(a)}</span>`).join("") ||
    `<span class="meta">no agents recorded</span>`;
  c.innerHTML =
    `<div class="idline"><span class="rid">${esc(r.id)}</span>` +
    `<span class="badge ${r.status}">${esc(r.status)}</span></div>` +
    `<div class="meta"><span>${r.steps} steps</span>${cfgBits.map((b) => `<span>${esc(b)}</span>`).join("")}</div>` +
    `<div class="agents">${agents}</div>`;
  c.addEventListener("click", () => { location.hash = `#/run/${enc(r.id)}`; });
  return c;
}

$("newBtn").addEventListener("click", openLauncher);
$("refreshBtn").addEventListener("click", showIndex);

/* ================================================================== RUN VIEW */
const Run = {
  id: null, meta: null, history: [], agents: new Set(), registry: null,
  cur: 0, follow: true, playing: false, selected: null, tab: "state",
  es: null, playTimer: null, live: false, mode: "graph", kernels: {},
  teardown() {
    if (this.es) { this.es.close(); this.es = null; }
    if (this.playTimer) { clearInterval(this.playTimer); this.playTimer = null; }
    this.playing = false; this.selected = null; closeSheet();
  },
};

async function showRun(id, trajectory) {
  const fresh = Run.id !== id;
  if (fresh) { Run.teardown(); Object.assign(Run, { id, history: [], agents: new Set(), cur: 0, follow: true, selected: null }); }
  $("indexBar").style.display = "none";
  $("index").style.display = "none";
  $("runView").classList.add("show");
  $("runTitle").textContent = id;

  if (fresh) {
    try {
      Run.meta = await API.meta(id);
      Run.agents = new Set(Run.meta.agents || []);
      Run.registry = Run.meta.registry;
      Run.live = LIVE.has(Run.meta.status);
      const hist = await API.history(id);
      hist.forEach((s) => { Run.history[s.step] = s; });
      try { Run.kernels = await API.kernels(id); } catch (e) { Run.kernels = {}; }
    } catch (e) { toast("could not load run"); return; }
    ensureCy();
    populateAgentSelect();
    setupOperator();
    scrub.max = lastStep();
    gotoStep(lastStep());
    if (Run.live) connectStream(); else setConn("done");
  }
  setMode(trajectory ? "trajectory" : "graph");
  if (trajectory) renderTrajectory();
}

$("backBtn").addEventListener("click", () => { location.hash = "#/"; });
$("segGraph").addEventListener("click", () => { location.hash = `#/run/${enc(Run.id)}`; });
$("segTraj").addEventListener("click", () => { location.hash = `#/run/${enc(Run.id)}/trajectory`; });

function setMode(mode) {
  Run.mode = mode;
  $("runView").classList.toggle("trajectory", mode === "trajectory");
  $("segGraph").classList.toggle("on", mode === "graph");
  $("segTraj").classList.toggle("on", mode === "trajectory");
  if (mode === "graph" && cy) cy.resize();
}

/* ---------------- cytoscape (lazy) ---------------- */
let cy = null;
function ensureCy() {
  if (cy) { applyStep(Run.history[Run.cur]); return; }
  cy = cytoscape({
    container: $("cy"), minZoom: 0.2, maxZoom: 3, wheelSensitivity: 0.25,
    style: [
      { selector: "node", style: { "background-color": "#7ee0c0", "label": "data(label)",
          "color": "#cfe0ff", "font-size": 11, "text-valign": "bottom", "text-margin-y": 4,
          "width": "data(size)", "height": "data(size)", "border-width": 2, "border-color": "#0b0e14",
          "transition-property": "background-color, width, height, border-color", "transition-duration": "200ms" } },
      { selector: "node.agent", style: { "background-color": "#6ea8fe" } },
      { selector: "node.registry", style: { "background-color": "#c79bff" } },
      { selector: "node.sel", style: { "border-color": "#ffffff", "border-width": 3 } },
      { selector: "node.acted", style: { "border-color": "#46d17f", "border-width": 3 } },
      { selector: "edge", style: { "width": 1.4, "line-color": "#2c3856", "target-arrow-color": "#2c3856",
          "target-arrow-shape": "triangle", "arrow-scale": 0.8, "curve-style": "bezier", "opacity": 0.75 } },
      { selector: "edge.inc", style: { "line-color": "#6ea8fe", "target-arrow-color": "#6ea8fe", "opacity": 1, "width": 2 } },
      { selector: "edge.out", style: { "line-color": "#7ee0c0", "target-arrow-color": "#7ee0c0", "opacity": 1, "width": 2 } },
    ],
  });
  cy.on("tap", "node", (e) => openSheet(e.target.id()));
  cy.on("tap", (e) => { if (e.target === cy) closeSheet(); });
  applyStep(Run.history[Run.cur]);
}
function colorOf(id) {
  if (id === Run.registry) return "registry";
  if (Run.agents.has(id)) return "agent";
  return "object";
}
function runLayout() {
  cy.layout({ name: "cose", animate: true, animationDuration: 500, nodeRepulsion: 9000,
    idealEdgeLength: 90, edgeElasticity: 120, gravity: 0.4, numIter: 600, randomize: false,
    fit: true, padding: 60 }).run();
}
function applyStep(snap) {
  if (!snap || !cy) return;
  const ids = new Set(Object.keys(snap.states));
  let topo = false;
  cy.batch(() => {
    cy.nodes().forEach((n) => { if (!ids.has(n.id())) { n.remove(); topo = true; } });
    ids.forEach((id) => {
      let n = cy.getElementById(id);
      if (n.empty()) { cy.add({ group: "nodes", data: { id, label: id, size: 26 } }); n = cy.getElementById(id); topo = true; }
      n.data("state", snap.states[id]);
      n.removeClass("agent registry object acted");
      n.addClass(colorOf(id));
      if ((snap.traced || []).includes(id)) n.addClass("acted");
      n.data("size", Math.max(22, Math.min(46, 22 + countIn(snap, id) * 5)));
    });
    const want = new Set();
    for (const [u, outs] of Object.entries(snap.arcs || {})) for (const w of outs) if (ids.has(w)) want.add(u + " " + w);
    cy.edges().forEach((e) => { if (!want.has(e.id())) { e.remove(); topo = true; } });
    want.forEach((eid) => {
      if (cy.getElementById(eid).empty()) { const [u, w] = eid.split(" "); cy.add({ group: "edges", data: { id: eid, source: u, target: w } }); topo = true; }
    });
  });
  if (topo) runLayout();
  if (Run.selected) highlightNeighbours(Run.selected);
}
function countIn(snap, id) { let c = 0; for (const outs of Object.values(snap.arcs || {})) if (outs.includes(id)) c++; return c; }
function highlightNeighbours(id) {
  cy.elements().removeClass("sel inc out");
  const n = cy.getElementById(id); if (n.empty()) return;
  n.addClass("sel"); n.outgoers("edge").addClass("out"); n.incomers("edge").addClass("inc");
}

/* ---------------- bottom sheet ---------------- */
async function openSheet(id) {
  Run.selected = id; highlightNeighbours(id);
  const cls = colorOf(id);
  $("sheetTitle").textContent = id;
  const tag = $("sheetTag"); tag.className = "tag " + cls; tag.textContent = cls;
  // Live runs create objects and their errors change over time — refresh the
  // kernel map so the Code tab (and its visibility) reflects the current step.
  if (Run.live) { try { Run.kernels = await API.kernels(Run.id); } catch (e) {} }
  if (Run.selected !== id) return;  // a newer tap superseded this one
  const hasCode = !!(Run.kernels && Run.kernels[id]);
  $("tabTrace").style.display = Run.agents.has(id) ? "" : "none";
  $("tabCode").style.display = hasCode ? "" : "none";
  // A dot on the Code tab when the object's last transition errored.
  const errored = hasCode && Run.kernels[id].error;
  $("tabCode").classList.toggle("has-err", !!errored);
  $("tabCode").textContent = errored ? "Code ⚠" : "Code";
  if (Run.tab === "trace" && !Run.agents.has(id)) setTab("state");
  if (Run.tab === "code" && !hasCode) setTab("state");
  renderSheet(); $("sheet").classList.add("open");
}
function closeSheet() { $("sheet").classList.remove("open"); Run.selected = null; if (cy) cy.elements().removeClass("sel inc out"); }
$("sheetClose").addEventListener("click", closeSheet);
function setTab(t) {
  Run.tab = t;
  $("tabState").classList.toggle("on", t === "state");
  $("tabCode").classList.toggle("on", t === "code");
  $("tabTrace").classList.toggle("on", t === "trace");
  renderSheet();
}
$("tabState").addEventListener("click", () => setTab("state"));
$("tabCode").addEventListener("click", () => setTab("code"));
$("tabTrace").addEventListener("click", () => setTab("trace"));

function renderSheet() {
  const id = Run.selected; if (!id) return;
  const body = $("sheetBody");
  if (Run.tab === "trace") { renderTraceTab(id, body); return; }
  if (Run.tab === "code") { renderCodeTab(id, body); return; }
  const snap = Run.history[Run.cur];
  const state = snap ? snap.states[id] : null;
  const arcs = (snap && snap.arcs) || {};
  const observes = arcs[id] || [];
  const observedBy = Object.entries(arcs).filter(([, o]) => o.includes(id)).map(([u]) => u);
  body.innerHTML = "";
  body.appendChild(chipSection("Observes  (its inputs →)", observes));
  body.appendChild(chipSection("Observed by  (← can influence)", observedBy));
  const lbl = document.createElement("div"); lbl.className = "section-label"; lbl.textContent = "State";
  body.appendChild(lbl);
  const pre = document.createElement("pre"); pre.className = "state"; pre.innerHTML = jsonHtml(state);
  body.appendChild(pre);
}
function chipSection(label, ids) {
  const wrap = document.createElement("div");
  const l = document.createElement("div"); l.className = "section-label";
  l.textContent = label + (ids.length ? "  (" + ids.length + ")" : ""); wrap.appendChild(l);
  const chips = document.createElement("div"); chips.className = "chips";
  if (!ids.length) { const c = document.createElement("span"); c.className = "chip empty"; c.textContent = "none"; chips.appendChild(c); }
  else ids.forEach((nid) => { const c = document.createElement("span"); c.className = "chip"; c.textContent = nid; c.addEventListener("click", () => openSheet(nid)); chips.appendChild(c); });
  wrap.appendChild(chips); return wrap;
}
async function renderTraceTab(id, body) {
  body.innerHTML = '<div class="section-label">loading turn…</div>';
  let data; try { data = await API.trace(Run.id, Run.cur, id); } catch (e) { body.innerHTML = '<div class="section-label">could not load trace</div>'; return; }
  if (Run.selected !== id || Run.tab !== "trace") return;
  const msgs = (data && data.messages) || [];
  if (!msgs.length) { body.innerHTML = `<div class="section-label">No turn at step ${Run.cur}. Scrub to a step where this agent is outlined green.</div>`; return; }
  body.innerHTML = `<div class="section-label">Turn at step ${Run.cur} — ${msgs.length} messages</div>`;
  msgs.forEach((m) => body.appendChild(msgCard(m)));
}

/* The behaviour of a runtime-created object: its transition source, plus the
   most recent error if its code raised (which is why it may look inert — a
   crashing transition silently holds its state). */
async function renderCodeTab(id, body) {
  let entry = Run.kernels && Run.kernels[id];
  if (!entry || Run.live) {
    if (!entry) body.innerHTML = '<div class="section-label">loading code…</div>';
    try { Run.kernels = await API.kernels(Run.id); } catch (e) {}
    if (Run.selected !== id || Run.tab !== "code") return;
    entry = Run.kernels && Run.kernels[id];
  }
  body.innerHTML = "";
  if (!entry) { body.appendChild(el("div", "section-label", "No source recorded for this object.")); return; }
  if (entry.error) {
    body.appendChild(el("div", "section-label", "Last transition error"));
    const e = document.createElement("pre"); e.className = "state err"; e.textContent = entry.error;
    body.appendChild(e);
    body.appendChild(el("div", "code-hint",
      "This object's code raised on its most recent step, so it held its state instead of updating. Fix the transition to make its state advance."));
  }
  body.appendChild(el("div", "section-label", "transition(state, inputs, emit)"));
  const pre = document.createElement("pre"); pre.className = "state code";
  pre.textContent = entry.code || "(no code)";
  body.appendChild(pre);
}

/* ---------------- trajectory (whole-run transcript) ---------------- */
function populateAgentSelect() {
  const sel = $("agentSel"); const prev = sel.value; sel.innerHTML = "";
  const agents = [...Run.agents].sort();
  agents.forEach((a) => { const o = document.createElement("option"); o.value = a; o.textContent = a; sel.appendChild(o); });
  if (prev && Run.agents.has(prev)) sel.value = prev;
  sel.onchange = renderTrajectory;
  $("segTraj").style.display = agents.length ? "" : "none";
}
async function renderTrajectory() {
  const body = $("trajBody");
  const agent = $("agentSel").value || [...Run.agents][0];
  if (!agent) { body.innerHTML = `<div class="empty-note">This run has no agent transcripts.</div>`; return; }
  body.innerHTML = `<div class="empty-note">loading trajectory…</div>`;
  let conv; try { conv = await API.conversation(Run.id, agent); } catch (e) { body.innerHTML = `<div class="empty-note">could not load trajectory</div>`; return; }
  if (Run.mode !== "trajectory") return;
  body.innerHTML = "";
  if (conv.system) {
    const sys = msgCard({ role: "system", content: conv.system });
    body.appendChild(sys);
  }
  if (!conv.turns.length) { body.appendChild(el("div", "empty-note", "No turns recorded for this agent.")); return; }
  conv.turns.forEach((turn) => {
    const div = document.createElement("div"); div.className = "step-div";
    div.innerHTML = `<span>Step ${turn.step}</span>`;
    div.style.cursor = "pointer";
    div.title = "view this step in the graph";
    div.addEventListener("click", () => { location.hash = `#/run/${enc(Run.id)}`; gotoStep(turn.step, true); });
    body.appendChild(div);
    turn.messages.forEach((m) => body.appendChild(msgCard(m)));
  });
}

/* ---------------- shared message card ---------------- */
function msgCard(m) {
  const role = m.role || "?";
  const card = document.createElement("div"); card.className = "msg";
  const head = document.createElement("div"); head.className = "msg-head";
  head.innerHTML = `<span class="role ${role}">${role}</span><span class="msg-prev">${esc(previewOf(m))}</span><span class="caret">›</span>`;
  card.appendChild(head);
  const body = document.createElement("div"); body.className = "msg-body";
  if (m.reasoning) { const r = document.createElement("div"); r.className = "reasoning"; r.textContent = m.reasoning; body.appendChild(r); }
  if (m.content) { const p = document.createElement("div"); p.textContent = m.content; body.appendChild(p); }
  (m.tool_calls || []).forEach((tc) => {
    const fn = tc.function || {};
    let args = fn.arguments; try { args = JSON.stringify(JSON.parse(args), null, 2); } catch (e) {}
    const d = document.createElement("div"); d.className = "toolcall";
    d.innerHTML = `<span class="fn">${esc(fn.name || "fn")}</span>(<br/>${esc(typeof args === "string" ? args : JSON.stringify(args, null, 2))}<br/>)`;
    body.appendChild(d);
  });
  if (!m.content && !m.reasoning && !(m.tool_calls || []).length) body.textContent = "(empty)";
  card.appendChild(body);
  head.addEventListener("click", () => card.classList.toggle("open"));
  if (role === "assistant" || role === "tool") card.classList.add("open");
  return card;
}
function previewOf(m) {
  if (m.tool_calls && m.tool_calls.length) return m.tool_calls.map((t) => (t.function && t.function.name) || "call").join(", ");
  return (m.content || m.reasoning || "").replace(/\s+/g, " ").slice(0, 90);
}
function el(tag, cls, txt) { const e = document.createElement(tag); if (cls) e.className = cls; if (txt) e.textContent = txt; return e; }

/* ---------------- JSON pretty-print ---------------- */
function jsonHtml(v) {
  if (v === undefined) return '<span class="nl">undefined</span>';
  const json = JSON.stringify(v, null, 2);
  if (json === undefined) return esc(String(v));
  return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
    (match) => { let cls = "n"; if (/^"/.test(match)) cls = /:$/.test(match) ? "k" : "s"; else if (/true|false/.test(match)) cls = "b"; else if (/null/.test(match)) cls = "nl"; return `<span class="${cls}">${esc(match)}</span>`; });
}

/* ---------------- transport ---------------- */
const scrub = $("scrub");
function lastStep() { return Math.max(0, Run.history.length - 1); }
function updateStepLabels() {
  const max = lastStep();
  $("stepLabel").textContent = `${Run.cur} / ${max}`;
  $("prevBtn").disabled = Run.cur <= 0; $("nextBtn").disabled = Run.cur >= max;
}
function gotoStep(i, fromUser) {
  i = Math.max(0, Math.min(i, lastStep())); Run.cur = i; scrub.value = i;
  applyStep(Run.history[i]);
  if (Run.selected) renderSheet();
  if (fromUser && i < lastStep()) setLive(false);
  updateStepLabels();
}
function stepBy(d) { setPlaying(false); gotoStep(Run.cur + d, true); }
function setLive(on) { Run.follow = on; $("liveBtn").classList.toggle("on", on); if (on) { setPlaying(false); gotoStep(lastStep()); } }
function setPlaying(on) { Run.playing = on; $("playBtn").textContent = on ? "❚❚" : "▶"; $("playBtn").classList.toggle("on", on); }
scrub.addEventListener("input", () => gotoStep(parseInt(scrub.value, 10), true));
$("liveBtn").addEventListener("click", () => setLive(!Run.follow));
$("prevBtn").addEventListener("click", () => stepBy(-1));
$("nextBtn").addEventListener("click", () => stepBy(1));
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
  if (Run.mode !== "graph" || !$("runView").classList.contains("show")) return;
  if (e.key === "ArrowLeft") { e.preventDefault(); stepBy(-1); }
  else if (e.key === "ArrowRight") { e.preventDefault(); stepBy(1); }
});
$("playBtn").addEventListener("click", () => {
  if (Run.playing) { setPlaying(false); return; }
  if (Run.cur >= lastStep()) Run.cur = 0; setLive(false); setPlaying(true);
});
Run.playTimer = null;
setInterval(() => {
  if (!Run.playing) return;
  if (Run.cur >= Run.history.length - 1) { setPlaying(false); return; }
  gotoStep(Run.cur + 1);
}, 900);

/* ---------------- live stream ---------------- */
function connectStream() {
  const from = Run.history.length;
  const es = new EventSource(`/api/runs/${enc(Run.id)}/stream?from=${from}`);
  Run.es = es;
  es.addEventListener("hello", (ev) => { ingestMeta(JSON.parse(ev.data)); setConn("live"); });
  es.addEventListener("step", (ev) => { setConn("live"); pushSnap(JSON.parse(ev.data)); });
  es.addEventListener("control", (ev) => applyControl(JSON.parse(ev.data).state));
  es.onerror = () => { setConn("replay"); es.close(); if (Run.id) setTimeout(() => { if (Run.id && Run.live) connectStream(); }, 2500); };
}
function ingestMeta(meta) {
  if (meta.agents) { Run.agents = new Set(meta.agents); populateAgentSelect(); }
  if (meta.registry) Run.registry = meta.registry;
  if (meta.control) applyControl(meta.control);
  Run.live = LIVE.has(meta.status);
}
function pushSnap(snap) {
  // On a freshly launched run the hello meta may predate any agent turns, so
  // learn agents from `traced` (and the registry from genesis) as steps arrive.
  let grew = false;
  (snap.traced || []).forEach((a) => { if (!Run.agents.has(a)) { Run.agents.add(a); grew = true; } });
  if (grew) populateAgentSelect();
  if (!Run.registry && snap.states && snap.states.registry) Run.registry = "registry";
  Run.history[snap.step] = snap; scrub.max = lastStep();
  if (Run.follow && Run.mode === "graph") gotoStep(lastStep()); else updateStepLabels();
}
function setConn(state) {
  const dot = $("conn");
  dot.className = "dot " + (state === "live" ? "live" : state === "replay" ? "replay" : "");
  dot.title = state === "live" ? "live" : state === "replay" ? "reconnecting…" : state === "done" ? "archived" : "—";
}

/* ---------------- operator controls ---------------- */
function setupOperator() {
  const show = Run.live;
  ["runState", "pauseBtn", "stopBtn"].forEach((id) => $(id).classList.toggle("hidden", !show));
  if (show) applyControl(Run.meta.control);
  $("liveBtn").classList.toggle("hidden", !show);
}
const Control = { state: "running" };
function applyControl(state) {
  if (!state) return; Control.state = state;
  const pill = $("runState"); pill.textContent = state; pill.className = "pill run-" + state;
  const pause = $("pauseBtn"), stop = $("stopBtn");
  if (state === "stopped") { pause.disabled = true; stop.disabled = true; Run.live = false; setConn("done"); }
  else { pause.disabled = false; stop.disabled = false; pause.textContent = state === "paused" ? "▶" : "⏸"; pause.title = state === "paused" ? "resume" : "pause"; }
}
$("pauseBtn").addEventListener("click", async () => {
  if (Control.state === "stopped") return;
  const action = Control.state === "paused" ? "resume" : "pause";
  try { const d = await API.control(Run.id, action); if (d.state) applyControl(d.state); } catch (e) { toast("control failed"); }
});
$("stopBtn").addEventListener("click", () => { if (Control.state !== "stopped") $("confirmModal").classList.add("open"); });
$("confirmCancel").addEventListener("click", () => $("confirmModal").classList.remove("open"));
$("confirmStop").addEventListener("click", async () => {
  $("confirmModal").classList.remove("open");
  applyControl("stopped");
  try { await API.control(Run.id, "stop"); } catch (e) {}
  toast("Run stopped — saved for inspection.");
});

/* ---------------- launcher ---------------- */
function openLauncher() { syncKind(); $("launchModal").classList.add("open"); }
$("f_kind").addEventListener("change", syncKind);
function syncKind() {
  const gemma = $("f_kind").value === "gemma";
  document.querySelectorAll(".gemma-only").forEach((e) => e.classList.toggle("hidden", !gemma));
}
$("launchCancel").addEventListener("click", () => $("launchModal").classList.remove("open"));
$("launchModal").addEventListener("click", (e) => { if (e.target.id === "launchModal") $("launchModal").classList.remove("open"); });
$("confirmModal").addEventListener("click", (e) => { if (e.target.id === "confirmModal") $("confirmModal").classList.remove("open"); });
$("launchGo").addEventListener("click", async () => {
  const kind = $("f_kind").value;
  const spec = {
    kind, steps: parseInt($("f_steps").value || "0", 10), delay: parseFloat($("f_delay").value || "1"),
  };
  if (kind === "gemma") {
    Object.assign(spec, {
      model: $("f_model").value.trim() || "gemma4", url: $("f_url").value.trim(),
      agents: parseInt($("f_agents").value || "1", 10), level: parseInt($("f_level").value, 10),
      system: $("f_system").value.trim() || null, bare: $("f_bare").checked, continuous: $("f_continuous").checked,
    });
  }
  try {
    const r = await API.launch(spec);
    $("launchModal").classList.remove("open");
    toast("Launched " + r.id);
    location.hash = `#/run/${enc(r.id)}`;
  } catch (e) { toast("launch failed: " + e.message); }
});

/* ---------------- toast ---------------- */
let toastTimer;
function toast(msg) { const t = $("toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 2600); }

route();
