"use strict";

// Alla anrop som andrar nagot maste ha den har headern (skydd mot andra webbsidor).
const HEADER = { "X-Akasha-Meet": "1" };
const INGEN_TJANST = "Akasha Meet svarar inte. Se till att programmet är igång och försök igen. Det som redan är sparat ligger kvar.";
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
let koInsp = null; // senaste inspelningen i fliken: rutan #ko och "Spara ljudet som fil" gar mot den
let visadId = null;
let visadMeta = null; // inspelningen som visas, med text: behovs nar talare ska rattas
let doljOsakraOrd = false;
let senastOsakra = -1; // senaste replik som "Nasta osakra" visade
let pollTimer = null;
let namnLage = null; // talarnamnen som sparats eller halls pa att sparas: { id, sparade, ko, vantar }
let prov = null; // pagaende rostprov fran en Lyssna-knapp: { knapp, start, slut, timer }
let talarvalAnkare = null; // det som oppnade talarvalsrutan, dit fokus gar tillbaka
let modellerVisades = false; // modellkortet syntes vid senaste renderingen
let modellerInteNu = false; // "Inte nu" tryckt i den har sidvisningen (bara nar rostmodellen saknas)
let modellTimer = null;
let halsaTimer = null; // nasta /health-fraga medan tjansten inte svarar
let senastTillstand = null; // hamtningens tillstand vid senaste renderingen
let modellAnrop = false; // ett POST fran "Hamta nu" ar pa vag: en rendering far inte skriva over knappen
let stoppAnrop = false; // detsamma for "Stoppa hamtningen"

// --- hjalpfunktioner -----------------------------------------------------------------------

// Tjansten svarade inte alls (natfel), till skillnad fran ett svar med felkod.
class TjanstFel extends Error {}

