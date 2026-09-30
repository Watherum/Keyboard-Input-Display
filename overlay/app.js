/* Keyboard Input Display — overlay client.
   Renders the layout from config.json and lights keys from the
   server's SSE stream. Editing config.json live-reloads the layout. */

const stage = document.getElementById("stage");

// scrollbars for preview in a normal browser; OBS keeps the clean crop
if (!navigator.userAgent.includes("OBS")) {
  document.documentElement.style.overflow = "auto";
  document.body.style.overflow = "auto";
}

const FLASH_MS = 140; // wheel tick visual duration
const flashTimers = new Map();

async function buildLayout() {
  // ?profile=Name on the page URL pins this source to a specific profile
  const profile = new URLSearchParams(location.search).get("profile");
  const url = profile
    ? `/config.json?profile=${encodeURIComponent(profile)}`
    : "/config.json";
  const res = await fetch(url, { cache: "no-store" });
  const cfg = await res.json();

  const unit = cfg.unit ?? 64;
  const gap = cfg.gap ?? 8;
  const rootStyle = document.documentElement.style;
  const glow = cfg.glowColor ?? cfg.accent;
  if (glow) rootStyle.setProperty("--accent", glow);
  if (cfg.keyColor) rootStyle.setProperty("--cap", cfg.keyColor);
  if (cfg.textColor) rootStyle.setProperty("--legend", cfg.textColor);

  stage.innerHTML = "";
  let maxX = 0, maxY = 0;

  for (const k of cfg.keys ?? []) {
    const w = (k.w ?? 1) * unit + ((k.w ?? 1) - 1) * gap;
    const h = (k.h ?? 1) * unit + ((k.h ?? 1) - 1) * gap;
    const left = k.x * (unit + gap);
    const top = k.y * (unit + gap);

    const el = document.createElement("div");
    el.className = "key";
    el.dataset.key = k.id;
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
    el.style.width = `${w}px`;
    el.style.height = `${h}px`;
    if (k.glow) el.style.setProperty("--accent", k.glow);
    if (k.color) el.style.setProperty("--cap", k.color);
    if (k.text) el.style.setProperty("--legend", k.text);

    const label = k.label ?? k.id;
    const span = document.createElement("span");
    span.textContent = label;
    // size legends to the cap: full size whenever the text fits the width
    const base = unit * 0.34;
    const fits = (w * 0.9) / (label.length * 0.9); // ~0.9em per glyph in HK Modular
    el.style.setProperty("--fs", `${Math.min(base, fits, h * 0.5)}px`);
    el.appendChild(span);
    stage.appendChild(el);

    maxX = Math.max(maxX, left + w);
    maxY = Math.max(maxY, top + h);
  }
  const ext = buildMotion(cfg, unit, gap);
  if (ext) {
    maxX = Math.max(maxX, ext.right);
    maxY = Math.max(maxY, ext.bottom);
  }

  stage.style.width = `${maxX}px`;
  stage.style.height = `${maxY}px`;
}

/* ------------------------------------------------- mouse motion widget */

let motionCtl = null;

function buildMotion(cfg, unit, gap) {
  motionCtl?.destroy();
  motionCtl = null;
  const m = cfg.motion;
  const style = m?.style ?? "off";
  if (!m || style === "off") return null;

  const uw = m.w ?? 2.5, uh = m.h ?? 2.5;
  const w = uw * unit + (uw - 1) * gap;
  const h = uh * unit + (uh - 1) * gap;
  const left = (m.x ?? 0) * (unit + gap);
  const top = (m.y ?? 0) * (unit + gap);
  const sens = m.sensitivity ?? 1;

  const panel = document.createElement("div");
  panel.className = `pad style-${style}`;
  panel.style.left = `${left}px`;
  panel.style.top = `${top}px`;
  panel.style.width = `${w}px`;
  panel.style.height = `${h}px`;
  if (m.glow) panel.style.setProperty("--accent", m.glow);
  if (m.color) panel.style.setProperty("--cap", m.color);
  stage.appendChild(panel);

  if (style === "pad") motionCtl = makePad(panel, w, h, sens);
  else if (style === "arrows") motionCtl = makeArrows(panel, w, h, sens, unit);
  else motionCtl = makeTrail(panel, w, h, sens);

  return { right: left + w, bottom: top + h };
}

