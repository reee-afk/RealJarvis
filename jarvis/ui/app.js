"use strict";

/* ============================================================
   Tunables — the one place to change turn-taking feel.
   ============================================================ */
const SILENCE_LEVEL_THRESHOLD = 10; // 0-255 scale off getByteFrequencyData
const SILENCE_DURATION_MS = 900; // how long you can go quiet before the turn ends
const LEVEL_CHECK_INTERVAL_MS = 100; // setInterval, NOT requestAnimationFrame —
// rAF stops dead in a backgrounded tab and the mic would go silently deaf.
const MAX_RECORDING_MS = 45000; // safety cap if silence is never detected

const EXAMPLE_PROMPTS = [
  "What did Bloom & Co Salon sign up for?",
  "Plan my day",
  "Brief me",
  "Remember that Whitfield Dental wants the case-study deck",
  "What's the market rate for a booking integration in the UK?",
  "Who's overdue on invoices?",
];

/* ============================================================
   State
   ============================================================ */
const state = {
  mode: "idle", // idle | listening | thinking | speaking
  muted: false,
  status: null,
  graphData: { nodes: [], edges: [] },
};

let graph = null;
let mic = {
  stream: null,
  ctx: null,
  analyser: null,
  recorder: null,
  chunks: [],
  levelTimer: null,
  lastAboveThreshold: 0,
  spokeOnce: false,
  maxTimer: null,
};
let playback = { audioEl: null, ctx: null, analyser: null, timer: null };
let currentLevel = 0;

/* ============================================================
   DOM
   ============================================================ */
const $ = (id) => document.getElementById(id);
const el = {
  canvas: $("graph-canvas"),
  reactorCanvas: $("reactor-canvas"),
  reactorState: $("reactor-state"),
  bars: Array.from(document.querySelectorAll("#bars .bar")),
  caption: $("caption"),
  chatlog: $("chatlog"),
  askInput: $("ask-input"),
  btnMic: $("btn-mic"),
  btnMute: $("btn-mute"),
  btnBrief: $("btn-brief"),
  btnPlan: $("btn-plan"),
  btnMemory: $("btn-memory"),
  examplePrompt: $("example-prompt"),
  errorBanner: $("error-banner"),
  inspectorBody: $("inspector-body"),
  hubsList: $("hubs-list"),
  filters: $("filters"),
  badgeDemo: $("badge-demo"),
  badgeModel: $("badge-model"),
  badgeVoice: $("badge-voice"),
};

/* ============================================================
   Degrade loudly — never a silent failure
   ============================================================ */
let bannerTimer = null;
function showError(msg, ms = 6000) {
  el.errorBanner.textContent = msg;
  el.errorBanner.classList.add("show");
  clearTimeout(bannerTimer);
  bannerTimer = setTimeout(() => el.errorBanner.classList.remove("show"), ms);
}

/* ============================================================
   Reactor HUD
   ============================================================ */
function setMode(mode) {
  state.mode = mode;
  el.reactorState.textContent = mode;
}

