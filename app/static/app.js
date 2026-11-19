"use strict";

// Alla anrop som andrar nagot maste ha den har headern (skydd mot andra webbsidor).
const HEADER = { "X-Akasha-Meet": "1" };
const DEL_MS = 5000; // webblasaren skickar ljudet till disken var femte sekund
const PAGAENDE = new Set(["koar", "transkriberar", "talare"]);
const STATUS = {
  spelar_in: "Spelar in",
  sparad: "Sparad, inte transkriberad",
  koar: "I kö",
  transkriberar: "Transkriberar",
  talare: "Delar upp per talare",
  klar: "Klar",
  fel: "Fel",
  avbruten: "Avbruten",
};

const $ = (id) => document.getElementById(id);
let inspelning = null; // pagaende inspelning i den har fliken
let visadId = null;
let visadMeta = null; // inspelningen som visas, med text: behovs nar talare ska rattas
let pollTimer = null;

// --- hjalpfunktioner -----------------------------------------------------------------------

async function api(metod, url, kropp, headers = {}) {
  const opt = { method: metod, headers: { ...HEADER, ...headers } };
  if (kropp instanceof Blob || kropp instanceof FormData) {
    opt.body = kropp;
  } else if (kropp !== undefined) {
    opt.body = JSON.stringify(kropp);
    opt.headers["Content-Type"] = "application/json";
  }
  const svar = await fetch(url, opt);
  let data = null;
  try { data = await svar.json(); } catch { /* inte JSON */ }
  if (!svar.ok) throw new Error((data && data.error) || `Fel ${svar.status}`);
  return data;
}

function el(tagg, attr = {}, ...barn) {
  const e = document.createElement(tagg);
  for (const [k, v] of Object.entries(attr)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? "" : v);
  }
  for (const b of barn) if (b !== null && b !== undefined) e.append(b);
  return e;
}