async function api(metod, url, kropp, headers = {}) {
  const opt = { method: metod, headers: { ...HEADER, ...headers } };
  if (kropp instanceof Blob || kropp instanceof FormData) {
    opt.body = kropp;
  } else if (kropp !== undefined) {
    opt.body = JSON.stringify(kropp);
    opt.headers["Content-Type"] = "application/json";
  }
  let svar;
  try {
    svar = await fetch(url, opt);
  } catch {
    // fetch avvisas bara vid natfel: tjansten ar nere.
    tjanstenSvararInte();
    throw new TjanstFel(INGEN_TJANST);
  }
  let data = null;
  try { data = await svar.json(); } catch { /* inte JSON */ }
  if (!svar.ok) {
    const fel = new Error((data && data.error) || `Fel ${svar.status}`);
    fel.status = svar.status; // sa att kon kan skilja 4xx fran 5xx
    throw fel;
  }
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

// Senaste svaren, sa att etiketten kan sattas ur bada oavsett vilket som kommer forst.
let senastHalsa = null; // /health, eller false nar tjansten inte svarade
let senastModeller = null; // /api/modeller

let halsaPaVag = false; // ett /health-anrop ar pa vag
let modellVersion = 0; // raknas upp varje gang ett riktigt svar fran /api/modeller tas emot

// Etiketten uppe till hoger. Den andras inte medan nagot svar saknas eller svaren motsager varandra
// ("Kontrollerar…" star kvar), sa att den aldrig blinkar rod nar inget ar fel. Rod visas bara nar
// /health inte svarar, vid hinder, nar /api/modeller inte svarar eller av ett annat skal. Ger
// tillbaka "fel" nar den visar rott (da ska orsaken ocksa meddelas). halsanNy: /health-svaret ar
// nyare an modellsvaret, sa att en motsagelse da ar riktig och inte ett gammalt svar.
function visaTjanst(halsanNy = false) {
  const t = $("tjanst");
  const rod = (text, title) => {
    t.textContent = text;
    t.title = title;
    t.className = "tjanst fel";
    return "fel";
  };
  const h = senastHalsa;
  if (h === false) return rod("Tjänsten svarar inte", "");
  if (h === null) return null; // inget svar an
  if (h.status === "ok") {
    t.textContent = h.talare === "ok" ? `Redo · ${h.modell}` : `Redo · utan talaruppdelning`;
    t.title = h.talare === "ok" ? "" : h.talare;
    t.className = "tjanst ok";
    return "ok";
  }
  const d = senastModeller;
  if (d === null) return null; // /api/modeller har inte svarat an
  if (d === "fel") return rod("Inte redo", h.problem || ""); // sa att sidan inte fastnar pa "Kontrollerar…"
  if (d.hinder) return rod("Inte redo", d.hinder);
  if ((d.saknas || []).some((p) => p.id === "taligenkanning")) {
    t.textContent = HAMTAR.has(d.hamtning.tillstand) ? "Hämtar modellerna…" : "Modellerna behöver hämtas";
    t.title = "";
    t.className = "tjanst vantar";
    return "vantar";
  }
  if (d.redo === true && !halsanNy) {
    // Halsosvaret ar aldre an modellsvaret: be om ett nytt i stallet for att visa det gamla. Inte
    // medan en hamtning pagar: da visar det nya svaret "Redo · utan talaruppdelning" mitt i
    // hamtningen (taligenkanningen klar, rostmodellen kvar), och etiketten skulle blinka till.
    if (!halsaPaVag && !HAMTAR.has(d.hamtning.tillstand)) kollaTjanst();
    return null;
  }
  return rod("Inte redo", h.problem || "");
}

// Etiketten, och orsaken i #meddelande nar den blir rod och /health inte ar ok.
function uppdateraTjanst(halsanNy = false) {
  if (visaTjanst(halsanNy) === "fel" && senastHalsa && senastHalsa.status !== "ok") {
    meddela(`Tjänsten är inte redo: ${senastHalsa.problem}`, true);
  }
}

// Etiketten blir rod och sidan fragar var femte sekund tills tjansten svarar igen.
function tjanstenSvararInte() {
  senastHalsa = false;
  visaTjanst();
  planeraHalsa();
}

function planeraHalsa() {
  clearTimeout(halsaTimer);
  halsaTimer = setTimeout(kollaTjanst, 5000);
}

// Tar bort sidans egna "svarar inte"-texter nar tjansten ar tillbaka. Andra fel ligger kvar.
function stadaTjanstFel() {
  const ar = (e) => e.textContent.includes(INGEN_TJANST);
  if (ar($("meddelande"))) meddela("");
  if (ar($("om-fel"))) $("om-fel").textContent = "";
  if (ar($("m-fel"))) sattText($("m-fel"), "");
  // Under en inspelning ger kon sitt eget besked nar allt ar sparat: da visas inte det allmanna.
  const koGerBesked = koInsp && !koInsp.fel && (koInsp.nere || koInsp.harVantat || koInsp.klarVantar);
  const koKvittoKom = $("kvitto-status").textContent.startsWith("Akasha Meet svarar igen");
  if (!koGerBesked && !koKvittoKom && (ar($("kvitto-fel")) || !$("kvitto-fel").textContent)) {
    const hadeFokus = $("kvitto").contains(document.activeElement);
    kvitto("Akasha Meet svarar igen.");
    if (hadeFokus && fokusForeKvitto && fokusForeKvitto.isConnected) fokusForeKvitto.focus();
  }
}

async function kollaTjanst() {
  halsaPaVag = true;
  const version = modellVersion;
  const varNere = senastHalsa === false;
  try {
    const svar = await fetch("/health");
    const h = await svar.json();
    $("datakatalog").textContent = h.datakatalog;
    senastHalsa = h;
    halsaPaVag = false;
    if (varNere && senastModeller === "fel") senastModeller = null; // ett gammalt fel, fraga om
    uppdateraTjanst(version === modellVersion);
    if (varNere) {
      // Tjansten ar tillbaka: hamta om allt utan omladdning.
      clearTimeout(halsaTimer);
      stadaTjanstFel();
      knuffaKo(); // inspelningens kon skickar direkt i stallet for att vanta ut sin paus
      kollaModeller();
      uppdateraLista();
    }
  } catch {
    halsaPaVag = false;
    senastHalsa = false;
    visaTjanst();
    planeraHalsa();
  }
}

// --- modellerna: forsta start ---------------------------------------------------------------

const HAMTAR = new Set(["hamtar", "kontrollerar"]);

// Decimala enheter, avrundat forst sa att 999,6 MB blir "1,0 GB" och aldrig "1000 MB". Samma regel
// som modeller.storlek_text i Python.
function storlekText(byte) {
  const mb = Math.round(byte / 1e6);
  if (mb < 1000) return `${mb} MB`;
  return `${(byte / 1e9).toFixed(1).replace(".", ",")} GB`;
}

async function kollaModeller() {
  clearTimeout(modellTimer);
  let d;
  let timer;
  try {
    // Tidsgrans, sa att etiketten inte fastnar pa "Kontrollerar…" om svaret aldrig kommer.
    d = await Promise.race([
      api("GET", "/api/modeller"),
      new Promise((_, avvisa) => { timer = setTimeout(() => avvisa(new Error("tidsgräns")), 10000); }),
    ]);
  } catch {
    // Ett fel ersatter aldrig ett riktigt svar fran tidigare.
    if (senastModeller === null) {
      senastModeller = "fel";
      uppdateraTjanst();
    }
    // Syns kortet gar hamtningen kanske vidare: forsok igen. Har inget riktigt svar kommit an
    // provas det igen efter en stund aven om kortet inte syns.
    if (modellerVisades || senastModeller === "fel") {
      modellTimer = setTimeout(kollaModeller, modellerVisades ? 3000 : 10000);
    }
    return;
  } finally {
    clearTimeout(timer);
  }
  renderaModeller(d);
  clearTimeout(modellTimer); // bara en timer, aven om tva anrop var pa vag samtidigt
  if (HAMTAR.has(d.hamtning.tillstand)) modellTimer = setTimeout(kollaModeller, 1000);
}

// Kortet #modeller enligt tabellen i planen: fullt lage (taligenkanningen saknas), talarlage
// (bara rostmodellen) eller dolt. Allt byggs med el() och textContent, aldrig innerHTML.
function renderaModeller(d) {
  senastModeller = d;
  modellVersion++;
  uppdateraTjanst();
  const h = d.hamtning;
  const saknas = d.saknas || [];
  const pagar = HAMTAR.has(h.tillstand);
  const fullt = !d.hinder && saknas.some((p) => p.id === "taligenkanning");
  const lage = d.hinder || !saknas.length ? null : fullt ? "fullt" : modellerInteNu ? null : "talare";
  // Fokus lases innan nagot doljs: ett dolt element ger body.
  const fokus = document.activeElement;
  const fokusIKortet = !fokus || fokus === document.body || $("modeller").contains(fokus);
  const stoppad = HAMTAR.has(senastTillstand) && h.tillstand === "avbruten";

  if (!lage) {
    const hadeKort = modellerVisades;
    $("modeller").hidden = true;
    $("ny").hidden = false;
    modellerVisades = false;
    if (hadeKort && !d.hinder && !saknas.length) {
      meddela("");
      kvitto("Klart. Modellerna är hämtade och kontrollerade.");
      kollaTjanst();
      if (fokusIKortet) $("ny-rubrik").focus();
    }
    senastTillstand = h.tillstand;
    return;
  }

  modellerVisades = true;
  $("modeller").hidden = false;
  $("ny").hidden = lage === "fullt";
  if (lage === "fullt") meddela(""); // "Tjansten ar inte redo" hor inte hemma i det dolda kortet

  sattText($("m-rubrik"), lage === "fullt" ? "Hämta modellerna" : "Hämta röstmodellen");
  sattText($("m-intro"),
    lage === "talare"
      ? "Röstmodellen som delar upp texten per talare är inte hämtad. Utan den blir texten inte uppdelad per talare. Det görs bara en gång."
      : saknas.length > 1
        ? "Innan du kan transkribera behöver Akasha Meet hämta modellerna som gör tal till text och delar upp texten per talare. Det görs bara en gång."
        : "Innan du kan transkribera behöver Akasha Meet hämta modellen som gör tal till text. Det görs bara en gång.");

  const lista = $("m-lista");
  const nyckel = JSON.stringify(saknas);
  if (lista.dataset.nyckel !== nyckel) {
    lista.dataset.nyckel = nyckel;
    lista.replaceChildren(...saknas.map((p) => el("li", {}, el("strong", {}, p.namn),
      `: ${p.beskrivning}. ${storlekText(p.storlek)} från ${p.kalla}, licens ${p.licens}.`)));
  }

  // totalt ar hela filernas storlek; det som ligger kvar som .delvis hamtas inte igen.
  const aterstar = Math.max(0, d.totalt - d.redan_hamtat);
  const disk = $("m-disk");
  disk.hidden = pagar; // raden andras inte varje sekund, och forloppet visar redan hur mycket som ar hamtat
  const diskNyckel = [d.katalog, aterstar, d.ledigt, d.redan_hamtat].join("|");
  if (!pagar && disk.dataset.nyckel !== diskNyckel) { // ledigt andras hela tiden under hamtningen
    disk.dataset.nyckel = diskNyckel;
    disk.replaceChildren("Modellerna sparas i ", el("code", {}, d.katalog),
      `. Det behövs ${storlekText(aterstar)} ledigt utrymme, och det finns ${storlekText(d.ledigt)}.`
      + (d.redan_hamtat > 0 ? ` ${storlekText(d.redan_hamtat)} är redan hämtat och hämtas inte igen.` : ""));
  }

  $("m-forlopp").hidden = !pagar;
  $("m-pagar").hidden = !pagar;
  if (pagar) {
    const andel = h.totalt > 0 ? Math.max(0, Math.min(1, h.hamtat / h.totalt)) : 0;
    $("m-andel").value = andel;
    sattText($("m-procent"), `${storlekText(h.hamtat)} av ${storlekText(h.totalt)} · ${Math.round(andel * 100)} %`);
    sattText($("m-forlopp-text"), `${h.tillstand === "kontrollerar" ? "Kontrollerar" : "Hämtar"}${h.fil ? ` ${h.fil}` : ""}.`
      + (h.kvar_s !== null && h.kvar_s !== undefined ? ` ${kvarText(h.kvar_s)}` : ""));
  }
  sattText($("m-fel"), h.tillstand === "fel" ? h.fel || "" : "");

  // Under hamtningen ar "Hamta nu" dold och "Stoppa hamtningen" synlig, annars tvartom.
  const hamta = $("m-hamta"), stoppa = $("m-stoppa");
  hamta.hidden = pagar;
  stoppa.hidden = !pagar;
  $("m-inte-nu").hidden = lage !== "talare" || pagar;
  if (!pagar && !modellAnrop) {
    hamta.textContent = h.tillstand === "fel" ? "Försök igen" : `Hämta nu (${storlekText(aterstar)})`;
    hamta.removeAttribute("aria-disabled");
  }
  if (pagar && !stoppAnrop) {
    const stoppar = !!h.stoppas;
    sattText(stoppa, stoppar ? "Stoppar…" : "Stoppa hämtningen");
    if (stoppar) stoppa.setAttribute("aria-disabled", "true"); else stoppa.removeAttribute("aria-disabled");
  }

  // aria-disabled i stallet for disabled, sa att fokus stannar pa knappen medan den arbetar.
  if (pagar && fokus === hamta) stoppa.focus();
  if (stoppad) {
    kvitto("Hämtningen är stoppad. Det som redan hämtats ligger kvar, och Hämta nu fortsätter där det slutade.");
    if (fokusIKortet) hamta.focus();
  }
  senastTillstand = h.tillstand;
}

async function hamtaModeller() {
  const knapp = $("m-hamta");
  if (knapp.getAttribute("aria-disabled") === "true") return;
  modellAnrop = true;
  knapp.textContent = "Hämtar…";
  knapp.setAttribute("aria-disabled", "true");
  try {
    const svar = await api("POST", "/api/modeller/hamta");
    modellAnrop = false;
    renderaModeller(svar);
    kollaModeller();
  } catch (e) {
    modellAnrop = false;
    sattText($("m-fel"), e.message);
    knapp.textContent = "Försök igen";
    knapp.removeAttribute("aria-disabled");
  }
}

async function stoppaHamtning() {
  const knapp = $("m-stoppa");
  if (knapp.getAttribute("aria-disabled") === "true") return;
  stoppAnrop = true;
  knapp.textContent = "Stoppar…";
  knapp.setAttribute("aria-disabled", "true");
  try {
    const svar = await api("POST", "/api/modeller/avbryt");
    stoppAnrop = false;
    renderaModeller(svar); // pollningen fortsatter tills tillstandet inte langre ar hamtar/kontrollerar
  } catch (e) {
    stoppAnrop = false;
    kvitto(e.message, true);
    knapp.textContent = "Stoppa hämtningen";
    knapp.removeAttribute("aria-disabled");
  }
}

function inteNu() {
  modellerInteNu = true;
  modellerVisades = false;
  $("modeller").hidden = true;
  $("ny-rubrik").focus();
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
  // delar: alla delar i ordning, aven de som redan ar sparade (raddningsfilen ska bli hela
  // inspelningen). sparade: antal delar servern har kvitterat.
  const insp = { id, rec, ljud, start: Date.now(), delar: [], sparade: 0, skickar: false, fel: null,
    lage: "spelar", mime: format.mime, andelse: format.andelse, filDelar: 0, vackning: null,
    nere: false, harVantat: false, stoppad: false, tomma: [], senastKoText: null };
  inspelning = insp;
  koInsp = insp;
  $("ko").hidden = true;
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
  const sekunder = (Date.now() - insp.start) / 1000; // ljudet fram till hit finns i den har delen
  insp.delar.push({ blob, sekunder });
  skickaKo(insp);
}

// Vantetider i sekunder mellan forsoken nar tjansten inte svarar: 1, 2, 4, 8 och sedan var 10:e.
function vantetid(forsok) { return [1, 2, 4, 8][forsok] ?? 10; }

// Vantar ms millisekunder, men kan vackas av knuffaKo() nar /health svarar igen.
function vanta(insp, ms) {
  return new Promise((klar) => {
    const timer = setTimeout(klar, ms);
    insp.vackning = () => { clearTimeout(timer); klar(); };
  }).finally(() => { insp.vackning = null; });
}

function knuffaKo() {
  inspelning?.vackning?.();
}

// En enda slinga skickar delarna i ordning. Servern vagrar luckor, sa en del far aldrig hoppas over:
// svarar tjansten inte forsoker slingan igen for alltid, och ett riktigt serverfel stoppar den.
async function skickaKo(insp) {
  if (insp.skickar || insp.fel) return;
  insp.skickar = true;
  let forsok = 0;
  let serverForsok = 0;
  while (insp.sparade < insp.delar.length && !insp.fel && !insp.slappt) {
    const nr = insp.sparade;
    try {
      await api("POST", `/api/inspelningar/${insp.id}/del?nr=${nr}`, insp.delar[nr].blob,
        { "Content-Type": "application/octet-stream" });
      insp.sparade = nr + 1;
      insp.nere = false;
      forsok = 0;
      serverForsok = 0;
      uppdateraKo(insp);
      losTomma(insp);
    } catch (e) {
      if (e instanceof TjanstFel) {
        insp.nere = true;
        insp.harVantat = true;
        uppdateraKo(insp);
        await vanta(insp, vantetid(forsok++) * 1000);
      } else if (e.status >= 500 && serverForsok < 3) {
        await vanta(insp, 2000 * 2 ** serverForsok++);
      } else {
        insp.fel = e.message.replace(/\.+$/, "");
        uppdateraKo(insp);
      }
    }
  }
  insp.skickar = false; // ingen await mellan loopvillkoret och hit: en ny del hinner inte slinka igenom
  losTomma(insp);
}

// Loser upp den som vantar pa att kon ar tom (eller har fatt ett fel).
function losTomma(insp) {
  if (insp.sparade < insp.delar.length && !insp.fel) return;
  insp.tomma.splice(0).forEach((r) => r());
}

function vantaPaKon(insp) {
  if (insp.sparade >= insp.delar.length || insp.fel) return Promise.resolve();
  return new Promise((r) => insp.tomma.push(r));
}

// Den sparade filen har allt ljud: inspelaren har stannat (inga fler delar kommer) och filen
// sparades efter den sista delen.
function filenArHel(insp) {
  return insp.slut && insp.filDelar > 0 && insp.filDelar === insp.delar.length;
}

// Rutan #ko och raden #sparat. Texten i rutan skrivs bara nar laget eller felet byts, sa att
// skarmlasare inte laser upp den varje sekund. Mangden som vantar star bara i #sparat.
function uppdateraKo(insp) {
  if (koInsp !== insp) return;
  const vantande = insp.delar.slice(insp.sparade);
  const sistaSparad = insp.sparade ? insp.delar[insp.sparade - 1].sekunder : 0;
  const sist = insp.delar.length ? insp.delar[insp.delar.length - 1].sekunder : 0;
  const mangd = `${tid(sist - sistaSparad)} ljud`;
  if (insp.harVantat && !vantande.length && !insp.nere) {
    insp.harVantat = false;
    if (!insp.stoppad && !insp.fel) kvitto("Akasha Meet svarar igen, och allt ljud är sparat.");
  }
  const vantar = insp.nere || (insp.harVantat && (vantande.length > 0 || insp.klarVantar));

  let sparat = "";
  if (insp.fel) sparat = "Sparas inte: se rutan nedan";
  else if (vantar && vantande.length) sparat = `Väntar på att få spara: ${mangd}`;
  else if (insp.sparade) sparat = `Sparat: ${tid(sistaSparad)}`;
  if ($("sparat").textContent !== sparat) $("sparat").textContent = sparat;

  let text = null;
  let sort = ""; // vilken text det ar: rutan skrivs bara om nar sorten byts
  if (insp.fel) {
    sort = insp.stoppad ? "fel-stoppad" : "fel-spelar";
    text = insp.stoppad
      ? `Ljudet kunde inte sparas på datorn: ${insp.fel}. Spara ljudet som en fil och ladda upp den med knappen Ladda upp ljudfil. Tryck Klar när filen är sparad.`
      : `Ljudet kan inte sparas på datorn: ${insp.fel}. Inspelningen fortsätter i den här fliken. Stoppa när mötet är slut och spara ljudet som en fil.`;
  } else if (vantar) {
    sort = !insp.stoppad ? "spelar" : vantande.length ? "vantar-ljud" : "vantar-klar";
    if (!insp.stoppad) {
      text = "Akasha Meet svarar inte just nu. Inspelningen fortsätter, och ljudet sparas i den här fliken tills Akasha Meet är igång igen. Stäng inte fliken.";
    } else if (vantande.length) {
      text = `Inspelningen är stoppad. ${mangd} väntar på att sparas, eftersom Akasha Meet inte svarar. Sidan försöker igen av sig själv och startar transkriberingen när allt har kommit fram. Stäng inte fliken. Vill du inte vänta kan du spara ljudet som en fil.`;
    } else {
      text = "Inspelningen är stoppad och sparad. Transkriberingen startar när Akasha Meet svarar igen. Stäng inte fliken.";
    }
  }
  // Filen sparades tidigare men saknar slutet: en extra mening i lagen "vantar-ljud" och "fel-stoppad".
  const gammalFil = insp.stoppad && insp.filDelar > 0 && !filenArHel(insp);
  if (gammalFil && (sort === "vantar-ljud" || sort === "fel-stoppad")) {
    text += " Filen du sparade tidigare har inte med allt. Spara ljudet som fil igen för att få med hela inspelningen.";
  }
  const nyckel = `${sort}|${insp.fel}|${gammalFil}`;
  $("ko").hidden = text === null;
  // Klar visas bara nar filen ar sparad: da kan inspelningen slappas utan att ljud tappas.
  $("ko-klar").hidden = !(insp.stoppad && filenArHel(insp) && (insp.fel || insp.nere || insp.harVantat || insp.klarVantar));
  if (text !== null && insp.stoppad && $("meddelande").textContent === "Sparar de sista sekunderna…") meddela("");
  if (text === null) insp.senastKoText = null;
  else if (insp.senastKoText !== nyckel) {
    insp.senastKoText = nyckel;
    $("ko-text").textContent = text;
  }
}

// Hela inspelningen som en fil, sa att ljudet inte forloras om tjansten aldrig kommer tillbaka.
function sparaLjudSomFil(insp) {
  if (!insp || !insp.delar.length) return;
  const url = URL.createObjectURL(new Blob(insp.delar.map((d) => d.blob), { type: insp.mime.split(";")[0] }));
  const d = new Date(insp.start);
  const p = (n) => String(n).padStart(2, "0");
  // Bara ASCII i filnamnet: ett namn med a, a eller o blev "download" i Chromium.
  const namn = `Akasha Meet ${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}.${p(d.getMinutes())}${insp.andelse}`;
  const lank = el("a", { href: url, download: namn });
  document.body.append(lank);
  lank.click();
  lank.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  insp.filDelar = insp.delar.length;
  uppdateraKo(insp);
  const tidIFilen = tid(insp.delar[insp.delar.length - 1].sekunder);
  kvitto(!insp.slut
    ? `Ljudet fram till nu (${tidIFilen}) är sparat som en fil bland dina hämtade filer. Inspelningen fortsätter. Spara igen efter Stoppa, så att filen får med allt.`
    : insp.fel
    ? "Ljudet är sparat som en fil bland dina hämtade filer. Ladda upp den med knappen Ladda upp ljudfil. Den ofullständiga inspelningen i listan kan du radera."
    : "Ljudet är sparat som en fil bland dina hämtade filer. Sidan fortsätter att försöka spara inspelningen här.");
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
      if (inspelning !== insp || insp.slut) return;
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
  uppdateraKo(insp);
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
  if (!insp || insp.stoppad) return;
  insp.stoppad = true;
  insp.lage = "vantar";
  // Antal talare, ord och rubrik lases nu, sa att de kan andras under motet. En tom rubrik
  // skickas inte, och da behalls den fran starten.
  const { talare, ord, titel } = installningar();
  insp.klarData = { talare, ord, titel };
  $("stoppa").disabled = true;
  meddela("Sparar de sista sekunderna…");
  // Den sista delen laggs i kon av dataavailable fore stop.
  await new Promise((r) => { insp.rec.addEventListener("stop", r, { once: true }); insp.rec.stop(); });
  // Mikrofonen och klockan stangs direkt, aven om ljud vantar pa tjansten.
  insp.slut = true;
  stangLjud(insp.ljud);
  clearInterval(insp.klocka);
  insp.ljudctx?.close();
  try { await insp.wakeLock?.release(); } catch { /* valfritt */ }

  $("stoppa").hidden = true;
  $("stoppa").disabled = false;
  $("inspelningspanel").hidden = true;
  $("niva").value = 0;
  visaTystnad(false);
  document.title = SIDTITEL;
  // "Spela in" forblir dold och "Ladda upp ljudfil" avstangd: inspelningen slapps i slappInspelning.
  if (insp.fel) insp.lage = "fel";
  uppdateraKo(insp);
  skickaKo(insp);
  await vantaPaKon(insp); // tom, eller servern vagrar delen (insp.fel)
  if (insp.slappt) return; // anvandaren tryckte Klar under tiden
  if (insp.fel) {
    // Inget /klar: inspelningen ar ofullstandig och halls kvar tills filen ar sparad och Klar tryckt.
    insp.lage = "fel";
    uppdateraKo(insp);
  } else {
    await avslutaInspelning(insp);
  }
  uppdateraLista();
}

// Klar efter sparad fil: inspelningen slapps och kon slutar skicka.
function slappEfterFil() {
  const insp = koInsp;
  if (!insp || !insp.stoppad || !filenArHel(insp)) return;
  const lageFel = insp.lage === "fel" || !!insp.fel;
  insp.slappt = true;
  insp.vackning?.();
  insp.tomma.splice(0).forEach((r) => r());
  $("ko").hidden = true;
  slappInspelning(insp);
  koInsp = null;
  meddela("");
  kvitto(lageFel
    ? "Ladda upp filen du sparade med knappen Ladda upp ljudfil, och radera den ofullständiga inspelningen i listan."
    : "Den ofullständiga inspelningen ligger kvar i listan. Ladda upp filen du sparade när Akasha Meet är igång igen, och radera den ofullständiga.");
  $("spela-in").focus();
  uppdateraLista();
}

function slappInspelning(insp) {
  if (inspelning === insp) inspelning = null;
  $("spela-in").hidden = false;
  $("valj-fil").disabled = false;
  $("kalla").disabled = false;
}

// Allt ljud ar sparat: starta transkriberingen. Svarar inte tjansten forsoker sidan igen.
async function avslutaInspelning(insp) {
  for (let forsok = 0; ; forsok++) {
    try {
      await api("POST", `/api/inspelningar/${insp.id}/klar`, { starta: true, ...insp.klarData });
      break;
    } catch (e) {
      if (!(e instanceof TjanstFel)) {
        meddela(`Inspelningen är sparad, men transkriberingen startade inte: ${e.message}`, true);
        $("ko").hidden = true;
        slappInspelning(insp);
        return;
      }
      insp.nere = true;
      insp.harVantat = true;
      insp.klarVantar = true;
      uppdateraKo(insp);
      await vanta(insp, vantetid(forsok) * 1000);
      if (insp.slappt) return;
    }
  }
  if (insp.slappt) return;
  insp.nere = false;
  insp.harVantat = false;
  insp.klarVantar = false;
  $("ko").hidden = true;
  slappInspelning(insp);
  $("titel").value = ""; // annars far nasta inspelning samma rubrik
  meddela("Inspelningen är sparad och transkriberas nu." + (insp.filDelar > 0 ? " Filen du sparade behövs inte." : ""));
  visa(insp.id);
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
  xhr.addEventListener("error", () => {
    meddela(`Uppladdningen misslyckades. ${INGEN_TJANST}`, true);
    tjanstenSvararInte();
    $("fil").value = "";
  });
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
  return kvarText((sekunder * (1 - andel)) / andel);
}

// Tid kvar som text, grovt avrundad. Samma formulering for transkriberingen och modellhamtningen.
function kvarText(kvar) {
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

// Namnfalten byggs bara om nar talarna andras (eller en annan inspelning visas). Annars skulle
// det man skriver i ett falt, och fokus, forsvinna nar visningen ritas om efter en rattning.
function renderaNamn(m) {
  const rad = $("v-namn");
  const nummer = talarnummer(m);
  if (!namnLage || namnLage.id !== m.id) {
    namnLage = { id: m.id, sparade: { ...(m.namn || {}) }, ko: Promise.resolve(), vantar: 0 };
  } else if (namnLage.vantar) {
    m.namn = { ...namnLage.sparade }; // svaret kan vara aldre an ett namn som sparas just nu
  } else {
    namnLage.sparade = { ...(m.namn || {}) };
  }
  const nyckel = `${m.id}:${nummer.join()}`;
  if (rad.dataset.nyckel === nyckel) { uppdateraLyssnaKnappar(m); return; }
  const sammaInspelning = (rad.dataset.nyckel || "").startsWith(`${m.id}:`);
  const skrivet = {};
  if (sammaInspelning) for (const f of rad.querySelectorAll("input[data-talare]")) skrivet[f.dataset.talare] = f.value;
  const fokusId = rad.contains(document.activeElement) ? document.activeElement.id : null;
  if (prov && rad.contains(prov.knapp)) stoppaProv(true);
  rad.dataset.nyckel = nyckel;
  rad.replaceChildren();
  rad.hidden = nummer.length === 0;
  if (!nummer.length) return;
  for (const nr of nummer) {
    const falt = el("input", { type: "text", id: `namn-${nr}`, maxlength: "60", autocomplete: "off",
      placeholder: `Talare ${nr}`, "data-talare": String(nr),
      value: skrivet[nr] ?? ((m.namn || {})[String(nr)] || ""),
      onblur: () => sparaNamn(nr),
      onkeydown: (e) => { if (e.key === "Enter") { e.preventDefault(); sparaNamn(nr, true); } } });
    const lyssna = el("button", { type: "button", id: `lyssna-${nr}`, class: "knapp liten-knapp lyssna",
      "data-talare": String(nr), onclick: (e) => vaxlaProv(nr, e.currentTarget) }, "▶ Lyssna");
    // Lyssna-knappen star pa etikettens rad, sa att faltet far hela bredden.
    rad.append(el("div", { class: "falt" }, el("div", { class: "namnfalt-huvud" },
      el("label", { for: `namn-${nr}`, class: farg(nr) }, `Talare ${nr} heter`), lyssna), falt));
  }
  rad.append(el("p", { id: "v-namn-kvitto", class: "namn-kvitto", role: "status" }));
  uppdateraLyssnaKnappar(m);
  if (fokusId && $(fokusId)) $(fokusId).focus({ preventScroll: true });
}

// Sparas nar man lamnar faltet eller trycker Enter. Bara det har faltet skickas med sitt nya
// varde; de andra skickas som de senast sparades, sa att det man borjat skriva i nasta falt
// inte sparas halvfardigt (och falten ritas inte om, sa att det inte forsvinner heller).
function sparaNamn(nr, igen = false) {
  const m = visadMeta;
  const falt = $(`namn-${nr}`);
  if (!m || !falt || !namnLage || namnLage.id !== m.id) return;
  const lage = namnLage;
  const nyckel = String(nr);
  const varde = falt.value.trim();
  if (varde === (lage.sparade[nyckel] || "") && !(igen && falt.dataset.fel)) return;
  lage.sparade = { ...lage.sparade, [nyckel]: varde };
  if (!varde) delete lage.sparade[nyckel]; // tomt falt: talaren heter "Talare N" igen
  m.namn = { ...lage.sparade };
  uppdateraNamnen(m); // direkt, sa att ett klick pa ett namn i texten redan visar det nya
  const namn = { ...lage.sparade };
  lage.vantar++;
  lage.ko = lage.ko.then(async () => {
    try {
      await api("POST", `/api/inspelningar/${lage.id}/namn`, namn);
      delete falt.dataset.fel;
      if (lage === namnLage) namnKvitto("Sparat");
    } catch (e) {
      falt.dataset.fel = "1"; // Enter forsoker igen, aven om namnet inte andrats
      if (lage === namnLage) namnKvitto(`Namnet sparades inte: ${e.message}`, true);
    } finally {
      lage.vantar--;
    }
  });
}

let namnKvittoTimer = null;
function namnKvitto(text, fel = false) {
  const k = $("v-namn-kvitto");
  if (!k) return;
  clearTimeout(namnKvittoTimer);
  k.textContent = text;
  k.classList.toggle("fel", fel);
  if (!fel) namnKvittoTimer = setTimeout(() => { k.textContent = ""; }, 4000); // ett kvitto, inget som ligger kvar
}

// Namnen star pa flera stallen: i texten, i forklaringen och pa Lyssna-knapparna.
function uppdateraNamnen(m) {
  for (const e of $("visning").querySelectorAll(".namn[data-talare]")) {
    const namn = namnFor(m, Number(e.dataset.talare));
    e.textContent = `${namn}:`;
    if (e.tagName === "BUTTON") e.setAttribute("aria-label", `${namn}, byt talare`);
  }
  uppdateraLyssnaKnappar(m);
}

function uppdateraLyssnaKnappar(m) {
  for (const k of $("v-namn").querySelectorAll("button.lyssna")) {
    const nr = Number(k.dataset.talare);
    const namn = namnFor(m, nr);
    const vem = namn === `Talare ${nr}` ? namn : `${namn} (Talare ${nr})`;
    const spelar = !!prov && prov.knapp === k;
    k.textContent = spelar ? "■ Stoppa" : "▶ Lyssna";
    k.setAttribute("aria-label", spelar ? `Stoppa provet på ${vem}` : `Lyssna på ${vem}`);
  }
}

// --- lyssna -------------------------------------------------------------------------------

// All uppspelning fran sidan gar har igenom. Ett pagaende rostprov avbryts, sa att dess stopp
// inte pausar det man startar nu.
function spelaFran(t) {
  stoppaProv(false);
  const a = $("v-ljud");
  a.currentTime = t;
  a.play().catch(() => { /* t.ex. om ljudet inte gar att spela */ });
}

// Ett prov pa talarens rost: den langsta repliken som inte ar osaker (finns ingen, den langsta).
function provReplik(m, nr) {
  const egna = ((m.resultat && m.resultat.segment) || []).filter((s) => s.speaker === nr);
  const sakra = egna.filter((s) => !s.osaker_talare);
  const urval = sakra.length ? sakra : egna;
  return urval.reduce((b, s) => (!b || s.end - s.start > b.end - b.start ? s : b), null);
}

function vaxlaProv(nr, knapp) {
  if (prov && prov.knapp === knapp) { stoppaProv(true); return; }
  const s = provReplik(visadMeta, nr);
  if (!s) return;
  spelaFran(s.start);
  const a = $("v-ljud");
  const detta = { knapp, start: s.start, slut: Math.min(s.end, s.start + 10) };
  // Ljudets egen tid jamfors, inte klockan: provet blir lika langt aven om ljudet laddar en stund.
  detta.timer = setInterval(() => { if (prov === detta && a.currentTime >= detta.slut) stoppaProv(true); }, 100);
  prov = detta;
  uppdateraLyssnaKnappar(visadMeta);
}

function stoppaProv(pausa) {
  const p = prov;
  if (!p) return;
  prov = null;
  clearInterval(p.timer);
  if (pausa) $("v-ljud").pause();
  if (visadMeta) uppdateraLyssnaKnappar(visadMeta);
}

// Uppskattad tid for ord k, som _tid_vid i rattning.py: andelen tecken fore ordet.
function ordTid(s, k) {
  const tecken = s.text.trim().split(/\s+/).map((o) => [...o].length + 1);
  const fore = tecken.slice(0, k).reduce((a, b) => a + b, 0);
  const alla = tecken.reduce((a, b) => a + b, 0);
  return s.start + (s.end - s.start) * (fore / Math.max(1, alla));
}

// Ett rent klick pa ett osakert ord spelar fran strax fore det. Ar ord markerade ar det en
// rattning pa gang (efterMarkering), och da spelas inget.
function klickPaOrd(e) {
  const ord = e.target.closest && e.target.closest(".osakert-ord");
  if (!ord || doljOsakraOrd || !visadMeta) return;
  const sel = window.getSelection();
  if (sel && !sel.isCollapsed) return;
  const s = visadMeta.resultat.segment[Number(ord.closest("p[data-replik]").dataset.replik)];
  if (s) spelaFran(Math.max(s.start, ordTid(s, Number(ord.dataset.ord)) - 2));
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
    const tidKnapp = el("button", { type: "button", class: "tid", "aria-label": `Lyssna från ${tid(s.start)}`,
      title: "Lyssna härifrån", onclick: () => spelaFran(s.start) }, tid(s.start));
    const p = el("p", { "data-replik": String(i), class: s.osaker_talare ? "osaker" : undefined }, tidKnapp);
    if ("speaker" in s) {
      const namn = namnFor(m, s.speaker);
      const nr = String(s.speaker);
      p.append(kanRatta
        ? el("button", { type: "button", class: `namn ${farg(s.speaker)}`, "data-talare": nr, title: "Byt talare",
          "aria-label": `${namn}, byt talare`, "aria-haspopup": "dialog",
          onclick: (e) => oppnaTalarval(e.currentTarget, i, null, null) }, `${namn}:`)
        : el("span", { class: `namn ${farg(s.speaker)}`, "data-talare": nr }, `${namn}:`));
      if (s.osaker_talare) {
        // En knapp till samma talarval som namnet: tecknet ar det som drar blicken till sig.
        p.append(kanRatta
          ? el("button", { type: "button", class: "osaker-tecken", "aria-haspopup": "dialog",
            "aria-label": "Osäker talare. Kontrollera och välj talare.",
            title: "Osäker talare: kontrollera mot ljudet och välj talare",
            onclick: (e) => oppnaTalarval(e.currentTarget, i, null, null) }, "?")
          : el("span", { class: "osaker-tecken", title: "Osäker talare: kontrollera mot ljudet" }, "?"));
      }
      // Varje ord i ett eget span, sa att markerade ord kan fa en annan talare.
      const osakra = new Set(s.osakra_ord || []);
      const text = el("span", { class: "repliktext" });
      s.text.trim().split(/\s+/).forEach((ord, k) => {
        if (k) text.append(" ");
        text.append(osakra.has(k)
          ? el("span", { "data-ord": String(k), class: "osakert-ord", title: ordTitel() }, ord)
          : el("span", { "data-ord": String(k) }, ord));
      });
      p.append(text);
    } else {
      p.append(s.text);
    }
    yta.append(p);
  });
}