function drawReactor(now) {
  const ctx = el.reactorCanvas.getContext("2d");
  const w = el.reactorCanvas.width;
  const h = el.reactorCanvas.height;
  const cx = w / 2;
  const cy = h / 2;
  ctx.clearRect(0, 0, w, h);

  const level = currentLevel / 255;
  const breathe = 0.5 + 0.5 * Math.sin(now / 900);

  const colors = { idle: "#2de6d6", listening: "#2de6d6", thinking: "#e6a13a", speaking: "#2de6d6" };
  const color = colors[state.mode] || "#2de6d6";
  ctx.strokeStyle = color;

  // outer ring
  ctx.globalAlpha = 0.35;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(cx, cy, 52, 0, Math.PI * 2);
  ctx.stroke();

  // reactive ring
  let radius = 40;
  if (state.mode === "listening" || state.mode === "speaking") {
    radius = 36 + level * 18;
  } else if (state.mode === "idle") {
    radius = 38 + breathe * 3;
  }
  ctx.globalAlpha = 0.8;
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.stroke();

  // thinking: rotating dashed ring
  if (state.mode === "thinking") {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(now / 400);
    ctx.setLineDash([6, 6]);
    ctx.globalAlpha = 0.9;
    ctx.beginPath();
    ctx.arc(0, 0, 44, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  // core
  ctx.globalAlpha = 1;
  ctx.fillStyle = color;
  ctx.shadowColor = color;
  ctx.shadowBlur = 12 + level * 20;
  ctx.beginPath();
  ctx.arc(cx, cy, 10 + level * 6, 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;

  requestAnimationFrame(drawReactor);
}
requestAnimationFrame(drawReactor);

function updateBars(level0to255) {
  const n = el.bars.length;
  for (let i = 0; i < n; i++) {
    const jitter = 0.6 + Math.random() * 0.4;
    const h = Math.max(2, (level0to255 / 255) * 20 * jitter);
    el.bars[i].style.height = `${h}px`;
  }
}

/* ============================================================
   Mic capture — press once, then just talk
   ============================================================ */
async function startListening() {
  if (state.mode === "speaking") {
    // mic must stay deaf while JARVIS talks; treat this click as barge-in instead
    stopSpeaking();
    return;
  }
  if (state.mode === "listening") {
    stopListening(true);
    return;
  }
  if (state.status && !state.status.voice_configured) {
    showError("Voice isn't configured — add ELEVENLABS_API_KEY to .env and restart.");
    return;
  }

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    showError("Microphone blocked — allow mic access for this page in your browser settings.");
    return;
  }

  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  const ctx = new AudioCtx();
  const source = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  source.connect(analyser);

  let recorder;
  try {
    recorder = new MediaRecorder(stream);
  } catch (err) {
    showError("This browser can't record audio (MediaRecorder unsupported).");
    stream.getTracks().forEach((t) => t.stop());
    return;
  }

  mic = {
    stream,
    ctx,
    analyser,
    recorder,
    chunks: [],
    levelTimer: null,
    lastAboveThreshold: performance.now(),
    spokeOnce: false,
    maxTimer: null,
  };

  recorder.ondataavailable = (e) => {
    if (e.data.size > 0) mic.chunks.push(e.data);
  };
  recorder.onstop = onRecordingStopped;
  recorder.start();

  el.btnMic.classList.add("active");
  setMode("listening");
  el.caption.textContent = "listening…";

  const buf = new Uint8Array(analyser.frequencyBinCount);
  mic.levelTimer = setInterval(() => {
    analyser.getByteFrequencyData(buf);
    const avg = buf.reduce((a, b) => a + b, 0) / buf.length;
    currentLevel = avg;
    updateBars(avg);

    const now = performance.now();
    if (avg > SILENCE_LEVEL_THRESHOLD) {
      mic.lastAboveThreshold = now;
      mic.spokeOnce = true;
    } else if (mic.spokeOnce && now - mic.lastAboveThreshold > SILENCE_DURATION_MS) {
      stopListening(false);
    }
  }, LEVEL_CHECK_INTERVAL_MS);

  mic.maxTimer = setTimeout(() => stopListening(false), MAX_RECORDING_MS);
}

function stopListening(cancelled) {
  if (mic.levelTimer) clearInterval(mic.levelTimer);
  if (mic.maxTimer) clearTimeout(mic.maxTimer);
  mic.levelTimer = null;
  el.btnMic.classList.remove("active");
  if (mic.recorder && mic.recorder.state !== "inactive") {
    mic.recorder._cancelled = cancelled;
    mic.recorder.stop();
  }
  if (mic.stream) mic.stream.getTracks().forEach((t) => t.stop());
  if (mic.ctx) mic.ctx.close();
  currentLevel = 0;
  updateBars(0);
}

async function onRecordingStopped() {
  if (this._cancelled) {
    setMode("idle");
    el.caption.textContent = "";
    return;
  }
  if (!mic.spokeOnce) {
    setMode("idle");
    el.caption.textContent = "didn't catch anything, sir";
    return;
  }
  setMode("thinking");
  el.caption.textContent = "transcribing…";

  const blob = new Blob(mic.chunks, { type: mic.recorder.mimeType || "audio/webm" });
  try {
    const res = await fetch("/api/listen", {
      method: "POST",
      headers: { "Content-Type": blob.type },
      body: blob,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showError(err.error || "Speech-to-text failed.");
      setMode("idle");
      el.caption.textContent = "";
      return;
    }
    const data = await res.json();
    const text = (data.text || "").trim();
    el.caption.textContent = text || "(silence)";
    if (text) sendMessage(text, true);
    else setMode("idle");
  } catch (err) {
    showError("Couldn't reach the server to transcribe that.");
    setMode("idle");
  }
}

/* Barge-in: explicit action only, never automatic, so the mic can't
   transcribe JARVIS's own voice back into itself. */
function stopSpeaking() {
  if (playback.audioEl) {
    playback.audioEl.pause();
    playback.audioEl.currentTime = 0;
  }
  if (playback.timer) clearInterval(playback.timer);
  if (playback.ctx) playback.ctx.close().catch(() => {});
  playback = { audioEl: null, ctx: null, analyser: null, timer: null };
  currentLevel = 0;
  updateBars(0);
  setMode("idle");
}

document.addEventListener("keydown", (e) => {
  if ((e.code === "Space" || e.code === "Escape") && state.mode === "speaking") {
    e.preventDefault();
    stopSpeaking();
  } else if (e.code === "Space" && document.activeElement !== el.askInput) {
    if (state.mode === "idle") {
      e.preventDefault();
      startListening();
    }
  }
});

/* ============================================================
   Speak a reply
   ============================================================ */
async function speak(text) {
  if (state.muted || !state.status || !state.status.voice_configured) {
    setMode("idle");
    return;
  }
  setMode("speaking");
  try {
    const res = await fetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showError(err.error || "Text-to-speech failed.");
      setMode("idle");
      return;
    }
    const buf = await res.arrayBuffer();
    const audioBlob = new Blob([buf], { type: "audio/mpeg" });
    const url = URL.createObjectURL(audioBlob);
    const audioEl = new Audio(url);

    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    const ctx = new AudioCtx();
    const source = ctx.createMediaElementSource(audioEl);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    analyser.connect(ctx.destination);

    const buf2 = new Uint8Array(analyser.frequencyBinCount);
    const timer = setInterval(() => {
      analyser.getByteFrequencyData(buf2);
      const avg = buf2.reduce((a, b) => a + b, 0) / buf2.length;
      currentLevel = avg;
      updateBars(avg);
    }, LEVEL_CHECK_INTERVAL_MS);

    playback = { audioEl, ctx, analyser, timer };
    audioEl.onended = () => {
      clearInterval(timer);
      currentLevel = 0;
      updateBars(0);
      setMode("idle");
    };
    await audioEl.play();
  } catch (err) {
    showError("Playback failed.");
    setMode("idle");
  }
}

/* ============================================================
   Chat
   ============================================================ */
function appendMessage(who, text, card) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${who}`;
  const label = document.createElement("div");
  label.className = "who";
  label.textContent = who === "user" ? "you" : "jarvis";
  wrap.appendChild(label);
  const body = document.createElement("div");
  body.textContent = text;
  wrap.appendChild(body);
  if (card && card.tool) {
    const cardEl = document.createElement("div");
    cardEl.className = "card";
    cardEl.textContent = formatCard(card);
    wrap.appendChild(cardEl);
  }
  el.chatlog.appendChild(wrap);
  el.chatlog.scrollTop = el.chatlog.scrollHeight;
}

function formatCard(card) {
  switch (card.tool) {
    case "search_brain":
      return (card.results || []).map((r) => `${r.title} — ${r.snippet}`).join("\n");
    case "research_web":
      return (card.results || []).join("\n") + (card.your_pricing?.length ? "\n\n" + card.your_pricing.join("\n") : "");
    case "read_inbox":
      return card.configured
        ? (card.messages || []).map((m) => `${m.from} — ${m.subject}${m.known_client ? " (known)" : ""}`).join("\n") || "inbox clear"
        : "inbox not connected";
    case "brief_me":
      return `overdue: ${(card.overdue_invoices || []).map((i) => `${i.client || "?"} ${i.currency}${i.amount}`).join(", ") || "none"}\ncalendar connected: ${card.calendar_connected}`;
    case "remember":
      return `wrote ${card.file}`;
    case "plan_day":
      return (card.items || []).map((i, idx) => `${idx + 1}. ${i.label} [${i.source}]`).join("\n");
    default:
      return JSON.stringify(card);
  }
}

async function sendMessage(text, fromVoice) {
  appendMessage("user", text);
  el.askInput.value = "";
  setMode("thinking");
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    const data = await res.json();
    if (data.error) {
      showError(data.error);
      setMode("idle");
      return;
    }
    appendMessage("jarvis", data.spoken, data.card);
    if (data.meta && !data.meta.llm) {
      // heuristic routing — badge already shows this, no need to nag per-message
    }
    await speak(data.spoken);
  } catch (err) {
    showError("Couldn't reach JARVIS's server.");
    setMode("idle");
  }
}

el.askInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && el.askInput.value.trim()) {
    sendMessage(el.askInput.value.trim(), false);
  }
});

el.btnMic.addEventListener("click", startListening);
el.btnMute.addEventListener("click", () => {
  state.muted = !state.muted;
  el.btnMute.classList.toggle("active", state.muted);
  if (state.muted && state.mode === "speaking") stopSpeaking();
});
el.btnBrief.addEventListener("click", () => sendMessage("brief me", false));
el.btnPlan.addEventListener("click", () => sendMessage("plan my day", false));
el.btnMemory.addEventListener("click", () => {
  el.askInput.value = "remember: ";
  el.askInput.focus();
});

/* ============================================================
   Example prompt rotation
   ============================================================ */
let exampleIdx = 0;
function rotateExample() {
  el.examplePrompt.textContent = `try: "${EXAMPLE_PROMPTS[exampleIdx]}"`;
  exampleIdx = (exampleIdx + 1) % EXAMPLE_PROMPTS.length;
}
rotateExample();
setInterval(rotateExample, 5000);

/* ============================================================
   Inspector + hubs + filters
   ============================================================ */
function renderInspector(node) {
  if (!node) {
    el.inspectorBody.innerHTML = '<p class="empty">Click a node to inspect it.</p>';
    return;
  }
  fetch(`/api/node?id=${encodeURIComponent(node.id)}`)
    .then((r) => r.json())
    .then((full) => {
      const excerpt = (full.content || "").slice(0, 1200);
      el.inspectorBody.innerHTML = `
        <p class="node-title">${escapeHtml(node.title)}</p>
        <p class="node-meta">${escapeHtml(node.type)} · ${node.connections} link${node.connections === 1 ? "" : "s"}</p>
        <div class="node-excerpt">${escapeHtml(excerpt)}</div>
      `;
    });
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function renderHubs(nodes) {
  const top = [...nodes].sort((a, b) => b.connections - a.connections).slice(0, 10);
  el.hubsList.innerHTML =
    '<div class="panel-header" style="padding-left:0;border:none;margin-bottom:4px;">Top hubs</div>' +
    top
      .map((n) => `<div class="hub-row" data-id="${encodeURIComponent(n.id)}"><span>${escapeHtml(n.title)}</span><span class="n">${n.connections}</span></div>`)
      .join("");
  el.hubsList.querySelectorAll(".hub-row").forEach((row) => {
    row.addEventListener("click", () => {
      const id = decodeURIComponent(row.dataset.id);
      graph.clearPath();
      graph.focusById(id);
      const node = graph.byId.get(id);
      renderInspector(node);
    });
  });
}

function renderFilters(nodes) {
  const counts = {};
  for (const n of nodes) counts[n.type] = (counts[n.type] || 0) + 1;
  const types = Object.keys(counts).sort();
  const active = new Set(types);
  el.filters.innerHTML = types
    .map(
      (t) => `<div class="filter-row" data-type="${t}">
        <span><span class="swatch" style="background:${swatchFor(t)}"></span>${t}</span>
        <span class="count">${counts[t]}</span>
      </div>`
    )
    .join("");
  el.filters.querySelectorAll(".filter-row").forEach((row) => {
    row.addEventListener("click", () => {
      const t = row.dataset.type;
      if (active.has(t)) {
        active.delete(t);
        row.classList.add("off");
      } else {
        active.add(t);
        row.classList.remove("off");
      }
      graph.setTypeFilter(active);
    });
  });
  graph.setTypeFilter(active);
}

const SWATCHES = {
  clients: "#2de6d6",
  invoices: "#e6a13a",
  proposals: "#5fb0ff",
  notes: "#7fd9d0",
  research: "#b48cff",
  text: "#8fd6cf",
  pdf: "#ff6b5e",
  file: "#8aa0a2",
};
function swatchFor(t) {
  return SWATCHES[t] || "#8aa0a2";
}

/* ============================================================
   Status + boot
   ============================================================ */
async function loadStatus() {
  try {
    const res = await fetch("/api/status");
    const status = await res.json();
    state.status = status;
    el.badgeDemo.textContent = status.demo ? "DEMO DATA" : "REAL DATA";
    el.badgeDemo.className = "badge " + (status.demo ? "ok" : "warn");
    el.badgeModel.textContent = status.llm_configured ? "MODEL: CLAUDE" : "MODEL: HEURISTIC";
    el.badgeModel.className = "badge " + (status.llm_configured ? "ok" : "warn");
    el.badgeVoice.textContent = status.voice_configured ? "VOICE: READY" : "VOICE: OFFLINE";
    el.badgeVoice.className = "badge " + (status.voice_configured ? "ok" : "warn");
    if (!status.voice_configured) {
      showError("Voice isn't configured — set ELEVENLABS_API_KEY in .env to enable mic and speech.", 9000);
    }
  } catch (err) {
    showError("Can't reach the JARVIS server.");
  }
}

async function loadGraph() {
  const res = await fetch("/api/graph");
  const data = await res.json();
  state.graphData = data;
  graph.setData(data.nodes, data.edges);
  renderHubs(data.nodes);
  renderFilters(data.nodes);
}

function boot() {
  graph = new window.JarvisGraph(el.canvas, {
    onFocus: (node) => renderInspector(node),
  });
  window.graph = graph; // debug hook
  loadStatus();
  loadGraph();
}

boot();
