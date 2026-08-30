/* reelpipe desktop ui. plain js, no build step. python side is window.pywebview.api */

"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  models: [],
  defaults: {},
  envKeys: {},
  videoExts: ["mp4", "mov", "m4v", "mkv", "avi", "webm", "mpg", "mpeg", "ts", "m2ts", "mts", "wmv", "flv", "mxf"],
  audioExts: ["mp3", "wav", "m4a", "aac", "flac", "ogg", "opus", "aif", "aiff", "wma"],
  source: null,      // {path, name, duration, width, height, fps}
  options: {},
  slug: null,
  prompts: [],
  results: null,
  vcache: {},        // clip index -> cache-bust counter
  runStages: [],
  timer: null,
  startedAt: 0,
};

const STAGE_LABELS = {
  probe: "Read the media",
  transcribe: "Transcribe with whisper",
  prompt: "Build the prompt",
  select: "Ask the API",
  anchor: "Anchor picks to words",
  cut: "Cut clips",
  handoff: "Write the Resolve handoff",
};

/* ---------- low-poly background ---------- */

function drawPoly(dark = false) {
  const svg = $("poly");
  const W = 1600, H = 1000, COLS = 16, ROWS = 10;
  let seed = 20250827;
  const rand = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const pts = [];
  for (let r = 0; r <= ROWS; r++) {
    pts[r] = [];
    for (let c = 0; c <= COLS; c++) {
      const edgeX = c === 0 || c === COLS, edgeY = r === 0 || r === ROWS;
      pts[r][c] = [
        (c / COLS) * W + (edgeX ? 0 : (rand() - 0.5) * (W / COLS) * 0.9),
        (r / ROWS) * H + (edgeY ? 0 : (rand() - 0.5) * (H / ROWS) * 0.9),
      ];
    }
  }
  const tris = [];
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      const a = pts[r][c], b = pts[r][c + 1], d = pts[r + 1][c], e = pts[r + 1][c + 1];
      if (rand() > 0.5) tris.push([a, b, e], [a, e, d]);
      else tris.push([a, b, d], [b, e, d]);
    }
  }
  const stroke = dark ? "rgba(255,255,255,0.05)" : "rgba(255,255,255,0.65)";
  svg.innerHTML = tris.map((t) => {
    const accent = rand() > 0.96;
    const h = accent ? 222 : 210 + rand() * 20;
    const s = accent ? (dark ? 40 : 55) : (dark ? 10 : 14) + rand() * (dark ? 8 : 12);
    const l = dark
      ? (accent ? 17 + rand() * 4 : 10 + rand() * 5)
      : (accent ? 91 + rand() * 3 : 94 + rand() * 4.5);
    return `<polygon points="${t.map((p) => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ")}"` +
      ` fill="hsl(${h.toFixed(0)},${s.toFixed(0)}%,${l.toFixed(1)}%)" stroke="${stroke}" stroke-width="1.1"/>`;
  }).join("");
}

function applyTheme(dark, persist) {
  state.dark = !!dark;
  document.body.classList.toggle("dark", state.dark);
  drawPoly(state.dark);
  $("set-dark").checked = state.dark;
  if (persist) call("set_ui", { dark: state.dark });
}

/* ---------- helpers ---------- */

function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

function fmtClock(seconds, tenths = false) {
  seconds = Math.max(0, Number(seconds) || 0);
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const ss = tenths ? s.toFixed(1).padStart(4, "0") : String(Math.floor(s)).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

function parseClock(text) {
  const parts = String(text).trim().replace(",", ".").split(":");
  if (!parts.length || parts.some((p) => p.trim() === "" || isNaN(Number(p)))) return null;
  return parts.reduce((total, p) => total * 60 + Number(p), 0);
}

let toastTimer = null;
function toast(message, isError = false, ms = 0) {
  const el = $("toast");
  el.textContent = message;
  el.classList.toggle("error", isError);
  el.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), ms || (isError ? 6000 : 2600));
}

function fmtBytes(bytes) {
  if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + " GB";
  if (bytes >= 1e6) return Math.round(bytes / 1e6) + " MB";
  return Math.max(1, Math.round(bytes / 1e3)) + " KB";
}

function api() {
  // pywebview injects the api object a moment before the methods land on it,
  // so "exists" isn't "ready" — probe for an actual function
  const bridge = window.pywebview && window.pywebview.api;
  return bridge && typeof bridge.boot === "function" ? bridge : null;
}

const AUTH_TOKEN = new URLSearchParams(location.search).get("t") || "";