function tid(s) {
  s = Math.round(s || 0);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sek = s % 60;
  const p = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${p(m)}:${p(sek)}` : `${p(m)}:${p(sek)}`;
}

function meddela(text, fel = false) {
  const m = $("meddelande");
  m.textContent = text;
  m.classList.toggle("fel", fel);
}

function installningar() {
  return { talare: $("talare").value, ord: $("ord").value.trim(), titel: $("titel").value.trim(),
           kalla: $("kalla").value };
}

// Bara hur man spelar in (mikrofon eller digitalt) sparas mellan besoken. Antal talare och namn
// ar olika for varje mote: ett sparat "1 - dela inte upp" gjorde att nasta mote inte delades upp.
function sparaVal() {
  localStorage.setItem("akasha-meet-val", JSON.stringify({ kalla: $("kalla").value }));
}

function hamtaVal() {
  try {
    const v = JSON.parse(localStorage.getItem("akasha-meet-val") || "{}");
    if (v.kalla === "digitalt" && kanDelaFlik()) $("kalla").value = "digitalt";
  } catch { /* ignorera */ }
  visaKallaHjalp();
}

// Flikljud gar bara att dela i Chrome och andra Chromium-webblasare (inte Safari eller Firefox).
function kanDelaFlik() {
  return !!navigator.mediaDevices?.getDisplayMedia && /Chrome|Chromium|Edg/.test(navigator.userAgent);
}

function visaKallaHjalp() {
  const digitalt = $("kalla").value === "digitalt";
  $("digital-hjalp").hidden = !digitalt;
  if (digitalt && !kanDelaFlik()) {
    meddela("Digitala möten kan bara spelas in i Chrome. Öppna sidan i Chrome, eller kör mötet med högtalare.", true);
  }
}

// --- tjanstens status ----------------------------------------------------------------------

async function kollaTjanst() {
  const t = $("tjanst");
  try {
    const svar = await fetch("/health");
    const h = await svar.json();
    $("datakatalog").textContent = h.datakatalog;
    if (h.status === "ok") {
      t.textContent = h.talare === "ok" ? `Redo · ${h.modell}` : `Redo · utan talaruppdelning`;
      t.title = h.talare === "ok" ? "" : h.talare;
      t.className = "tjanst ok";
    } else {
      t.textContent = "Inte redo";
      t.title = h.problem || "";
      t.className = "tjanst fel";
      meddela(`Tjänsten är inte redo: ${h.problem}`, true);
    }
  } catch {
    t.textContent = "Tjänsten svarar inte";
    t.className = "tjanst fel";
  }
}

// --- inspelning ----------------------------------------------------------------------------

function valjFormat() {
  const kandidater = [
    ["audio/webm;codecs=opus", ".webm"], // Chrome, Edge, Firefox
    ["audio/mp4", ".m4a"], // Safari
    ["audio/webm", ".webm"],
    ["audio/ogg;codecs=opus", ".ogg"],
  ];
  if (!window.MediaRecorder) return null;
  for (const [mime, andelse] of kandidater) {
    if (MediaRecorder.isTypeSupported(mime)) return { mime, andelse };
  }
  return null;
}

async function spelaIn() {
  const format = valjFormat();
  if (!format || !navigator.mediaDevices) {
    meddela("Webbläsaren kan inte spela in. Prova Safari eller Chrome, eller ladda upp en fil.", true);
    return;
  }
  sparaVal();
  const inst = installningar();
  if (inst.kalla === "digitalt" && !kanDelaFlik()) {
    meddela("Digitala möten kan bara spelas in i Chrome.", true);
    return;
  }
  let ljud;
  try {
    ljud = await oppnaLjud(inst.kalla);
  } catch (e) {
    meddela(e.message, true);
    return;
  }
  let id;
  try {
    ({ id } = await api("POST", "/api/inspelningar", { andelse: format.andelse, ...inst }));
  } catch (e) {
    stangLjud(ljud);
    meddela(`Kunde inte starta: ${e.message}`, true);
    return;
  }

  const stream = ljud.stream;
  const rec = new MediaRecorder(stream, {
    mimeType: format.mime, audioBitsPerSecond: inst.kalla === "digitalt" ? 96000 : 64000 });
  inspelning = { id, rec, ljud, nr: 0, sparade: 0, ko: Promise.resolve(), start: Date.now(), fel: null };
  rec.addEventListener("dataavailable", (e) => { if (e.data && e.data.size) skickaDel(e.data); });
  rec.start(DEL_MS);

  starta_niva(stream);
  inspelning.klocka = setInterval(() => {
    $("klocka").textContent = tid((Date.now() - inspelning.start) / 1000);
  }, 500);
  try { inspelning.wakeLock = await navigator.wakeLock?.request("screen"); } catch { /* valfritt */ }

  $("spela-in").hidden = true;
  $("valj-fil").disabled = true;
  $("stoppa").hidden = false;
  $("inspelningspanel").hidden = false;
  $("sparat").textContent = "";
  meddela(inst.kalla === "digitalt"
    ? "Spelar in dig och mötet. Ljudet sparas löpande på datorn."
    : "Spelar in. Ljudet sparas löpande på datorn.");
  uppdateraLista();
}

// Mikrofonen, och vid digitalt mote aven ljudet fran en delad flik. Mikrofonen hamnar i
// vanster kanal och motet i hoger, sa att servern vet vad du sa och vad de andra sa.
async function oppnaLjud(kalla) {
  let mik;
  try {
    mik = await navigator.mediaDevices.getUserMedia({
      // Whisper klarar sig bast med obehandlat ljud. Automatisk niva hjalper nar nagon sitter
      // langre bort. Vid digitalt mote tar ekosläckningen bort motesljudet om du har hogtalare.
      audio: { echoCancellation: kalla === "digitalt", noiseSuppression: false, autoGainControl: true },
    });
  } catch {
    throw new Error("Fick inte tillgång till mikrofonen. Tillåt mikrofonen för den här sidan och försök igen.");
  }
  if (kalla !== "digitalt") return { stream: mik, kallor: [mik] };

  let flik;
  try {
    flik = await navigator.mediaDevices.getDisplayMedia({
      video: { displaySurface: "browser" },
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false,
               suppressLocalAudioPlayback: false },
      preferCurrentTab: false, selfBrowserSurface: "exclude", surfaceSwitching: "include", systemAudio: "exclude",
    });
  } catch {
    mik.getTracks().forEach((t) => t.stop());
    throw new Error("Ingen flik delades. Tryck Spela in igen och välj fliken med mötet.");
  }
  flik.getVideoTracks().forEach((t) => t.stop()); // bara ljudet behovs
  if (!flik.getAudioTracks().length) {
    [mik, flik].forEach((s) => s.getTracks().forEach((t) => t.stop()));
    throw new Error("Mötesljudet kom inte med. Välj fliken med mötet och kryssa i \"Dela även flikljud\".");
  }
  const ctx = new AudioContext();
  const kanaler = ctx.createChannelMerger(2);
  ctx.createMediaStreamSource(mik).connect(kanaler, 0, 0);
  ctx.createMediaStreamSource(new MediaStream(flik.getAudioTracks())).connect(kanaler, 0, 1);
  const mal = ctx.createMediaStreamDestination();
  mal.channelCount = 2;
  kanaler.connect(mal);
  flik.getAudioTracks()[0].addEventListener("ended", () => {
    if (inspelning) meddela("Mötesfliken delas inte längre. Nu spelas bara din mikrofon in.", true);
  });
  return { stream: mal.stream, kallor: [mik, flik], ctx };
}

function stangLjud(ljud) {
  ljud.kallor.forEach((s) => s.getTracks().forEach((t) => t.stop()));
  ljud.ctx?.close();
}

function skickaDel(blob) {
  const insp = inspelning;
  const nr = insp.nr++;
  const sekunder = (Date.now() - insp.start) / 1000; // ljudet fram till hit finns i den har delen
  insp.ko = insp.ko.then(() => skickaMedForsok(insp, nr, blob, sekunder));
}

async function skickaMedForsok(insp, nr, blob, sekunder) {
  for (let forsok = 0; forsok < 6; forsok++) {
    try {
      await api("POST", `/api/inspelningar/${insp.id}/del?nr=${nr}`, blob,
        { "Content-Type": "application/octet-stream" });
      insp.sparade = nr + 1;
      $("sparat").textContent = `Sparat: ${tid(sekunder)}`;
      return;
    } catch (e) {
      insp.fel = e.message;
      $("sparat").textContent = `Kunde inte spara (försöker igen): ${e.message}`;
      await new Promise((r) => setTimeout(r, 1000 * 2 ** forsok));
    }
  }
  meddela(`Ljudet kunde inte sparas: ${insp.fel}. Stoppa inspelningen.`, true);
}

function starta_niva(stream) {
  try {
    const ctx = new AudioContext();
    const analys = ctx.createAnalyser();
    analys.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(analys);
    const buf = new Float32Array(analys.fftSize);
    const steg = () => {
      if (!inspelning) return;
      analys.getFloatTimeDomainData(buf);
      let summa = 0;
      for (const v of buf) summa += v * v;
      $("niva").value = Math.min(1, Math.sqrt(summa / buf.length) * 4);
      requestAnimationFrame(steg);
    };
    inspelning.ljudctx = ctx;
    steg();
  } catch { /* nivamatare ar valfri */ }
}

async function stoppa() {
  const insp = inspelning;
  if (!insp) return;
  $("stoppa").disabled = true;
  meddela("Sparar de sista sekunderna…");
  await new Promise((r) => { insp.rec.addEventListener("stop", r, { once: true }); insp.rec.stop(); });
  await insp.ko;
  stangLjud(insp.ljud);
  clearInterval(insp.klocka);
  insp.ljudctx?.close();
  try { await insp.wakeLock?.release(); } catch { /* valfritt */ }
  inspelning = null;

  $("stoppa").hidden = true;
  $("stoppa").disabled = false;
  $("spela-in").hidden = false;
  $("valj-fil").disabled = false;
  $("inspelningspanel").hidden = true;
  $("niva").value = 0;
  try {
    const { talare, ord } = installningar();
    await api("POST", `/api/inspelningar/${insp.id}/klar`, { starta: true, talare, ord });
    meddela("Inspelningen är sparad och transkriberas nu.");
    visa(insp.id);
  } catch (e) {
    meddela(`Inspelningen är sparad, men transkriberingen startade inte: ${e.message}`, true);
  }
  uppdateraLista();
}

// --- uppladdning ---------------------------------------------------------------------------

function laddaUpp(fil) {
  sparaVal();
  const inst = installningar();
  const form = new FormData();
  form.append("ljud", fil);
  form.append("titel", inst.titel);
  form.append("talare", inst.talare);
  form.append("ord", inst.ord);
  const xhr = new XMLHttpRequest(); // XHR for att kunna visa uppladdningens framsteg
  xhr.open("POST", "/api/inspelningar/fil");
  for (const [k, v] of Object.entries(HEADER)) xhr.setRequestHeader(k, v);
  xhr.upload.addEventListener("progress", (e) => {
    if (e.lengthComputable) meddela(`Laddar upp: ${Math.round((e.loaded / e.total) * 100)} %`);
  });
  xhr.addEventListener("load", () => {
    let data = {};
    try { data = JSON.parse(xhr.responseText); } catch { /* inte JSON */ }
    if (xhr.status === 201) {
      meddela("Filen är uppladdad och transkriberas nu.");
      visa(data.id);
    } else {
      meddela(`Uppladdningen misslyckades: ${data.error || xhr.status}`, true);
    }
    $("fil").value = "";
    uppdateraLista();
  });
  xhr.addEventListener("error", () => meddela("Uppladdningen misslyckades.", true));
  xhr.send(form);
}

// --- listan --------------------------------------------------------------------------------

function statusElement(m) {
  const text = STATUS[m.status] || m.status;
  const span = el("span", { class: `status ${m.status}` });
  if (PAGAENDE.has(m.status) && m.framsteg) {
    const andel = m.framsteg.andel || 0;
    span.append(`${STATUS[m.framsteg.fas] || text} ${Math.round(andel * 100)} % `,
      el("progress", { max: "1", value: String(andel) }));
  } else if (m.status === "fel" || m.status === "avbruten") {
    span.append(`${text}: ${m.fel || ""}`);
  } else {
    span.append(text);
  }
  return span;
}

function rendera(lista) {
  const ul = $("lista");
  ul.replaceChildren();
  $("tom").hidden = lista.length > 0;
  for (const m of lista) {
    const atgarder = el("span", { class: "knappar" });
    const egenInspelning = inspelning && inspelning.id === m.id;
    if (m.status === "spelar_in" && !egenInspelning) {
      atgarder.append(el("button", { type: "button", class: "knapp liten-knapp", onclick: () => avsluta(m.id) },
        "Avsluta och transkribera"));
    }
    if (["sparad", "fel", "avbruten", "klar"].includes(m.status)) {
      atgarder.append(el("button", { type: "button", class: "knapp liten-knapp", onclick: () => transkriberaIgen(m) },
        m.status === "klar" ? "Gör om" : "Transkribera"));
    }
    if (!PAGAENDE.has(m.status) && !egenInspelning) {
      atgarder.append(el("button", { type: "button", class: "knapp liten-knapp fara", onclick: () => radera(m) },
        "Radera"));
    }
    ul.append(el("li", {},
      el("button", { type: "button", class: "post", onclick: () => visa(m.id) },
        el("span", { class: "post-rubrik" }, m.rubrik),
        el("span", { class: "post-info" }, m.info || ""), " ",
        statusElement(m)),
      atgarder));
  }
}

async function uppdateraLista() {
  clearTimeout(pollTimer);
  try {
    const { inspelningar } = await api("GET", "/api/inspelningar");
    rendera(inspelningar);
    const visad = inspelningar.find((m) => m.id === visadId);
    if (visad && $("visning").dataset.status !== visad.status) visa(visadId, true);
    if (inspelningar.some((m) => PAGAENDE.has(m.status) || m.status === "spelar_in")) {
      pollTimer = setTimeout(uppdateraLista, 2000);
    }
  } catch (e) {
    pollTimer = setTimeout(uppdateraLista, 5000);
  }
}

async function avsluta(id) {
  // Inspelningen avbrots (fliken stangdes): anvand installningarna fran nar den startade.
  try {
    await api("POST", `/api/inspelningar/${id}/klar`, { starta: true });
    meddela("Inspelningen transkriberas med de inställningar den startades med.");
  } catch (e) { meddela(e.message, true); }
  uppdateraLista();
}

async function transkriberaIgen(m) {
  const id = m.id;
  if (m.rattad && !confirm(`Göra om "${m.rubrik}"? Dina rättningar av talarna försvinner.`)) return;
  const { talare, ord } = installningar();
  try {
    await api("POST", `/api/inspelningar/${id}/transkribera`, { talare, ord });
    meddela(`Transkriberar igen med ${talare === "auto" ? "gissat antal" : talare} talare.`);
    visa(id);
  } catch (e) { meddela(e.message, true); }
  uppdateraLista();
}

async function radera(m) {
  if (!confirm(`Radera "${m.rubrik}"? Ljudet och texten tas bort från datorn.`)) return;
  try {
    await api("POST", `/api/inspelningar/${m.id}/radera`);
    if (visadId === m.id) stangVisning();
  } catch (e) { meddela(e.message, true); }
  uppdateraLista();
}

// --- visning -------------------------------------------------------------------------------

async function visa(id, tyst = false) {
  let m;
  try { m = await api("GET", `/api/inspelningar/${id}`); } catch (e) { meddela(e.message, true); return; }
  const byttId = visadId !== id;
  visadId = id;
  const v = $("visning");
  v.hidden = false;
  v.dataset.status = m.status;
  $("v-rubrik").textContent = m.rubrik;
  $("v-titel").placeholder = m.rubrik;
  if (byttId) visaRubrikform(false);
  v.dataset.titel = m.titel || "";
  const res = m.resultat;
  $("v-info").textContent = [m.info, res && res.motor].filter(Boolean).join(" · ");
  if (byttId) $("v-ljud").src = `/api/inspelningar/${id}/ljud`;

  const harText = res && res.segment && res.segment.length;
  $("v-atgarder").hidden = !harText;
  $("v-varning").hidden = !(res && res.varning);
  $("v-varning").textContent = (res && res.varning) || "";
  $("v-status").textContent = m.status === "klar"
    ? (harText ? "" : "Ingen text hittades i inspelningen.")
    : `${STATUS[m.status] || m.status}${m.fel ? `: ${m.fel}` : ""}`;
  $("v-status").classList.toggle("fel", m.status === "fel");

  visadMeta = m;
  stangTalarval();
  renderaNamn(m);
  renderaText(m);
  $("v-md").href = `/api/inspelningar/${id}/text.md`;
  $("v-txt").href = `/api/inspelningar/${id}/text.txt`;
  $("v-ljudfil").href = `/api/inspelningar/${id}/ljud?ladda_ner=1`;
  const harTalare = harText && res.segment.some((s) => "speaker" in s);
  $("v-ratta-hjalp").hidden = !harTalare || PAGAENDE.has(m.status);
  $("v-angra").hidden = !(res && res.segment_original);
  if (byttId && !tyst) v.scrollIntoView({ behavior: "smooth", block: "start" });
  if (PAGAENDE.has(m.status)) uppdateraLista();
}

function talarnummer(m) {
  const segs = (m.resultat && m.resultat.segment) || [];
  return [...new Set(segs.filter((s) => "speaker" in s).map((s) => s.speaker))].sort((a, b) => a - b);
}

function namnFor(m, nr) {
  return ((m.namn || {})[String(nr)] || "").trim() || `Talare ${nr}`;
}

function renderaNamn(m) {
  const rad = $("v-namn");
  const nummer = talarnummer(m);
  rad.replaceChildren();
  rad.hidden = nummer.length === 0;
  if (!nummer.length) return;
  for (const nr of nummer) {
    const falt = el("input", { type: "text", id: `namn-${nr}`, maxlength: "60",
      placeholder: `Talare ${nr}`, value: (m.namn || {})[String(nr)] || "" });
    rad.append(el("div", { class: "falt" }, el("label", { for: `namn-${nr}`, class: `t${((nr - 1) % 6) + 1}` },
      `Talare ${nr} heter`), falt));
  }
  rad.append(el("button", { type: "button", class: "knapp", onclick: () => sparaNamn(m, nummer) }, "Spara namn"));
}

async function sparaNamn(m, nummer) {
  const namn = {};
  for (const nr of nummer) namn[nr] = $(`namn-${nr}`).value.trim();
  try {
    await api("POST", `/api/inspelningar/${m.id}/namn`, namn);
    visa(m.id, true);
  } catch (e) { meddela(e.message, true); }
}

function farg(nr) {
  return `t${((nr - 1) % 6) + 1}`;
}

function renderaText(m) {
  const yta = $("v-text");
  yta.replaceChildren();
  const segs = (m.resultat && m.resultat.segment) || [];
  const kanRatta = !PAGAENDE.has(m.status);
  segs.forEach((s, i) => {
    const tidKnapp = el("button", { type: "button", class: "tid", title: "Lyssna härifrån",
      onclick: () => { const a = $("v-ljud"); a.currentTime = s.start; a.play(); } }, tid(s.start));
    const p = el("p", { "data-replik": String(i) }, tidKnapp);
    if ("speaker" in s) {
      const namn = `${namnFor(m, s.speaker)}:`;
      p.append(kanRatta
        ? el("button", { type: "button", class: `namn ${farg(s.speaker)}`, title: "Byt talare",
          "aria-haspopup": "dialog", onclick: (e) => oppnaTalarval(e.currentTarget, i, null, null) }, namn)
        : el("span", { class: `namn ${farg(s.speaker)}` }, namn));
      // Varje ord i ett eget span, sa att markerade ord kan fa en annan talare.
      const text = el("span", { class: "repliktext" });
      s.text.trim().split(/\s+/).forEach((ord, k) => {
        if (k) text.append(" ");
        text.append(el("span", { "data-ord": String(k) }, ord));
      });
      p.append(text);
    } else {
      p.append(s.text);
    }
    yta.append(p);
  });
}

// --- ratta talare --------------------------------------------------------------------------

function stangTalarval() {
  const ruta = $("talarval");
  if (ruta.hidden) return;
  ruta.hidden = true;
  ruta.replaceChildren();
}

function oppnaTalarval(ankare, i, fran, till) {
  const m = visadMeta;
  const s = m.resultat.segment[i];
  const orden = s.text.trim().split(/\s+/);
  const helReplik = fran === null;
  const markerat = helReplik ? "" : orden.slice(fran, till).join(" ");
  const ruta = $("talarval");
  ruta.replaceChildren(el("p", { id: "talarval-rubrik", class: "talarval-rubrik" },
    helReplik ? `Vem sa repliken (${tid(s.start)})?` : "Vem sa det markerade?"));
  if (!helReplik) {
    ruta.append(el("p", { class: "citat" }, `”${markerat.length > 80 ? markerat.slice(0, 77) + "…" : markerat}”`));
  }
  const val = el("div", { class: "knappar" });
  for (const nr of talarnummer(m)) {
    if (helReplik && nr === s.speaker) continue;
    val.append(el("button", { type: "button", class: `knapp liten-knapp ${farg(nr)}`,
      onclick: () => ratta(i, { talare: nr, fran, till }) }, namnFor(m, nr)));
  }
  val.append(el("button", { type: "button", class: "knapp liten-knapp",
    onclick: () => ratta(i, { talare: "ny", fran, till }) }, "Ny talare"));
  ruta.append(val);
  const andra = talarnummer(m).filter((nr) => nr !== s.speaker);
  if (helReplik && andra.length) {
    const alla = el("div", { class: "knappar" });
    for (const nr of andra) {
      alla.append(el("button", { type: "button", class: `knapp liten-knapp ${farg(nr)}`,
        onclick: () => ratta(i, { talare: nr, alla: true }) }, namnFor(m, nr)));
    }
    ruta.append(el("p", { class: "dampad liten" }, `Alla repliker från ${namnFor(m, s.speaker)} är egentligen:`), alla);
  }
  ruta.append(el("button", { type: "button", class: "knapp liten-knapp", onclick: stangTalarval }, "Avbryt"));

  ruta.hidden = false;
  const r = ankare.getBoundingClientRect();
  const bredd = document.documentElement.clientWidth;
  ruta.style.top = `${r.bottom + window.scrollY + 6}px`;
  ruta.style.left = `${Math.max(8, Math.min(r.left + window.scrollX, bredd - ruta.offsetWidth - 8 + window.scrollX))}px`;
  ruta.querySelector("button").focus({ preventScroll: true });
}

async function ratta(i, val) {
  const m = visadMeta;
  stangTalarval();
  window.getSelection().removeAllRanges();
  try {
    await api("POST", `/api/inspelningar/${m.id}/talare`, { replik: i, text: m.resultat.segment[i].text, ...val });
    const y = window.scrollY;
    await visa(m.id, true);
    window.scrollTo(0, y);
    uppdateraLista();
  } catch (e) {
    $("v-status").textContent = e.message;
    $("v-status").classList.add("fel");
  }
}

function markeradeOrd() {
  // Markerade ord i en och samma replik -> [replik, fran, till] (till raknas inte med), annars null.
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount || !visadMeta) return null;
  const r = sel.getRangeAt(0);
  const replik = (n) => (n.nodeType === 1 ? n : n.parentElement)?.closest("#v-text p[data-replik]");
  const p = replik(r.startContainer);
  if (!p || p !== replik(r.endContainer)) return null;
  const traffade = [...p.querySelectorAll("[data-ord]")].filter((ord) => {
    const o = document.createRange();
    o.selectNodeContents(ord);
    // overlappar om markeringen borjar fore ordets slut och slutar efter ordets borjan
    return r.compareBoundaryPoints(Range.END_TO_START, o) < 0 && r.compareBoundaryPoints(Range.START_TO_END, o) > 0;
  });
  if (!traffade.length) return null;
  return [Number(p.dataset.replik), Number(traffade[0].dataset.ord),
    Number(traffade[traffade.length - 1].dataset.ord) + 1, traffade[traffade.length - 1]];
}

function efterMarkering() {
  setTimeout(() => {
    if (!visadMeta || PAGAENDE.has(visadMeta.status)) return;
    const m = markeradeOrd();
    if (m) oppnaTalarval(m[3], m[0], m[1], m[2]);
  }, 0);
}

async function angraRattningar() {
  if (!confirm("Ångra alla rättningar av talarna? Texten går tillbaka till hur den var efter transkriberingen.")) return;
  try {
    await api("POST", `/api/inspelningar/${visadId}/talare/angra`);
    visa(visadId, true);
    uppdateraLista();
  } catch (e) { meddela(e.message, true); }
}

async function kopiera() {
  try {
    const svar = await fetch(`/api/inspelningar/${visadId}/text.txt`);
    await navigator.clipboard.writeText(await svar.text());
    meddela("Texten är kopierad.");
  } catch (e) { meddela(`Kunde inte kopiera: ${e.message}`, true); }
}

function visaRubrikform(visa) {
  $("v-rubrikform").hidden = !visa;
  $("v-byt-rubrik").setAttribute("aria-expanded", String(visa));
  if (visa) {
    $("v-titel").value = $("visning").dataset.titel || "";
    $("v-titel").focus();
  }
}

async function sparaRubrik(e) {
  e.preventDefault();
  try {
    const { rubrik } = await api("POST", `/api/inspelningar/${visadId}/titel`, { titel: $("v-titel").value });
    visaRubrikform(false);
    meddela(`Rubriken är ändrad till "${rubrik}".`);
    visa(visadId, true);
    uppdateraLista();
  } catch (fel) { meddela(fel.message, true); }
}

function stangVisning() {
  visadId = null;
  visadMeta = null;
  stangTalarval();
  $("visning").hidden = true;
  $("v-ljud").removeAttribute("src");
}

// --- start ---------------------------------------------------------------------------------

$("spela-in").addEventListener("click", spelaIn);
$("kalla").addEventListener("change", () => { meddela(""); visaKallaHjalp(); });
$("stoppa").addEventListener("click", stoppa);
$("valj-fil").addEventListener("click", () => $("fil").click());
$("fil").addEventListener("change", () => { if ($("fil").files[0]) laddaUpp($("fil").files[0]); });
$("v-kopiera").addEventListener("click", kopiera);
$("v-stang").addEventListener("click", stangVisning);
$("v-byt-rubrik").addEventListener("click", () => visaRubrikform($("v-rubrikform").hidden));
$("v-rubrik-avbryt").addEventListener("click", () => visaRubrikform(false));
$("v-rubrikform").addEventListener("submit", sparaRubrik);
$("v-angra").addEventListener("click", angraRattningar);
$("v-text").addEventListener("mouseup", efterMarkering);
$("v-text").addEventListener("keyup", (e) => { if (e.shiftKey) efterMarkering(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") stangTalarval(); });
document.addEventListener("mousedown", (e) => {
  if (!$("talarval").hidden && !$("talarval").contains(e.target)) stangTalarval();
});
window.addEventListener("beforeunload", (e) => {
  if (inspelning) { e.preventDefault(); e.returnValue = ""; }
});

hamtaVal();
kollaTjanst();
uppdateraLista();
