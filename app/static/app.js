"use strict";

// Alla anrop som andrar nagot maste ha den har headern (skydd mot andra webbsidor).
const HEADER = { "X-Akasha-Meet": "1" };
const DEL_MS = 5000; // webblasaren skickar ljudet till disken var femte sekund
// Varning om inget ljud kommer in: ljudnivan (RMS) under -80 dBFS i 10 sekunder. En avstangd
// eller fel vald mikrofon ger nollor eller nastan nollor (16-bitarsljudets minsta steg ar ca
// -90 dBFS). Bakgrundsbruset i ett tyst rum med fungerande mikrofon ligger kring -60 till -50 dBFS,
// och hogre med automatisk niva, sa marginalen mot falsklarm ar minst 20 dB.
const TYST_NIVA = 0.0001;
const TYST_MS = 10000;
const SIDTITEL = document.title;
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
let doljOsakraOrd = false;
let senastOsakra = -1; // senaste replik som "Nasta osakra" visade
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

// Kvitton och fel for det man gor i listan och visningen. meddela() skriver hogst upp i
// formularet, som inte syns nar man arbetar langre ner. Ett nytt kvitto ersatter det gamla.
// Vanliga kvitton forsvinner efter en stund, fel ligger kvar tills man stanger dem.
let kvittoTimer = null;
let fokusForeKvitto = null; // dit fokus gar tillbaka nar man stanger med tangentbordet

function kvitto(text, fel = false) {
  const ruta = $("kvitto");
  clearTimeout(kvittoTimer);
  // Bara den ena raden har text: role="alert" for fel, role="status" for kvitton.
  $("kvitto-status").textContent = fel ? "" : text;
  $("kvitto-fel").textContent = fel ? text : "";
  $("kvitto-stang").hidden = !(fel && text);
  ruta.classList.remove("visas");
  ruta.classList.toggle("ar-fel", fel);
  if (!text) return;
  void ruta.offsetWidth; // starta om inglidningen aven om en ruta redan syns
  ruta.classList.add("visas");
  if (!fel) kvittoTimer = setTimeout(() => kvitto(""), 6000);
}

function stangKvitto() {
  const hadeFokus = $("kvitto").contains(document.activeElement);
  kvitto("");
  if (hadeFokus && fokusForeKvitto && fokusForeKvitto.isConnected) fokusForeKvitto.focus();
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
  // I Safari och Firefox gar flikljud inte att dela: stang av valet i stallet for att lata
  // inspelningen misslyckas forst nar man trycker Spela in.
  if (!kanDelaFlik()) {
    const digitalt = $("kalla").querySelector('option[value="digitalt"]');
    digitalt.disabled = true;
    digitalt.textContent = "Digitalt (kräver Chrome)";
    $("kalla-hjalp").textContent =
      "Gäller när du spelar in. Uppladdade filer påverkas inte. Digitala möten kan bara spelas in i Chrome.";
  }
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
  const insp = { id, rec, ljud, nr: 0, sparade: 0, ko: Promise.resolve(), start: Date.now(), fel: null };
  inspelning = insp;
  rec.addEventListener("dataavailable", (e) => { if (e.data && e.data.size) skickaDel(e.data); });
  rec.start(DEL_MS);

  starta_niva(stream);
  // Klockan, tystnadskollen och flikens titel gar pa en timer och inte pa requestAnimationFrame,
  // som star still nar fliken ar i bakgrunden (vid digitala moten ar man i motesfliken).
  insp.klocka = setInterval(() => uppdateraKlocka(insp), 500);
  uppdateraKlocka(insp);
  try { insp.wakeLock = await navigator.wakeLock?.request("screen"); } catch { /* valfritt */ }

  $("spela-in").hidden = true;
  $("valj-fil").disabled = true;
  $("kalla").disabled = true; // kallan gar inte att byta mitt i en inspelning
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
  const insp = inspelning;
  try {
    const ctx = new AudioContext();
    ctx.resume().catch(() => { /* valfritt */ });
    const analys = ctx.createAnalyser();
    analys.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(analys);
    const buf = new Float32Array(analys.fftSize);
    insp.ljudctx = ctx;
    insp.senastLjud = Date.now();
    insp.lasNiva = () => {
      // Ett pausat ljudsammanhang ger bara nollor och sager inget om mikrofonen: inget larm da.
      if (ctx.state !== "running") { insp.senastLjud = Date.now(); return null; }
      analys.getFloatTimeDomainData(buf);
      let summa = 0;
      for (const v of buf) summa += v * v;
      const rms = Math.sqrt(summa / buf.length);
      if (rms >= TYST_NIVA) insp.senastLjud = Date.now();
      return rms;
    };
    const steg = () => {
      if (inspelning !== insp) return;
      const rms = insp.lasNiva();
      if (rms !== null) $("niva").value = Math.min(1, rms * 4);
      requestAnimationFrame(steg);
    };
    steg();
  } catch { /* nivamatare ar valfri */ }
}