async function httpCall(name, args) {
  // the custom header is what makes this uforgeable cross-origin; the token proves same-app
  const reply = await fetch(`/api/${name}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Reelpipe": AUTH_TOKEN },
    body: JSON.stringify({ args }),
  });
  if (!reply.ok) throw new Error(`backend replied ${reply.status}`);
  return reply.json();
}

async function call(name, ...args) {
  try {
    // the js bridge when it works; plain http to the same backend when it doesn't
    if (api()) return await api()[name](...args);
    return await httpCall(name, args);
  } catch (err) {
    toast(String(err && err.message || err), true);
    return null;
  }
}

/* progress events arrive by bridge push, or by polling when the bridge is out */
let lastSeq = 0;
let poller = null;

function startPolling() {
  if (poller) return;
  const tick = async () => {
    try {
      const reply = await fetch(`/api/events?after=${lastSeq}`, { headers: { "X-Reelpipe": AUTH_TOKEN } });
      if (reply.ok) for (const event of (await reply.json()).events) reelApp.onEvent(event);
    } catch { /* transient, next tick retries */ }
    // self-rescheduling so a slow poll can't stack requests
    if (poller) poller = setTimeout(tick, 700);
  };
  poller = setTimeout(tick, 700);
}

function stopPolling() {
  if (poller) { clearTimeout(poller); poller = null; }
}

function show(name) {
  for (const section of document.querySelectorAll(".screen")) {
    section.classList.toggle("hidden", section.id !== `screen-${name}`);
  }
  for (const tab of document.querySelectorAll(".nav button")) {
    tab.classList.toggle("on", tab.dataset.nav === (name === "settings" ? "settings" : "home"));
  }
  window.scrollTo(0, 0);
}

/* the pipeline's warning strings are written for the terminal; translate for the ui */
const WARN_REWRITES = [
  [/padded up to the (\d+)s floor/, "extended to meet the $1-second minimum"],
  [/trimmed to the (\d+)s cap/, "shortened to the $1-second maximum"],
  [/start quote only matched [\d.]+.*/, "check the start point"],
  [/end quote only matched [\d.]+.*/, "check the end point"],
  [/fell back to the model's approximate times/, "timing is approximate, check it"],
  [/end landed before the start.*/, "check the end point"],
  [/transcript had no words.*/, "no transcript words, timing unverified"],
];

function humanizeWarnings(warnings) {
  const parts = (warnings || []).map((raw) => {
    for (const [pattern, replacement] of WARN_REWRITES) {
      if (pattern.test(raw)) return raw.replace(pattern, replacement);
    }
    return raw;
  });
  const text = parts.join("; ");
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

function segmented(el, value, onchange) {
  el.dataset.value = value;
  for (const btn of el.querySelectorAll("button")) {
    btn.classList.toggle("on", btn.dataset.value === value);
    btn.onclick = () => { segmented(el, btn.dataset.value, onchange); if (onchange) onchange(btn.dataset.value); };
  }
}

/* ---------- events from python ---------- */

window.reelApp = {
  onNativeDrop(paths) {
    chooseSources(Array.isArray(paths) ? paths : [paths]);
  },
  onEvent(event) {
    if (event.seq) {
      if (event.seq <= lastSeq) return; // bridge push and poller can overlap
      lastSeq = event.seq;
    }
    switch (event.type) {
      case "log": appendLog(event.line); break;
      case "stage": setStage(event.stage, event.state); break;
      case "progress": setProgress(event.frac); break;
      case "job": state.slug = event.ref || event.slug; break;
      case "ready": break; // batch job transcribed; it shows up in the jobs list
      case "batch_start": showBatch(event.total); break;
      case "batch_item": setBatchItem(event.index, event.total, event.name); break;
      case "batch_done":
        stopTimer();
        toast(`${event.done} of ${event.total} transcribed. Open each from Previous jobs.`, false, 6000);
        goHome();
        break;
      case "awaiting":
        stopTimer();
        state.slug = event.ref || event.slug;
        state.prompts = event.prompts || [];
        renderPaste([]);
        show("paste");
        break;
      case "done":
        stopTimer();
        state.slug = event.ref || event.slug;
        state.results = event.results;
        state.vcache = {};
        renderResults();
        show("results");
        break;
      case "error":
        stopTimer();
        markActiveStageFailed();
        toast(event.message || "something went wrong", true);
        runningToHomeButton();
        break;
      case "cancelled":
        stopTimer();
        toast("cancelled");
        goHome();
        break;
    }
  },
};

/* ---------- boot ---------- */

let booted = false;
async function init() {
  if (booted) return;
  booted = true;
  let boot = null;
  for (let attempt = 0; attempt < 5 && !boot; attempt++) {
    boot = await call("boot");
    if (!boot) await new Promise((r) => setTimeout(r, 500));
  }
  if (!boot) { booted = false; return; } // exhausted retries; a later trigger can retry
  // start the poll cursor past existing history so a reload never replays old events
  lastSeq = Math.max(lastSeq, boot.seq || 0);
  state.models = boot.models;
  state.defaults = boot.defaults;
  state.envKeys = boot.env_keys;
  applyBoot(boot);
  buildSetupForm();
  if (boot.busy) toast("a job from a previous window is still running", true);
  checkUpdate(true);
}

const INSTALL_CMDS = { Darwin: "brew install ffmpeg", Windows: "winget install Gyan.FFmpeg" };

function applyBoot(boot) {
  renderDoctor(boot.doctor);
  renderJobs(boot.jobs);
  if (boot.video_exts) state.videoExts = boot.video_exts;
  if (boot.audio_exts) state.audioExts = boot.audio_exts;
  if (boot.ui && !!boot.ui.dark !== state.dark) applyTheme(boot.ui.dark, false);
  state.ffmpegOk = !!boot.doctor.ffmpeg;
  $("ffmpeg-block").classList.toggle("hidden", state.ffmpegOk);
  $("dropzone").classList.toggle("disabled", !state.ffmpegOk);
  $("ffmpeg-cmd").textContent = INSTALL_CMDS[boot.platform] || "sudo apt install ffmpeg";
}

function renderDoctor(doctor) {
  const chips = [];
  chips.push(doctor.ffmpeg
    ? `<span class="chip ok" title="${esc(doctor.ffmpeg)}">ffmpeg</span>`
    : `<span class="chip bad" title="install ffmpeg and restart">ffmpeg missing</span>`);
  const backend = (doctor.backends || []).find((row) => row[0] === "chosen backend");
  const name = backend ? backend[1] : "none";
  chips.push(name.startsWith("none")
    ? `<span class="chip bad" title="${esc(name)}">whisper missing</span>`
    : `<span class="chip ok">whisper: ${esc(name)}</span>`);
  $("doctor").innerHTML = chips.join("");
}

function renderJobs(jobs) {
  const block = $("jobs-block");
  if (!jobs || !jobs.length) { block.classList.add("hidden"); return; }
  block.classList.remove("hidden");
  $("jobs").innerHTML = jobs.map((job) =>
    `<button class="job-row" data-ref="${esc(job.ref || job.slug)}">` +
    `<span>${esc(job.slug)}${job.kind === "audio" ? ' <span class="kindtag">audio</span>' : ""}</span>` +
    `<span class="status ${esc(job.status)}">${esc(job.status)}</span></button>`
  ).join("");
  for (const row of $("jobs").querySelectorAll(".job-row")) {
    row.onclick = () => resumeJob(row.dataset.ref);
  }
}

async function resumeJob(ref) {
  const info = await call("resume", ref);
  if (!info) return;
  state.slug = info.ref || info.slug;
  if (info.status === "awaiting") {
    state.prompts = info.prompts || [];
    renderPaste(info.responses || []);
    show("paste");
  } else if (info.status === "done") {
    state.results = info.results;
    state.vcache = {};
    renderResults();
    show("results");
  } else if (info.status === "responded" || info.status === "anchored") {
    const stages = info.status === "anchored" ? ["cut", "handoff"] : ["anchor", "cut", "handoff"];
    const started = await call("finish_job", state.slug);
    if (started && started.error) { toast(started.error, true); return; }
    showRunning("Finishing " + info.slug, stages);
  } else {
    toast("That job never finished. Drop the file again.", true);
  }
}

/* ---------- home / picking a file ---------- */

function wireHome() {
  const zone = $("dropzone");
  for (const eventName of ["dragover", "dragenter"]) {
    zone.addEventListener(eventName, (e) => { e.preventDefault(); zone.classList.add("hover"); });
  }
  for (const eventName of ["dragleave", "drop"]) {
    zone.addEventListener(eventName, (e) => { e.preventDefault(); zone.classList.remove("hover"); });
  }
  // dropped file paths arrive through python (pywebview only exposes them to
  // handlers registered via its dom api), see reelApp.onNativeDrop
  zone.addEventListener("dblclick", browse);
  $("browse").addEventListener("click", (e) => { e.stopPropagation(); browse(); });
}

function ffmpegGate() {
  if (state.ffmpegOk) return true;
  toast("Install ffmpeg first.", true);
  return false;
}

async function browse() {
  if (!ffmpegGate()) return;
  const info = await call("pick_source");
  if (info) acceptSources([info.path]);
}

async function chooseSources(paths) {
  if (!ffmpegGate()) return;
  await acceptSources(paths);
}

async function acceptSources(paths) {
  const infos = [];
  for (const path of paths) {
    const info = await call("inspect", path);
    if (!info) return;
    if (info.error) { toast(info.error, true); return; }
    infos.push(info);
  }
  if (!infos.length) return;
  state.sources = infos;
  if (infos.length === 1) {
    const info = infos[0];
    $("setup-name").textContent = info.name;
    const bits = [fmtClock(info.duration) + " long"];
    if (info.has_video && info.width) bits.push(`${info.width}×${info.height} @ ${Number(info.fps).toFixed(2).replace(/\.?0+$/, "")} fps`);
    if (!info.has_video) bits.push("audio only");
    $("setup-meta").textContent = bits.join(" · ");
  } else {
    $("setup-name").textContent = `${infos.length} files`;
    $("setup-meta").textContent = infos.map((i) => i.name).join(", ");
  }
  show("setup");
}

/* ---------- setup form ---------- */

function buildSetupForm() {
  const d = state.defaults;
  $("opt-model").innerHTML = state.models.map((m) => `<button data-value="${esc(m)}">${esc(m)}</button>`).join("");
  segmented($("opt-model"), d.asr_model);
  segmented($("opt-profile"), d.prompt_profile);
  segmented($("opt-format"), d.render_vertical ? "vertical" : "landscape");
  segmented($("opt-llm"), d.llm_mode, (value) => $("api-panel").classList.toggle("hidden", value !== "api"));
  $("api-panel").classList.toggle("hidden", d.llm_mode !== "api");
  segmented($("opt-provider"), d.llm_provider, updateKeyHint);
  updateKeyHint();

  const bindRange = (input, output, value, fmt) => {
    input.value = value;
    output.textContent = fmt(input.value);
    input.addEventListener("input", () => output.textContent = fmt(input.value));
  };
  bindRange($("opt-count"), $("out-count"), d.clips_count, (v) => v);
  bindRange($("opt-length"), $("out-length"), d.clips_target_seconds || 30, (v) => `~${v}s`);
  bindRange($("opt-min"), $("out-min"), d.clips_min_seconds, (v) => `${v}s`);
  bindRange($("opt-max"), $("out-max"), d.clips_max_seconds, (v) => `${v}s`);
  $("opt-min").addEventListener("input", () => {
    if (Number($("opt-max").value) < Number($("opt-min").value)) {
      $("opt-max").value = $("opt-min").value;
      $("out-max").textContent = `${$("opt-max").value}s`;
    }
  });
  $("opt-max").addEventListener("input", () => {
    if (Number($("opt-min").value) > Number($("opt-max").value)) {
      $("opt-min").value = $("opt-max").value;
      $("out-min").textContent = `${$("opt-min").value}s`;
    }
  });
  const lengthPanels = (mode) => {
    $("len-auto").classList.toggle("hidden", mode !== "auto");
    $("len-range").classList.toggle("hidden", mode !== "range");
  };
  const lenMode = d.length_mode === "range" ? "range" : "auto";
  segmented($("opt-lenmode"), lenMode, lengthPanels);
  lengthPanels(lenMode);

  $("opt-leadin").value = d.clips_lead_in;
  $("opt-leadout").value = d.clips_lead_out;
  $("opt-language").value = d.asr_language;
  $("opt-energy").checked = !!d.energy_enabled;
  $("opt-burn").checked = !!d.render_burn_subs;
}

function updateKeyHint() {
  const provider = $("opt-provider").dataset.value || "anthropic";
  $("key-hint").textContent = state.envKeys[provider] ? "found in environment, leave blank to use it" : "";
}

function collectOptions() {
  return {
    asr_model: $("opt-model").dataset.value,
    asr_language: $("opt-language").value.trim(),
    clips_count: Number($("opt-count").value),
    clips_target_seconds: $("opt-lenmode").dataset.value === "auto" ? Number($("opt-length").value) : 0,
    clips_min_seconds: Number($("opt-min").value),
    clips_max_seconds: Number($("opt-max").value),
    clips_lead_in: Number($("opt-leadin").value) || 0,
    clips_lead_out: Number($("opt-leadout").value) || 0,
    energy_enabled: $("opt-energy").checked,
    prompt_profile: $("opt-profile").dataset.value,
    render_burn_subs: $("opt-burn").checked,
    render_vertical: $("opt-format").dataset.value === "vertical",
    llm_mode: $("opt-llm").dataset.value,
    llm_provider: $("opt-provider").dataset.value,
    length_mode: $("opt-lenmode").dataset.value,
  };
}

async function startJob() {
  const options = collectOptions();
  if (options.llm_mode === "api") {
    const key = $("opt-key").value.trim();
    if (key) await call("set_api_key", options.llm_provider, key);
  }
  state.options = options;
  const sources = state.sources || [];
  if (sources.length > 1) {
    const started = await call("start_batch", sources.map((s) => s.path), options);
    if (!started) return;
    if (started.error) { toast(started.error, true); return; }
    showBatch(sources.length);
    return;
  }
  const stages = options.llm_mode === "api"
    ? ["probe", "transcribe", "prompt", "select", "anchor", "cut", "handoff"]
    : ["probe", "transcribe", "prompt"];
  const started = await call("start", sources[0].path, options);
  if (!started) return;
  if (started.error) { toast(started.error, true); return; }
  showRunning("Cutting " + sources[0].name, stages);
}

/* ---------- running ---------- */

function showRunning(title, stages, sub) {
  state.runStages = stages;
  $("run-title").textContent = title;
  $("run-sub").textContent = sub || "";
  $("run-sub").classList.toggle("hidden", !sub);
  $("stages").innerHTML = stages.map((s) =>
    `<li data-stage="${s}"><span class="dot"></span>${STAGE_LABELS[s] || s}</li>`).join("");
  setProgress(null);
  $("logbox").textContent = "";
  const cancelBtn = $("cancel");
  cancelBtn.textContent = "Cancel";
  cancelBtn.disabled = false;
  cancelBtn.onclick = async () => {
    await call("cancel");
    cancelBtn.textContent = "Cancelling…";
    cancelBtn.disabled = true;
  };
  startTimer();
  show("running");
}

function showBatch(total) {
  showRunning("Batch", ["probe", "transcribe", "prompt"], `Preparing ${total} files`);
}

function setBatchItem(index, total, name) {
  $("run-title").textContent = `File ${index} of ${total}`;
  $("run-sub").textContent = name;
  $("run-sub").classList.remove("hidden");
  for (const li of document.querySelectorAll("#stages li")) li.classList.remove("running", "done", "error");
  setProgress(null);
}

function setProgress(frac) {
  const bar = $("progress");
  if (frac === null || frac === undefined) { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");
  $("progress-bar").style.width = `${Math.round(Math.max(0, Math.min(1, frac)) * 100)}%`;
}

function setStage(stage, stageState) {
  const li = document.querySelector(`#stages li[data-stage="${stage}"]`);
  if (!li) return;
  li.classList.remove("running", "done", "error");
  li.classList.add(stageState);
  // the progress bar belongs to transcription; clear it as soon as we leave that stage
  if (stage === "transcribe" && stageState === "running") setProgress(0);
  else if (stage === "transcribe") setProgress(null);
  else if (stageState === "running") setProgress(null);
}

function markActiveStageFailed() {
  const li = document.querySelector("#stages li.running");
  if (li) { li.classList.remove("running"); li.classList.add("error"); }
}

function runningToHomeButton() {
  const cancelBtn = $("cancel");
  cancelBtn.textContent = "← Home";
  cancelBtn.disabled = false;
  cancelBtn.onclick = goHome;
}

function appendLog(line) {
  const box = $("logbox");
  const lines = (box.textContent ? box.textContent.split("\n") : []).concat(line);
  box.textContent = lines.slice(-200).join("\n");
  box.scrollTop = box.scrollHeight;
}

function startTimer() {
  state.startedAt = Date.now();
  stopTimer();
  $("elapsed").textContent = "0:00";
  state.timer = setInterval(() => {
    $("elapsed").textContent = fmtClock((Date.now() - state.startedAt) / 1000);
  }, 1000);
}

function stopTimer() {
  if (state.timer) { clearInterval(state.timer); state.timer = null; }
}

/* ---------- paste ---------- */

function renderPaste(prefill) {
  const many = state.prompts.length > 1;
  $("prompts").innerHTML = state.prompts.map((_, index) =>
    `<div class="prompt-block" data-index="${index}">
      <div class="prompt-bar">
        <b>${many ? `Prompt ${index + 1} of ${state.prompts.length}` : "Prompt"}</b>
        <button class="btn ghost small copy-prompt">Copy prompt</button>
      </div>
      <textarea placeholder="paste the reply here"></textarea>
      <div class="parse-note"></div>
    </div>`).join("");
  for (const block of $("prompts").querySelectorAll(".prompt-block")) {
    const index = Number(block.dataset.index);
    const area = block.querySelector("textarea");
    area.value = (prefill && prefill[index]) || "";
    block.querySelector(".copy-prompt").onclick = async () => {
      const result = await call("copy_text", state.prompts[index]);
      if (result && result.ok) toast("Prompt copied.");
      else toast((result && result.error) || "copy failed", true);
    };
    let debounce = null;
    area.addEventListener("input", () => {
      clearTimeout(debounce);
      debounce = setTimeout(() => validateResponse(block), 500);
    });
    if (area.value) validateResponse(block);
  }
  updateApplyButton();
}

async function validateResponse(block) {
  const note = block.querySelector(".parse-note");
  const text = block.querySelector("textarea").value;
  if (!text.trim()) { note.textContent = ""; note.className = "parse-note"; block.dataset.ok = ""; updateApplyButton(); return; }
  const result = await call("check_response", text);
  if (result && result.ok) {
    note.textContent = `${result.picks} pick${result.picks === 1 ? "" : "s"} found`;
    note.className = "parse-note ok";
    block.dataset.ok = "1";
  } else {
    note.textContent = (result && result.error) || "couldn't parse that";
    note.className = "parse-note bad";
    block.dataset.ok = "";
  }
  updateApplyButton();
}

function updateApplyButton() {
  const blocks = [...$("prompts").querySelectorAll(".prompt-block")];
  $("apply").disabled = !blocks.length || !blocks.every((b) => b.dataset.ok === "1");
}

async function applyResponses() {
  const texts = [...$("prompts").querySelectorAll("textarea")].map((a) => a.value);
  const started = await call("submit_responses", state.slug, texts);
  if (!started) return;
  if (started.error) { toast(started.error, true); return; }
  showRunning("Cutting " + state.slug, ["anchor", "cut", "handoff"]);
}

/* ---------- results ---------- */

function videoUrl(clip) {
  const version = state.vcache[clip.index] || 0;
  return `${clip.video}?v=${version}`;
}

function jobRef() {
  return state.results && (state.results.ref || state.results.slug);
}

function renderResults() {
  closeTheater();
  const results = state.results;
  $("res-title").textContent = results.slug;
  $("res-path").textContent = results.root;
  $("clips").innerHTML = "";
  for (const clip of results.clips) $("clips").appendChild(clipCard(clip));
  $("handoff").innerHTML = (results.handoff || []).map((name) =>
    `<button data-file="${esc(name)}">${esc(name)}</button>`).join("");
  for (const btn of $("handoff").querySelectorAll("button")) {
    btn.onclick = () => call("reveal", jobRef(), "handoff/" + btn.dataset.file);
  }
  $("handoff-card").classList.toggle("hidden", !(results.handoff || []).length);
  const burnable = !results.burned && (results.clips || []).some((c) => c.kind === "video" && c.rendered);
  $("burn-all").classList.toggle("hidden", !burnable);
}

function clipCard(clip) {
  const card = document.createElement("div");
  card.className = "clip-card";
  card.dataset.index = clip.index;
  const note = humanizeWarnings(clip.warnings);
  const version = state.vcache[clip.index] || 0;
  const poster = clip.poster ? ` poster="${esc(clip.poster)}?v=${version}"` : "";
  const player = !clip.rendered
    ? `<div class="clip-note">not rendered yet</div>`
    : clip.kind === "audio"
      ? `<div class="audio-wrap"><audio controls preload="metadata" src="${esc(videoUrl(clip))}"></audio></div>`
      : `<div class="vid-wrap${clip.vertical ? " vert" : ""}"><video controls preload="metadata"${poster} src="${esc(videoUrl(clip))}"></video><button class="expand" title="fullscreen">⛶</button></div>`;
  card.innerHTML = `
    ${player}
    <div class="clip-title" title="${esc(clip.title)}"><span class="idx">${String(clip.index).padStart(2, "0")}</span>${esc(clip.title)}</div>
    <div class="clip-meta">
      <span>${fmtClock(clip.start)} &ndash; ${fmtClock(clip.end)}</span>
      <span>${clip.duration.toFixed(1)}s</span>
      <span title="how confidently the quoted words were found in the transcript">match <b>${Math.round(clip.match * 100)}%</b></span>
    </div>
    ${note ? `<div class="clip-note" title="${esc((clip.warnings || []).join("; "))}">${esc(note)}</div>` : ""}
    <div class="clip-foot">
      <button class="btn small adjust">Adjust splice</button>
      <div class="clip-files">
        <button class="show-media">${esc((clip.ext || ".mp4").slice(1))}</button>
        <button class="edit-subs">subtitles</button>
        <button class="copy-caption">caption</button>
        <button class="delete">delete</button>
      </div>
    </div>`;

  const expand = card.querySelector(".expand");
  if (expand) expand.onclick = () => openTheater(card.querySelector("video"));
  card.querySelector(".adjust").onclick = () => openEditor(clip);
  card.querySelector(".delete").onclick = () => deleteClip(clip);
  card.querySelector(".show-media").onclick = () => call("reveal", jobRef(), `clips/${clip.slug}${clip.ext || ".mp4"}`);
  card.querySelector(".edit-subs").onclick = () => openSubEditor(clip);
  card.querySelector(".copy-caption").onclick = async () => {
    const blob = [clip.caption, (clip.hashtags || []).join(" ")].filter(Boolean).join("\n");
    const result = await call("copy_text", blob || clip.title);
    if (result && result.ok) toast("caption copied");
  };
  return card;
}

async function deleteClip(clip) {
  const sure = await askConfirm(`Delete clip ${String(clip.index).padStart(2, "0")} "${clip.title}"?`);
  if (!sure) return;
  const result = await call("delete_clip", jobRef(), clip.index);
  if (!result) return;
  if (result.error) { toast(result.error, true); return; }
  state.results = result.results;
  renderResults();
  toast("clip deleted");
}

/* ---------- theater (in-window fullscreen) ---------- */

const theater = { video: null, parent: null, next: null };

function openTheater(video) {
  if (!video || theater.video) return;
  theater.video = video;
  theater.parent = video.parentNode;
  theater.next = video.nextSibling;
  $("theater-slot").appendChild(video);
  $("theater").classList.remove("hidden");
}

function closeTheater() {
  const video = theater.video;
  if (!video) return;
  theater.parent.insertBefore(video, theater.next);
  theater.video = theater.parent = theater.next = null;
  $("theater").classList.add("hidden");
}

/* ---------- subtitle text editor ---------- */

const subedit = { clip: null };

async function openSubEditor(clip) {
  const data = await call("get_subtitles", jobRef(), clip.index);
  if (!data) return;
  if (data.error) { toast(data.error, true); return; }
  if (!(data.cues || []).length) { toast("No subtitles in this clip."); return; }
  subedit.clip = clip;
  $("sub-title").textContent = `${String(clip.index).padStart(2, "0")}  ${clip.title}`;
  $("sub-rows").innerHTML = data.cues.map((cue, i) =>
    `<div class="cue-row"><span class="cue-time">${fmtClock(cue.start, true)}</span><input type="text" data-cue="${i}" value="${esc(cue.text)}"></div>`).join("");
  $("subedit").classList.remove("hidden");
}

function closeSubEditor() {
  $("subedit").classList.add("hidden");
  subedit.clip = null;
}

async function saveSubtitles() {
  const texts = [...$("sub-rows").querySelectorAll("input")].map((el) => el.value);
  const button = $("sub-save");
  button.disabled = true;
  button.textContent = "Saving…";
  const result = await call("set_subtitles", jobRef(), subedit.clip.index, texts);
  button.disabled = false;
  button.textContent = "Save";
  if (!result) return;
  if (result.error) { toast(result.error, true); return; }
  if (result.clip) {
    state.vcache[result.clip.index] = (state.vcache[result.clip.index] || 0) + 1;
    const position = state.results.clips.findIndex((c) => c.index === result.clip.index);
    if (position >= 0) state.results.clips[position] = result.clip;
    const card = document.querySelector(`.clip-card[data-index="${result.clip.index}"]`);
    if (card) card.replaceWith(clipCard(result.clip));
  }
  closeSubEditor();
  toast("Subtitles updated.");
}

/* ---------- confirm dialog ---------- */

let confirmResolve = null;

function askConfirm(message, yesLabel = "Delete", challenge = null) {
  $("confirm-text").textContent = message;
  $("confirm-yes").textContent = yesLabel;
  const input = $("confirm-challenge");
  input.value = "";
  input.classList.toggle("hidden", !challenge);
  $("confirm-yes").disabled = !!challenge;
  if (challenge) {
    input.placeholder = `type “${challenge}” to confirm`;
    input.oninput = () => { $("confirm-yes").disabled = input.value.trim().toLowerCase() !== challenge; };
  }
  $("confirm").classList.remove("hidden");
  if (challenge) input.focus();
  return new Promise((resolve) => { confirmResolve = resolve; });
}

function settleConfirm(answer) {
  $("confirm").classList.add("hidden");
  $("confirm-yes").disabled = false;
  if (confirmResolve) confirmResolve(answer);
  confirmResolve = null;
}

/* ---------- splice editor ---------- */

const editor = { clip: null, pad: 8, windowStart: 0, windowEnd: 0, start: 0, end: 0, origStart: 0, origEnd: 0 };
const MIN_CLIP_SECONDS = 1;

async function openEditor(clip) {
  editor.clip = clip;
  editor.pad = 8;
  editor.start = clip.start;
  editor.end = clip.end;
  editor.origStart = clip.start;
  editor.origEnd = clip.end;
  $("ed-title").textContent = `${String(clip.index).padStart(2, "0")}  ${clip.title}`;
  $("ed-video").classList.toggle("audio", clip.kind === "audio");
  $("ed-expand").classList.toggle("hidden", clip.kind === "audio");
  $("editor").classList.remove("hidden");
  syncEditor();
  await loadPreview(true);
}

async function loadPreview(seekToStart) {
  $("ed-status").textContent = "preparing the preview…";
  const preview = await call("make_preview", jobRef(), editor.clip.index, editor.pad);
  if (!preview || preview.error) {
    $("ed-status").textContent = "";
    if (preview) toast(preview.error, true);
    return;
  }
  editor.windowStart = preview.window_start;
  editor.windowEnd = preview.window_end;
  const video = $("ed-video");
  video.src = preview.url + "?v=" + Date.now();
  video.onloadedmetadata = () => {
    if (seekToStart) video.currentTime = Math.max(0, editor.start - editor.windowStart);
  };
  $("ed-status").textContent = "";
  syncEditor();
}

function syncEditor() {
  $("ed-start").value = fmtClock(editor.start, true);
  $("ed-end").value = fmtClock(editor.end, true);
  $("ed-dur").textContent = `${Math.max(0, editor.end - editor.start).toFixed(1)}s selected`;
  const span = (editor.windowEnd - editor.windowStart) || 1;
  const pct = (t) => Math.min(100, Math.max(0, ((t - editor.windowStart) / span) * 100));
  const left = pct(editor.start), right = pct(editor.end);
  $("ed-range").style.left = left + "%";
  $("ed-range").style.width = Math.max(0, right - left) + "%";
  $("ed-handle-start").style.left = left + "%";
  $("ed-handle-end").style.left = right + "%";
  $("ed-orig-start").style.left = pct(editor.origStart) + "%";
  $("ed-orig-end").style.left = pct(editor.origEnd) + "%";
}

function closeEditor() {
  closeTheater();
  const video = $("ed-video");
  video.pause();
  video.removeAttribute("src");
  video.load();
  $("editor").classList.add("hidden");
  editor.clip = null;
}

function wireEditor() {
  $("ed-close").onclick = closeEditor;
  $("editor").addEventListener("mousedown", (e) => { if (e.target === $("editor")) closeEditor(); });
  $("confirm-no").onclick = () => settleConfirm(false);
  $("confirm-yes").onclick = () => settleConfirm(true);
  $("confirm").addEventListener("mousedown", (e) => { if (e.target === $("confirm")) settleConfirm(false); });
  $("theater-close").onclick = closeTheater;
  $("theater").addEventListener("mousedown", (e) => { if (e.target === $("theater") || e.target === $("theater-slot")) closeTheater(); });
  $("ed-expand").onclick = () => openTheater($("ed-video"));
  $("sub-close").onclick = closeSubEditor;
  $("sub-save").onclick = saveSubtitles;
  $("subedit").addEventListener("mousedown", (e) => { if (e.target === $("subedit")) closeSubEditor(); });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (theater.video) closeTheater();
    else if (confirmResolve) settleConfirm(false);
    else if (subedit.clip) closeSubEditor();
    else if (editor.clip) closeEditor();
  });

  const video = $("ed-video");
  video.addEventListener("timeupdate", () => {
    if (!video.duration) return;
    $("ed-playhead").style.left = (video.currentTime / video.duration) * 100 + "%";
  });

  // dragging the shaded range's edges is how splices get adjusted; the dashed
  // markers show where the cut originally sat, and the handles snap onto them
  const barFrac = (e) => {
    const rect = $("ed-bar").getBoundingClientRect();
    return Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
  };
  let dragging = null;
  const onDrag = (e) => {
    const span = editor.windowEnd - editor.windowStart;
    let when = editor.windowStart + barFrac(e) * span;
    const snap = Math.max(0.15, span * 0.012);
    const anchor = dragging === "start" ? editor.origStart : editor.origEnd;
    if (Math.abs(when - anchor) < snap) when = anchor;
    if (dragging === "start") editor.start = Math.min(when, editor.end - MIN_CLIP_SECONDS);
    else editor.end = Math.max(when, editor.start + MIN_CLIP_SECONDS);
    if (video.duration) {
      video.currentTime = Math.max(0, Math.min(video.duration, when - editor.windowStart));
    }
    syncEditor();
  };
  const endDrag = () => {
    dragging = null;
    document.removeEventListener("pointermove", onDrag);
  };
  for (const which of ["start", "end"]) {
    $(`ed-handle-${which}`).addEventListener("pointerdown", (e) => {
      e.preventDefault();
      dragging = which;
      document.addEventListener("pointermove", onDrag);
      document.addEventListener("pointerup", endDrag, { once: true });
    });
  }
  $("ed-bar").addEventListener("click", (e) => {
    if (e.target.classList.contains("ed-handle")) return;
    if (video.duration) video.currentTime = barFrac(e) * video.duration;
  });

  for (const btn of document.querySelectorAll(".ed-nudge")) {
    btn.onclick = () => {
      const [which, delta] = btn.dataset.ed.split(":");
      editor[which] = Math.max(0, editor[which] + Number(delta));
      syncEditor();
    };
  }
  for (const which of ["start", "end"]) {
    $(`ed-${which}`).addEventListener("change", (e) => {
      const value = parseClock(e.target.value);
      if (value === null) { toast("times look like 1:23.4 or plain seconds", true); syncEditor(); return; }
      editor[which] = Math.max(0, value);
      syncEditor();
    });
  }

  $("ed-wider").onclick = () => {
    editor.pad = Math.min(40, editor.pad * 2);
    loadPreview(false);
  };

  $("ed-save").onclick = async () => {
    if (editor.end - editor.start < 1) { toast("a clip has to be at least a second long", true); return; }
    const button = $("ed-save");
    button.disabled = true;
    button.textContent = "Re-cutting…";
    const result = await call("update_clip", jobRef(), editor.clip.index, editor.start, editor.end);
    button.disabled = false;
    button.textContent = "Save & re-cut";
    if (!result) return;
    if (result.error) { toast(result.error, true); return; }
    const fresh = result.clip;
    state.vcache[fresh.index] = (state.vcache[fresh.index] || 0) + 1;
    const position = state.results.clips.findIndex((c) => c.index === fresh.index);
    if (position >= 0) state.results.clips[position] = fresh;
    const card = document.querySelector(`.clip-card[data-index="${fresh.index}"]`);
    if (card) card.replaceWith(clipCard(fresh));
    closeEditor();
    toast(`clip ${fresh.index} re-cut`);
  };
}

