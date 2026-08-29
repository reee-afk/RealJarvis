"use strict";

/* Canvas force-directed graph. Spatial grid keeps repulsion near-linear;
   SVG would need a DOM node per element and stalls well before 1,500 nodes. */

const TYPE_COLORS = {
  clients: "#2de6d6",
  invoices: "#e6a13a",
  proposals: "#5fb0ff",
  notes: "#7fd9d0",
  research: "#b48cff",
  text: "#8fd6cf",
  pdf: "#ff6b5e",
  file: "#8aa0a2",
};
const DEFAULT_COLOR = "#8aa0a2";

const REPEL = 2600;
const SPRING_LEN = 90;
const SPRING_K = 0.02;
const CENTER_PULL = 0.0025;
const DAMPING = 0.86;
const GRID_CELL = 140;
const SETTLE_ITERATIONS = 260;
const IDLE_PULSE_INTERVAL_MS = 3200;

function colorFor(type) {
  return TYPE_COLORS[type] || DEFAULT_COLOR;
}

class JarvisGraph {
  constructor(canvas, { onFocus, onFilterChange } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.onFocus = onFocus || (() => {});
    this.nodes = [];
    this.edges = [];
    this.byId = new Map();
    this.adjacency = new Map();
    this.activeTypes = new Set();

    this.offsetX = 0;
    this.offsetY = 0;
    this.scale = 1;

    this.hovered = null;
    this.focused = null;
    this.pathHighlight = null; // {nodeIds:Set, edgeKeys:Set}
    this.shiftAnchor = null;

    this.dragNode = null;
    this.panning = false;
    this.panStart = null;

    this.settleTicksLeft = SETTLE_ITERATIONS;
    this.pulse = null;
    this._lastPulseAt = 0;

    this._bindEvents();
    this._resize();
    window.addEventListener("resize", () => this._resize());
    requestAnimationFrame((t) => this._tick(t));
  }

  setData(nodes, edges) {
    const cx = this.canvas.width / 2;
    const cy = this.canvas.height / 2;
    this.nodes = nodes.map((n, i) => {
      const prev = this.byId.get(n.id);
      const angle = (i / nodes.length) * Math.PI * 2;
      return {
        ...n,
        x: prev ? prev.x : cx + Math.cos(angle) * 200 + (Math.random() - 0.5) * 40,
        y: prev ? prev.y : cy + Math.sin(angle) * 200 + (Math.random() - 0.5) * 40,
        vx: 0,
        vy: 0,
        r: Math.max(4, Math.min(26, 5 + Math.sqrt(n.connections || 0) * 4)),
      };
    });
    this.byId = new Map(this.nodes.map((n) => [n.id, n]));
    this.edges = edges.filter((e) => this.byId.has(e.source) && this.byId.has(e.target));
    this.adjacency = new Map();
    for (const e of this.edges) {
      if (!this.adjacency.has(e.source)) this.adjacency.set(e.source, new Set());
      if (!this.adjacency.has(e.target)) this.adjacency.set(e.target, new Set());
      this.adjacency.get(e.source).add(e.target);
      this.adjacency.get(e.target).add(e.source);
    }
    this.activeTypes = new Set(this.nodes.map((n) => n.type));
    this.settleTicksLeft = SETTLE_ITERATIONS;
  }

  setTypeFilter(activeTypes) {
    this.activeTypes = activeTypes;
  }

  focusById(id) {
    const node = this.byId.get(id);
    if (node) this._focus(node);
  }

  clearPath() {
    this.pathHighlight = null;
    this.shiftAnchor = null;
  }

  setPath(ids) {
    const nodeIds = new Set(ids);
    const edgeKeys = new Set();
    for (let i = 0; i < ids.length - 1; i++) {
      edgeKeys.add([ids[i], ids[i + 1]].sort().join("|"));
    }
    this.pathHighlight = { nodeIds, edgeKeys };
  }

  // ---------------------------------------------------------------- events
  _bindEvents() {
    const c = this.canvas;
    c.addEventListener("mousemove", (e) => this._onMouseMove(e));
    c.addEventListener("mousedown", (e) => this._onMouseDown(e));
    window.addEventListener("mouseup", () => this._onMouseUp());
    c.addEventListener("wheel", (e) => this._onWheel(e), { passive: false });
    c.addEventListener("click", (e) => this._onClick(e));
  }

