/* Interface JARVIS : WebSocket, conversation, panneaux, reglages. */
(() => {
  const $ = (s) => document.querySelector(s);
  const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  let ws = null, settings = {}, current = null, attachments = [], confirmId = null, confirmTimer = null;
  const STATE_LABEL = { idle: "EN VEILLE", listening: "À L'ÉCOUTE", thinking: "ANALYSE EN COURS", working: "EXÉCUTION", speaking: "TRANSMISSION", control: "PRISE DE CONTRÔLE" };

  // ------------------------------------------------------------ markdown minimal
  function md(src) {
    const blocks = [];
    let s = esc(src).replace(/```(\w*)\n?([\s\S]*?)```/g, (_, l, code) => { blocks.push(`<pre><code>${code}</code></pre>`); return `\u0000${blocks.length - 1}\u0000`; });
    s = s.replace(/^(\|.+\|)\n\|[\s:|-]+\|\n((?:\|.*\|\n?)*)/gm, (_, head, body) => {
      const row = (r, t) => "<tr>" + r.trim().replace(/^\||\|$/g, "").split("|").map((c) => `<${t}>${c.trim()}</${t}>`).join("") + "</tr>";
      return `<table>${row(head, "th")}${body.trim().split("\n").map((r) => row(r, "td")).join("")}</table>`;
    });
    s = s.replace(/^### (.*)$/gm, "<h5>$1</h5>").replace(/^## (.*)$/gm, "<h4>$1</h4>").replace(/^# (.*)$/gm, "<h4>$1</h4>")
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
    s = s.replace(/(?:^[-*•] .*(?:\n|$))+/gm, (m) => "<ul>" + m.trim().split("\n").map((l) => `<li>${l.replace(/^[-*•] /, "")}</li>`).join("") + "</ul>");
    s = s.replace(/(?:^\d+\. .*(?:\n|$))+/gm, (m) => "<ol>" + m.trim().split("\n").map((l) => `<li>${l.replace(/^\d+\. /, "")}</li>`).join("") + "</ol>");
    s = s.split(/\n{2,}/).map((p) => /^\s*<(ul|ol|table|h4|h5|pre)/.test(p) || p.includes("\u0000") ? p : `<p>${p.replace(/\n/g, "<br>")}</p>`).join("");
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => blocks[i]);
  }

  // ------------------------------------------------------------ websocket
  function connect() {
    ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onopen = () => { setChip("#chip-net", "on", "OK"); while (outbox.length) ws.send(JSON.stringify(outbox.shift())); };
    ws.onclose = () => { setChip("#chip-net", "err", "PERDUE"); setTimeout(connect, 1500); };
    ws.onmessage = (ev) => handle(JSON.parse(ev.data));
  }
  const outbox = [];
  const send = (obj) => { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); else outbox.push(obj); };

  function handle(m) {
    switch (m.type) {
      case "hello":
        applySettings(m.settings);
        $("#transcript").innerHTML = "";
        (m.history || []).forEach((h) => addMsg(h.role, h.text));
        setChip("#chip-control", m.gui ? "on" : "warn", m.gui ? "PRÊT" : "INDISPO");
        setState(m.state);
        break;
      case "settings": applySettings(m.settings); break;
      case "state": setState(m.state); break;
      case "user_echo": break;
      case "assistant_start":
        current = addMsg("assistant", ""); current.body.classList.add("cursor"); current.text = "";
        break;
      case "assistant_delta":
        if (!current) { current = addMsg("assistant", ""); current.text = ""; }
        current.text += m.text; current.body.innerHTML = md(current.text); current.body.classList.add("cursor");
        caption(current.text); scrollDown();
        break;
      case "assistant_end":
        if (current) {
          current.body.classList.remove("cursor");
          if (m.error) current.box.classList.add("error");
          if (!current.text && !m.interrupted) current.box.remove();
        }
        current = null;
        if (m.usage) $("#usage").textContent = `${Math.round((m.usage.input + m.usage.output) / 1000)}k jetons`;
        maybeContinue();
        break;
      case "audio": if (voiceOn()) Voice.enqueueAudio(m.data); break;
      case "speak": if (voiceOn()) Voice.enqueueText(m.text); break;
      case "stop_audio": Voice.stop(); break;
      case "tool_start": logActivity(m.id, `<b>${esc(m.name)}</b> ${esc(shortArgs(m.args))}`, "run"); Voice.sfx("tool"); break;
      case "tool_end": finishActivity(m.id, m.ok, m.summary); break;
      case "activity": logActivity(null, esc(m.text).slice(0, 400), m.kind === "thought" ? "thought" : m.kind === "web" ? "web" : ""); break;
      case "hud_card": showCard(m.card); break;
      case "confirm": openConfirm(m.id, m.text); break;
      case "confirm_closed": if (m.id === confirmId) closeConfirm(); break;
      case "toast": toast(m.title, m.message); break;
      case "announcement": toast(m.title, m.text, true); addMsg("assistant", m.text); break;
      case "alarm": Voice.sfx("alert"); break;
      case "stats": renderStats(m.data); break;
      case "panels_changed": loadPanels(); break;
      case "session_cleared": $("#transcript").innerHTML = ""; $("#cards").innerHTML = ""; $("#activity").innerHTML = ""; caption(""); break;
    }
  }

  // ------------------------------------------------------------ etat / chips
  function setState(s) {
    s = s || "idle";
    document.body.dataset.state = s; Reactor.setState(s);
    $("#reactor-state").textContent = STATE_LABEL[s] || s.toUpperCase();
  }
  function setChip(sel, cls, txt) { const c = $(sel); c.className = "chip " + cls; c.querySelector("em").textContent = txt; }
  const voiceOn = () => $("#t-voice").checked && settings.tts_engine !== "off";

  function caption(text) {
    const clean = text.replace(/```[\s\S]*?```/g, "").replace(/[*#`|]/g, "").trim();
    const parts = clean.split(/(?<=[.!?])\s+/);
    $("#caption").textContent = parts.slice(-2).join(" ").slice(-220);
  }

  // ------------------------------------------------------------ conversation
  function addMsg(role, text) {
    const box = el("div", "msg " + (role === "user" ? "user" : "assistant"));
    box.appendChild(el("div", "who", role === "user" ? esc(settings.user_name || "VOUS").toUpperCase() : esc(settings.assistant_name || "JARVIS")));
    const body = el("div", "body", role === "user" ? esc(text) : md(text || ""));
    box.appendChild(body);
    $("#transcript").appendChild(box);
    scrollDown();
    return { box, body, text };
  }
  const scrollDown = () => { const t = $("#transcript"); t.scrollTop = t.scrollHeight; };

  function submit(text) {
    text = (text || "").trim();
    if (!text && !attachments.length) return;
    Voice.unlock(); Voice.stop(); Voice.sfx("send");
    addMsg("user", text + (attachments.length ? `  [${attachments.length} image(s)]` : ""));
    send({ type: "user_message", text, images: attachments });
    attachments = []; renderAttachments();
    $("#input").value = "";
  }

  function maybeContinue() {
    if (!$("#t-continuous").checked) return;
    const wait = () => (Voice.isSpeaking() ? setTimeout(wait, 300) : setTimeout(() => startListening(), 400));
    setTimeout(wait, 600);
  }

  // ------------------------------------------------------------ activite
  const shortArgs = (a) => { try { const s = JSON.stringify(a); return s.length > 120 ? s.slice(0, 117) + "…" : s; } catch (_) { return ""; } };
  function logActivity(id, html, cls) {
    const li = el("li", cls || "", `<small>${new Date().toLocaleTimeString("fr-FR")}</small> ${html}`);
    if (id) li.dataset.id = id;
    const feed = $("#activity"); feed.appendChild(li);
    while (feed.children.length > 120) feed.firstChild.remove();
    feed.scrollTop = feed.scrollHeight;
  }
  function finishActivity(id, ok, summary) {
    const li = $(`#activity li[data-id="${CSS.escape(id)}"]`);
    if (!li) return;
    li.className = ok ? "ok" : "err";
    if (summary) li.appendChild(el("div", "", `<small>${esc(summary.slice(0, 160))}</small>`));
  }

  // ------------------------------------------------------------ cartes holographiques
  function showCard(card) {
    Voice.sfx("card");
    const c = el("div", "card");
    c.innerHTML = `<button class="close" title="Fermer">✕</button><h4>${esc(card.title)}</h4>`;
    if (card.image_url) c.appendChild(el("div", "", `<img src="${esc(card.image_url)}" alt="">`));
    if (card.markdown) c.appendChild(el("div", "", md(card.markdown)));
    if (card.chart) { const cv = el("canvas"); c.appendChild(cv); requestAnimationFrame(() => drawChart(cv, card.chart)); }
    c.querySelector(".close").onclick = () => c.remove();
    const cards = $("#cards"); cards.prepend(c);
    while (cards.children.length > 4) cards.lastChild.remove();
  }

  function drawChart(cv, chart) {
    const r = cv.getBoundingClientRect(), dpr = devicePixelRatio || 1;
    cv.width = r.width * dpr; cv.height = r.height * dpr;
    const g = cv.getContext("2d"); g.scale(dpr, dpr);
    const W = r.width, H = r.height, pad = 30;
    const css = getComputedStyle(document.body);
    const palette = [css.getPropertyValue("--c"), css.getPropertyValue("--accent"), css.getPropertyValue("--c2"), "#3dffa8", "#ff6b9d"];
    const labels = chart.labels || [], series = chart.series || [];
    g.font = "11px Rajdhani, sans-serif"; g.fillStyle = "#8fb5c7";
    if (chart.type === "pie") {
      const vals = (series[0] || { values: [] }).values, total = vals.reduce((a, b) => a + b, 0) || 1;
      let a = -Math.PI / 2; const R = Math.min(W, H) / 2 - 20;
      vals.forEach((v, i) => {
        const da = (v / total) * Math.PI * 2;
        g.beginPath(); g.moveTo(W / 3, H / 2); g.arc(W / 3, H / 2, R, a, a + da); g.closePath();
        g.fillStyle = palette[i % palette.length]; g.globalAlpha = 0.75; g.fill(); g.globalAlpha = 1;
        g.fillText(`${labels[i] || ""} ${Math.round((v / total) * 100)}%`, (W * 2) / 3 - 10, 20 + i * 16);
        a += da;
      });
      return;
    }
    const all = series.flatMap((s) => s.values || []); const max = Math.max(...all, 0) || 1, min = Math.min(...all, 0);
    const y = (v) => H - pad - ((v - min) / (max - min || 1)) * (H - pad * 2);
    g.strokeStyle = "rgba(255,255,255,.1)";
    for (let i = 0; i <= 4; i++) { const yy = pad + ((H - pad * 2) * i) / 4; g.beginPath(); g.moveTo(pad, yy); g.lineTo(W - 8, yy); g.stroke(); g.fillText((max - ((max - min) * i) / 4).toFixed(1), 2, yy + 3); }
    const n = labels.length || 1, step = (W - pad - 8) / n;
    labels.forEach((l, i) => g.fillText(String(l).slice(0, 8), pad + i * step + 2, H - 10));
    series.forEach((s, si) => {
      const col = palette[si % palette.length]; g.strokeStyle = g.fillStyle = col; g.lineWidth = 2;
      if (chart.type === "bar") {
        const bw = (step * 0.7) / series.length;
        (s.values || []).forEach((v, i) => { g.globalAlpha = 0.8; g.fillRect(pad + i * step + si * bw + step * 0.15, y(v), bw - 2, y(min) - y(v)); g.globalAlpha = 1; });
      } else {
        g.beginPath(); (s.values || []).forEach((v, i) => g[i ? "lineTo" : "moveTo"](pad + i * step + step / 2, y(v))); g.stroke();
      }
    });
  }

  // ------------------------------------------------------------ confirmation
  function openConfirm(id, text) {
    confirmId = id; Voice.sfx("confirm");
    $("#confirm-text").textContent = text; $("#confirm").hidden = false;
    const bar = $("#confirm-bar"); bar.style.transition = "none"; bar.style.width = "100%";
    requestAnimationFrame(() => { bar.style.transition = "width 90s linear"; bar.style.width = "0%"; });
    clearTimeout(confirmTimer);
    if (Voice.sttSupported) confirmTimer = setTimeout(() => { if (confirmId === id) startListening(true); }, 1800);
  }
  function answerConfirm(ok) { if (!confirmId) return; send({ type: "confirm_response", id: confirmId, approved: ok }); closeConfirm(); }
  function closeConfirm() { confirmId = null; $("#confirm").hidden = true; clearTimeout(confirmTimer); }
  $("#confirm-yes").onclick = () => answerConfirm(true);
  $("#confirm-no").onclick = () => answerConfirm(false);

  // ------------------------------------------------------------ voix (micro)
  function startListening(forConfirm) {
    Voice.unlock();
    if (!Voice.sttSupported) { toast("Micro", "La reconnaissance vocale necessite Chrome ou Edge."); return; }
    Voice.listenOnce();
    Voice._forConfirm = !!forConfirm;
  }
  Voice.onListenState = (on, mode) => {
    $("#btn-mic").classList.toggle("live", on && mode === "ptt");
    if (mode === "denied") toast("Micro", "Acces au micro refuse.");
    setChip("#chip-mic", on ? "on" : (Voice.mode === "wake" ? "warn" : ""), on ? (mode === "ptt" ? "ACTIF" : "VEILLE") : "OFF");
    if (on && mode === "ptt") setState("listening"); else if (document.body.dataset.state === "listening") setState("idle");
  };
  Voice.onInterim = (t) => { $("#interim").textContent = t; if (t) Reactor.target = 0.5; };
  Voice.onSpeechStart = () => { Voice.stop(); };
  Voice.onFinal = (text) => {
    $("#interim").textContent = "";
    if (confirmId) {
      const low = text.toLowerCase();
      if (/\b(oui|confirme|confirmé|vas-y|d'accord|ok|autorise|go|valide)\b/.test(low)) return answerConfirm(true);
      if (/\b(non|annule|stop|refuse|pas)\b/.test(low)) return answerConfirm(false);
      return;
    }
    submit(text);
  };

  // ------------------------------------------------------------ telemetrie
  const netHist = [];
  const fmtRate = (b) => b > 1e6 ? (b / 1e6).toFixed(1) + " Mo/s" : (b / 1e3).toFixed(0) + " Ko/s";
  const fmtUp = (s) => { const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60); return (d ? d + "j " : "") + h + "h" + String(m).padStart(2, "0"); };
  function gauge(id, v) {
    const g = $(id); g.querySelector(".val").style.strokeDashoffset = 264 - (264 * Math.min(100, v)) / 100;
    g.querySelector("b").textContent = Math.round(v); g.classList.toggle("hot", v > 88);
  }
  function renderStats(d) {
    gauge("#g-cpu", d.cpu); gauge("#g-ram", d.ram.percent); gauge("#g-disk", d.disk.percent);
    $("#net-down").textContent = fmtRate(d.net.down_bps); $("#net-up").textContent = fmtRate(d.net.up_bps);
    $("#battery").textContent = d.battery ? `${d.battery.percent}% ${d.battery.plugged ? "⚡" : ""}` : "secteur";
    $("#temp").textContent = d.temp_c ? Math.round(d.temp_c) + "°C" : "--";
    $("#uptime").textContent = fmtUp(d.uptime_s); $("#procs").textContent = d.process_count;
    const cores = $("#cores");
    if (cores.children.length !== d.cpu_cores.length) cores.innerHTML = d.cpu_cores.map(() => "<i></i>").join("");
    d.cpu_cores.forEach((v, i) => (cores.children[i].style.height = Math.max(2, v) + "%"));
    netHist.push(d.cpu); if (netHist.length > 60) netHist.shift();
    const cv = $("#spark"), g = cv.getContext("2d"); cv.width = cv.clientWidth;
    const col = getComputedStyle(document.body).getPropertyValue("--c").trim();
    g.clearRect(0, 0, cv.width, cv.height); g.strokeStyle = col; g.lineWidth = 1.5; g.beginPath();
    netHist.forEach((v, i) => g[i ? "lineTo" : "moveTo"]((i / 59) * cv.width, cv.height - (v / 100) * (cv.height - 4) - 2)); g.stroke();
    g.lineTo(cv.width, cv.height); g.lineTo(0, cv.height); g.globalAlpha = 0.12; g.fillStyle = col; g.fill(); g.globalAlpha = 1;
  }

  // ------------------------------------------------------------ meteo / news / panneaux
  const WICON = (c, day) => c === 0 ? (day ? "☀" : "☾") : c <= 2 ? "⛅" : c === 3 ? "☁" : c <= 48 ? "🌫" : c <= 67 || (c >= 80 && c <= 82) ? "🌧" : c <= 77 || c >= 85 && c <= 86 ? "❄" : "⛈";
  async function loadWeather() {
    try {
      const w = await (await fetch("/api/weather")).json(); if (w.error) throw 0;
      const a = w.actuel;
      $("#w-place").textContent = w.lieu; $("#w-icon").textContent = WICON(a.code, a.jour);
      $("#w-temp").textContent = Math.round(a.temperature_c) + "°"; $("#w-desc").textContent = `${a.conditions} · ressenti ${Math.round(a.ressenti_c)}°`;
      $("#w-extra").innerHTML = `<div><span>Vent</span><b>${Math.round(a.vent_kmh)} km/h</b></div><div><span>Humidite</span><b>${a.humidite_pct}%</b></div><div><span>UV</span><b>${a.uv ?? "-"}</b></div><div><span>Air (AQI)</span><b>${w.qualite_air?.indice_europeen ?? "-"}</b></div>`;
      $("#w-days").innerHTML = w.jours.slice(0, 4).map((d) => `<div><span>${new Date(d.date).toLocaleDateString("fr-FR", { weekday: "short" })}</span><b>${WICON(d.code, 1)}</b>${Math.round(d.min_c)}°/${Math.round(d.max_c)}°<br><span>${d.proba_pluie_pct ?? 0}%☂</span></div>`).join("");
    } catch (_) { $("#w-desc").textContent = "meteo indisponible"; }
  }
  async function loadNews() {
    try {
      const items = await (await fetch("/api/news")).json(); if (items.error) throw 0;
      $("#news").innerHTML = items.map((n) => `<li><a href="${esc(n.lien)}" target="_blank" rel="noopener">${esc(n.titre)}</a><small>${esc(n.source)} · ${n.date ? new Date(n.date).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) : ""}</small></li>`).join("");
      $("#news-time").textContent = "maj " + new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    } catch (_) { $("#news").innerHTML = '<li class="empty">Flux indisponible</li>'; }
  }
  async function panelAction(kind, id, action) {
    await fetch(`/api/panels/${kind}/${id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }) });
  }
  async function loadPanels() {
    const p = await (await fetch("/api/panels")).json();
    const rem = $("#reminders"); rem.innerHTML = "";
    p.reminders.forEach((r) => {
      const li = el("li", "rem", `<span class="t">${esc(r.message)}</span><small data-due="${Date.now() + r.in_s * 1000}">${r.when}</small><button title="Annuler">✕</button>`);
      li.querySelector("button").onclick = () => panelAction("reminders", r.id, "delete"); rem.appendChild(li);
    });
    const td = $("#todos"); td.innerHTML = "";
    p.todos.forEach((t) => {
      const li = el("li", t.done ? "done" : "", `<span class="chk"></span><span class="t">${esc(t.text)}</span><small>${esc(t.due || "")}</small><button title="Supprimer">✕</button>`);
      li.querySelector(".chk").onclick = () => panelAction("todos", t.id, "toggle");
      li.querySelector("button").onclick = () => panelAction("todos", t.id, "delete"); td.appendChild(li);
    });
    if (!p.reminders.length && !p.todos.length) td.innerHTML = '<li class="empty">Rien de prevu. Dites « rappelle-moi… » ou « ajoute … a ma liste ».</li>';
    const mem = $("#memory"); mem.innerHTML = "";
    p.memory.forEach((m) => { const li = el("li", "", `<span class="t">${esc(m.fact)}</span><button>✕</button>`); li.querySelector("button").onclick = () => panelAction("memory", m.id, "delete"); mem.appendChild(li); });
    if (!p.memory.length) mem.innerHTML = '<li class="empty">Aucun souvenir pour le moment.</li>';
    $("#routines").innerHTML = p.routines.map((r) => `<li><span class="t"><b>${esc(r.name)}</b> — ${esc(r.description)}</span></li>`).join("");
  }
  setInterval(() => document.querySelectorAll("[data-due]").forEach((s) => {
    const left = (+s.dataset.due - Date.now()) / 1000;
    if (left > 0 && left < 3600) s.textContent = `${Math.floor(left / 60)}:${String(Math.floor(left % 60)).padStart(2, "0")}`;
  }), 1000);

  // ------------------------------------------------------------ reglages
  const FIELDS = ["model", "effort", "autonomy", "computer_use", "web_search", "user_name", "assistant_name", "city", "tts_engine", "voice", "voice_rate", "voice_pitch", "voice_fx", "wake_word", "theme", "sound_fx", "boot_sequence", "morning_briefing"];
  function applySettings(s) {
    const firstTime = !settings.theme;
    settings = s;
    document.body.dataset.theme = s.theme; Reactor.refreshColors();
    Voice.fx = s.voice_fx; Voice.sfxOn = s.sound_fx;
    $("#wake-label").textContent = s.wake_word;
    $("#t-wake").checked = s.wake_word_enabled; $("#t-continuous").checked = s.continuous_conversation;
    if (firstTime) $("#t-voice").checked = s.tts_engine !== "off";
    if (s.wake_word_enabled !== (Voice.mode === "wake")) Voice.setWakeMode(s.wake_word_enabled, s.wake_word);
    setChip("#chip-brain", s.api_key_set ? "on" : "warn", s.api_key_set ? s.model.replace("claude-", "").toUpperCase() : "AUTONOME");
    $("#key-hint").textContent = s.api_key_set ? `(enregistree ${s.api_key_hint || ""})` : "(absente : mode autonome)";
  }
  async function openSettings() {
    const info = await (await fetch("/api/info")).json();
    $("#s-model").innerHTML = Object.entries(info.models).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
    $("#s-voice").innerHTML = info.voices.map((v) => `<option value="${v.id}">${esc(v.label)}</option>`).join("");
    for (const f of FIELDS) { const i = $("#s-" + f); if (!i) continue; if (i.type === "checkbox") i.checked = !!settings[f]; else i.value = settings[f]; }
    $("#s-api_key").value = ""; $("#o-rate").textContent = settings.voice_rate + "%"; $("#o-pitch").textContent = settings.voice_pitch + "Hz";
    $("#diag-host").textContent = info.identity.hostname;
    $("#settings").hidden = false; loadPanels();
  }
  $("#s-voice_rate").oninput = (e) => ($("#o-rate").textContent = e.target.value + "%");
  $("#s-voice_pitch").oninput = (e) => ($("#o-pitch").textContent = e.target.value + "Hz");
  function collectSettings() {
    const changes = {};
    for (const f of FIELDS) { const i = $("#s-" + f); if (!i) continue; changes[f] = i.type === "checkbox" ? i.checked : i.type === "range" ? +i.value : i.value; }
    const key = $("#s-api_key").value.trim(); if (key) changes.api_key = key;
    return changes;
  }
  $("#settings-save").onclick = () => { send({ type: "settings_update", changes: collectSettings() }); $("#settings").hidden = true; toast("Configuration", "Parametres enregistres."); };
  $("#settings-close").onclick = () => ($("#settings").hidden = true);
  $("#btn-settings").onclick = openSettings;
  $("#voice-test").onclick = async () => {
    Voice.unlock();
    const name = $("#s-user_name").value || "Monsieur";
    if ($("#s-tts_engine").value === "browser") return Voice.enqueueText(`Bonjour ${name}, voici ma voix.`);
    const r = await fetch(`/api/tts?voice_id=${encodeURIComponent($("#s-voice").value)}&text=${encodeURIComponent(`Bonjour ${name}. Tous les systemes sont operationnels. Comment puis-je vous aider ?`)}`);
    if (!r.ok) return toast("Voix", "Voix neurale indisponible (hors ligne ?).");
    const buf = await r.arrayBuffer(); let bin = ""; new Uint8Array(buf).forEach((b) => (bin += String.fromCharCode(b)));
    Voice.fx = $("#s-voice_fx").checked; Voice.enqueueAudio(btoa(bin));
  };

  // ------------------------------------------------------------ toasts
  function toast(title, msg, alarm) {
    const t = el("div", "toast" + (alarm ? " alarm" : ""), `<b>${esc(title)}</b>${esc(msg)}`);
    $("#toasts").appendChild(t); setTimeout(() => t.remove(), alarm ? 12000 : 5000);
    if (alarm && "Notification" in window && Notification.permission === "granted" && document.hidden) new Notification(title, { body: msg });
  }

  // ------------------------------------------------------------ images jointes
  function addImageFile(file) {
    if (!file.type.startsWith("image/")) return;
    const img = new Image(), reader = new FileReader();
    reader.onload = () => {
      img.onload = () => {
        const scale = Math.min(1, 1568 / Math.max(img.width, img.height));
        const cv = document.createElement("canvas"); cv.width = img.width * scale; cv.height = img.height * scale;
        cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height);
        attachments.push(cv.toDataURL("image/jpeg", 0.88)); renderAttachments();
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  }
  function renderAttachments() {
    $("#attachments").innerHTML = attachments.map((a, i) => `<img src="${a}" data-i="${i}" title="Retirer">`).join("");
    $("#attachments").querySelectorAll("img").forEach((im) => (im.onclick = () => { attachments.splice(+im.dataset.i, 1); renderAttachments(); }));
  }
  $("#btn-attach").onclick = () => $("#file").click();
  $("#file").onchange = (e) => { [...e.target.files].forEach(addImageFile); e.target.value = ""; };
  addEventListener("paste", (e) => [...(e.clipboardData?.files || [])].forEach(addImageFile));
  addEventListener("dragover", (e) => { e.preventDefault(); document.body.classList.add("dragging"); });
  addEventListener("dragleave", (e) => { if (!e.relatedTarget) document.body.classList.remove("dragging"); });
  addEventListener("drop", (e) => { e.preventDefault(); document.body.classList.remove("dragging"); [...e.dataTransfer.files].forEach(addImageFile); });

  // ------------------------------------------------------------ commandes
  $("#composer").onsubmit = (e) => { e.preventDefault(); submit($("#input").value); };
  $("#btn-mic").onclick = () => startListening();
  $(".reactor-wrap").onclick = () => startListening();
  $("#btn-stop").onclick = () => { send({ type: "stop" }); Voice.stop(); Voice.sfx("stop"); };
  $("#btn-new").onclick = () => { send({ type: "new_session" }); toast("Session", "Nouvelle conversation."); };
  $("#quick").onclick = (e) => { const b = e.target.closest("button"); if (b) submit(b.dataset.q); };
  $("#t-wake").onchange = (e) => {
    Voice.unlock();
    if (!Voice.sttSupported) { e.target.checked = false; return toast("Micro", "Reconnaissance vocale indisponible dans ce navigateur (utilisez Chrome ou Edge)."); }
    send({ type: "settings_update", changes: { wake_word_enabled: e.target.checked } });
  };
  $("#t-continuous").onchange = (e) => send({ type: "settings_update", changes: { continuous_conversation: e.target.checked } });
  $("#t-voice").onchange = (e) => { if (!e.target.checked) Voice.stop(); };
  addEventListener("keydown", (e) => {
    if (e.key === "Escape") { if (!$("#settings").hidden) $("#settings").hidden = true; else if (confirmId) answerConfirm(false); else { send({ type: "stop" }); Voice.stop(); } }
    if (e.ctrlKey && e.code === "Space") { e.preventDefault(); startListening(); }
    if (e.ctrlKey && e.key.toLowerCase() === "k") { e.preventDefault(); $("#input").focus(); }
    if (e.ctrlKey && e.key === ",") { e.preventDefault(); openSettings(); }
  });

  // ------------------------------------------------------------ horloge
  setInterval(() => {
    const d = new Date();
    $("#clock-time").textContent = d.toLocaleTimeString("fr-FR");
    $("#clock-date").textContent = d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  }, 1000);

  // ------------------------------------------------------------ demarrage
  async function boot() {
    let info = {};
    try { info = await (await fetch("/api/info")).json(); } catch (_) {}
    const s = info.settings || {};
    const lines = [
      "> Initialisation du noyau J.A.R.V.I.S. v" + (info.version || "1.0"),
      `> Plateforme : ${info.identity?.os || "?"} · hote ${info.identity?.hostname || "?"}`,
      `> Modules d'action charges : ${info.tools || 0} protocoles`,
      `> Reseau neuronal : ${s.api_key_set ? "Claude " + (s.model || "") + " — EN LIGNE" : "MODE AUTONOME (aucune cle API)"}`,
      `> Controle peripheriques : ${info.gui ? "OPERATIONNEL" : "LIMITE"}`,
      `> Synthese vocale : ${s.tts_engine === "edge" ? "voix neurale " + s.voice : s.tts_engine}`,
      "> Tous les systemes sont operationnels.",
    ];
    const log = $("#boot-log");
    const fast = s.boot_sequence === false;
    if (!fast) Voice.sfx && setTimeout(() => { try { Voice.sfx("boot"); } catch (_) {} }, 50);
    for (const l of lines) { log.textContent += l + "\n"; await new Promise((r) => setTimeout(r, fast ? 0 : 260)); }
    const finish = () => {
      $("#boot").classList.add("done"); setTimeout(() => $("#boot").remove(), 1100);
      const h = new Date().getHours(), name = s.user_name || "Monsieur";
      const greet = `${h < 5 || h >= 18 ? "Bonsoir" : "Bonjour"} ${name}. Tous les systemes sont operationnels.`;
      caption(greet);
      if (s.morning_briefing && s.api_key_set) submit("Fais-moi le briefing du jour : meteo, agenda et actualites principales, en quelques phrases.");
      else if (s.boot_sequence !== false) send({ type: "speak", text: greet });
      if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    };
    const ctx = Voice.unlock();
    if (ctx && ctx.state !== "running") {
      const b = $("#boot-start"); b.hidden = false;
      b.onclick = () => { Voice.unlock(); finish(); };
    } else setTimeout(finish, fast ? 0 : 500);
  }

  connect(); boot(); loadWeather(); loadNews(); loadPanels();
  setInterval(loadWeather, 15 * 60 * 1000); setInterval(loadNews, 10 * 60 * 1000);
})();