/* ---------- updates ---------- */

let updateUrl = null;

async function checkUpdate(announce) {
  const status = $("update-status");
  status.textContent = "checking…";
  const info = await call("check_update");
  if (!info) { status.textContent = "ReelPipe"; return; }
  if (info.offline) {
    status.textContent = `ReelPipe ${info.current} · couldn't reach GitHub`;
    status.title = info.detail || "";
    return;
  }
  if (info.update) {
    updateUrl = info.url;
    status.textContent = `ReelPipe ${info.current} · version ${info.latest} is available`;
    $("update-get").classList.remove("hidden");
    if (announce) toast(`ReelPipe ${info.latest} is available. See Settings.`, false, 6000);
  } else {
    updateUrl = null;
    status.textContent = `ReelPipe ${info.current} · up to date`;
    $("update-get").classList.add("hidden");
  }
}

/* ---------- uninstall ---------- */

async function uninstallApp() {
  const info = await call("uninstall_info");
  if (!info) return;
  if (!info.targets.length) {
    toast("Nothing to remove.");
    return;
  }
  const sure = await askConfirm(
    `Removes the downloaded whisper models and app settings (${fmtBytes(info.bytes)}). Job outputs are kept.`,
    "Uninstall", "uninstall");
  if (!sure) return;
  const result = await call("uninstall");
  if (!result) return;
  if (result.error) { toast(result.error, true); return; }
  const followUp = result.frozen
    ? "Removed. Drag ReelPipe.app to the Trash to finish."
    : "Removed. Run pip uninstall reelpipe to finish.";
  toast(followUp, false, 12000);
}