function uppdateraKlocka(insp) {
  const t = tid((Date.now() - insp.start) / 1000);
  $("klocka").textContent = t;
  insp.lasNiva?.();
  const tyst = !!insp.lasNiva && Date.now() - insp.senastLjud >= TYST_MS;
  visaTystnad(tyst);
  document.title = `${tyst ? "⚠ Inget ljud" : "●"} ${t} – ${SIDTITEL}`;
}

function visaTystnad(tyst) {
  const v = $("tyst-varning");
  if (v.hidden !== tyst) return;
  v.hidden = !tyst;
  // Texten satts nar varningen visas, sa att skarmlasare laser upp den (role="alert").
  v.textContent = tyst
    ? "Inget ljud hörs. Kontrollera att rätt mikrofon är vald och att den inte är avstängd." : "";
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
  $("kalla").disabled = false;
  $("inspelningspanel").hidden = true;
  $("niva").value = 0;
  visaTystnad(false);
  document.title = SIDTITEL;
  try {
    // Antal talare, ord och rubrik lases nu, sa att de kan andras under motet. En tom rubrik
    // skickas inte, och da behalls den fran starten.
    const { talare, ord, titel } = installningar();
    await api("POST", `/api/inspelningar/${insp.id}/klar`, { starta: true, talare, ord, titel });
    $("titel").value = ""; // annars far nasta inspelning samma rubrik
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
      $("titel").value = ""; // annars far nasta inspelning samma rubrik
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

// Etiketten ar kort. Ett felmeddelande star pa en egen rad under (se rendera), annars bryts
// etiketten fult. I ko finns inget framsteg att visa, sa dar blir det bara "I ko".
function statusElement(m) {
  const text = STATUS[m.status] || m.status;
  const span = el("span", { class: `status ${m.status}` });
  const fas = m.framsteg && m.framsteg.fas;
  if (PAGAENDE.has(m.status) && m.status !== "koar" && fas && fas !== "koar") {
    const andel = m.framsteg.andel || 0;
    span.append(`${STATUS[fas] || text} ${Math.round(andel * 100)} % `,
      el("progress", { max: "1", value: String(andel), "aria-hidden": "true" }));
  } else {
    span.append(text);
  }
  return span;
}

function rendera(lista) {
  const ul = $("lista");
  // Listan byggs om varannan sekund medan nagot transkriberas: behall fokus pa samma knapp,
  // annars tappar den som anvander tangentbordet sin plats.
  const fokus = ul.contains(document.activeElement)
    ? { id: document.activeElement.closest("li")?.dataset.id, roll: document.activeElement.dataset.roll }
    : null;
  ul.replaceChildren();
  $("tom").hidden = lista.length > 0;
  for (const m of lista) {
    const atgarder = el("span", { class: "knappar" });
    const egenInspelning = inspelning && inspelning.id === m.id;
    if (m.status === "spelar_in" && !egenInspelning) {
      atgarder.append(el("button", { type: "button", class: "knapp liten-knapp", "data-roll": "avsluta",
        onclick: () => avsluta(m.id) }, "Avsluta och transkribera"));
    }
    if (["sparad", "fel", "avbruten", "klar"].includes(m.status)) {
      atgarder.append(el("button", { type: "button", class: "knapp liten-knapp", "data-roll": "transkribera",
        "aria-haspopup": "dialog", onclick: () => transkriberaIgen(m) },
      m.status === "klar" ? "Transkribera igen" : "Transkribera"));
    }
    if (!PAGAENDE.has(m.status) && !egenInspelning) {
      atgarder.append(el("button", { type: "button", class: "knapp liten-knapp fara", "data-roll": "radera",
        onclick: () => radera(m) }, "Radera"));
    }
    const harFel = (m.status === "fel" || m.status === "avbruten") && m.fel;
    ul.append(el("li", { "data-id": m.id },
      el("button", { type: "button", class: "post", "data-roll": "visa", onclick: () => visa(m.id) },
        el("span", { class: "post-text" },
          el("span", { class: "post-rubrik" }, m.rubrik),
          el("span", { class: "post-rad" }, el("span", { class: "post-info" }, m.info || ""), " ", statusElement(m)),
          harFel ? el("span", { class: "post-fel" }, m.fel) : null),
        el("span", { class: "post-pil", "aria-hidden": "true" }, "›")),
      atgarder));
  }
  markeraVisad();
  if (fokus && fokus.id) {
    const li = [...ul.children].find((x) => x.dataset.id === fokus.id);
    const knapp = li && (li.querySelector(`[data-roll="${fokus.roll}"]`) || li.querySelector(".post"));
    if (knapp) knapp.focus({ preventScroll: true });
  }
}

// Raden for inspelningen som visas ar markerad, sa att man ser var i listan man ar.
function markeraVisad() {
  for (const li of $("lista").children) {
    const vald = visadId !== null && li.dataset.id === visadId;
    li.classList.toggle("visad", vald);
    const post = li.querySelector(".post");
    if (vald) post.setAttribute("aria-current", "true");
    else post.removeAttribute("aria-current");
  }
}

async function uppdateraLista() {
  clearTimeout(pollTimer);
  try {
    const { inspelningar } = await api("GET", "/api/inspelningar");
    rendera(inspelningar);
    const visad = inspelningar.find((m) => m.id === visadId);
    if (visad && $("visning").dataset.status !== visad.status) visa(visadId, true);
    else if (visad) renderaForlopp(visad); // bara stapeln: ljudet och texten far vara ifred
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
    kvitto("Inspelningen transkriberas med de inställningar den startades med.");
  } catch (e) { kvitto(e.message, true); }
  uppdateraLista();
}

// --- transkribera igen ---------------------------------------------------------------------

let omInspelning = null; // inspelningen som dialogen galler

// Oppnar dialogen. Antal talare och ord fylls i fran inspelningen sjalv, inte fran formularet
// hogst upp: efter en omladdning star det 2 talare dar, vilket gjorde om stora moten fel.
// m ar en post fran listan (m.rattad) eller hela inspelningen (m.resultat.segment_original).
function transkriberaIgen(m) {
  const inst = m.installningar || {};
  const talare = String(inst.talare ?? "2");
  omInspelning = m;
  $("om-rubrik").textContent = `${m.status === "klar" ? "Transkribera igen" : "Transkribera"}: ${m.rubrik}`;
  fyllTalarval($("om-talare"), talare);
  $("om-ord").value = inst.ord || "";
  $("om-digital").hidden = inst.kalla !== "digitalt";
  $("om-rattad").hidden = !(m.rattad || (m.resultat && m.resultat.segment_original));
  $("om-fel").textContent = "";
  $("om-starta").disabled = false;
  $("om-dialog").showModal();
}

// Samma alternativ som i formularet hogst upp. Servern tillater 1-10 och auto, sa ett varde
// som inte finns bland alternativen laggs till i stallet for att tyst bli nagot annat.
function fyllTalarval(select, varde) {
  const forlaga = $("talare");
  select.replaceChildren(...(forlaga
    ? [...forlaga.options].map((o) => el("option", { value: o.value }, o.textContent))
    : ["1", "2", "3", "4", "5", "6", "auto"].map((v) => el("option", { value: v }, v))));
  if (![...select.options].some((o) => o.value === varde)) {
    const ny = el("option", { value: varde }, varde);
    const efter = [...select.options].find((o) => o.value === "auto" || Number(o.value) > Number(varde));
    select.insertBefore(ny, efter || null);
  }
  select.value = varde;
}

async function startaOmtranskribering(e) {
  e.preventDefault();
  const m = omInspelning;
  if (!m) return;
  const talare = $("om-talare").value, ord = $("om-ord").value.trim();
  $("om-starta").disabled = true;
  $("om-fel").textContent = "";
  try {
    await api("POST", `/api/inspelningar/${m.id}/transkribera`, { talare, ord });
  } catch (fel) {
    // Dialogen stannar oppen, sa att man ser vad som gick fel och kan forsoka igen.
    $("om-fel").textContent = `Kunde inte starta: ${fel.message}`;
    $("om-starta").disabled = false;
    $("om-starta").focus(); // knappen tappade fokus nar den var avstangd
    return;
  }
  omInspelning = null; // fokus ska inte tillbaka till listan: visningen oppnas
  $("om-dialog").close();
  visa(m.id);
  uppdateraLista();
}

function stangOmdialog() {
  // close-handelsen kommer i efterhand: har dialogen hunnit oppnas igen galler den en annan inspelning.
  if ($("om-dialog").open) return;
  const id = omInspelning && omInspelning.id;
  omInspelning = null;
  // Listan kan ha byggts om medan dialogen var oppen. Da finns knappen som oppnade den inte
  // langre, och fokus ska tillbaka till samma knapp i den nya listan.
  if (id && document.activeElement === document.body) {
    const li = [...$("lista").children].find((x) => x.dataset.id === id);
    const knapp = li && (li.querySelector('[data-roll="transkribera"]') || li.querySelector(".post"));
    if (knapp) knapp.focus();
  }
}

async function radera(m) {
  if (!confirm(`Radera "${m.rubrik}"? Ljudet och texten tas bort från datorn.`)) return;
  try {
    await api("POST", `/api/inspelningar/${m.id}/radera`);
    if (visadId === m.id) stangVisning();
  } catch (e) { kvitto(e.message, true); }
  uppdateraLista();
}

// --- visning -------------------------------------------------------------------------------

// Med smidig rullning bara om anvandaren inte bett om mindre rorelse.
function rulla(mal, block) {
  const lugnt = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  mal.scrollIntoView({ behavior: lugnt ? "auto" : "smooth", block });
}

async function visa(id, tyst = false) {
  let m;
  try { m = await api("GET", `/api/inspelningar/${id}`); } catch (e) { kvitto(e.message, true); return; }
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
  // Datum, langd och antal talare. Vilken motor som anvants ar for den nyfikne: den star i title.
  $("v-info").textContent = m.info || "";
  $("v-info").title = res && res.motor ? `Transkriberat med ${res.motor}` : "";
  if (byttId) {
    $("v-ljud").src = `/api/inspelningar/${id}/ljud`;
    $("v-kopierat").textContent = "";
    senastOsakra = -1;
  }

  // Under en ny transkribering ligger den gamla texten kvar pa disken: visa forloppet i stallet.
  const harText = !!(res && res.segment && res.segment.length) && !PAGAENDE.has(m.status) && m.status !== "spelar_in";
  const harTalare = harText && res.segment.some((s) => "speaker" in s);
  $("v-varning").hidden = !(res && res.varning) || PAGAENDE.has(m.status); // varningen hor till den gamla texten
  $("v-varning").textContent = (res && res.varning) || "";
  visaLage(m, harText);
  renderaForlopp(m);

  visadMeta = m;
  stangTalarval();
  renderaNamn(m);
  renderaText(m);
  $("v-text").hidden = !harText;
  renderaOsakert(m);

  // Stegen 1-3 och forklaringen finns bara nar det finns text. Ljudspelaren och "Ladda ner
  // ljudet" finns alltid: man ska kunna lyssna medan man vantar, och ljudet ar vart att spara.
  $("v-steg-namn").hidden = !harTalare;
  $("v-kontroll-rubrik").hidden = !harText;
  $("v-forklaring").hidden = !harText;
  $("v-anvand-rubrik").hidden = !harText;
  $("v-atgarder").hidden = !harText;
  $("v-till-nedladdning").hidden = !harText;
  $("v-rattad").hidden = !(harText && res.segment_original);
  v.classList.toggle("utan-text", !harText);
  numreraSteg();

  $("v-md").href = `/api/inspelningar/${id}/text.md`;
  $("v-txt").href = `/api/inspelningar/${id}/text.txt`;
  $("v-ljudfil").href = `/api/inspelningar/${id}/ljud?ladda_ner=1`;
  if (byttId && !tyst) rulla(v, "start");
  if (PAGAENDE.has(m.status)) uppdateraLista();
  markeraVisad();
}

// Vad som hant och vad man kan gora harnast, nar det inte finns nagon text att visa.
function visaLage(m, harText) {
  const status = $("v-status");
  let text = "", knapp = "";
  if (m.status === "klar") {
    text = harText ? "" : "Ingen text hittades i inspelningen.";
  } else if (m.status === "fel" || m.status === "avbruten") {
    text = m.fel || STATUS[m.status];
    knapp = "Försök igen";
  } else if (m.status === "sparad") {
    text = "Inspelningen är sparad men har inte transkriberats än.";
    knapp = "Transkribera";
  } else if (!PAGAENDE.has(m.status)) {
    text = STATUS[m.status] || m.status;
  }
  status.textContent = text;
  status.classList.toggle("fel", m.status === "fel" || m.status === "avbruten");
  $("v-forsok").hidden = !knapp;
  $("v-forsok").textContent = knapp;
}

function sattText(e, text) {
  if (e.textContent !== text) e.textContent = text; // annars laser skarmlasaren upp samma sak igen
}

// Var i forloppet jobbet ar. Anropas vid varje hamtning av listan, sa att stapeln ror sig
// aven nar status ar densamma, utan att resten av visningen byggs om.
function renderaForlopp(m) {
  const ruta = $("v-forlopp");
  ruta.hidden = !PAGAENDE.has(m.status);
  if (ruta.hidden) return;
  const f = m.framsteg || {};
  const fas = f.fas || m.status;
  // Med en talare delas texten inte upp: da finns inget mellansteg.
  const delar = String((m.installningar || {}).talare) !== "1";
  const steg = [...(fas === "koar" ? [["koar", "I kö"]] : []), ["transkriberar", "Transkriberar"],
    ...(delar ? [["talare", "Delar upp per talare"]] : []), ["klar", "Klar"]];
  const nu = steg.findIndex(([k]) => k === fas);
  const ol = $("v-forlopp-steg");
  const nyckel = `${steg.map(([k]) => k).join()}:${fas}`;
  if (ol.dataset.nyckel !== nyckel) {
    ol.dataset.nyckel = nyckel;
    ol.replaceChildren(...steg.map(([, namn], i) => el("li", {
      class: i < nu ? "klart" : i === nu ? "pagar" : "kommer", "aria-current": i === nu ? "step" : undefined,
    }, i < nu ? el("span", { "aria-hidden": "true" }, "✓ ") : null, namn)));
  }
  const koar = fas === "koar";
  const andel = Math.max(0, Math.min(1, Number(f.andel) || 0));
  $("v-forlopp-stapel").hidden = koar;
  $("v-forlopp-andel").value = andel;
  sattText($("v-forlopp-procent"), `${Math.round(andel * 100)} %`);
  sattText($("v-forlopp-text"), koar ? "Väntar på att en annan transkribering ska bli klar."
    : fas === "transkriberar" ? tidKvar(andel, Number(f.sekunder)) : "");
}

// Ungefar hur lang tid som ar kvar av transkriberingen, grovt avrundat. Tom om det ar for
// tidigt att saga (eller om servern inte skickar hur lange steget har hallit pa).
function tidKvar(andel, sekunder) {
  if (!(andel >= 0.05) || !(sekunder >= 15)) return "";
  const kvar = (sekunder * (1 - andel)) / andel;
  if (kvar < 60) return "Mindre än en minut kvar.";
  let min = Math.round(kvar / 60);
  if (min < 60) {
    if (min >= 10) min = Math.round(min / 5) * 5;
    return `Ungefär ${min} ${min === 1 ? "minut" : "minuter"} kvar.`;
  }
  let tim = Math.floor(min / 60), rest = Math.round((min % 60) / 10) * 10;
  if (rest === 60) { tim += 1; rest = 0; }
  const timmar = `${tim} ${tim === 1 ? "timme" : "timmar"}`;
  return `Ungefär ${timmar}${rest ? ` och ${rest} minuter` : ""} kvar.`;
}

// Stegen numreras efter vad som visas: utan talaruppdelning borjar det med "Kontrollera".
function numreraSteg() {
  let nr = 0;
  for (const id of ["v-steg-namn", "v-steg-kontroll", "v-steg-anvand"]) {
    const rubrik = $(id).querySelector("h3");
    if (!$(id).hidden && !rubrik.hidden) rubrik.querySelector(".stegnr").textContent = String(++nr);
  }
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
  yta.classList.toggle("dolj-osakra-ord", doljOsakraOrd);
  const segs = (m.resultat && m.resultat.segment) || [];
  const kanRatta = !PAGAENDE.has(m.status);
  segs.forEach((s, i) => {
    const tidKnapp = el("button", { type: "button", class: "tid", title: "Lyssna härifrån",
      onclick: () => { const a = $("v-ljud"); a.currentTime = s.start; a.play(); } }, tid(s.start));
    const p = el("p", { "data-replik": String(i), class: s.osaker_talare ? "osaker" : undefined }, tidKnapp);
    if ("speaker" in s) {
      const namn = `${namnFor(m, s.speaker)}:`;
      p.append(kanRatta
        ? el("button", { type: "button", class: `namn ${farg(s.speaker)}`, title: "Byt talare",
          "aria-haspopup": "dialog", onclick: (e) => oppnaTalarval(e.currentTarget, i, null, null) }, namn)
        : el("span", { class: `namn ${farg(s.speaker)}` }, namn));
      if (s.osaker_talare) {
        p.append(el("span", { class: "osaker-tecken", title: "Osäker talare: kontrollera mot ljudet" }, "?"));
      }
      // Varje ord i ett eget span, sa att markerade ord kan fa en annan talare.
      const osakra = new Set(s.osakra_ord || []);
      const text = el("span", { class: "repliktext" });
      s.text.trim().split(/\s+/).forEach((ord, k) => {
        if (k) text.append(" ");
        text.append(osakra.has(k)
          ? el("span", { "data-ord": String(k), class: "osakert-ord", title: "Programmet var osäkert på ordet" }, ord)
          : el("span", { "data-ord": String(k) }, ord));
      });
      p.append(text);
    } else {
      p.append(s.text);
    }
    yta.append(p);
  });
}

// Forklaringen visar markeringarna sa som de ser ut i texten, och bara de som finns.
function renderaOsakert(m) {
  const lista = $("v-osakert");
  const segs = (m.resultat && m.resultat.segment) || [];
  const talare = segs.filter((s) => s.osaker_talare).length;
  const ord = segs.reduce((n, s) => n + (s.osakra_ord || []).length, 0);
  const nummer = talarnummer(m);
  lista.replaceChildren();
  const rad = (prov, ...text) => lista.append(el("li", {},
    el("span", { class: "prov", "aria-hidden": "true" }, prov), el("span", {}, ...text)));
  rad(el("span", { class: "tid" }, "00:00"), "Klicka på en tid för att lyssna därifrån.");
  if (nummer.length) {
    rad(el("span", { class: `namn ${farg(nummer[0])}` }, `${namnFor(m, nummer[0])}:`),
      "Klicka på namnet för att byta talare. Markera några ord för att byta talare på bara dem.");
  }
  if (talare) {
    rad(el("span", { class: "osaker-tecken" }, "?"),
      el("strong", {}, "Osäker talare"), ` – ${talare} ${talare === 1 ? "replik" : "repliker"}.`);
  }
  if (ord) {
    rad(el("span", { class: "osakert-ord" }, "ord"),
      el("strong", {}, "Osäkert ord"), ` – ${ord} ord som programmet var osäkert på. `,
      el("button", { type: "button", id: "v-understrykningar", class: "knapp liten-knapp",
        "aria-pressed": String(doljOsakraOrd), onclick: vaxlaUnderstrykningar },
      doljOsakraOrd ? "Visa understrykningar" : "Dölj understrykningar"));
  }
  if (talare || ord) lista.append(el("li", { class: "dampad" }, "Fel kan finnas även där inget är markerat."));
  uppdateraNastaOsakra();
}

// Byter bara klassen: att bygga om texten skulle tappa fokus och markering.
function vaxlaUnderstrykningar() {
  doljOsakraOrd = !doljOsakraOrd;
  $("v-text").classList.toggle("dolj-osakra-ord", doljOsakraOrd);
  const knapp = $("v-understrykningar");
  knapp.setAttribute("aria-pressed", String(doljOsakraOrd));
  knapp.textContent = doljOsakraOrd ? "Visa understrykningar" : "Dölj understrykningar";
}

// Knappen visar var man ar bland de osakra: "1 av 3" ar den som ar markerad i texten nu.
function uppdateraNastaOsakra() {
  const knapp = $("v-nasta-osakra");
  const osakra = [...document.querySelectorAll("#v-text p.osaker")].map((p) => Number(p.dataset.replik));
  knapp.hidden = !osakra.length || $("v-text").hidden;
  if (knapp.hidden) return;
  const plats = osakra.filter((r) => r <= senastOsakra).length;
  knapp.textContent = plats
    ? `Nästa osäkra talare (${plats} av ${osakra.length})`
    : `Första osäkra talare (av ${osakra.length})`;
  knapp.title = plats ? `Du står på osäker talare ${plats} av ${osakra.length}.` : "";
}

function nastaOsakra() {
  const osakra = [...document.querySelectorAll("#v-text p.osaker")];
  if (!osakra.length) return;
  const nasta = osakra.find((p) => Number(p.dataset.replik) > senastOsakra) || osakra[0];
  senastOsakra = Number(nasta.dataset.replik);
  document.querySelectorAll("#v-text p.vald-osaker").forEach((p) => p.classList.remove("vald-osaker"));
  nasta.classList.add("vald-osaker");
  uppdateraNastaOsakra();
  // Mitt i fonstret om den far plats under kontrollraden, annars overst (scroll-margin i
  // stil.css haller den fri fran kontrollraden).
  const ledigt = window.innerHeight - $("v-kontrollrad").offsetHeight;
  rulla(nasta, nasta.offsetHeight < ledigt / 2 ? "center" : "start");
  const namn = nasta.querySelector("button.namn");
  if (namn) namn.focus({ preventScroll: true });
}

function backa() {
  const ljud = $("v-ljud");
  ljud.currentTime = Math.max(0, ljud.currentTime - 5);
}

function tillNedladdning() {
  rulla($("v-steg-anvand"), "start");
  $("v-anvand-rubrik").focus({ preventScroll: true });
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
  if (helReplik && s.osaker_talare) {
    val.append(el("button", { type: "button", class: `knapp liten-knapp ${farg(s.speaker)}`,
      onclick: () => ratta(i, { talare: s.speaker }) }, `${namnFor(m, s.speaker)} stämmer`));
  }
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
  } catch (e) { kvitto(e.message, true); }
}

async function kopiera() {
  try {
    const svar = await fetch(`/api/inspelningar/${visadId}/text.txt`);
    if (!svar.ok) throw new Error(`Fel ${svar.status}`);
    await navigator.clipboard.writeText(await svar.text());
    $("v-kopierat").textContent = "Texten är kopierad. Klistra in den där du vill ha den.";
    $("v-kopierat").classList.remove("fel");
  } catch (e) {
    // Meddelandet visas intill knappen: rutan langst upp syns inte harifran.
    $("v-kopierat").textContent = `Kunde inte kopiera: ${e.message}`;
    $("v-kopierat").classList.add("fel");
  }
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
    kvitto(`Rubriken är ändrad till "${rubrik}".`);
    visa(visadId, true);
    uppdateraLista();
  } catch (fel) { kvitto(fel.message, true); }
}

