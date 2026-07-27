(() => {
  "use strict";

  // ── canvas ──────────────────────────────────────────────────────────────
  const canvas = document.getElementById("game");
  const ctx = canvas.getContext("2d");
  const W = canvas.width;
  const H = canvas.height;

  // ── HUD / overlay ───────────────────────────────────────────────────────
  const scoreEl = document.getElementById("score");
  const bestEl = document.getElementById("best");
  const padsEl = document.getElementById("pads");
  const overlay = document.getElementById("overlay");
  const overlayTitle = document.getElementById("overlay-title");
  const overlayMsg = document.getElementById("overlay-msg");
  const startBtn = document.getElementById("start-btn");

  const BEST_KEY = "mars-hopper-best";
  // Sandboxed iframe (no allow-same-origin) has no durable storage —
  // fail soft so high scores are session-only inside Switch Bay.
  function loadBest() {
    try { return Number(localStorage.getItem(BEST_KEY) || 0); } catch { return 0; }
  }
  function saveBest(n) {
    try { localStorage.setItem(BEST_KEY, String(n)); } catch { /* opaque origin */ }
  }
  let best = loadBest();
  bestEl.textContent = String(best);

  // ── palette ─────────────────────────────────────────────────────────────
  const C = {
    skyTop: "#1a0c14",
    skyMid: "#3a1818",
    skyBot: "#6a2a1a",
    ground: "#4a2010",
    dust: "#8a4030",
    pad: "#6a7080",
    padLite: "#a0a8b4",
    padDark: "#3a4048",
    padStripe: "#f0c040",
    padGlow: "#5eb8ff",
    ship: "#c8d0d8",       // stainless steel
    shipLite: "#e8eef4",
    shipDark: "#8a929c",
    shipShade: "#6a727c",
    heatTile: "#1a1a1c",   // black TPS / flaps
    heatTileLite: "#2e2e32",
    heatTileDark: "#0c0c0e",
    shipTip: "#b8c0c8",    // nose is steel, not blue
    fin: "#141416",        // black flaps only
    flame: "#ffcc40",
    flameHot: "#fff8e0",
    flameBlue: "#80c0ff",
    crater: "#2a1008",
    rock: "#5a3020",
    star: "#fff8e8",
    danger: "#ff4d4d",
    text: "#f5e6d3",
    fuel: "#40e080",
    fuelLow: "#ff8040",
    fuelEmpty: "#ff3030",
    tower: "#5a6068",
    towerDark: "#2a3038",
    chop: "#8a9098",
    chopLite: "#c0c8d0",
  };

  // ── game constants ──────────────────────────────────────────────────────
  const LANE_H = 56;
  const SHIP_W = 18;
  const SHIP_H = 28;
  const HOP_MS = 220;
  const GRAVITY = 0.35;
  const MAX_FUEL = 100;
  const FUEL_DRAIN = 22; // per second while boosting (~4.5s full tank)
  const CHOP_REFUEL = 140; // chopsticks: full tank in ~0.7s
  const BOOST_REFUEL = CHOP_REFUEL / 42; // boost pads: 42× slower drip
  const BOOST_RISE = 145; // world units / sec
  const CHOP_CATCH_HALF = 9; // px from center — tight chopsticks catch
  const HOLD_THRESHOLD = 0.12;

  // ── state ───────────────────────────────────────────────────────────────
  let state = "title"; // title | play | dead
  let score = 0;
  let padsHopped = 0;
  let cameraY = 0;
  let targetCameraY = 0;
  let time = 0;
  let hopCooldown = 0;
  let particles = [];
  let stars = [];
  let dustPuffs = [];
  let shake = 0;
  let lanes = [];
  let ship = null;
  let keys = Object.create(null);
  let lastTs = 0;
  let animId = 0;
  let hopHeld = false;
  let hopHoldTime = 0;
  let boostHintT = 0;
  let floatTexts = [];
  let boostStartLane = 0;

  // title chopsticks cinematic
  let titlePhase = 0; // seconds into loop
  const TITLE_LOOP = 8.6;
  const TITLE_SHIP_SCALE = 5; // hero scale on welcome only
  const HOP_ZONE_FRAC = 2 / 3; // bottom third = hold-to-hop on touch

  // ── audio ───────────────────────────────────────────────────────────────
  let audioCtx = null;
  let boostOsc = null;
  let boostGain = null;
  let ambientNodes = null; // title wind + raptor idle

  function ensureAudio() {
    if (!audioCtx) {
      try {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      } catch (_) {
        /* silent */
      }
    }
    if (audioCtx && audioCtx.state === "suspended") audioCtx.resume();
    if (state === "title") startTitleAmbient();
  }

  function beep(freq, dur, type = "square", gain = 0.04) {
    if (!audioCtx) return;
    const t0 = audioCtx.currentTime;
    const o = audioCtx.createOscillator();
    const g = audioCtx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(freq, t0);
    g.gain.setValueAtTime(gain, t0);
    g.gain.exponentialRampToValueAtTime(0.001, t0 + dur);
    o.connect(g);
    g.connect(audioCtx.destination);
    o.start(t0);
    o.stop(t0 + dur);
  }

  function sfxHop() {
    beep(220, 0.06, "square", 0.03);
    beep(440, 0.08, "square", 0.025);
  }
  function sfxLand() {
    beep(160, 0.05, "triangle", 0.04);
    beep(90, 0.08, "sine", 0.03);
  }
  function sfxDie() {
    beep(180, 0.12, "sawtooth", 0.04);
    beep(90, 0.2, "sawtooth", 0.035);
    beep(50, 0.28, "square", 0.03);
  }
  function sfxScore() {
    beep(520, 0.06, "square", 0.03);
    beep(780, 0.1, "square", 0.025);
  }
  function sfxCatch() {
    beep(120, 0.1, "triangle", 0.05);
    beep(80, 0.15, "sine", 0.04);
    beep(240, 0.08, "square", 0.02);
  }
  function sfxBoostStart() {
    beep(90, 0.1, "sawtooth", 0.035);
    beep(180, 0.12, "square", 0.03);
    beep(360, 0.08, "square", 0.02);
  }
  function sfxBoostEnd() {
    beep(200, 0.06, "triangle", 0.03);
    beep(100, 0.1, "sine", 0.025);
  }

  function startBoostHum() {
    if (!audioCtx || boostOsc) return;
    boostOsc = audioCtx.createOscillator();
    boostGain = audioCtx.createGain();
    boostOsc.type = "sawtooth";
    boostOsc.frequency.value = 55;
    boostGain.gain.value = 0.018;
    boostOsc.connect(boostGain);
    boostGain.connect(audioCtx.destination);
    boostOsc.start();
  }

  function stopBoostHum() {
    if (!boostOsc) return;
    try {
      boostGain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.08);
      boostOsc.stop(audioCtx.currentTime + 0.1);
    } catch (_) {
      /* ignore */
    }
    boostOsc = null;
    boostGain = null;
  }

  function startTitleAmbient() {
    if (!audioCtx || ambientNodes) return;

    const master = audioCtx.createGain();
    master.gain.value = 0.0;
    master.connect(audioCtx.destination);
    master.gain.linearRampToValueAtTime(1, audioCtx.currentTime + 0.8);

    // Mars wind: filtered noise
    const windBuf = audioCtx.createBuffer(1, audioCtx.sampleRate * 2, audioCtx.sampleRate);
    const windData = windBuf.getChannelData(0);
    let last = 0;
    for (let i = 0; i < windData.length; i++) {
      const white = Math.random() * 2 - 1;
      last = (last + 0.02 * white) / 1.02; // brown-ish
      windData[i] = last * 3.5;
    }
    const windSrc = audioCtx.createBufferSource();
    windSrc.buffer = windBuf;
    windSrc.loop = true;
    const windFilter = audioCtx.createBiquadFilter();
    windFilter.type = "bandpass";
    windFilter.frequency.value = 280;
    windFilter.Q.value = 0.6;
    const windGain = audioCtx.createGain();
    windGain.gain.value = 0.035;
    windSrc.connect(windFilter);
    windFilter.connect(windGain);
    windGain.connect(master);
    windSrc.start();

    // Distant raptor idle — dual low rumbles
    const raptorGain = audioCtx.createGain();
    raptorGain.gain.value = 0.012;
    raptorGain.connect(master);

    const r1 = audioCtx.createOscillator();
    r1.type = "sawtooth";
    r1.frequency.value = 42;
    const r1f = audioCtx.createBiquadFilter();
    r1f.type = "lowpass";
    r1f.frequency.value = 120;
    r1.connect(r1f);
    r1f.connect(raptorGain);
    r1.start();

    const r2 = audioCtx.createOscillator();
    r2.type = "triangle";
    r2.frequency.value = 63;
    const r2g = audioCtx.createGain();
    r2g.gain.value = 0.5;
    r2.connect(r2g);
    r2g.connect(raptorGain);
    r2.start();

    // slow pulse on idle
    const lfo = audioCtx.createOscillator();
    lfo.frequency.value = 0.35;
    const lfoGain = audioCtx.createGain();
    lfoGain.gain.value = 0.006;
    lfo.connect(lfoGain);
    lfoGain.connect(raptorGain.gain);
    lfo.start();

    // sparse wind gusts via gain automation
    const gust = () => {
      if (!ambientNodes) return;
      const t = audioCtx.currentTime;
      windGain.gain.cancelScheduledValues(t);
      windGain.gain.setValueAtTime(windGain.gain.value, t);
      windGain.gain.linearRampToValueAtTime(0.055, t + 0.4);
      windGain.gain.linearRampToValueAtTime(0.03, t + 1.6);
      ambientNodes.gustTimer = setTimeout(gust, 2800 + Math.random() * 3200);
    };

    ambientNodes = { master, windSrc, r1, r2, lfo, windGain, gustTimer: null };
    ambientNodes.gustTimer = setTimeout(gust, 1200);
  }

  function stopTitleAmbient() {
    if (!ambientNodes) return;
    const nodes = ambientNodes;
    ambientNodes = null;
    if (nodes.gustTimer) clearTimeout(nodes.gustTimer);
    try {
      const t = audioCtx.currentTime;
      nodes.master.gain.cancelScheduledValues(t);
      nodes.master.gain.setValueAtTime(nodes.master.gain.value, t);
      nodes.master.gain.linearRampToValueAtTime(0.001, t + 0.4);
      setTimeout(() => {
        try {
          nodes.windSrc.stop();
          nodes.r1.stop();
          nodes.r2.stop();
          nodes.lfo.stop();
        } catch (_) {
          /* ignore */
        }
      }, 450);
    } catch (_) {
      /* ignore */
    }
  }

  // ── helpers ─────────────────────────────────────────────────────────────
  function clamp(v, a, b) {
    return Math.max(a, Math.min(b, v));
  }
  function rand(a, b) {
    return a + Math.random() * (b - a);
  }
  function irand(a, b) {
    return (Math.random() * (b - a + 1) + a) | 0;
  }
  function lerp(a, b, t) {
    return a + (b - a) * t;
  }
  function easeInOut(t) {
    return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
  }
  function worldToScreenY(wy) {
    return H - 48 - (wy - cameraY);
  }

  // ── starfield ───────────────────────────────────────────────────────────
  function initStars() {
    stars = [];
    for (let i = 0; i < 48; i++) {
      stars.push({
        x: Math.random() * W,
        y: Math.random() * H,
        s: Math.random() < 0.3 ? 2 : 1,
        tw: Math.random() * Math.PI * 2,
      });
    }
  }

  // ── lanes / pads ────────────────────────────────────────────────────────
  function makePad(x, w, kind) {
    return { x, w, kind: kind || "pad" };
  }

  function generateLane(index) {
    if (index === 0) {
      return {
        index,
        kind: "start",
        pads: [makePad(W / 2 - 50, 100, "home")],
        speed: 0,
        dir: 1,
        offset: 0,
      };
    }

    if (index > 0 && index % 8 === 0) {
      return {
        index,
        kind: "colony",
        pads: [makePad(40, W - 80, "colony")],
        speed: 0,
        dir: 1,
        offset: 0,
      };
    }

    // Rare chopsticks catch lane — precise center land, fast refuel
    // Reachable early (lane 6) then every ~12 lanes
    if (index === 6 || (index > 6 && index % 12 === 6)) {
      const chopW = 88;
      const speed = (0.35 + Math.random() * 0.25) * (Math.random() < 0.5 ? -1 : 1);
      return {
        index,
        kind: "pads",
        pads: [makePad(W / 2 - chopW / 2 + rand(-40, 40), chopW, "chopstick")],
        speed,
        dir: Math.sign(speed) || 1,
        offset: 0,
        hazard: null,
      };
    }

    const difficulty = Math.min(1, index / 40);
    const speed = (0.6 + difficulty * 1.6 + Math.random() * 0.5) * (Math.random() < 0.5 ? -1 : 1);
    const padCount = index < 4 ? 2 : irand(1, 3);
    const padW = clamp(70 - difficulty * 18 + irand(-6, 10), 42, 90);
    const pads = [];
    const gap = (W + padW) / padCount;
    const base = Math.random() * gap;

    // early boost pads to discover hold-to-boost (slow drip fuel)
    const forceBoost = index === 2 || index === 5;
    for (let i = 0; i < padCount; i++) {
      const x = (base + i * gap) % (W + padW) - padW * 0.25;
      let kind = "pad";
      if (forceBoost && i === 0) kind = "boost";
      else if (Math.random() < 0.14 + difficulty * 0.08) kind = "boost";
      // very rare chopsticks mixed into normal rows (rarer than boost)
      else if (index > 8 && Math.random() < 0.035) kind = "chopstick";
      const w =
        kind === "boost" ? padW + 10 : kind === "chopstick" ? Math.max(padW, 78) : padW;
      pads.push(makePad(x, w, kind));
    }

    let hazard = null;
    if (index > 3 && Math.random() < 0.22 + difficulty * 0.15) {
      hazard = {
        x: Math.random() * W,
        w: 28,
        h: 16,
        speed: (1.2 + difficulty) * (Math.random() < 0.5 ? -1 : 1),
      };
    }

    return {
      index,
      kind: "pads",
      pads,
      speed,
      dir: Math.sign(speed) || 1,
      offset: 0,
      hazard,
    };
  }

  function ensureLanesAround(shipLane) {
    const min = Math.max(0, Math.floor(shipLane) - 2);
    const max = Math.ceil(shipLane) + 14;
    const have = new Set(lanes.map((l) => l.index));
    for (let i = min; i <= max; i++) {
      if (!have.has(i)) lanes.push(generateLane(i));
    }
    lanes = lanes.filter((l) => l.index >= Math.floor(shipLane) - 3);
    lanes.sort((a, b) => a.index - b.index);
  }

  function laneWorldY(index) {
    return index * LANE_H;
  }

  function laneFromWorldY(wy) {
    return Math.round(wy / LANE_H);
  }

  // ── ship ────────────────────────────────────────────────────────────────
  function resetShip() {
    ship = {
      lane: 0,
      x: W / 2,
      y: 0,
      vx: 0,
      vy: 0,
      hopping: false,
      hopFrom: null,
      hopTo: null,
      hopT: 0,
      facing: 1,
      alive: true,
      onPad: null,
      thruster: 0,
      bob: 0,
      fuel: 0,
      boosting: false,
      boostReady: false,
      _arc: 0,
    };
  }

  // ── particles ───────────────────────────────────────────────────────────
  function burst(x, y, n, color, speed = 2) {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2;
      const sp = Math.random() * speed;
      particles.push({
        x,
        y,
        vx: Math.cos(a) * sp,
        vy: Math.sin(a) * sp - Math.random() * 1.5,
        life: rand(0.3, 0.8),
        max: 0.8,
        color,
        size: irand(1, 3),
      });
    }
  }

  function thrusterPuff(x, y, heavy = false) {
    const n = heavy ? 8 : 4;
    for (let i = 0; i < n; i++) {
      particles.push({
        x: x + rand(-5, 5),
        y: y + 4,
        vx: rand(-0.8, 0.8),
        vy: rand(1.2, heavy ? 4.5 : 3),
        life: rand(0.15, heavy ? 0.45 : 0.35),
        max: heavy ? 0.45 : 0.35,
        color: Math.random() < 0.4 ? C.flameBlue : Math.random() < 0.5 ? C.flame : C.flameHot,
        size: irand(2, heavy ? 4 : 3),
      });
    }
  }

  /** Dust + ember trail along a hop arc */
  function hopArcDust(x, y, t) {
    // flame kick early in hop
    if (t < 0.55) thrusterPuff(x, y, false);
    // regolith dust throughout
    for (let i = 0; i < 2; i++) {
      particles.push({
        x: x + rand(-6, 6),
        y: y + rand(2, 10),
        vx: rand(-1.2, 1.2),
        vy: rand(0.4, 2.2),
        life: rand(0.25, 0.5),
        max: 0.5,
        color: Math.random() < 0.35 ? C.flame : C.dust,
        size: irand(1, 3),
      });
    }
  }

  function spawnFloat(text, x, y, color, scale = 1) {
    floatTexts.push({
      text,
      x,
      y,
      life: 1.35,
      max: 1.35,
      color: color || C.flameHot,
      vy: -48,
      scale,
    });
  }

  function updateFloats(dt) {
    for (let i = floatTexts.length - 1; i >= 0; i--) {
      const f = floatTexts[i];
      f.y += f.vy * dt;
      f.vy *= 0.96;
      f.life -= dt;
      if (f.life <= 0) floatTexts.splice(i, 1);
    }
  }

  function drawFloats() {
    for (const f of floatTexts) {
      const a = clamp(f.life / f.max, 0, 1);
      ctx.globalAlpha = a;
      ctx.fillStyle = f.color;
      const size = (f.scale > 1 ? 9 : 7) ;
      ctx.font = `${size}px "Press Start 2P", monospace`;
      ctx.textAlign = "center";
      // shadow
      ctx.fillStyle = "rgba(0,0,0,0.55)";
      ctx.fillText(f.text, f.x + 1, f.y + 1);
      ctx.fillStyle = f.color;
      ctx.fillText(f.text, f.x, f.y);
    }
    ctx.globalAlpha = 1;
  }

  function padCenterX(pad) {
    return pad.x + pad.w / 2;
  }

  // ── collision ───────────────────────────────────────────────────────────
  function padUnderShip(lane, sx) {
    if (!lane) return null;
    for (const p of lane.pads) {
      const left = p.x;
      const right = p.x + p.w;
      if (sx >= left && sx <= right) return p;
      if (sx >= left - (W + 40) && sx <= right - (W + 40)) return p;
      if (sx >= left + (W + 40) && sx <= right + (W + 40)) return p;
    }
    return null;
  }

  function padCenter(pad) {
    return pad.x + pad.w / 2;
  }

  /** Chopsticks only count as a valid catch in a tight center band. */
  function isChopstickAligned(pad, sx) {
    if (!pad || pad.kind !== "chopstick") return true;
    return Math.abs(sx - padCenter(pad)) <= CHOP_CATCH_HALF;
  }

  /** Keep feet on the deck: half-ship inset from pad edges (tighter on chopsticks). */
  function clampXToPad(x, pad) {
    if (!pad) return clamp(x, 12, W - 12);
    if (pad.kind === "chopstick") {
      // once caught, stay in the jaws
      const c = padCenter(pad);
      return clamp(x, c - CHOP_CATCH_HALF, c + CHOP_CATCH_HALF);
    }
    const inset = SHIP_W * 0.35;
    const min = pad.x + inset;
    const max = pad.x + pad.w - inset;
    if (max <= min) return pad.x + pad.w / 2;
    return clamp(x, min, max);
  }

  function canBoostOnPad(pad) {
    return pad && (pad.kind === "boost" || pad.kind === "chopstick");
  }

  function refuelRateForPad(pad) {
    if (!pad) return 0;
    if (pad.kind === "chopstick") return CHOP_REFUEL;
    if (pad.kind === "boost") return BOOST_REFUEL;
    return 0;
  }

  function currentPad() {
    if (!ship || !ship.onPad) return null;
    // prefer live pad ref from lane (positions move)
    const lane = lanes.find((l) => l.index === ship.lane);
    if (!lane) return ship.onPad;
    const live = padUnderShip(lane, ship.x) || ship.onPad;
    return live;
  }

  function boundShipToPad() {
    if (!ship || ship.hopping || ship.boosting || !ship.alive) return;
    const pad = currentPad();
    if (!pad) return;
    ship.x = clampXToPad(ship.x, pad);
    ship.onPad = pad;
  }

  function hitHazard(lane, sx, sy) {
    if (!lane || !lane.hazard) return false;
    const h = lane.hazard;
    const shipLeft = sx - SHIP_W / 2;
    const shipRight = sx + SHIP_W / 2;
    const shipBottom = sy;
    const shipTop = sy + SHIP_H * 0.4;
    const hy = laneWorldY(lane.index);
    return (
      shipRight > h.x &&
      shipLeft < h.x + h.w &&
      shipBottom < hy + 14 &&
      shipTop > hy - 4
    );
  }

  // ── hop / boost ─────────────────────────────────────────────────────────
  function canBoostFromPad() {
    return (
      ship &&
      ship.alive &&
      ship.boostReady &&
      ship.fuel > 2 &&
      !ship.hopping &&
      canBoostOnPad(ship.onPad)
    );
  }

  function tryHop(dir = 1) {
    if (state !== "play" || !ship.alive || ship.hopping || ship.boosting || hopCooldown > 0) return;
    // boost pads: hop is hold-to-boost, not single hop (except hop back)
    if (dir > 0 && ship.boostReady && ship.fuel > 0) {
      startBoost();
      return;
    }

    const nextLaneIdx = ship.lane + dir;
    if (nextLaneIdx < 0) return;

    ensureLanesAround(nextLaneIdx);
    const fromY = ship.y;
    const toY = laneWorldY(nextLaneIdx);

    ship.hopping = true;
    ship.hopFrom = { x: ship.x, y: fromY, lane: ship.lane };
    ship.hopTo = { x: ship.x, y: toY, lane: nextLaneIdx };
    ship.hopT = 0;
    ship.thruster = 1;
    ship.onPad = null;
    ship.boostReady = false;
    hopCooldown = 0.12;

    // liftoff dust cloud + thruster kick
    thrusterPuff(ship.x, worldToScreenY(fromY), true);
    burst(ship.x, worldToScreenY(fromY) + 4, 10, C.dust, 2.2);
    burst(ship.x, worldToScreenY(fromY), 6, C.flame, 1.8);
    sfxHop();
  }

  function startBoost() {
    if (!canBoostFromPad() || ship.boosting) return;
    ship.boosting = true;
    ship.onPad = null;
    ship.thruster = 1.2;
    ship.vy = BOOST_RISE;
    boostStartLane = ship.lane;
    hopCooldown = 0;
    sfxBoostStart();
    startBoostHum();
    burst(ship.x, worldToScreenY(ship.y), 14, C.flame, 3);
    thrusterPuff(ship.x, worldToScreenY(ship.y), true);
  }

  function stopBoostAndLand(reason) {
    if (!ship || !ship.boosting) return;
    ship.boosting = false;
    ship.thruster = 0.5;
    ship.vy = 0;
    stopBoostHum();
    sfxBoostEnd();

    // land on the lane nearest current altitude
    let laneIdx = laneFromWorldY(ship.y);
    if (laneIdx < 0) laneIdx = 0;
    ensureLanesAround(laneIdx);

    // prefer landing slightly below if between pads (more forgiving)
    const frac = ship.y / LANE_H - laneIdx;
    if (frac < -0.15) laneIdx = Math.max(0, laneIdx - 1);

    ship.lane = laneIdx;
    ship.y = laneWorldY(laneIdx);
    ship._arc = 0;

    const lane = lanes.find((l) => l.index === ship.lane);
    const pad = padUnderShip(lane, ship.x);

    if (!pad) {
      die(reason || "Released off-pad. Starship is Mars dust.");
      return;
    }

    if (pad.kind === "chopstick" && !isChopstickAligned(pad, ship.x)) {
      die("Chopsticks miss — need dead-center alignment.");
      return;
    }

    applyLanding(lane, pad, true);
  }

  function applyLanding(lane, pad, fromBoost) {
    ship.onPad = pad;
    ship.hopping = false;
    ship.boosting = false;
    ship.y = laneWorldY(ship.lane);
    ship._arc = 0;
    // snap into chopsticks jaws on successful catch
    if (pad.kind === "chopstick") {
      ship.x = padCenter(pad);
    } else {
      ship.x = clampXToPad(ship.x, pad);
    }

    if (lane.kind === "pads") ship.vx = lane.speed;
    else ship.vx = 0;

    // boost / chopsticks arm continuous burn; fuel drips while parked (see update)
    if (canBoostOnPad(pad)) {
      ship.boostReady = ship.fuel > 2;
      boostHintT = fromBoost ? 0 : pad.kind === "chopstick" ? 2.8 : 2.2;
      if (pad.kind === "chopstick") {
        burst(ship.x, worldToScreenY(ship.y) - 12, 18, C.chopLite, 3);
        burst(ship.x, worldToScreenY(ship.y) - 8, 10, C.fuel, 2);
        sfxCatch();
      } else {
        burst(ship.x, worldToScreenY(ship.y) - 10, 12, C.padGlow, 2.5);
      }
      if (hopHeld && ship.fuel > 2) {
        setTimeout(() => {
          if (state === "play" && ship && ship.alive && hopHeld && canBoostFromPad()) {
            startBoost();
          }
        }, 40);
      }
    } else {
      ship.boostReady = false;
    }

    const prevPads = padsHopped;
    // during boost, padsHopped already ticks mid-flight — use boostStartLane for combos
    const boostLanes = fromBoost ? Math.max(0, ship.lane - boostStartLane) : 0;
    const lanesCleared = fromBoost ? boostLanes : Math.max(0, ship.lane - prevPads);
    const screenY = worldToScreenY(ship.y);

    if (ship.lane > prevPads || (fromBoost && boostLanes > 0) || pad.kind === "chopstick") {
      let gain =
        pad.kind === "chopstick"
          ? 40
          : pad.kind === "boost"
            ? 15
            : pad.kind === "colony"
              ? 25
              : 10;
      if (fromBoost) {
        gain += 5;
        if (boostLanes > 1) gain += (boostLanes - 1) * 5;
      }
      score += gain;
      padsHopped = Math.max(padsHopped, ship.lane);
      scoreEl.textContent = String(score);
      padsEl.textContent = String(padsHopped);

      if (fromBoost && boostLanes > 0) {
        const n = boostLanes;
        const label = n === 1 ? "+1 LANE" : `+${n} LANES`;
        spawnFloat(label, ship.x, screenY - 28, C.flameHot, n >= 4 ? 1.2 : 1);
        if (n >= 5) spawnFloat("MEGA HOP", ship.x, screenY - 48, C.padGlow, 1.15);
        spawnFloat(`+${gain}`, ship.x + 28, screenY - 14, C.fuel, 1);
      } else if (pad.kind === "chopstick") {
        spawnFloat("CATCH!", ship.x, screenY - 30, "#40ff80", 1.2);
        spawnFloat("FAST FUEL", ship.x, screenY - 48, C.fuel, 1);
      } else if (pad.kind === "boost") {
        spawnFloat("BOOST PAD", ship.x, screenY - 24, C.padGlow, 1);
        spawnFloat("SLOW FUEL", ship.x, screenY - 40, C.fuelLow, 1);
      } else if (pad.kind === "colony") {
        spawnFloat("BASE +", ship.x, screenY - 24, C.padStripe, 1);
      } else if (lanesCleared > 0) {
        spawnFloat(`+${gain}`, ship.x, screenY - 22, C.text, 1);
      }

      if (pad.kind === "boost" || pad.kind === "chopstick" || pad.kind === "colony" || fromBoost)
        sfxScore();
      else sfxLand();
    } else {
      sfxLand();
    }

    burst(ship.x, screenY, 6, C.dust, 1.5);
    shake = fromBoost || pad.kind === "chopstick" ? 5 : 3;
    targetCameraY = Math.max(0, ship.y - LANE_H * 3);
  }

  function finishHop() {
    const to = ship.hopTo;
    ship.hopping = false;
    ship.lane = to.lane;
    ship.y = to.y;
    ship.x = to.x;
    ship.thruster = 0.4;

    ensureLanesAround(ship.lane);
    const lane = lanes.find((l) => l.index === ship.lane);
    const pad = padUnderShip(lane, ship.x);

    if (!pad) {
      die("Missed the launchpad. Starship is Mars dust.");
      return;
    }

    if (pad.kind === "chopstick" && !isChopstickAligned(pad, ship.x)) {
      die("Chopsticks miss — line up on the center jaws.");
      return;
    }

    applyLanding(lane, pad, false);
  }

  function die(msg) {
    if (!ship.alive) return;
    ship.alive = false;
    ship.hopping = false;
    ship.boosting = false;
    ship.boostReady = false;
    stopBoostHum();
    state = "dead";
    burst(ship.x, worldToScreenY(ship.y), 24, C.danger, 3.5);
    burst(ship.x, worldToScreenY(ship.y), 12, C.flame, 2.5);
    shake = 12;
    sfxDie();

    if (score > best) {
      best = score;
      saveBest(best);
      bestEl.textContent = String(best);
    }

    overlayTitle.textContent = "HULL BREACH";
    overlayMsg.textContent = `${msg} Score ${score} · Pads ${padsHopped}`;
    startBtn.textContent = "RELAUNCH";
    showDeathOverlay();
  }

  function showDeathOverlay() {
    stopTitleAmbient();
    overlay.classList.add("visible");
    overlay.classList.remove("title-mode");
  }

  function showTitleOverlay() {
    overlayTitle.textContent = "STARSHIP READY";
    overlayMsg.textContent =
      "Hop launchpads across Mars base. BOOST pads: hold hop to fly (slow drip fuel). CHOPSTICKS: rare, dead-center catch for fast refuel + boost. Release hop to land.";
    startBtn.textContent = "IGNITE";
    overlay.classList.add("visible", "title-mode");
    // ambient starts after first user gesture (autoplay policy)
    if (audioCtx) startTitleAmbient();
  }

  // ── input ───────────────────────────────────────────────────────────────
  function isHopKey(k, code) {
    return ["arrowup", "w", " ", "spacebar"].includes(k) || code === "Space";
  }

  function onKey(e, down) {
    const k = e.key.toLowerCase();
    keys[k] = down;

    // Launch / relaunch screens: Enter or Space = IGNITE / RELAUNCH
    if (down && (state === "title" || state === "dead")) {
      if (k === "enter" || k === " " || k === "spacebar" || e.code === "Space" || e.code === "Enter") {
        if (e.repeat) return;
        e.preventDefault();
        ensureAudio();
        startGame();
        return;
      }
    }

    if (isHopKey(k, e.code)) {
      e.preventDefault();
      if (state !== "play" || !ship || !ship.alive) return;

      if (down) {
        if (!hopHeld) {
          hopHeld = true;
          hopHoldTime = 0;
          // immediate boost if armed
          if (canBoostFromPad()) startBoost();
          else if (!ship.boosting && !ship.hopping) tryHop(1);
        }
      } else {
        hopHeld = false;
        hopHoldTime = 0;
        if (ship.boosting) stopBoostAndLand();
      }
      return;
    }

    if (!down) return;

    if (k === "arrowdown" || k === "s") {
      e.preventDefault();
      if (state === "play" && ship.lane > 0 && !ship.boosting) tryHop(-1);
    }
  }

  window.addEventListener("keydown", (e) => onKey(e, true));
  window.addEventListener("keyup", (e) => onKey(e, false));

  // pointer — bottom third = hop hold zone; upper = strafe (multi-touch friendly)
  let hopPointerId = null;
  let strafePointerId = null;
  let strafeLastX = 0;
  let hopStartY = 0;

  function canvasLocalYFrac(clientY) {
    const rect = canvas.getBoundingClientRect();
    return (clientY - rect.top) / rect.height;
  }

  function isCoarsePointer() {
    try {
      return window.matchMedia("(pointer: coarse)").matches;
    } catch (_) {
      return navigator.maxTouchPoints > 0;
    }
  }

  function isInHopZone(clientY) {
    // Desktop mouse: whole canvas hops. Touch: bottom third only so drag-strafe stays clean.
    if (!isCoarsePointer()) return true;
    return canvasLocalYFrac(clientY) >= HOP_ZONE_FRAC;
  }

  function applyStrafeDx(dx) {
    if (!ship || !ship.alive || state !== "play") return;
    if (Math.abs(dx) < 1) return;
    if (ship.boosting) {
      ship.x = clamp(ship.x + dx * 0.09, 12, W - 12);
    } else if (!ship.hopping) {
      ship.x += dx * 0.09;
      boundShipToPad();
    }
    ship.facing = dx > 0 ? 1 : -1;
  }

  canvas.addEventListener("pointerdown", (e) => {
    ensureAudio();
    if (state !== "play" || !ship || !ship.alive) return;

    const hopZone = isInHopZone(e.clientY);

    if (hopZone) {
      hopPointerId = e.pointerId;
      hopStartY = e.clientY;
      hopHeld = true;
      hopHoldTime = 0;
      try {
        canvas.setPointerCapture(e.pointerId);
      } catch (_) {
        /* ignore */
      }
      if (canBoostFromPad()) startBoost();
      else if (!ship.boosting && !ship.hopping) tryHop(1);
      // also allow strafe from hop finger
      strafeLastX = e.clientX;
    } else {
      // upper zone: strafe only (won't accidental hop)
      strafePointerId = e.pointerId;
      strafeLastX = e.clientX;
      try {
        canvas.setPointerCapture(e.pointerId);
      } catch (_) {
        /* ignore */
      }
    }
  });

  canvas.addEventListener("pointermove", (e) => {
    if (state !== "play" || !ship || !ship.alive) return;

    if (e.pointerId === hopPointerId) {
      const dx = e.clientX - strafeLastX;
      applyStrafeDx(dx);
      strafeLastX = e.clientX;
    } else if (e.pointerId === strafePointerId) {
      const dx = e.clientX - strafeLastX;
      applyStrafeDx(dx);
      strafeLastX = e.clientX;
    }
  });

  function endPointer(e) {
    if (e.pointerId === hopPointerId) {
      const dy = e.clientY - hopStartY;
      hopPointerId = null;
      hopHeld = false;
      hopHoldTime = 0;
      if (ship && ship.boosting) {
        stopBoostAndLand();
      } else if (dy > 50 && state === "play" && ship && ship.lane > 0 && !ship.boosting) {
        // swipe down in hop zone = hop back
        tryHop(-1);
      }
    }
    if (e.pointerId === strafePointerId) {
      strafePointerId = null;
    }
  }

  canvas.addEventListener("pointerup", endPointer);
  canvas.addEventListener("pointercancel", (e) => {
    if (e.pointerId === hopPointerId) {
      hopPointerId = null;
      hopHeld = false;
      if (ship && ship.boosting) stopBoostAndLand();
    }
    if (e.pointerId === strafePointerId) strafePointerId = null;
  });

  startBtn.addEventListener("click", () => {
    ensureAudio();
    startGame();
  });

  // unlock title ambient on first gesture anywhere
  function unlockAudioOnce() {
    ensureAudio();
    window.removeEventListener("pointerdown", unlockAudioOnce);
    window.removeEventListener("keydown", unlockAudioOnce);
  }
  window.addEventListener("pointerdown", unlockAudioOnce);
  window.addEventListener("keydown", unlockAudioOnce);

  // ── game lifecycle ──────────────────────────────────────────────────────
  function startGame() {
    score = 0;
    padsHopped = 0;
    cameraY = 0;
    targetCameraY = 0;
    hopCooldown = 0;
    hopHeld = false;
    hopHoldTime = 0;
    boostHintT = 0;
    floatTexts = [];
    boostStartLane = 0;
    hopPointerId = null;
    strafePointerId = null;
    particles = [];
    dustPuffs = [];
    shake = 0;
    lanes = [];
    stopBoostHum();
    stopTitleAmbient();
    resetShip();
    ensureLanesAround(0);
    ship.y = laneWorldY(0);
    ship.onPad = lanes[0].pads[0];
    // always center on PAD-0 (and after every relaunch)
    ship.x = padCenterX(ship.onPad);
    // starter propellant so the first BOOST pad is usable before chopsticks
    ship.fuel = 35;
    ship.boostReady = false;
    scoreEl.textContent = "0";
    padsEl.textContent = "0";
    state = "play";
    overlay.classList.remove("visible", "title-mode");
    beep(330, 0.06, "square", 0.03);
    beep(495, 0.1, "square", 0.03);
  }

  // ── title chopsticks sim ────────────────────────────────────────────────
  function titlePose(t) {
    // Chopsticks are a tower mechanism — NOT parented to the ship.
    // armY is independent. While held, shipY is driven by armY (stack in jaws).
    //
    // 0.0–1.8  ship descends from above; arms wait open at catch height
    // 1.8–2.6  arms close at catch height (ship hovers in the jaws)
    // 2.6–2.8  catch thump — locked
    // 2.8–4.8  arms lower to pad (ship rides in jaws)
    // 4.8–5.6  rest on pad, jaws closed
    // 5.6–6.2  jaws open at pad (ship free on pad)
    // 6.2–7.3  ship launches alone; arms stay open at pad
    // 7.3–8.6  arms slowly retract pad → catch height
    const p = t % TITLE_LOOP;
    const catchY = H * 0.42;
    const padY = H - 88;
    let shipY = catchY;
    let armY = catchY; // independent chopsticks carriage height
    let thruster = 0;
    let armClose = 0;
    let caught = false;
    let onPad = false;
    let retracting = false;
    let launching = false;
    let shipX = W / 2;
    let shipTilt = 0;
    let shipVisible = true;

    if (p < 1.8) {
      // free flight in — arms fixed open at catch
      const u = p / 1.8;
      shipY = lerp(-100, catchY, easeInOut(u));
      armY = catchY;
      thruster = 0.85 + Math.sin(p * 28) * 0.15;
      armClose = 0;
      shipTilt = Math.sin(p * 1.3) * 0.035;
      shipX = W / 2 + Math.sin(p * 1.1) * 5;
    } else if (p < 2.6) {
      // CATCH: arms close in place; ship holds station in the catch zone
      const u = (p - 1.8) / 0.8;
      armY = catchY;
      shipY = catchY + Math.sin(u * Math.PI * 2) * 2; // tiny hover, not attached
      thruster = lerp(0.55, 0.2, u) + Math.sin(p * 20) * 0.05;
      armClose = easeInOut(u);
      shipTilt = (1 - u) * 0.02;
      shipX = W / 2 + (1 - u) * Math.sin(p * 2) * 3;
    } else if (p < 2.8) {
      // lock
      const u = (p - 2.6) / 0.2;
      armY = catchY;
      shipY = catchY; // snap into jaws
      thruster = 0.12 * (1 - u);
      armClose = 1;
      caught = true;
      shipX = W / 2;
      shipTilt = 0;
    } else if (p < 4.8) {
      // arms lower; ship is carried (follows armY while held)
      const u = (p - 2.8) / 2.0;
      armY = lerp(catchY, padY, easeInOut(u));
      shipY = armY;
      thruster = 0;
      armClose = 1;
      caught = true;
      shipX = W / 2;
      shipTilt = Math.sin(u * Math.PI) * 0.015;
    } else if (p < 5.6) {
      armY = padY;
      shipY = padY;
      thruster = 0;
      armClose = 1;
      caught = true;
      onPad = true;
      shipX = W / 2;
      shipTilt = Math.sin((p - 4.8) * 1.6) * 0.01;
    } else if (p < 6.2) {
      // release jaws — arms stay at pad, ship free on deck
      const u = (p - 5.6) / 0.6;
      armY = padY;
      shipY = padY;
      thruster = 0;
      armClose = 1 - easeInOut(u);
      onPad = true;
      shipX = W / 2;
    } else if (p < 7.3) {
      // ship only lifts off; chopsticks stay put at pad
      const u = (p - 6.2) / 1.1;
      armY = padY;
      armClose = 0;
      shipY = lerp(padY, -120, easeInOut(u));
      thruster = 0.5 + u * 0.6;
      launching = true;
      shipX = W / 2 + Math.sin(u * 4) * 2;
      shipTilt = Math.sin(u * Math.PI) * 0.025;
    } else {
      // chopsticks retract alone back to catch height
      const u = (p - 7.3) / Math.max(0.01, TITLE_LOOP - 7.3);
      armY = lerp(padY, catchY, easeInOut(u));
      armClose = 0;
      shipY = -140;
      shipVisible = false;
      thruster = 0;
      retracting = true;
      shipX = W / 2;
    }

    return {
      shipX,
      shipY,
      armY,
      thruster,
      armClose,
      caught,
      onPad,
      launching,
      retracting,
      shipVisible,
      shipTilt,
      phase: p,
      catchY,
      padY,
    };
  }

  // ── update ──────────────────────────────────────────────────────────────
  function update(dt) {
    time += dt;
    if (hopCooldown > 0) hopCooldown -= dt;
    if (shake > 0) shake = Math.max(0, shake - dt * 40);
    if (boostHintT > 0) boostHintT -= dt;

    for (const s of stars) s.tw += dt * 3;

    if (state === "title") {
      titlePhase += dt;
      // catch thump once per loop (no white flash)
      const p = titlePhase % TITLE_LOOP;
      const prev = (titlePhase - dt + TITLE_LOOP * 100) % TITLE_LOOP;
      if (prev < 2.6 && p >= 2.6) {
        shake = 6;
        sfxCatch();
        burst(W / 2, H * 0.42, 14, C.chopLite, 2);
        burst(W / 2, H * 0.42 - SHIP_H * TITLE_SHIP_SCALE * 0.45, 10, C.ship, 1.4);
      }
    }

    // move lanes during play / title backdrop
    if (state === "play") {
      for (const lane of lanes) {
        if (lane.kind === "pads" && lane.speed) {
          const wrap = W + 40;
          for (const p of lane.pads) {
            p.x += lane.speed * 60 * dt;
            if (p.x > W + 20) p.x -= wrap;
            if (p.x + p.w < -20) p.x += wrap;
          }
        }
        if (lane.hazard) {
          lane.hazard.x += lane.hazard.speed * 60 * dt;
          if (lane.hazard.x > W + 40) lane.hazard.x = -40;
          if (lane.hazard.x < -40) lane.hazard.x = W + 40;
        }
      }
    }

    if (Math.random() < 0.15) {
      dustPuffs.push({
        x: Math.random() * W,
        y: H + 10,
        vy: -rand(10, 30),
        life: rand(0.8, 1.6),
        max: 1.6,
        size: irand(1, 2),
      });
    }
    for (let i = dustPuffs.length - 1; i >= 0; i--) {
      const d = dustPuffs[i];
      d.y += d.vy * dt;
      d.x += Math.sin(time * 2 + d.x) * 8 * dt;
      d.life -= dt;
      if (d.life <= 0) dustPuffs.splice(i, 1);
    }

    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i];
      p.x += p.vx * 60 * dt;
      p.y += p.vy * 60 * dt;
      p.vy += GRAVITY * 60 * dt * 0.02;
      p.life -= dt;
      if (p.life <= 0) particles.splice(i, 1);
    }

    cameraY += (targetCameraY - cameraY) * Math.min(1, dt * 6);
    updateFloats(dt);

    // gentle raptor pitch drift on title ambient
    if (state === "title" && ambientNodes && audioCtx) {
      try {
        ambientNodes.r1.frequency.setTargetAtTime(
          40 + Math.sin(time * 0.7) * 4,
          audioCtx.currentTime,
          0.5
        );
      } catch (_) {
        /* ignore */
      }
    }

    if (state !== "play" || !ship) return;

    // strafe: free in air (boost), deck-bounded on pads
    let move = 0;
    if (keys["arrowleft"] || keys["a"]) move -= 1;
    if (keys["arrowright"] || keys["d"]) move += 1;
    if (move !== 0 && !ship.hopping) {
      const spd = ship.boosting ? 200 : 160;
      ship.x += move * spd * dt;
      ship.facing = move;
      if (ship.boosting) ship.x = clamp(ship.x, 12, W - 12);
      else boundShipToPad();
    }

    // continuous boost flight
    if (ship.boosting && ship.alive) {
      ship.fuel = Math.max(0, ship.fuel - FUEL_DRAIN * dt);
      ship.y += BOOST_RISE * dt;
      ship.lane = laneFromWorldY(ship.y);
      ship.thruster = 1.1 + Math.sin(time * 40) * 0.15;
      ship._arc = 8 + Math.sin(time * 20) * 3;
      ensureLanesAround(ship.lane);
      targetCameraY = Math.max(0, ship.y - LANE_H * 3);
      thrusterPuff(ship.x, worldToScreenY(ship.y + (ship._arc || 0)), true);

      // score tick while climbing
      if (ship.lane > padsHopped) {
        score += (ship.lane - padsHopped) * 3;
        padsHopped = ship.lane;
        scoreEl.textContent = String(score);
        padsEl.textContent = String(padsHopped);
      }

      // hum pitch rises as fuel drops
      if (boostOsc && audioCtx) {
        boostOsc.frequency.setTargetAtTime(55 + (1 - ship.fuel / MAX_FUEL) * 40, audioCtx.currentTime, 0.05);
      }

      // hazard while boosting through a lane
      const lane = lanes.find((l) => l.index === ship.lane);
      if (lane && hitHazard(lane, ship.x, ship.y)) {
        die("Hit a Mars base rover mid-boost. Insurance denied.");
        return;
      }

      if (ship.fuel <= 0) {
        stopBoostAndLand("Fuel empty — engines cut. Missed the pad.");
        return;
      }

      // still holding? if not (keyboard released edge case), land
      if (!hopHeld && !(keys["arrowup"] || keys["w"] || keys[" "] || keys["spacebar"])) {
        stopBoostAndLand();
        return;
      }
    } else if (ship.hopping) {
      ship.hopT += dt / (HOP_MS / 1000);
      const t = clamp(ship.hopT, 0, 1);
      const ease = easeInOut(t);
      const from = ship.hopFrom;
      const to = ship.hopTo;
      ship.x = from.x + (to.x - from.x) * ease;
      const arc = Math.sin(t * Math.PI) * 36;
      ship.y = from.y + (to.y - from.y) * ease;
      ship._arc = arc;
      ship.thruster = 1 - t * 0.6;
      if (t < 0.85) hopArcDust(ship.x, worldToScreenY(ship.y + arc), t);
      if (t >= 1) {
        ship._arc = 0;
        finishHop();
      }
    } else if (ship.alive) {
      ship._arc = 0;
      ship.bob = Math.sin(time * 6) * 1.5;
      const lane = lanes.find((l) => l.index === ship.lane);

      if (lane && ship.onPad) {
        // ride moving pads; stay glued to deck bounds
        if (lane.kind === "pads" && lane.speed) {
          ship.x += lane.speed * 60 * dt;
          if (ship.x > W + 10) ship.x -= W + 40;
          if (ship.x < -10) ship.x += W + 40;
        }
        let pad = padUnderShip(lane, ship.x);
        // if X drifted past edges, snap back onto last known pad
        if (!pad && ship.onPad) {
          ship.x = clampXToPad(ship.x, ship.onPad);
          pad = padUnderShip(lane, ship.x) || ship.onPad;
        }
        if (!pad) {
          die("Slid off the launchpad into the regolith.");
          return;
        }
        ship.onPad = pad;
        ship.x = clampXToPad(ship.x, pad);

        // continuous refuel while parked
        const rate = refuelRateForPad(pad);
        if (rate > 0 && ship.fuel < MAX_FUEL) {
          const before = ship.fuel;
          ship.fuel = Math.min(MAX_FUEL, ship.fuel + rate * dt);
          // occasional drip FX on chopsticks
          if (pad.kind === "chopstick" && ship.fuel > before && Math.random() < 0.2) {
            burst(ship.x, worldToScreenY(ship.y) - 6, 2, C.fuel, 0.8);
          }
        }

        if (canBoostOnPad(pad)) {
          ship.boostReady = ship.fuel > 2;
        } else {
          ship.boostReady = false;
        }
      }

      if (lane && hitHazard(lane, ship.x, ship.y)) {
        die("Hit a Mars base rover. Insurance denied.");
        return;
      }

      if (ship.thruster > 0) ship.thruster = Math.max(0, ship.thruster - dt * 2);
    }
  }

  // ── draw ────────────────────────────────────────────────────────────────
  function drawBackground() {
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, C.skyTop);
    g.addColorStop(0.45, C.skyMid);
    g.addColorStop(1, C.skyBot);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);

    for (const s of stars) {
      const a = 0.4 + 0.6 * (0.5 + 0.5 * Math.sin(s.tw));
      ctx.globalAlpha = a;
      ctx.fillStyle = C.star;
      ctx.fillRect(s.x | 0, ((s.y + cameraY * 0.02) % H) | 0, s.s, s.s);
    }
    ctx.globalAlpha = 1;

    ctx.fillStyle = "#4a1810";
    ctx.beginPath();
    ctx.moveTo(0, H * 0.55);
    for (let x = 0; x <= W; x += 40) {
      const y = H * 0.52 + Math.sin(x * 0.02 + cameraY * 0.01) * 18 + Math.cos(x * 0.01) * 10;
      ctx.lineTo(x, y);
    }
    ctx.lineTo(W, H);
    ctx.lineTo(0, H);
    ctx.fill();

    ctx.fillStyle = "#5a2214";
    ctx.beginPath();
    ctx.moveTo(0, H * 0.7);
    for (let x = 0; x <= W; x += 28) {
      const y = H * 0.68 + Math.sin(x * 0.03 - cameraY * 0.015) * 12;
      ctx.lineTo(x, y);
    }
    ctx.lineTo(W, H);
    ctx.lineTo(0, H);
    ctx.fill();

    ctx.fillStyle = C.ground;
    ctx.fillRect(0, H - 40, W, 40);
    ctx.fillStyle = C.dust;
    for (let x = 0; x < W; x += 8) {
      if (((x / 8) | 0) % 3 === 0) ctx.fillRect(x, H - 40, 4, 4);
    }

    for (const d of dustPuffs) {
      ctx.globalAlpha = clamp(d.life / d.max, 0, 0.5);
      ctx.fillStyle = C.dust;
      ctx.fillRect(d.x | 0, d.y | 0, d.size, d.size);
    }
    ctx.globalAlpha = 1;
  }

  function drawCrater(sx, sy, r) {
    ctx.fillStyle = C.crater;
    ctx.beginPath();
    ctx.ellipse(sx, sy, r, r * 0.55, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#3a1810";
    ctx.beginPath();
    ctx.ellipse(sx - r * 0.2, sy - r * 0.1, r * 0.45, r * 0.25, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  function drawLane(lane) {
    const y = worldToScreenY(laneWorldY(lane.index));
    if (y < -80 || y > H + 40) return;

    if (lane.kind !== "start" && lane.kind !== "colony") {
      ctx.fillStyle = "rgba(80, 30, 20, 0.35)";
      ctx.fillRect(0, y - 10, W, LANE_H - 8);
      ctx.fillStyle = C.rock;
      const seed = lane.index * 97;
      for (let i = 0; i < 5; i++) {
        const rx = ((seed * (i + 3) * 13) % (W - 20)) + 10;
        ctx.fillRect(rx, y + 8 + (i % 3) * 4, 3 + (i % 2), 2);
      }
      if (lane.index % 3 === 1) drawCrater(((seed * 7) % (W - 60)) + 30, y + 18, 10);
    }

    if (lane.kind === "colony") {
      ctx.fillStyle = "#3a4450";
      ctx.fillRect(20, y - 6, W - 40, 22);
      ctx.fillStyle = "#5a7088";
      ctx.fillRect(24, y - 2, W - 48, 12);
      for (let x = 40; x < W - 40; x += 28) {
        ctx.fillStyle = "#80e0ff";
        ctx.fillRect(x, y + 1, 6, 4);
      }
      ctx.fillStyle = C.padStripe;
      ctx.fillRect(20, y + 14, W - 40, 3);
      ctx.fillStyle = C.padGlow;
      ctx.font = '8px "Press Start 2P", monospace';
      ctx.textAlign = "center";
      ctx.fillText("MARS BASE", W / 2, y + 10);
    }

    for (const p of lane.pads) drawPad(p, y, lane);
    if (lane.hazard) drawRover(lane.hazard.x, y + 2, lane.hazard.w, lane.hazard.h);
  }

  function drawPad(p, y, lane) {
    const x = p.x | 0;
    const w = p.w | 0;
    const h = 14;
    const py = (y | 0) - 2;
    const isBoost = p.kind === "boost";
    const isChop = p.kind === "chopstick";
    const cx = x + (w / 2 | 0);

    ctx.fillStyle = "rgba(0,0,0,0.35)";
    ctx.fillRect(x + 3, py + h, w - 2, 4);

    if (isChop) {
      // Mechazilla catch deck — wide structure, tight center jaws
      ctx.fillStyle = "rgba(64, 255, 128, 0.12)";
      ctx.fillRect(x - 4, py - 18, w + 8, h + 28);

      // outer deck (unsafe to land outside center)
      ctx.fillStyle = "#3a4048";
      ctx.fillRect(x, py, w, h);
      ctx.fillStyle = "#5a6068";
      ctx.fillRect(x, py, w, 3);
      ctx.fillStyle = "#1a1e24";
      ctx.fillRect(x, py + h - 3, w, 3);

      // danger zones left/right of catch
      ctx.fillStyle = "rgba(255, 60, 60, 0.22)";
      const zoneL = cx - CHOP_CATCH_HALF;
      const zoneR = cx + CHOP_CATCH_HALF;
      ctx.fillRect(x, py, Math.max(0, zoneL - x), h);
      ctx.fillRect(zoneR, py, Math.max(0, x + w - zoneR), h);

      // safe catch band
      const pulse = 0.5 + 0.5 * Math.sin(time * 7 + lane.index);
      ctx.fillStyle = `rgba(64, 255, 128, ${0.25 + pulse * 0.35})`;
      ctx.fillRect(zoneL, py - 1, CHOP_CATCH_HALF * 2, h + 2);
      ctx.fillStyle = "#40ff80";
      ctx.fillRect(zoneL, py + 5, CHOP_CATCH_HALF * 2, 2);

      // mini chopsticks arms
      const armY = py - 14;
      const open = 18 + Math.sin(time * 3 + lane.index) * 2;
      ctx.fillStyle = C.chop;
      ctx.fillRect(cx - open - 6, armY, 6, 12);
      ctx.fillRect(cx + open, armY, 6, 12);
      ctx.fillStyle = C.chopLite;
      ctx.fillRect(cx - open - 5, armY + 1, 2, 10);
      ctx.fillRect(cx + open + 3, armY + 1, 2, 10);
      // jaw tips
      ctx.fillStyle = pulse > 0.7 ? "#40ff80" : "#6a8090";
      ctx.fillRect(cx - open - 2, armY + 4, 4, 8);
      ctx.fillRect(cx + open - 2, armY + 4, 4, 8);

      // tower stub
      ctx.fillStyle = C.towerDark;
      ctx.fillRect(cx - 3, armY - 10, 6, 12);
      ctx.fillStyle = C.tower;
      ctx.fillRect(cx - 2, armY - 8, 4, 8);

      ctx.fillStyle = "#40ff80";
      ctx.font = '5px "Press Start 2P", monospace';
      ctx.textAlign = "center";
      ctx.fillText("CHOP", cx, py + 11);
    } else if (isBoost) {
      ctx.fillStyle = "rgba(94, 184, 255, 0.2)";
      ctx.fillRect(x - 3, py - 4, w + 6, h + 8);
      ctx.fillStyle = "#2a5070";
      ctx.fillRect(x, py, w, h);
      ctx.fillStyle = "#80c0ff";
      ctx.fillRect(x, py, w, 3);
      ctx.fillStyle = "#1a3048";
      ctx.fillRect(x, py + h - 3, w, 3);
      const pulse = 0.55 + 0.45 * Math.sin(time * 8 + lane.index);
      ctx.globalAlpha = pulse;
      ctx.fillStyle = C.padGlow;
      for (let i = 0; i < 3; i++) {
        const cy = py - 2 - i * 5;
        ctx.fillRect(cx - 1, cy, 2, 3);
        ctx.fillRect(cx - 3, cy + 2, 2, 2);
        ctx.fillRect(cx + 1, cy + 2, 2, 2);
      }
      ctx.globalAlpha = 1;
      ctx.fillStyle = C.flameHot;
      ctx.font = '5px "Press Start 2P", monospace';
      ctx.textAlign = "center";
      ctx.fillText("BOOST", cx, py + 11);
      ctx.fillStyle = C.flame;
      ctx.globalAlpha = pulse;
      ctx.fillRect(x + 2, py + 4, 3, 5);
      ctx.fillRect(x + w - 5, py + 4, 3, 5);
      ctx.globalAlpha = 1;
    } else {
      ctx.fillStyle = p.kind === "home" ? "#4a5850" : C.pad;
      ctx.fillRect(x, py, w, h);
      ctx.fillStyle = C.padLite;
      ctx.fillRect(x, py, w, 3);
      ctx.fillStyle = C.padDark;
      ctx.fillRect(x, py + h - 3, w, 3);
      ctx.fillStyle = C.padStripe;
      ctx.fillRect(x + 4, py + 5, w - 8, 2);
    }

    const blink = ((time * 4 + lane.index) | 0) % 2 === 0;
    ctx.fillStyle = isChop
      ? blink
        ? "#40ff80"
        : "#106030"
      : isBoost
        ? blink
          ? "#80e0ff"
          : "#2060a0"
        : blink
          ? "#40ff80"
          : "#106030";
    ctx.fillRect(x + 2, py + 2, 3, 3);
    ctx.fillRect(x + w - 5, py + 2, 3, 3);

    ctx.fillStyle = C.padDark;
    ctx.fillRect(x + 6, py + h, 3, 8);
    ctx.fillRect(x + w - 9, py + h, 3, 8);

    // edge lips / ticks
    const lip = isChop ? "#80ffb0" : isBoost ? "#a0e0ff" : "#d0c8a0";
    const lipDark = isChop ? "#104028" : isBoost ? "#104060" : "#2a2820";
    ctx.fillStyle = lipDark;
    ctx.fillRect(x - 1, py - 2, 3, h + 4);
    ctx.fillStyle = lip;
    ctx.fillRect(x - 1, py - 2, 3, 2);
    ctx.fillRect(x - 1, py + 3, 2, 2);
    ctx.fillRect(x - 1, py + 8, 2, 2);
    ctx.fillStyle = lipDark;
    ctx.fillRect(x + w - 2, py - 2, 3, h + 4);
    ctx.fillStyle = lip;
    ctx.fillRect(x + w - 2, py - 2, 3, 2);
    ctx.fillRect(x + w, py + 3, 2, 2);
    ctx.fillRect(x + w, py + 8, 2, 2);
    ctx.fillStyle = isChop ? "#40ff80" : isBoost ? C.padGlow : C.padStripe;
    ctx.fillRect(x, py - 3, 2, 2);
    ctx.fillRect(x + w - 2, py - 3, 2, 2);

    if (p.kind === "home") {
      ctx.fillStyle = C.text;
      ctx.font = '6px "Press Start 2P", monospace';
      ctx.textAlign = "center";
      ctx.fillText("PAD-0", cx, py + 11);
    }
  }

  function drawRover(x, y, w, h) {
    const rx = x | 0;
    const ry = y | 0;
    ctx.fillStyle = "#c05030";
    ctx.fillRect(rx, ry, w, h - 4);
    ctx.fillStyle = "#e08040";
    ctx.fillRect(rx + 2, ry + 2, w - 4, 4);
    ctx.fillStyle = "#c8d0d8";
    ctx.fillRect(rx + w / 2 - 1, ry - 8, 2, 8);
    ctx.fillRect(rx + w / 2 - 4, ry - 10, 8, 3);
    ctx.fillStyle = "#1a1010";
    ctx.fillRect(rx - 2, ry + h - 6, 6, 6);
    ctx.fillRect(rx + w - 4, ry + h - 6, 6, 6);
    ctx.fillRect(rx + w / 2 - 3, ry + h - 6, 6, 6);
  }

  function drawStarshipAt(sx, sy, thrusterAmt, tilt, scale = 1) {
    // Pixel Starship matching real silhouette: tall stainless stack,
    // pointed nose, black forward/aft flaps, orange Raptor plume.
    // sy = feet/engine plane. scale is visual only (title uses 5x).
    ctx.save();
    ctx.translate(sx, sy);
    if (tilt) ctx.rotate(tilt);
    if (scale !== 1) ctx.scale(scale, scale);

    // local design box ~18×32, feet at y=0
    const bw = 8; // body half-width interior
    // body x from -4 to +4 for core; flaps extend further

    // ── Raptor plumes (orange-white like reference) ───────────────────────
    if (thrusterAmt > 0.05) {
      const f = thrusterAmt;
      const flicker = Math.sin(time * 42) * 0.12;
      const fh = (10 + flicker * 10) * f * (f > 1 ? 1.5 : 1);
      // wide outer wash
      ctx.fillStyle = "rgba(255, 140, 40, 0.35)";
      ctx.fillRect(-7, 0, 14, (fh * 0.85) | 0);
      // three bells
      ctx.fillStyle = "#ff9020";
      ctx.fillRect(-6, 0, 3, (fh * 0.75) | 0);
      ctx.fillRect(-1, 0, 3, fh | 0);
      ctx.fillRect(4, 0, 3, (fh * 0.75) | 0);
      ctx.fillStyle = "#ffcc40";
      ctx.fillRect(-5, 0, 2, (fh * 0.65) | 0);
      ctx.fillRect(0, 0, 2, (fh * 0.9) | 0);
      ctx.fillRect(5, 0, 2, (fh * 0.65) | 0);
      ctx.fillStyle = "#fff6d0";
      ctx.fillRect(0, 0, 1, (fh * 0.55) | 0);
      ctx.fillRect(-5, 0, 1, (fh * 0.4) | 0);
      ctx.fillRect(5, 0, 1, (fh * 0.4) | 0);
    }

    // ── Aft flaps (black, near base — match reference) ────────────────────
    ctx.fillStyle = "#0a0a0c";
    ctx.fillRect(-9, -12, 5, 9);
    ctx.fillRect(4, -12, 5, 9);
    ctx.fillStyle = "#1a1a1e";
    ctx.fillRect(-8, -11, 4, 7);
    ctx.fillRect(4, -11, 4, 7);
    // slight taper on trailing edge
    ctx.fillStyle = "#2a2a30";
    ctx.fillRect(-8, -11, 1, 6);
    ctx.fillRect(7, -11, 1, 6);
    ctx.fillStyle = "#050506";
    ctx.fillRect(-8, -5, 4, 2);
    ctx.fillRect(4, -5, 4, 2);

    // ── Forward flaps (black canards, upper third) ────────────────────────
    ctx.fillStyle = "#0a0a0c";
    ctx.fillRect(-8, -24, 4, 6);
    ctx.fillRect(4, -24, 4, 6);
    ctx.fillStyle = "#1c1c22";
    ctx.fillRect(-7, -23, 3, 4);
    ctx.fillRect(4, -23, 3, 4);
    ctx.fillStyle = "#2e2e36";
    ctx.fillRect(-7, -23, 1, 3);
    ctx.fillRect(6, -23, 1, 3);

    // ── Main stainless body ───────────────────────────────────────────────
    // darker steel overall (reference is charcoal-silver)
    ctx.fillStyle = "#6a7078";
    ctx.fillRect(-4, -28, 8, 26);
    // left highlight band
    ctx.fillStyle = "#9aa2ac";
    ctx.fillRect(-3, -28, 2, 26);
    // bright specular edge
    ctx.fillStyle = "#c8d0d8";
    ctx.fillRect(-3, -27, 1, 24);
    // right shade
    ctx.fillStyle = "#3a4048";
    ctx.fillRect(2, -28, 2, 26);
    ctx.fillStyle = "#2a3038";
    ctx.fillRect(3, -27, 1, 24);
    // mid tone fill
    ctx.fillStyle = "#7a828c";
    ctx.fillRect(-1, -28, 3, 26);

    // ring seams (barrel sections)
    ctx.fillStyle = "rgba(20,24,28,0.55)";
    ctx.fillRect(-4, -22, 8, 1);
    ctx.fillRect(-4, -16, 8, 1);
    ctx.fillRect(-4, -10, 8, 1);
    ctx.fillRect(-4, -5, 8, 1);

    // subtle vertical panel line
    ctx.fillStyle = "rgba(20,24,28,0.35)";
    ctx.fillRect(0, -27, 1, 24);

    // ── Nose cone (sharp point) ───────────────────────────────────────────
    ctx.fillStyle = "#5a6068";
    ctx.fillRect(-3, -30, 6, 2);
    ctx.fillRect(-2, -32, 4, 2);
    ctx.fillRect(-1, -33, 2, 1);
    ctx.fillStyle = "#8a929c";
    ctx.fillRect(-2, -31, 1, 3);
    ctx.fillStyle = "#3a4048";
    ctx.fillRect(1, -31, 1, 3);
    // dark tip
    ctx.fillStyle = "#1a1c20";
    ctx.fillRect(-1, -34, 2, 1);
    ctx.fillRect(0, -35, 1, 1);

    // ── Chin / hardpoint band under nose ──────────────────────────────────
    ctx.fillStyle = "#4a5058";
    ctx.fillRect(-3, -28, 6, 2);
    ctx.fillStyle = "#2a3038";
    ctx.fillRect(-2, -27, 4, 1);

    // ── Aft skirt ─────────────────────────────────────────────────────────
    ctx.fillStyle = "#3a4048";
    ctx.fillRect(-4, -3, 8, 2);
    ctx.fillStyle = "#2a2e34";
    ctx.fillRect(-5, -2, 10, 2);

    // ── Engine bells (3) ──────────────────────────────────────────────────
    ctx.fillStyle = "#12141a";
    ctx.fillRect(-5, -1, 2, 2);
    ctx.fillRect(-1, -1, 2, 2);
    ctx.fillRect(3, -1, 2, 2);
    ctx.fillStyle = "#2a2e36";
    ctx.fillRect(-5, 0, 2, 1);
    ctx.fillRect(-1, 0, 2, 1);
    ctx.fillRect(3, 0, 2, 1);

    ctx.restore();
  }

  function drawStarship(sx, sy) {
    const thr =
      ship.boosting ? ship.thruster : ship.thruster > 0.05 || ship.hopping ? ship.thruster || 0.8 : 0;
    drawStarshipAt(sx, sy, thr, 0, 1);
  }

  // Mechazilla-style tower + chopsticks (title uses wider jaws for 5x ship)
  function drawChopsticks(armClose, catchY, forTitle) {
    const hero = !!forTitle;
    const towerW = hero ? 28 : 22;
    const towerTop = hero ? H * 0.08 : H * 0.18;
    const towerH = hero ? H * 0.78 : H * 0.62;
    const towerX = W / 2 - towerW / 2;
    const baseY = towerTop + towerH;

    // tower shaft (behind ship)
    ctx.fillStyle = C.towerDark;
    ctx.fillRect(towerX, towerTop, towerW, towerH);
    ctx.fillStyle = C.tower;
    ctx.fillRect(towerX + 3, towerTop, 5, towerH);
    ctx.fillRect(towerX + towerW - 8, towerTop, 5, towerH);
    for (let y = towerTop + 24; y < baseY - 10; y += 32) {
      ctx.fillStyle = C.chop;
      ctx.fillRect(towerX - 6, y, towerW + 12, 5);
    }
    ctx.fillStyle = C.chopLite;
    ctx.fillRect(towerX + towerW, catchY - SHIP_H * (hero ? TITLE_SHIP_SCALE * 0.45 : 0.4), hero ? 28 : 18, hero ? 8 : 5);

    // grab mid-body of ship (feet at catchY, body extends upward)
    const bodyMid = catchY - (hero ? SHIP_H * TITLE_SHIP_SCALE * 0.42 : 14);
    const pivotY = bodyMid;
    const openSpread = hero ? 150 : 78;
    // closed: hug ~body half-width at scale
    const closedSpread = hero ? 28 : 14;
    const spread = lerp(openSpread, closedSpread, armClose);
    const armThick = hero ? 14 : 8;
    const jawW = hero ? 16 : 8;
    const jawH = hero ? 36 : 14;

    function drawArm(side) {
      const px = W / 2 + side * (towerW * 0.35);
      const tipX = W / 2 + side * spread;
      const tipY = pivotY + (hero ? 10 : 6);

      ctx.fillStyle = C.towerDark;
      ctx.fillRect(px - (hero ? 8 : 4), pivotY - (hero ? 16 : 10), hero ? 16 : 8, hero ? 28 : 16);

      ctx.strokeStyle = C.chop;
      ctx.lineWidth = armThick;
      ctx.lineCap = "square";
      ctx.beginPath();
      ctx.moveTo(px, pivotY);
      ctx.lineTo(tipX, tipY);
      ctx.stroke();

      ctx.strokeStyle = C.chopLite;
      ctx.lineWidth = hero ? 5 : 3;
      ctx.beginPath();
      ctx.moveTo(px, pivotY - 3);
      ctx.lineTo(tipX, tipY - 3);
      ctx.stroke();

      // jaw pads
      ctx.fillStyle = armClose > 0.85 ? "#40ff80" : "#6a8090";
      ctx.fillRect(tipX - jawW / 2, tipY - jawH / 2, jawW, jawH);
      ctx.fillStyle = C.towerDark;
      ctx.fillRect(tipX - jawW / 2 - 1, tipY + jawH / 2 - 4, jawW + 2, 4);

      if (armClose > 0.7) {
        ctx.fillStyle = "#b0bcc8";
        ctx.fillRect(tipX - side * 3 - 2, tipY - jawH / 3, hero ? 10 : 6, hero ? 18 : 10);
      }
    }

    drawArm(-1);
    drawArm(1);

    if (armClose > 0.9) {
      ctx.fillStyle = "rgba(128, 224, 255, 0.25)";
      ctx.fillRect(W / 2 - closedSpread - 6, pivotY - 4, closedSpread * 2 + 12, hero ? 8 : 4);
    }
  }

  function drawTitleScene() {
    const pose = titlePose(titlePhase);
    const catchY = pose.catchY;

    // ground / OLM pad
    ctx.fillStyle = "#2a2228";
    ctx.fillRect(0, H - 48, W, 48);
    ctx.fillStyle = "#3a3038";
    ctx.fillRect(W / 2 - 100, H - 70, 200, 30);
    ctx.fillStyle = C.tower;
    ctx.fillRect(W / 2 - 60, H - 80, 120, 14);
    ctx.fillStyle = C.padStripe;
    ctx.fillRect(W / 2 - 54, H - 76, 108, 3);

    // tower shaft only (behind)
    const towerW = 28;
    const towerTop = H * 0.06;
    const towerH = H * 0.8;
    const towerX = W / 2 - towerW / 2;
    ctx.fillStyle = C.towerDark;
    ctx.fillRect(towerX, towerTop, towerW, towerH);
    ctx.fillStyle = C.tower;
    ctx.fillRect(towerX + 3, towerTop, 5, towerH);
    ctx.fillRect(towerX + towerW - 8, towerTop, 5, towerH);
    for (let y = towerTop + 28; y < towerTop + towerH - 10; y += 36) {
      ctx.fillStyle = C.chop;
      ctx.fillRect(towerX - 8, y, towerW + 16, 6);
    }

    // exhaust bloom
    if (pose.shipVisible && pose.thruster > 0.25) {
      const eg = ctx.createRadialGradient(pose.shipX, pose.shipY + 10, 8, pose.shipX, pose.shipY + 50, 100);
      eg.addColorStop(0, "rgba(255, 190, 80, 0.5)");
      eg.addColorStop(0.5, "rgba(255, 100, 30, 0.2)");
      eg.addColorStop(1, "rgba(255, 60, 10, 0)");
      ctx.fillStyle = eg;
      ctx.fillRect(pose.shipX - 100, pose.shipY - 20, 200, 160);
    }

    // hero Starship (5×) — launches alone after release
    if (pose.shipVisible) {
      drawStarshipAt(pose.shipX, pose.shipY, pose.thruster, pose.shipTilt, TITLE_SHIP_SCALE);
    }

    // chopsticks use armY (independent of ship after release)
    drawTitleArms(pose.armClose, pose.armY);

    // soft clamp sparks only (no white flash)
    if (pose.caught && !pose.launching && Math.random() < 0.25) {
      burst(
        W / 2 + rand(-20, 20),
        pose.armY - SHIP_H * TITLE_SHIP_SCALE * 0.4,
        2,
        C.chopLite,
        1.4
      );
    }

    // caption
    ctx.fillStyle = "rgba(0,0,0,0.5)";
    ctx.fillRect(W / 2 - 118, 22, 236, 30);
    ctx.font = '8px "Press Start 2P", monospace';
    ctx.textAlign = "center";
    if (pose.retracting) {
      ctx.fillStyle = C.chopLite;
      ctx.fillText("ARMS RETRACTING", W / 2, 42);
    } else if (pose.launching) {
      ctx.fillStyle = C.flame;
      ctx.fillText("LIFTOFF", W / 2, 42);
    } else if (pose.onPad && pose.armClose < 0.5) {
      ctx.fillStyle = "#40ff80";
      ctx.fillText("STACK ON PAD", W / 2, 42);
    } else if (pose.onPad) {
      ctx.fillStyle = "#40ff80";
      ctx.fillText("STACK ON PAD", W / 2, 42);
    } else if (pose.caught) {
      ctx.fillStyle = "#40ff80";
      ctx.fillText("LOWERING TO PAD", W / 2, 42);
    } else if (pose.armClose > 0.25) {
      ctx.fillStyle = C.padGlow;
      ctx.fillText("ARMS CLOSING…", W / 2, 42);
    } else if (pose.thruster > 0.3 && pose.shipY < catchY - 10) {
      ctx.fillStyle = C.flame;
      ctx.fillText("LANDING BURN", W / 2, 42);
    } else {
      ctx.fillStyle = C.text;
      ctx.fillText("MECHAZILLA STANDING BY", W / 2, 42);
    }
  }

  function drawTitleArms(armClose, armFeetY) {
    // Independent tower carriage. armFeetY = where a held ship's feet sit;
    // jaws close on mid-body (not parented to the sprite transform).
    // Body mid at scale 5: ~0.45 of ship height up from feet.
    const grabOffset = SHIP_H * TITLE_SHIP_SCALE * 0.45;
    const pivotY = armFeetY - grabOffset;
    // hull half-width at scale ≈ 4 * 5 = 20; closed jaws hug that
    const openSpread = 150;
    const closedSpread = 24;
    const spread = lerp(openSpread, closedSpread, armClose);
    const towerW = 28;
    const armThick = 14;
    const jawW = 16;
    const jawH = 48;

    // carriage rail on tower at this height (makes arms look tower-mounted)
    ctx.fillStyle = C.towerDark;
    ctx.fillRect(W / 2 - 22, pivotY - 12, 44, 22);
    ctx.fillStyle = C.chop;
    ctx.fillRect(W / 2 - 20, pivotY - 8, 40, 12);
    ctx.fillStyle = C.chopLite;
    ctx.fillRect(W / 2 - 18, pivotY - 6, 36, 3);

    function drawArm(side) {
      const rootX = W / 2 + side * (towerW * 0.55);
      const tipX = W / 2 + side * spread;
      const tipY = pivotY + 4;

      // hydraulic root bolted to tower carriage
      ctx.fillStyle = C.towerDark;
      ctx.fillRect(rootX - 9, pivotY - 16, 18, 30);
      ctx.fillStyle = C.chop;
      ctx.fillRect(rootX - 6, pivotY - 12, 12, 22);

      // arm beam (fixed to tower, not to ship)
      ctx.strokeStyle = "#6a7078";
      ctx.lineWidth = armThick + 2;
      ctx.lineCap = "square";
      ctx.beginPath();
      ctx.moveTo(rootX, pivotY);
      ctx.lineTo(tipX, tipY);
      ctx.stroke();

      ctx.strokeStyle = C.chopLite;
      ctx.lineWidth = 5;
      ctx.beginPath();
      ctx.moveTo(rootX, pivotY - 3);
      ctx.lineTo(tipX, tipY - 3);
      ctx.stroke();

      // jaw pads — green when fully closed on stack
      ctx.fillStyle = armClose > 0.92 ? "#40ff80" : armClose > 0.5 ? "#8aa0b0" : "#6a8090";
      ctx.fillRect(tipX - jawW / 2, tipY - jawH / 2, jawW, jawH);
      ctx.fillStyle = C.towerDark;
      ctx.fillRect(tipX - jawW / 2 - 1, tipY + jawH / 2 - 6, jawW + 2, 6);
      // inner contact face
      ctx.fillStyle = armClose > 0.85 ? "#d0d8e0" : "#9098a0";
      ctx.fillRect(tipX - side * 2 - 3, tipY - jawH / 3, 8, (jawH * 0.55) | 0);
    }

    drawArm(-1);
    drawArm(1);

    if (armClose > 0.9) {
      ctx.fillStyle = "rgba(64, 255, 128, 0.2)";
      ctx.fillRect(W / 2 - closedSpread - 6, pivotY - 8, closedSpread * 2 + 12, 12);
    }
  }

  function drawParticles() {
    for (const p of particles) {
      ctx.globalAlpha = clamp(p.life / p.max, 0, 1);
      ctx.fillStyle = p.color;
      ctx.fillRect(p.x | 0, p.y | 0, p.size, p.size);
    }
    ctx.globalAlpha = 1;
  }

  function drawFuelGauge() {
    if (state !== "play" || !ship) return;
    // only show once player has found boost or has fuel
    if (ship.fuel <= 0 && !ship.boostReady && !ship.boosting) return;

    const gx = 14;
    const gy = 50;
    const gw = 12;
    const gh = H - 140;

    ctx.fillStyle = "rgba(0,0,0,0.5)";
    ctx.fillRect(gx - 4, gy - 16, gw + 8, gh + 28);

    ctx.fillStyle = C.muted || "#a08070";
    ctx.fillStyle = "#a08070";
    ctx.font = '6px "Press Start 2P", monospace';
    ctx.textAlign = "left";
    ctx.fillText("FUEL", gx - 2, gy - 6);

    // empty tank
    ctx.fillStyle = "#1a1010";
    ctx.fillRect(gx, gy, gw, gh);
    ctx.strokeStyle = ship.boosting ? C.padGlow : "#6a5040";
    ctx.lineWidth = 2;
    ctx.strokeRect(gx - 1, gy - 1, gw + 2, gh + 2);

    const pct = clamp(ship.fuel / MAX_FUEL, 0, 1);
    const fh = (gh * pct) | 0;
    let col = C.fuel;
    if (pct < 0.35) col = C.fuelLow;
    if (pct < 0.15) col = C.fuelEmpty;
    if (ship.boosting && ((time * 10) | 0) % 2 === 0 && pct < 0.25) col = "#fff";

    ctx.fillStyle = col;
    ctx.fillRect(gx, gy + gh - fh, gw, fh);

    // tick marks
    ctx.fillStyle = "rgba(255,255,255,0.2)";
    for (let i = 1; i < 4; i++) {
      const ty = gy + ((gh * i) / 4) | 0;
      ctx.fillRect(gx, ty, gw, 1);
    }

    if (ship.boosting) {
      ctx.fillStyle = C.flame;
      ctx.font = '5px "Press Start 2P", monospace';
      ctx.fillText("BURN", gx - 2, gy + gh + 12);
    } else if (ship.boostReady) {
      ctx.fillStyle = C.padGlow;
      ctx.font = '5px "Press Start 2P", monospace';
      ctx.fillText("HOLD", gx - 2, gy + gh + 12);
    }
  }

  function drawHopZone() {
    if (state !== "play" || !ship || !ship.alive) return;
    // always show on touch; on desktop show lightly while boosting/held as feedback
    if (!isCoarsePointer() && !hopHeld && !ship.boosting) return;
    const zoneY = (H * HOP_ZONE_FRAC) | 0;
    const held = hopHeld || ship.boosting;

    // soft fill
    const g = ctx.createLinearGradient(0, zoneY, 0, H);
    g.addColorStop(0, held ? "rgba(94,184,255,0.08)" : "rgba(0,0,0,0.12)");
    g.addColorStop(1, held ? "rgba(94,184,255,0.22)" : "rgba(0,0,0,0.28)");
    ctx.fillStyle = g;
    ctx.fillRect(0, zoneY, W, H - zoneY);

    // top edge line
    ctx.fillStyle = held ? C.padGlow : "rgba(240,192,64,0.45)";
    ctx.fillRect(0, zoneY, W, 2);
    // dashed feel
    ctx.fillStyle = held ? "rgba(255,255,255,0.35)" : "rgba(255,255,255,0.12)";
    for (let x = 4; x < W; x += 12) ctx.fillRect(x, zoneY, 6, 1);

    ctx.font = '6px "Press Start 2P", monospace';
    ctx.textAlign = "center";
    if (ship.boosting) {
      ctx.fillStyle = C.flameHot;
      ctx.fillText("RELEASE TO LAND", W / 2, zoneY + 16);
    } else if (ship.boostReady) {
      ctx.fillStyle = C.padGlow;
      ctx.fillText("HOLD · BOOST", W / 2, zoneY + 16);
    } else {
      ctx.fillStyle = "rgba(245,230,211,0.55)";
      ctx.fillText("HOLD HOP", W / 2, zoneY + 16);
    }
    ctx.fillStyle = "rgba(160,128,112,0.7)";
    ctx.font = '5px "Press Start 2P", monospace';
    ctx.fillText("DRAG L/R TO STRAFE", W / 2, zoneY + 28);
  }

  function drawUI() {
    if (state === "play") {
      // right progress ribbon
      ctx.fillStyle = "rgba(0,0,0,0.35)";
      ctx.fillRect(W - 14, 40, 6, H - 100);
      const maxLane = Math.max(1, padsHopped + 5);
      const pct = clamp(ship.lane / maxLane, 0, 1);
      ctx.fillStyle = ship.boosting ? C.flame : C.padGlow;
      ctx.fillRect(W - 14, 40 + (H - 100) * (1 - pct), 6, Math.max(4, (H - 100) * pct));

      drawFuelGauge();
      drawHopZone();

      // boost / chopsticks hint
      if (boostHintT > 0 && ship.onPad && !ship.boosting) {
        ctx.globalAlpha = clamp(boostHintT, 0, 1);
        ctx.fillStyle = "rgba(0,0,0,0.55)";
        ctx.fillRect(W / 2 - 140, 36, 280, 40);
        ctx.textAlign = "center";
        if (ship.onPad.kind === "chopstick") {
          ctx.fillStyle = "#40ff80";
          ctx.font = '7px "Press Start 2P", monospace';
          ctx.fillText("CHOPSTICKS · FAST FUEL", W / 2, 52);
          ctx.fillStyle = C.text;
          ctx.font = '5px "Press Start 2P", monospace';
          ctx.fillText("HOLD HOP TO BOOST", W / 2, 66);
        } else if (ship.onPad.kind === "boost") {
          ctx.fillStyle = C.padGlow;
          ctx.font = '7px "Press Start 2P", monospace';
          ctx.fillText("HOLD HOP TO BOOST", W / 2, 52);
          ctx.fillStyle = C.fuelLow;
          ctx.font = '5px "Press Start 2P", monospace';
          ctx.fillText("SLOW DRIP FUEL · FIND CHOPSTICKS", W / 2, 66);
        }
        ctx.globalAlpha = 1;
      }

      if (ship.boosting) {
        ctx.fillStyle = "rgba(94,184,255,0.15)";
        ctx.fillRect(0, 0, W, 3);
        ctx.fillStyle = C.flameHot;
        ctx.font = '7px "Press Start 2P", monospace';
        ctx.textAlign = "center";
        ctx.fillText("BOOST · RELEASE TO LAND", W / 2, 24);
      }

      drawFloats();
    }
  }

  function draw() {
    ctx.save();
    if (shake > 0) {
      ctx.translate((Math.random() - 0.5) * shake, (Math.random() - 0.5) * shake);
    }

    drawBackground();

    if (state === "title") {
      drawTitleScene();
      drawParticles();
    } else {
      // gameplay: small ship (scale 1)
      const sorted = [...lanes].sort(
        (a, b) => worldToScreenY(laneWorldY(b.index)) - worldToScreenY(laneWorldY(a.index))
      );
      for (const lane of sorted) drawLane(lane);

      if (ship) {
        const arc = ship._arc || 0;
        const bob = ship.hopping || ship.boosting ? 0 : ship.bob || 0;
        const sy = worldToScreenY(ship.y) - arc + bob;
        const sx = ship.x;
        drawStarship(sx, sy);
        if (state === "play" && ship.x < 40) drawStarship(sx + W + 40, sy);
        if (state === "play" && ship.x > W - 40) drawStarship(sx - W - 40, sy);
      }

      drawParticles();
      drawUI();
    }

    const vg = ctx.createRadialGradient(W / 2, H / 2, H * 0.3, W / 2, H / 2, H * 0.75);
    vg.addColorStop(0, "rgba(0,0,0,0)");
    vg.addColorStop(1, "rgba(10,4,4,0.45)");
    ctx.fillStyle = vg;
    ctx.fillRect(0, 0, W, H);

    ctx.restore();

    ctx.fillStyle = "rgba(0,0,0,0.06)";
    for (let y = 0; y < H; y += 4) ctx.fillRect(0, y, W, 1);
  }

  // ── loop ────────────────────────────────────────────────────────────────
  function frame(ts) {
    if (!lastTs) lastTs = ts;
    let dt = (ts - lastTs) / 1000;
    lastTs = ts;
    dt = Math.min(dt, 0.05);

    update(dt);
    draw();
    animId = requestAnimationFrame(frame);
  }

  // ── boot ────────────────────────────────────────────────────────────────
  initStars();
  resetShip();
  titlePhase = 0;
  showTitleOverlay();
  animId = requestAnimationFrame(frame);

  window.addEventListener("keydown", (e) => {
    if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " "].includes(e.key)) {
      if (state === "play") e.preventDefault();
    }
  });
})();
