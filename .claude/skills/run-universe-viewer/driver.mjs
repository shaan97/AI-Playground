#!/usr/bin/env node
// Driver for the Universe phone viewer (a web app served by v2/viewer).
//
// Drives the *running* viewer over the Chrome DevTools Protocol using Node's
// built-in global WebSocket (Node >= 22) — no npm dependencies. It launches a
// headless Chrome/Edge, navigates to the viewer, waits for the graph to render,
// then screenshots three views and drives the real UI (selects the agent vertex
// and opens its Trace tab via the page's own functions). CDP captures on demand,
// so the live SSE stream does not block the screenshot.
//
// Prereq: a viewer must already be serving (see SKILL.md), e.g.
//   python v2/examples/viewer_demo.py --steps 30 --delay 0.6 --port 8000
//
// Usage:
//   node .claude/skills/run-universe-viewer/driver.mjs [URL] [OUTDIR]
//   URL     default http://127.0.0.1:8000
//   OUTDIR  default ./_viewer_shots   (PNG screenshots land here)
//   env CHROME=<path to chrome/edge> to override browser autodetect

import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const URL = process.argv[2] || "http://127.0.0.1:8000";
const OUTDIR = process.argv[3] || join(process.cwd(), "_viewer_shots");
const DBG_PORT = 9333;
const W = 430, H = 932; // iPhone-ish portrait — this is a phone-first UI

const BROWSERS = [
  process.env.CHROME,
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].filter(Boolean);

const browser = BROWSERS.find((p) => existsSync(p));
if (!browser) { console.error("No Chrome/Edge found. Set CHROME=<path>."); process.exit(2); }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function getJSON(u) { return (await fetch(u)).json(); }

// ---- tiny CDP client over the browser WebSocket (flat sessions) ----------
function cdpClient(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let id = 0;
  const pending = new Map();
  const ready = new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const { resolve, reject } = pending.get(m.id);
      pending.delete(m.id);
      m.error ? reject(new Error(m.error.message)) : resolve(m.result);
    }
  };
  const send = (method, params = {}, sessionId) =>
    new Promise((resolve, reject) => {
      const msg = { id: ++id, method, params };
      if (sessionId) msg.sessionId = sessionId;
      pending.set(msg.id, { resolve, reject });
      ws.send(JSON.stringify(msg));
    });
  return { ready, send, close: () => ws.close() };
}