  _resize() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    this.canvas.width = rect.width;
    this.canvas.height = rect.height;
  }

  _screenToWorld(px, py) {
    return { x: (px - this.offsetX) / this.scale, y: (py - this.offsetY) / this.scale };
  }

  _nodeAt(px, py) {
    const { x, y } = this._screenToWorld(px, py);
    let best = null;
    let bestD = Infinity;
    for (const n of this.nodes) {
      if (!this.activeTypes.has(n.type)) continue;
      const d = Math.hypot(n.x - x, n.y - y);
      if (d <= n.r + 6 && d < bestD) {
        best = n;
        bestD = d;
      }
    }
    return best;
  }

  _onMouseMove(e) {
    const rect = this.canvas.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;

    if (this.dragNode) {
      const { x, y } = this._screenToWorld(px, py);
      this.dragNode.x = x;
      this.dragNode.y = y;
      this.dragNode.vx = 0;
      this.dragNode.vy = 0;
      return;
    }
    if (this.panning) {
      this.offsetX += px - this.panStart.x;
      this.offsetY += py - this.panStart.y;
      this.panStart = { x: px, y: py };
      return;
    }
    this.hovered = this._nodeAt(px, py);
    this.canvas.style.cursor = this.hovered ? "pointer" : "grab";
  }

  _onMouseDown(e) {
    const rect = this.canvas.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    const node = this._nodeAt(px, py);
    if (node) {
      this.dragNode = node;
    } else {
      this.panning = true;
      this.panStart = { x: px, y: py };
    }
  }

  _onMouseUp() {
    this.dragNode = null;
    this.panning = false;
  }

  _onWheel(e) {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.08 : 0.93;
    this.scale = Math.max(0.25, Math.min(3.5, this.scale * factor));
  }

  _onClick(e) {
    const rect = this.canvas.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    const node = this._nodeAt(px, py);
    if (!node) return;

    if (e.shiftKey && this.shiftAnchor && this.shiftAnchor.id !== node.id) {
      this._requestPath(this.shiftAnchor.id, node.id);
      this.shiftAnchor = null;
      return;
    }
    if (e.shiftKey) {
      this.shiftAnchor = node;
      return;
    }
    this.clearPath();
    this._focus(node);
  }

  async _requestPath(a, b) {
    try {
      const res = await fetch(`/api/path?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
      const data = await res.json();
      if (data.path && data.path.length) this.setPath(data.path);
    } catch (_) {
      /* offline — silently skip, graph still usable */
    }
  }

  _focus(node) {
    this.focused = node;
    this.onFocus(node);
  }

  // ----------------------------------------------------------------- physics
  _step() {
    const grid = new Map();
    const cellOf = (n) => `${Math.floor(n.x / GRID_CELL)}:${Math.floor(n.y / GRID_CELL)}`;
    for (const n of this.nodes) {
      const key = cellOf(n);
      if (!grid.has(key)) grid.set(key, []);
      grid.get(key).push(n);
    }

    const active = this.nodes.filter((n) => this.activeTypes.has(n.type));
    const energyScale = this.settleTicksLeft > 0 ? 1 : 0.12;

    for (const n of active) {
      const cx = Math.floor(n.x / GRID_CELL);
      const cy = Math.floor(n.y / GRID_CELL);
      let fx = 0;
      let fy = 0;
      for (let gx = cx - 1; gx <= cx + 1; gx++) {
        for (let gy = cy - 1; gy <= cy + 1; gy++) {
          const bucket = grid.get(`${gx}:${gy}`);
          if (!bucket) continue;
          for (const other of bucket) {
            if (other === n) continue;
            let dx = n.x - other.x;
            let dy = n.y - other.y;
            let distSq = dx * dx + dy * dy;
            if (distSq < 1) distSq = 1;
            const dist = Math.sqrt(distSq);
            if (dist > GRID_CELL * 1.5) continue;
            const force = (REPEL / distSq) * energyScale;
            fx += (dx / dist) * force;
            fy += (dy / dist) * force;
          }
        }
      }
      n._fx = fx;
      n._fy = fy;
    }

    for (const e of this.edges) {
      const a = this.byId.get(e.source);
      const b = this.byId.get(e.target);
      if (!this.activeTypes.has(a.type) || !this.activeTypes.has(b.type)) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.hypot(dx, dy) || 1;
      const force = (dist - SPRING_LEN) * SPRING_K * energyScale;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a._fx = (a._fx || 0) + fx;
      a._fy = (a._fy || 0) + fy;
      b._fx = (b._fx || 0) - fx;
      b._fy = (b._fy || 0) - fy;
    }

    const cx0 = this.canvas.width / 2;
    const cy0 = this.canvas.height / 2;
    for (const n of active) {
      if (n === this.dragNode) continue;
      const towardCenter = ((cx0 - this.offsetX) / this.scale - n.x) * CENTER_PULL;
      const towardCenterY = ((cy0 - this.offsetY) / this.scale - n.y) * CENTER_PULL;
      n.vx = (n.vx + (n._fx || 0) + towardCenter) * DAMPING;
      n.vy = (n.vy + (n._fy || 0) + towardCenterY) * DAMPING;
      n.x += n.vx;
      n.y += n.vy;
    }

    if (this.settleTicksLeft > 0) this.settleTicksLeft--;
  }

  // ------------------------------------------------------------------ pulse
  _maybeStartPulse(now) {
    if (this.settleTicksLeft > 0) return;
    if (now - this._lastPulseAt < IDLE_PULSE_INTERVAL_MS) return;
    if (!this.edges.length) return;
    const e = this.edges[Math.floor(Math.random() * this.edges.length)];
    const a = this.byId.get(e.source);
    const b = this.byId.get(e.target);
    if (!a || !b) return;
    this.pulse = { a, b, start: now, duration: 900 };
    this._lastPulseAt = now;
  }

  // ------------------------------------------------------------------ render
  _tick(now) {
    this._step();
    this._maybeStartPulse(now);
    this._render(now);
    requestAnimationFrame((t) => this._tick(t));
  }

  _render(now) {
    const ctx = this.ctx;
    const { width, height } = this.canvas;
    ctx.clearRect(0, 0, width, height);
    ctx.save();
    ctx.translate(this.offsetX, this.offsetY);
    ctx.scale(this.scale, this.scale);

    const hoveredSet = this._connectedSet(this.hovered);
    const focusedSet = this._connectedSet(this.focused);
    const dimActive = this.hovered || this.focused || this.pathHighlight;

    // edges
    for (const e of this.edges) {
      const a = this.byId.get(e.source);
      const b = this.byId.get(e.target);
      if (!this.activeTypes.has(a.type) || !this.activeTypes.has(b.type)) continue;
      const key = [e.source, e.target].sort().join("|");
      const onPath = this.pathHighlight && this.pathHighlight.edgeKeys.has(key);
      const lit =
        onPath ||
        (this.hovered && (e.source === this.hovered.id || e.target === this.hovered.id)) ||
        (this.focused && (e.source === this.focused.id || e.target === this.focused.id));
      ctx.strokeStyle = onPath ? "#ffffff" : lit ? "#2de6d6" : "rgba(90,150,150,0.28)";
      ctx.globalAlpha = dimActive && !lit ? 0.08 : 1;
      ctx.lineWidth = onPath ? 2.4 / this.scale : lit ? 1.6 / this.scale : 0.8 / this.scale;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    // idle pulse
    if (this.pulse) {
      const t = (now - this.pulse.start) / this.pulse.duration;
      if (t >= 1) {
        this.pulse = null;
      } else {
        const { a, b } = this.pulse;
        const x = a.x + (b.x - a.x) * t;
        const y = a.y + (b.y - a.y) * t;
        ctx.fillStyle = "#e8fffb";
        ctx.beginPath();
        ctx.arc(x, y, 3 / this.scale, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // nodes
    const placedLabels = [];
    const sorted = [...this.nodes].sort((a, b) => (b.connections || 0) - (a.connections || 0));
    for (const n of sorted) {
      if (!this.activeTypes.has(n.type)) continue;
      const isHover = this.hovered && n.id === this.hovered.id;
      const isFocus = this.focused && n.id === this.focused.id;
      const onPath = this.pathHighlight && this.pathHighlight.nodeIds.has(n.id);
      const lit = isHover || isFocus || onPath || hoveredSet.has(n.id) || focusedSet.has(n.id);
      const r = isHover || isFocus ? n.r * 1.25 : n.r;

      ctx.globalAlpha = dimActive && !lit ? 0.1 : 1;
      ctx.fillStyle = colorFor(n.type);
      if (lit) {
        ctx.shadowColor = colorFor(n.type);
        ctx.shadowBlur = 14;
      } else {
        ctx.shadowBlur = 0;
      }
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      if ((lit || r > 9 || dimActive === null) && this.scale > 0.5) {
        this._tryLabel(ctx, n, r, placedLabels);
      }
    }
    ctx.globalAlpha = 1;
    ctx.restore();
  }

  _tryLabel(ctx, n, r, placed) {
    const fontSize = 11;
    ctx.font = `${fontSize}px ui-monospace, Consolas, monospace`;
    const text = n.title.length > 26 ? n.title.slice(0, 24) + "…" : n.title;
    const width = ctx.measureText(text).width;
    const box = { x: n.x + r + 4, y: n.y - fontSize / 2 - 2, w: width + 4, h: fontSize + 4 };
    for (const other of placed) {
      if (box.x < other.x + other.w && box.x + box.w > other.x && box.y < other.y + other.h && box.y + box.h > other.y) {
        return; // collides — skip this label rather than let the hub cluster turn to mush
      }
    }
    placed.push(box);
    ctx.fillStyle = "rgba(205,238,238,0.85)";
    ctx.fillText(text, box.x, n.y + fontSize / 3);
  }

  _connectedSet(node) {
    if (!node) return new Set();
    return this.adjacency.get(node.id) || new Set();
  }
}

window.JarvisGraph = JarvisGraph;