/* ---------- navigation ---------- */

async function goHome() {
  show("home");
  const boot = await call("boot");
  if (boot) applyBoot(boot);
}

function wireStatic() {
  wireHome();
  wireEditor();
  $("uninstall").onclick = uninstallApp;
  $("update-check").onclick = () => checkUpdate(false);
  $("update-get").onclick = () => { if (updateUrl) call("open_external", updateUrl); };
  $("report-problem").onclick = () => call("report_problem");
  $("copy-diag").onclick = async () => { const r = await call("copy_diagnostics"); if (r && r.ok) toast("Details copied."); };
  $("open-log").onclick = () => call("open_log");
  for (const tab of document.querySelectorAll(".nav button")) {
    tab.onclick = () => tab.dataset.nav === "settings" ? show("settings") : goHome();
  }
  $("set-dark").addEventListener("change", (e) => applyTheme(e.target.checked, true));
  $("ffmpeg-recheck").onclick = async () => {
    const boot = await call("boot");
    if (boot) applyBoot(boot);
    if (boot && boot.doctor.ffmpeg) toast("ffmpeg found.");
    else toast("still can't find ffmpeg", true);
  };
  $("setup-back").onclick = goHome;
  $("start").onclick = startJob;
  $("paste-home").onclick = goHome;
  $("apply").onclick = applyResponses;
  $("open-folder").onclick = () => call("open_folder", jobRef());
  $("burn-all").onclick = async () => {
    const started = await call("burn_captions", jobRef());
    if (!started) return;
    if (started.error) { toast(started.error, true); return; }
    showRunning("Burning captions", ["cut"]);
  };
  $("new-job").onclick = goHome;
  for (const btn of document.querySelectorAll("[data-open]")) {
    btn.onclick = () => call("open_external", btn.dataset.open);
  }
}

/* ---------- go ---------- */

drawPoly();
wireStatic();
window.addEventListener("pywebviewready", init);
const readyPoll = setInterval(() => {
  // if the bridge lands (even late), prefer it and drop the http poller
  if (api()) { clearInterval(readyPoll); stopPolling(); if (!booted) init(); }
}, 120);
// windows sometimes never injects the js bridge; fall back to http and keep working
setTimeout(() => {
  if (!api()) { startPolling(); init(); }
}, 3500);
// stop trying for the bridge after a while so readyPoll can't leak for the session
setTimeout(() => clearInterval(readyPoll), 30000);
