/* Voix : lecture audio (voix neurale), voix du navigateur, reconnaissance vocale, effets sonores. */
(() => {
  const Voice = {
    ctx: null, analyser: null, queue: [], playing: null, busy: false, fx: true, onIdle: null,
    recog: null, listening: false, mode: "off", wakeWord: "jarvis", awaitingCommand: false, awaitTimer: null,
    onInterim: () => {}, onFinal: () => {}, onListenState: () => {}, onSpeechStart: () => {}, sfxOn: true,
    browserVoiceName: "",
  };
  window.Voice = Voice;

  function ensureCtx() {
    if (!Voice.ctx) {
      Voice.ctx = new (window.AudioContext || window.webkitAudioContext)();
      Voice.analyser = Voice.ctx.createAnalyser();
      Voice.analyser.fftSize = 256;
      Voice.analyser.connect(Voice.ctx.destination);
      const data = new Uint8Array(Voice.analyser.frequencyBinCount);
      const loop = () => {
        Voice.analyser.getByteFrequencyData(data);
        let sum = 0; for (let i = 2; i < 60; i++) sum += data[i];
        const lvl = Math.min(1, sum / (58 * 140));
        if (lvl > 0.02) window.Reactor.target = Math.max(window.Reactor.target, lvl);
        requestAnimationFrame(loop);
      };
      loop();
    }
    if (Voice.ctx.state === "suspended") Voice.ctx.resume();
    return Voice.ctx;
  }
  Voice.unlock = ensureCtx;

  // Chaine "holographique" : legere reverb + chorus + filtre
  function fxChain(ctx) {
    const input = ctx.createGain();
    const hp = ctx.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = 140;
    const presence = ctx.createBiquadFilter(); presence.type = "peaking"; presence.frequency.value = 3200; presence.gain.value = 3;
    input.connect(hp); hp.connect(presence);
    const dry = ctx.createGain(); dry.gain.value = 0.9;
    presence.connect(dry); dry.connect(Voice.analyser);
    const delay = ctx.createDelay(); delay.delayTime.value = 0.018;
    const lfo = ctx.createOscillator(); lfo.frequency.value = 0.8;
    const depth = ctx.createGain(); depth.gain.value = 0.002;
    lfo.connect(depth); depth.connect(delay.delayTime); lfo.start();
    const wet = ctx.createGain(); wet.gain.value = 0.28;
    presence.connect(delay); delay.connect(wet); wet.connect(Voice.analyser);
    const echo = ctx.createDelay(); echo.delayTime.value = 0.09;
    const echoGain = ctx.createGain(); echoGain.gain.value = 0.12;
    presence.connect(echo); echo.connect(echoGain); echoGain.connect(Voice.analyser);
    return input;
  }

  function b64ToBuf(b64) {
    const bin = atob(b64); const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return buf.buffer;
  }

  Voice.enqueueAudio = (b64) => { Voice.queue.push({ kind: "audio", data: b64 }); pump(); };
  Voice.enqueueText = (text) => { Voice.queue.push({ kind: "text", data: text }); pump(); };

  async function pump() {
    if (Voice.busy) return;
    const item = Voice.queue.shift();
    if (!item) { Voice.onIdle && Voice.onIdle(); return; }
    Voice.busy = true;
    try {
      if (item.kind === "audio") await playAudio(item.data);
      else await speakBrowser(item.data);
    } catch (e) { console.warn("voix", e); }
    Voice.busy = false;
    pump();
  }

  async function playAudio(b64) {
    const ctx = ensureCtx();
    const buffer = await ctx.decodeAudioData(b64ToBuf(b64));
    return new Promise((resolve) => {
      const src = ctx.createBufferSource();
      src.buffer = buffer;
      if (Voice.fx && !Voice.fxIn) Voice.fxIn = fxChain(ctx);
      src.connect(Voice.fx ? Voice.fxIn : Voice.analyser);
      src.onended = () => { Voice.playing = null; resolve(); };
      Voice.playing = { stop: () => { try { src.stop(); } catch (_) {} resolve(); } };
      src.start();
    });
  }

  function pickVoice() {
    const voices = speechSynthesis.getVoices();
    if (Voice.browserVoiceName) { const v = voices.find((x) => x.name === Voice.browserVoiceName); if (v) return v; }
    const fr = voices.filter((v) => v.lang && v.lang.toLowerCase().startsWith("fr"));
    const female = /denise|julie|hortense|amelie|amélie|audrey|aurelie|marie|eloise|vivienne|celine|female|femme|google fran/i;
    return fr.find((v) => female.test(v.name)) || fr[0] || voices[0];
  }

  function speakBrowser(text) {
    return new Promise((resolve) => {
      if (!("speechSynthesis" in window) || !text) return resolve();
      const u = new SpeechSynthesisUtterance(text);
      const v = pickVoice(); if (v) { u.voice = v; u.lang = v.lang; } else u.lang = "fr-FR";
      u.rate = 1.03; u.pitch = 1.05;
      let alive = true;
      const pulse = () => { if (!alive) return; window.Reactor.target = 0.35 + Math.random() * 0.45; setTimeout(pulse, 90); };
      u.onstart = pulse;
      u.onend = u.onerror = () => { alive = false; Voice.playing = null; resolve(); };
      Voice.playing = { stop: () => { alive = false; speechSynthesis.cancel(); resolve(); } };
      speechSynthesis.speak(u);
    });
  }

  Voice.stop = () => {
    Voice.queue = [];
    if (Voice.playing) Voice.playing.stop();
    if ("speechSynthesis" in window) speechSynthesis.cancel();
  };
  Voice.isSpeaking = () => Voice.busy || Voice.queue.length > 0;

  // ---------------------------------------------------------------- effets sonores
  Voice.sfx = (kind) => {
    if (!Voice.sfxOn) return;
    const ctx = ensureCtx();
    const now = ctx.currentTime;
    const tone = (f0, f1, dur, type = "sine", vol = 0.08, delay = 0) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = type; o.frequency.setValueAtTime(f0, now + delay);
      o.frequency.exponentialRampToValueAtTime(f1, now + delay + dur);
      g.gain.setValueAtTime(0.0001, now + delay); g.gain.exponentialRampToValueAtTime(vol, now + delay + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, now + delay + dur);
      o.connect(g); g.connect(ctx.destination); o.start(now + delay); o.stop(now + delay + dur + 0.02);
    };
    if (kind === "listen") { tone(660, 990, 0.12); tone(990, 1320, 0.1, "sine", 0.06, 0.1); }
    else if (kind === "stop") { tone(880, 440, 0.15); }
    else if (kind === "send") { tone(1200, 1800, 0.07, "triangle", 0.05); }
    else if (kind === "tool") { tone(520, 780, 0.06, "square", 0.025); }
    else if (kind === "alert") { for (let i = 0; i < 3; i++) tone(880, 880, 0.15, "square", 0.05, i * 0.25); }
    else if (kind === "confirm") { tone(440, 660, 0.12, "sawtooth", 0.04); tone(660, 440, 0.12, "sawtooth", 0.04, 0.15); }
    else if (kind === "boot") { tone(80, 1400, 1.4, "sawtooth", 0.03); tone(220, 880, 1.2, "sine", 0.05, 0.2); }
    else if (kind === "card") { tone(1500, 2400, 0.08, "sine", 0.03); }
  };

  // ---------------------------------------------------------------- reconnaissance vocale
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  Voice.sttSupported = !!SR;
  let single = false;

  function createRecog() {
    const r = new SR();
    r.lang = "fr-FR"; r.interimResults = true; r.continuous = true; r.maxAlternatives = 1;
    r.onstart = () => { Voice.listening = true; Voice.onListenState(true, single ? "ptt" : Voice.mode); };
    r.onspeechstart = () => Voice.onSpeechStart();
    r.onerror = (e) => { if (e.error === "not-allowed") { Voice.mode = "off"; single = false; Voice.onListenState(false, "denied"); } };
    r.onend = () => {
      Voice.listening = false;
      if (Voice.mode === "wake" && !single) { setTimeout(() => { try { r.start(); } catch (_) {} }, 250); }
      else Voice.onListenState(false, "off");
      single = false;
    };
    r.onresult = (ev) => {
      let interim = "", final = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const res = ev.results[i];
        if (res.isFinal) final += res[0].transcript; else interim += res[0].transcript;
      }
      if (single) {
        if (interim) Voice.onInterim(interim);
        if (final.trim()) { Voice.onInterim(""); r.stop(); Voice.onFinal(final.trim()); }
        return;
      }
      // mode mot d'activation
      if (Voice.isSpeaking() && !Voice.awaitingCommand) return; // evite d'entendre sa propre voix
      const wake = Voice.wakeWord.toLowerCase();
      const low = (interim || final).toLowerCase();
      if (interim && (Voice.awaitingCommand || low.includes(wake))) Voice.onInterim(interim);
      if (!final.trim()) return;
      const text = final.trim(), lowF = text.toLowerCase();
      const idx = lowF.lastIndexOf(wake);
      if (Voice.awaitingCommand) {
        clearTimeout(Voice.awaitTimer); Voice.awaitingCommand = false; Voice.onInterim("");
        Voice.onFinal(idx >= 0 ? text.slice(idx + wake.length).replace(/^[\s,.!?]+/, "") || text : text);
      } else if (idx >= 0) {
        const cmd = text.slice(idx + wake.length).replace(/^[\s,.!?]+/, "");
        Voice.stop();
        if (cmd.length > 2) { Voice.onInterim(""); Voice.onFinal(cmd); }
        else {
          Voice.sfx("listen"); Voice.awaitingCommand = true; Voice.onInterim("À l'écoute…");
          Voice.awaitTimer = setTimeout(() => { Voice.awaitingCommand = false; Voice.onInterim(""); }, 8000);
        }
      }
    };
    return r;
  }

  Voice.listenOnce = () => {
    if (!SR) return false;
    ensureCtx(); Voice.stop();
    if (!Voice.recog) Voice.recog = createRecog();
    if (Voice.listening) { if (single) { Voice.recog.stop(); return true; } Voice.recog.abort(); }
    single = true;
    setTimeout(() => { try { Voice.recog.start(); Voice.sfx("listen"); } catch (_) {} }, Voice.listening ? 300 : 0);
    return true;
  };
  Voice.setWakeMode = (on, word) => {
    if (!SR) return false;
    Voice.wakeWord = (word || "jarvis").toLowerCase();
    Voice.mode = on ? "wake" : "off";
    if (!Voice.recog) Voice.recog = createRecog();
    if (on && !Voice.listening) { try { Voice.recog.start(); } catch (_) {} }
    if (!on && Voice.listening && !single) Voice.recog.stop();
    return true;
  };
})();