// Med dolda understrykningar gar orden inte att klicka pa, och da ska titeln inte lova det.
function ordTitel() {
  return doljOsakraOrd ? undefined : "Programmet var osäkert på ordet. Klicka för att lyssna.";
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
    rad(el("span", { class: `namn ${farg(nummer[0])}`, "data-talare": String(nummer[0]) }, `${namnFor(m, nummer[0])}:`),
      "Klicka på namnet för att byta talare. Markera några ord för att byta talare på bara dem.");
  }
  if (talare) {
    rad(el("span", { class: "osaker-tecken" }, "?"),
      el("strong", {}, "Osäker talare"), ` – ${talare} ${talare === 1 ? "replik" : "repliker"}.`);
  }
  if (ord) {
    rad(el("span", { class: "osakert-ord" }, "ord"),
      el("strong", {}, "Osäkert ord"), ` – ${ord} ord som programmet var osäkert på. Klicka på ett ord för att lyssna. `,
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
  for (const ord of $("v-text").querySelectorAll(".osakert-ord")) {
    if (doljOsakraOrd) ord.removeAttribute("title");
    else ord.title = ordTitel();
  }
}

// Lage star som egen text intill knappen: "3 osaker" innan man borjat, "1 av 3" nar man star
// pa en osaker replik. Star man inte pa nagon (den man stod pa ar rattad) visas antalet igen.
function uppdateraNastaOsakra() {
  const knapp = $("v-nasta-osakra");
  const lage = $("v-osakra-lage");
  const osakra = [...document.querySelectorAll("#v-text p.osaker")].map((p) => Number(p.dataset.replik));
  knapp.hidden = lage.hidden = !osakra.length || $("v-text").hidden;
  if (knapp.hidden) { sattText(lage, ""); return; }
  const plats = osakra.indexOf(senastOsakra) + 1;
  sattText(lage, plats ? `${plats} av ${osakra.length}`
    : `${osakra.length} ${osakra.length === 1 ? "osäker" : "osäkra"}`);
}

// Ramen kring den osakra repliken man star pa. Texten ritas om efter en rattning, och da
// satts den igen.
function markeraValdOsaker() {
  document.querySelectorAll("#v-text p.vald-osaker").forEach((p) => p.classList.remove("vald-osaker"));
  const p = document.querySelector(`#v-text p.osaker[data-replik="${senastOsakra}"]`);
  if (p) p.classList.add("vald-osaker");
}

function nastaOsakra() {
  const osakra = [...document.querySelectorAll("#v-text p.osaker")];
  if (!osakra.length) return;
  const nasta = osakra.find((p) => Number(p.dataset.replik) > senastOsakra) || osakra[0];
  senastOsakra = Number(nasta.dataset.replik);
  markeraValdOsaker();
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

// tillbaka: rutan stangdes utan val (Escape, Avbryt), och fokus ska tillbaka dit den oppnades
// fran. Bara en knapp: oppnades den genom att markera ord finns inget sadant stalle.
function stangTalarval(tillbaka = false) {
  const ruta = $("talarval");
  if (ruta.hidden) return;
  const ankare = talarvalAnkare;
  talarvalAnkare = null;
  ruta.hidden = true;
  ruta.replaceChildren();
  // Oppnades rutan av en markering tas markeringen bort. Ligger den kvar oppnar nasta klick
  // pa ett namn i texten rutan for de gamla orden i stallet for for repliken.
  if (ankare && ankare.tagName !== "BUTTON") window.getSelection().removeAllRanges();
  if (tillbaka && ankare && ankare.tagName === "BUTTON" && ankare.isConnected) ankare.focus({ preventScroll: true });
}

// Under ankaret om rutan far plats dar, annars ovanfor. Aldrig utanfor fonstret och aldrig
// under kontrollraden, som ligger overst i fonstret medan man bladdrar.
function placeraTalarval(ruta, ankare) {
  const r = ankare.getBoundingClientRect();
  const overst = Math.max(8, $("v-kontrollrad").getBoundingClientRect().bottom + 6);
  const nederst = window.innerHeight - 8;
  ruta.style.maxHeight = `${Math.max(120, nederst - overst)}px`;
  const h = ruta.offsetHeight;
  let y = r.bottom + 6;
  if (y + h > nederst) {
    const ovanfor = r.top - 6 - h;
    y = ovanfor >= overst ? ovanfor : Math.max(overst, nederst - h);
  }
  const bredd = document.documentElement.clientWidth;
  ruta.style.top = `${y + window.scrollY}px`;
  ruta.style.left = `${Math.max(8, Math.min(r.left, bredd - ruta.offsetWidth - 8)) + window.scrollX}px`;
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
  ruta.append(el("button", { type: "button", class: "knapp liten-knapp", onclick: () => stangTalarval(true) }, "Avbryt"));

  ruta.hidden = false;
  talarvalAnkare = ankare;
  placeraTalarval(ruta, ankare);
  ruta.querySelector("button").focus({ preventScroll: true });
}

// Var det rattade hamnar: servern delar repliken vid den uppskattade tiden (_tid_vid i
// rattning.py) och slar ihop grannar med samma talare. En ihopslagen replik behaller den
// tidigaste starten, sa det rattade ligger i den sista repliken som borjar senast vid tiden.
function replikVid(segs, t, talare) {
  let hittad = -1, medTalare = -1;
  segs.forEach((s, k) => {
    if (s.start > t + 0.005) return;
    hittad = k;
    if (s.speaker === talare) medTalare = k;
  });
  return medTalare >= 0 && segs[medTalare].start === segs[hittad].start ? medTalare : hittad;
}

async function ratta(i, val) {
  const m = visadMeta;
  const s = m.resultat.segment[i];
  const ankare = talarvalAnkare;
  stangTalarval();
  window.getSelection().removeAllRanges();
  const t = val.alla || !val.fran ? s.start : Math.round(ordTid(s, val.fran) * 100) / 100;
  const segs = m.resultat.segment;
  const senastTid = senastOsakra >= 0 && segs[senastOsakra] ? segs[senastOsakra].start : null;
  try {
    await (namnLage && namnLage.ko); // annars kan ett namn som sparas just nu visas med sitt gamla varde
    const svar = await api("POST", `/api/inspelningar/${m.id}/talare`, { replik: i, text: s.text, ...val });
    const y = window.scrollY;
    await visa(m.id, true);
    window.scrollTo(0, y);
    const nya = visadMeta.resultat.segment;
    const mal = replikVid(nya, t, svar.talare);
    // Platsen bland de osakra foljer med: den man stod pa ar inte osaker langre, de andra kan ha flyttat.
    if (senastTid !== null) {
      senastOsakra = senastOsakra === i ? mal : replikVid(nya, senastTid, segs[senastOsakra].speaker);
      markeraValdOsaker();
      uppdateraNastaOsakra();
    }
    const namn = document.querySelector(`#v-text p[data-replik="${mal}"] button.namn`);
    if (namn) namn.focus({ preventScroll: true });
    uppdateraLista();
  } catch (e) {
    kvitto(e.message, true);
    if (ankare && ankare.tagName === "BUTTON" && ankare.isConnected) ankare.focus({ preventScroll: true });
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

function efterMarkering(e) {
  // Ett klick pa en knapp i texten (tid, namn, "?") ar ingen markering.
  if (e && e.type === "mouseup" && e.target.closest && e.target.closest("button")) return;
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
  // Stangs formularet medan fokus ar i det ska fokus tillbaka till knappen, inte till sidans borjan.
  const hadeFokus = $("v-rubrikform").contains(document.activeElement);
  $("v-rubrikform").hidden = !visa;
  $("v-byt-rubrik").setAttribute("aria-expanded", String(visa));
  if (!visa && hadeFokus) $("v-byt-rubrik").focus({ preventScroll: true });
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
$("ko-spara-fil").addEventListener("click", () => sparaLjudSomFil(koInsp));
$("ko-klar").addEventListener("click", slappEfterFil);
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
$("m-hamta").addEventListener("click", hamtaModeller);
$("m-inte-nu").addEventListener("click", inteNu);
$("m-stoppa").addEventListener("click", stoppaHamtning);
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
$("v-text").addEventListener("click", klickPaOrd);
// Ett rostprov slutar galla sa fort anvandaren sjalv pausar eller hoppar i ljudet (spelarens
// reglage, "Backa 5 s"); annars skulle provets stopp pausa det man valt att lyssna pa.
$("v-ljud").addEventListener("pause", () => stoppaProv(false));
$("v-ljud").addEventListener("emptied", () => stoppaProv(false)); // visningen stangd eller annat ljud
$("v-ljud").addEventListener("seeking", () => {
  if (prov && Math.abs($("v-ljud").currentTime - prov.start) > 0.3) stoppaProv(false);
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") stangTalarval(true); });
document.addEventListener("mousedown", (e) => {
  if ($("talarval").hidden || $("talarval").contains(e.target)) return;
  const ankare = talarvalAnkare;
  stangTalarval();
  // Klickade man pa nagot som inte tar fokus hamnar fokus annars overst pa sidan.
  setTimeout(() => {
    const fokus = document.activeElement;
    if ((!fokus || fokus === document.body) && ankare && ankare.tagName === "BUTTON" && ankare.isConnected) {
      ankare.focus({ preventScroll: true });
    }
  }, 0);
});
window.addEventListener("beforeunload", (e) => {
  if (inspelning) { e.preventDefault(); e.returnValue = ""; }
});

hamtaVal();
kollaTjanst();
kollaModeller();
uppdateraLista();
