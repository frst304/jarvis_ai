/* Noyau holographique (reacteur ARC) + fond anime. */
(() => {
  const css = (name) => getComputedStyle(document.body).getPropertyValue(name).trim();
  const hexToRgb = (hex) => {
    const m = hex.replace("#", "").match(/.{2}/g) || ["00", "e5", "ff"];
    return m.map((x) => parseInt(x, 16));
  };

  const Reactor = {
    state: "idle", level: 0, target: 0, t: 0, colors: {},
    setState(s) { this.state = s; },
    refreshColors() {
      this.colors = { c: hexToRgb(css("--c") || "#00e5ff"), a: hexToRgb(css("--accent") || "#ffb547"),
        d: hexToRgb(css("--danger") || "#ff3b5c"), c2: hexToRgb(css("--c2") || "#4dd0ff") };
    },
  };
  window.Reactor = Reactor;

  // ---------------------------------------------------------------- reacteur
  const cv = document.getElementById("reactor");
  const ctx = cv.getContext("2d");
  let W = 0, H = 0, DPR = Math.min(window.devicePixelRatio || 1, 2);
  function resize() {
    const r = cv.getBoundingClientRect();
    W = r.width; H = r.height;
    cv.width = W * DPR; cv.height = H * DPR;
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }
  new ResizeObserver(resize).observe(cv);

  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  const segs = Array.from({ length: 64 }, () => Math.random());

  function ring(r, width, color, a0, a1, alpha = 1) {
    ctx.beginPath(); ctx.arc(0, 0, r, a0, a1);
    ctx.strokeStyle = rgba(color, alpha); ctx.lineWidth = width; ctx.stroke();
  }

  function draw() {
    Reactor.t += 1 / 60;
    const t = Reactor.t, st = Reactor.state;
    Reactor.level += (Reactor.target - Reactor.level) * 0.25;
    Reactor.target *= 0.9;
    const lvl = Reactor.level;
    const C = Reactor.colors.c || [0, 229, 255];
    const main = st === "thinking" || st === "working" ? Reactor.colors.a : st === "control" ? Reactor.colors.d : C;
    const speed = { idle: 0.25, listening: 0.6, thinking: 1.8, working: 1.4, speaking: 0.8, control: 1.2 }[st] || 0.3;
    ctx.clearRect(0, 0, W, H);
    ctx.save();
    ctx.translate(W / 2, H / 2);
    const R = Math.min(W, H) / 2 - 12;
    ctx.shadowColor = rgba(main, 0.9); ctx.shadowBlur = 14;

    // halo
    const g = ctx.createRadialGradient(0, 0, R * 0.05, 0, 0, R * (0.55 + lvl * 0.25));
    g.addColorStop(0, rgba([255, 255, 255], 0.95));
    g.addColorStop(0.18, rgba(main, 0.85));
    g.addColorStop(0.5, rgba(main, 0.12 + lvl * 0.2));
    g.addColorStop(1, rgba(main, 0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(0, 0, R, 0, Math.PI * 2); ctx.fill();

    // anneau exterieur gradue
    ctx.save(); ctx.rotate(t * 0.05 * speed);
    for (let i = 0; i < 120; i++) {
      const a = (i / 120) * Math.PI * 2, long = i % 10 === 0;
      ctx.beginPath();
      ctx.moveTo(Math.cos(a) * (R - (long ? 12 : 6)), Math.sin(a) * (R - (long ? 12 : 6)));
      ctx.lineTo(Math.cos(a) * R, Math.sin(a) * R);
      ctx.strokeStyle = rgba(C, long ? 0.9 : 0.35); ctx.lineWidth = long ? 2 : 1; ctx.stroke();
    }
    ctx.restore();

    // arcs segmentes rotatifs
    ctx.save(); ctx.rotate(-t * 0.4 * speed);
    for (let i = 0; i < 3; i++) ring(R * 0.86, 3, main, i * 2.1, i * 2.1 + 1.3, 0.85);
    ctx.restore();
    ctx.save(); ctx.rotate(t * 0.7 * speed);
    for (let i = 0; i < 8; i++) ring(R * 0.78, 6, C, i * 0.785, i * 0.785 + 0.5, 0.45);
    ctx.restore();

    // egaliseur circulaire (voix)
    ctx.save(); ctx.rotate(t * 0.1);
    for (let i = 0; i < 64; i++) {
      const a = (i / 64) * Math.PI * 2;
      segs[i] += (Math.random() - segs[i]) * 0.2;
      const amp = (st === "speaking" || st === "listening" ? lvl : lvl * 0.3) * (0.3 + segs[i]) * R * 0.28;
      const r0 = R * 0.6;
      ctx.beginPath();
      ctx.moveTo(Math.cos(a) * r0, Math.sin(a) * r0);
      ctx.lineTo(Math.cos(a) * (r0 + 3 + amp), Math.sin(a) * (r0 + 3 + amp));
      ctx.strokeStyle = rgba(main, 0.8); ctx.lineWidth = 3; ctx.stroke();
    }
    ctx.restore();

    // anneaux internes (style reacteur Mark)
    ring(R * 0.5, 1.5, C, 0, Math.PI * 2, 0.8);
    ctx.save(); ctx.rotate(-t * speed * 0.9);
    for (let i = 0; i < 10; i++) {
      const a = (i / 10) * Math.PI * 2;
      ctx.save(); ctx.rotate(a);
      ctx.fillStyle = rgba(main, 0.55 + lvl * 0.4);
      ctx.fillRect(R * 0.34, -5, R * 0.12, 10);
      ctx.restore();
    }
    ctx.restore();
    ring(R * 0.3, 2, C, 0, Math.PI * 2, 0.9);
    // triangle central
    ctx.save(); ctx.rotate(t * speed * 0.3);
    ctx.beginPath();
    for (let i = 0; i < 3; i++) {
      const a = (i / 3) * Math.PI * 2 - Math.PI / 2;
      ctx[i ? "lineTo" : "moveTo"](Math.cos(a) * R * 0.22, Math.sin(a) * R * 0.22);
    }
    ctx.closePath(); ctx.strokeStyle = rgba([255, 255, 255], 0.75); ctx.lineWidth = 2; ctx.stroke();
    ctx.restore();
    // coeur
    const core = R * (0.12 + lvl * 0.06 + Math.sin(t * 2) * 0.008);
    const cg = ctx.createRadialGradient(0, 0, 0, 0, 0, core);
    cg.addColorStop(0, "#fff"); cg.addColorStop(0.6, rgba(main, 1)); cg.addColorStop(1, rgba(main, 0.2));
    ctx.fillStyle = cg; ctx.beginPath(); ctx.arc(0, 0, core, 0, Math.PI * 2); ctx.fill();

    // balayage radar en reflexion
    if (st === "thinking" || st === "working" || st === "control") {
      ctx.save(); ctx.rotate(t * 3);
      const sg = ctx.createLinearGradient(0, 0, R, 0);
      sg.addColorStop(0, rgba(main, 0.0)); sg.addColorStop(1, rgba(main, 0.35));
      ctx.fillStyle = sg; ctx.beginPath(); ctx.moveTo(0, 0); ctx.arc(0, 0, R * 0.95, -0.35, 0); ctx.closePath(); ctx.fill();
      ctx.restore();
    }
    ctx.restore();
    requestAnimationFrame(draw);
  }

  // ---------------------------------------------------------------- fond
  const bg = document.getElementById("bg");
  const bctx = bg.getContext("2d");
  let parts = [];
  function bgResize() {
    bg.width = innerWidth; bg.height = innerHeight;
    parts = Array.from({ length: Math.min(110, Math.floor(innerWidth / 14)) }, () => ({
      x: Math.random() * bg.width, y: Math.random() * bg.height,
      vx: (Math.random() - 0.5) * 0.25, vy: (Math.random() - 0.5) * 0.25, r: Math.random() * 1.6 + 0.3,
    }));
  }
  addEventListener("resize", bgResize);
  function hexGrid() {
    const C = Reactor.colors.c || [0, 229, 255];
    const s = 34, h = s * Math.sqrt(3) / 2;
    bctx.strokeStyle = rgba(C, 0.035); bctx.lineWidth = 1;
    for (let y = 0, row = 0; y < bg.height + s; y += h, row++) {
      for (let x = (row % 2) * s * 0.75; x < bg.width + s; x += s * 1.5) {
        bctx.beginPath();
        for (let i = 0; i < 6; i++) {
          const a = (Math.PI / 3) * i;
          bctx[i ? "lineTo" : "moveTo"](x + (s / 2) * Math.cos(a), y + (s / 2) * Math.sin(a));
        }
        bctx.closePath(); bctx.stroke();
      }
    }
  }
  function bgDraw() {
    const C = Reactor.colors.c || [0, 229, 255];
    bctx.clearRect(0, 0, bg.width, bg.height);
    hexGrid();
    for (const p of parts) {
      p.x += p.vx; p.y += p.vy;
      if (p.x < 0 || p.x > bg.width) p.vx *= -1;
      if (p.y < 0 || p.y > bg.height) p.vy *= -1;
      bctx.fillStyle = rgba(C, 0.5); bctx.beginPath(); bctx.arc(p.x, p.y, p.r, 0, Math.PI * 2); bctx.fill();
    }
    for (let i = 0; i < parts.length; i++) for (let j = i + 1; j < parts.length; j++) {
      const a = parts[i], b = parts[j], d = Math.hypot(a.x - b.x, a.y - b.y);
      if (d < 110) { bctx.strokeStyle = rgba(C, 0.08 * (1 - d / 110)); bctx.beginPath(); bctx.moveTo(a.x, a.y); bctx.lineTo(b.x, b.y); bctx.stroke(); }
    }
    setTimeout(() => requestAnimationFrame(bgDraw), 33);
  }

  Reactor.refreshColors();
  bgResize(); resize();
  requestAnimationFrame(draw); bgDraw();
})();