async function main() {
  mkdirSync(OUTDIR, { recursive: true });

  // 1. Sanity-check the HTTP/JSON API before touching the browser.
  const meta = await getJSON(`${URL}/api/meta`);
  console.log(`[api] meta: ${JSON.stringify(meta)}`);
  if (!(meta.count > 0)) throw new Error("viewer has no snapshots — is the world stepping?");
  const hist = await getJSON(`${URL}/api/history`);
  console.log(`[api] history: ${hist.length} snapshots`);
  const agent = (meta.agents || [])[0];
  if (agent) {
    const tracedStep = [...hist].reverse().find((s) => (s.traced || []).includes(agent));
    if (tracedStep) {
      const tr = await getJSON(`${URL}/api/trace/${tracedStep.step}/${agent}`);
      console.log(`[api] trace ${agent}@${tracedStep.step}: ${tr.messages.length} messages`);
    }
  }

  // 2. Launch a headless browser with isolated profile + remote debugging.
  const profile = join(tmpdir(), `viewer_drv_${Date.now()}`);
  const proc = spawn(browser, [
    "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    `--user-data-dir=${profile}`, `--remote-debugging-port=${DBG_PORT}`,
    `--window-size=${W},${H}`, "about:blank",
  ], { stdio: "ignore" });
  proc.on("error", (e) => { console.error("browser spawn failed:", e); process.exit(2); });

  // 3. Wait for the DevTools endpoint, then connect to the browser target.
  let version;
  for (let i = 0; i < 40; i++) {
    try { version = await getJSON(`http://127.0.0.1:${DBG_PORT}/json/version`); break; }
    catch { await sleep(250); }
  }
  if (!version) throw new Error("DevTools endpoint never came up");
  const cdp = cdpClient(version.webSocketDebuggerUrl);
  await cdp.ready;

  const { targetId } = await cdp.send("Target.createTarget", { url: "about:blank", width: W, height: H, newWindow: true });
  const { sessionId } = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
  const S = (m, p) => cdp.send(m, p, sessionId);
  await S("Page.enable");
  await S("Runtime.enable");
  await S("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 2, mobile: true });

  const evalJs = async (expr) => {
    const r = await S("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + " :: " + expr);
    return r.result.value;
  };
  const shot = async (name) => {
    const { data } = await S("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    const path = join(OUTDIR, name);
    writeFileSync(path, Buffer.from(data, "base64"));
    console.log(`[shot] ${path}`);
    return path;
  };

  // 4. Navigate and wait for Cytoscape + the first snapshot to render.
  await S("Page.navigate", { url: URL });
  // NB: the page uses `const cy`/`const App` in a classic script, so they are
  // NOT properties of window — reference the bare identifiers via typeof.
  let rendered = false, last = "";
  for (let i = 0; i < 60; i++) {
    last = await evalJs(
      "JSON.stringify({" +
      "lib:(typeof cytoscape!=='undefined')," +
      "n:(typeof cy!=='undefined'?cy.nodes().length:-1)," +
      "h:(typeof App!=='undefined'?App.history.length:-1)})");
    const { n, h } = JSON.parse(last);
    if (n > 0 && h > 0) { rendered = true; break; }
    await sleep(500);
  }
  if (!rendered) throw new Error(`graph never rendered (state=${last}; CDN blocked / no internet?)`);
  await sleep(1500); // let the force layout settle
  await shot("01-graph.png");

  // 5. Drive the real UI: select the agent vertex (opens the bottom sheet).
  if (agent) {
    await evalJs(`openSheet(${JSON.stringify(agent)})`);
    await sleep(700);
    await shot("02-vertex-state.png");

    // 6. Switch to the Trace tab (fetches + renders the agent's turn).
    await evalJs(`setTab('trace')`);
    await sleep(1500);
    const cards = await evalJs("document.querySelectorAll('#sheetBody .msg').length");
    console.log(`[ui] trace cards rendered: ${cards}`);
    await shot("03-agent-trace.png");

    // 6b. Freeze the run (also verifies Pause), then deterministically step
    // through history with the in-sheet ‹ › and transport ‹ › arrows.
    await evalJs("document.getElementById('pauseBtn').click()");
    await sleep(500);
    const paused = await evalJs("document.getElementById('runState').textContent");
    console.log(`[ui] after pause: runState=${paused}`);
    await evalJs("setTab('state')");
    const c0 = await evalJs("App.cur");
    await evalJs("document.getElementById('sheetPrev').click()");
    await sleep(250);
    const c1 = await evalJs("App.cur");
    await evalJs("document.getElementById('prevBtn').click()");
    await sleep(250);
    const c2 = await evalJs("App.cur");
    await evalJs("document.getElementById('sheetNext').click()");
    await sleep(250);
    const c3 = await evalJs("App.cur");
    console.log(`[ui] step nav: start=${c0} sheetPrev=${c1} prevBtn=${c2} sheetNext=${c3}`);
    if (!(c1 === c0 - 1 && c2 === c1 - 1 && c3 === c2 + 1)) throw new Error("step arrows did not move as expected");
    await shot("05-step-nav.png");
    // Resume (verifies the toggle back to running).
    await evalJs("document.getElementById('pauseBtn').click()");
    await sleep(400);
    const resumed = await evalJs("document.getElementById('runState').textContent");
    console.log(`[ui] after resume: runState=${resumed}`);
  }

  // 7. Operator controls: open the "Are you sure?" stop modal, screenshot, cancel.
  await evalJs("document.getElementById('stopBtn').click()");
  await sleep(400);
  const modalOpen = await evalJs("document.getElementById('modal').classList.contains('open')");
  console.log(`[ui] stop-confirm modal open: ${modalOpen}`);
  await shot("04-confirm-modal.png");
  await evalJs("document.getElementById('modalCancel').click()");
  await sleep(200);

  // 9. Report and tear down the browser (leaves the python server untouched).
  console.log(`\nPASS — viewer driven over CDP. Screenshots in ${OUTDIR}`);
  await cdp.send("Target.closeTarget", { targetId });
  cdp.close();
  proc.kill();
}

main().catch((e) => { console.error("FAIL:", e.message); process.exit(1); });