/* glowing line tracing recent motion, fades out */
function makeTrail(panel, w, h, sens) {
  const canvas = document.createElement("canvas");
  const dpr = window.devicePixelRatio || 1;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;
  panel.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const accent = getComputedStyle(panel).getPropertyValue("--accent").trim();

  // infinite plane: the head roams unbounded virtual coordinates and a
  // soft camera chases it, so the trail never pins against the panel edge
  const LIFE = 700, SCALE = 0.1 * sens, FOLLOW = 0.16;
  let pts = [], px = 0, py = 0, camX = 0, camY = 0, lastMove = 0;
  let raf;

  function frame() {
    const now = performance.now();
    while (pts.length && now - pts[0].t > LIFE) pts.shift();
    if (!pts.length && now - lastMove > LIFE) {
      px = py = camX = camY = 0;            // re-zero so floats never drift
    }
    camX += (px - camX) * FOLLOW;
    camY += (py - camY) * FOLLOW;
    const ox = w / 2 - camX, oy = h / 2 - camY;

    ctx.clearRect(0, 0, w, h);
    ctx.lineCap = ctx.lineJoin = "round";
    ctx.strokeStyle = ctx.fillStyle = ctx.shadowColor = accent;
    for (let i = 1; i < pts.length; i++) {
      const fade = 1 - (now - pts[i].t) / LIFE;
      ctx.globalAlpha = fade;
      ctx.lineWidth = 1.5 + 1.5 * fade;
      ctx.shadowBlur = 9 * fade;
      ctx.beginPath();
      ctx.moveTo(pts[i - 1].x + ox, pts[i - 1].y + oy);
      ctx.lineTo(pts[i].x + ox, pts[i].y + oy);
      ctx.stroke();
    }
    if (pts.length) {                       // glowing head
      ctx.globalAlpha = 1 - (now - lastMove) / LIFE;
      ctx.shadowBlur = 12;
      ctx.beginPath();
      ctx.arc(px + ox, py + oy, 3, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    raf = requestAnimationFrame(frame);
  }
  raf = requestAnimationFrame(frame);

  return {
    onMove(dx, dy) {
      const t = performance.now();
      px += dx * SCALE;
      py += dy * SCALE;
      pts.push({ x: px, y: py, t });
      lastMove = t;
    },
    destroy() { cancelAnimationFrame(raf); },
  };
}

/* joystick-style dot deflecting with velocity, springs back to center */
function makePad(panel, w, h, sens) {
  const dot = document.createElement("div");
  dot.className = "pad-dot";
  panel.appendChild(dot);

  const cx = w / 2, cy = h / 2;
  const radius = Math.min(w, h) / 2 - 16;
  const K = 0.05 * sens;
  let vx = 0, vy = 0, raf;

  function frame() {
    vx *= 0.85;
    vy *= 0.85;
    let ox = vx * K, oy = vy * K;
    const len = Math.hypot(ox, oy);
    if (len > radius) { ox *= radius / len; oy *= radius / len; }
    const stretch = 1 + 0.35 * Math.min(len / radius, 1);
    dot.style.transform =
      `translate(${cx + ox - 8}px, ${cy + oy - 8}px) scale(${stretch})`;
    raf = requestAnimationFrame(frame);
  }
  raf = requestAnimationFrame(frame);

  return {
    onMove(dx, dy) { vx += dx; vy += dy; },
    destroy() { cancelAnimationFrame(raf); },
  };
}

/* four keycap arrows that light while moving in that direction */
function makeArrows(panel, w, h, sens, unit) {
  const s = Math.min(unit * 0.7, w / 3.4, h / 3.4);
  const cx = w / 2, cy = h / 2, g = 5;
  const defs = [
    ["up", "▲", cx - s / 2, cy - 1.5 * s - g],
    ["down", "▼", cx - s / 2, cy + s / 2 + g],
    ["left", "◀", cx - 1.5 * s - g, cy - s / 2],
    ["right", "▶", cx + s / 2 + g, cy - s / 2],
  ];
  const els = {}, timers = {};
  for (const [dir, glyph, x, y] of defs) {
    const el = document.createElement("div");
    el.className = "key";
    el.style.left = `${x}px`;
    el.style.top = `${y}px`;
    el.style.width = `${s}px`;
    el.style.height = `${s}px`;
    el.style.setProperty("--fs", `${s * 0.38}px`);
    const span = document.createElement("span");
    span.textContent = glyph;
    el.appendChild(span);
    panel.appendChild(el);
    els[dir] = el;
  }

  const DEAD = 4 / sens, HOLD = 140;
  function trigger(dir) {
    els[dir].classList.add("down");
    clearTimeout(timers[dir]);
    timers[dir] = setTimeout(() => els[dir].classList.remove("down"), HOLD);
  }

  return {
    onMove(dx, dy) {
      if (dx > DEAD) trigger("right");
      else if (dx < -DEAD) trigger("left");
      if (dy > DEAD) trigger("down");
      else if (dy < -DEAD) trigger("up");
    },
    destroy() { Object.values(timers).forEach(clearTimeout); },
  };
}

function keyEls(id) {
  return stage.querySelectorAll(`[data-key="${CSS.escape(id)}"]`);
}

function setDown(id, down) {
  keyEls(id).forEach((el) => el.classList.toggle("down", down));
}

function flash(id) {
  keyEls(id).forEach((el) => {
    el.classList.add("down");
    clearTimeout(flashTimers.get(el));
    flashTimers.set(el, setTimeout(() => el.classList.remove("down"), FLASH_MS));
  });
}

let es = null;
let esMotion = false;

function connect() {
  // only subscribe to mouse motion when this layout has a motion widget
  es?.close();
  esMotion = !!motionCtl;
  es = new EventSource(esMotion ? "/events" : "/events?motion=0");

  es.onopen = () => stage.classList.remove("offline");
  es.onerror = () => stage.classList.add("offline");  // EventSource auto-reconnects
  es.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    switch (msg.t) {
      case "down":
        setDown(msg.k, true);
        break;
      case "up":
        setDown(msg.k, false);
        break;
      case "flash":
        flash(msg.k);
        break;
      case "move":
        motionCtl?.onMove(msg.dx, msg.dy);
        break;
      case "state":
        stage.querySelectorAll(".key.down").forEach((el) => el.classList.remove("down"));
        msg.held.forEach((k) => setDown(k, true));
        break;
      case "reload":
        // resubscribe if the new layout gained or lost the motion widget
        buildLayout().then(() => {
          if (!!motionCtl !== esMotion) connect();
        });
        break;
    }
  };
}

buildLayout().then(connect);