function stangVisning() {
  visadId = null;
  visadMeta = null;
  stangTalarval();
  $("visning").hidden = true;
  $("v-ljud").pause();
  $("v-ljud").removeAttribute("src");
  markeraVisad();
  $("v-forlopp-steg").dataset.nyckel = "";
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
$("om-form").addEventListener("submit", startaOmtranskribering);
$("kvitto-stang").addEventListener("click", stangKvitto);
// Escape stanger ett fel, sa att man slipper tabba ner till rutan. Fangas fore lyssnaren som
// stanger talarvalet: ar talarvalet eller en dialog oppen ar det den som ska stangas.
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("kvitto-stang").hidden && $("talarval").hidden && !$("om-dialog").open) stangKvitto();
}, true);
$("kvitto").addEventListener("focusin", (e) => {
  if (e.relatedTarget && !$("kvitto").contains(e.relatedTarget)) fokusForeKvitto = e.relatedTarget;
});
$("om-avbryt").addEventListener("click", () => $("om-dialog").close());
$("om-dialog").addEventListener("close", stangOmdialog);
$("v-forsok").addEventListener("click", () => transkriberaIgen(visadMeta));
$("v-backa").addEventListener("click", backa);
$("v-nasta-osakra").addEventListener("click", nastaOsakra);
$("v-till-nedladdning").addEventListener("click", tillNedladdning);
// Kontrollradens hojd (den bryts i smala fonster) styr hur langt ovanfor den en replik hamnar.
new ResizeObserver(([rad]) => {
  $("visning").style.setProperty("--kontrollhojd", `${Math.ceil(rad.borderBoxSize[0].blockSize)}px`);
}).observe($("v-kontrollrad"));
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
