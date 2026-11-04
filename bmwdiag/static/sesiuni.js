// Pagina „Sesiuni”: listă și detaliu, pe hash (#<id> sau #<id>/<tab>). Doar citire, fără grafice (Etapa 8).
"use strict";

const $ = (id) => document.getElementById(id);
const FILE = [
  ["rezumat", "Rezumat"], ["evenimente", "Evenimente"], ["erori", "Erori"],
  ["instantaneu", "Instantaneu la start"], ["jurnal", "Jurnal"], ["fisiere", "Fișiere"],
];
const RE_VIN = /^[A-HJ-NPR-Z0-9]{17}$/;
const RE_CHEIE_VIN = /VIN|FGNR|FAHRGEST/i;

let dict = { coloane: {}, stat: {}, joburi: {}, steaguri: {}, unitati: {}, erori_detalii: {} };
let lista = [];
let detaliu = null; // {id, date}
let tabCurent = "rezumat";
let jetonNav = 0; // ignoră răspunsurile întârziate după o navigare

// ---------- ajutoare ----------
function el(eticheta, atribute, ...copii) {
  const e = document.createElement(eticheta);
  for (const [k, v] of Object.entries(atribute || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of copii.flat()) {
    if (c === null || c === undefined || c === false) continue;
    e.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return e;
}

async function api(cale) {
  const r = await fetch(cale);
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.eroare || `Eroare ${r.status}`);
  }
  return r;
}

function eroarePagina(text) {
  const p = $("eroare-pagina");
  p.textContent = text || "";
  p.hidden = !text;
}

function dataRo(iso, cuSecunde) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/.exec(iso || "");
  if (!m) return "–";
  return `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}` + (cuSecunde ? `:${m[6] || "00"}` : "");
}

function oraRo(iso) {
  const m = /[T ](\d{2}:\d{2}:\d{2})/.exec(iso || "");
  return m ? m[1] : "–";
}

function durata(s) {
  if (s === null || s === undefined || isNaN(s)) return "–";
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  if (h) return `${h} h ${String(m).padStart(2, "0")} min`;
  if (m) return `${m} min ${String(sec).padStart(2, "0")} s`;
  return `${sec} s`;
}

function minSec(s) {
  if (s === null || s === undefined || isNaN(s)) return "–";
  const t = Math.floor(s);
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
}

function nr(v, cifre = 5) {
  if (v === null || v === undefined || v === "") return "–";
  if (typeof v !== "number") return String(v);
  if (!isFinite(v)) return "–";
  return v.toLocaleString("ro-RO", { maximumSignificantDigits: cifre });
}

function unitate(brut) {
  const u = brut === null || brut === undefined ? "" : String(brut).trim();
  return dict.unitati[u] || u;
}

function eticheta(alias) {
  const d = dict.coloane[alias];
  return d && d.eticheta ? d.eticheta : alias;
}

function unitateColoana(alias, coloane) {
  const d = dict.coloane[alias];
  if (d && d.unitate_afisata !== undefined && d.unitate_afisata !== "") return d.unitate_afisata;
  return unitate((coloane[alias] || {}).unitate);
}

function numeSteag(nume) {
  return dict.steaguri[nume] || nume;
}

function insignaConditie(c) {
  c = c || "necunoscut";
  return el("span", { class: "eticheta " + (c === "rece" || c === "cald" ? c : ""), text: c });
}

function insignaStare(stare) {
  if (stare === "în desfășurare") return el("span", { class: "eticheta verde", text: "în desfășurare" });
  if (stare === "întreruptă") return el("span", { class: "eticheta galben", text: "întreruptă" });
  return null;
}

function tabel(cap, randuri, clasa) {
  return el("div", { class: "derulare" }, el("table", { class: clasa || "tabel" },
    el("thead", {}, el("tr", {}, cap.map((c) => {
      const [text, nrCol] = Array.isArray(c) ? c : [c, false];
      return el("th", { class: nrCol ? "nr" : "" , text });
    }))),
    el("tbody", {}, randuri)));
}

function gol(text) {
  return el("p", { class: "gol", text });
}

// ---------- listă ----------
async function incarcaLista() {
  const jeton = ++jetonNav;
  eroarePagina("");
  try {
    const r = await api("/api/sesiuni");
    const d = await r.json();
    if (jeton !== jetonNav) return;
    lista = d;
  } catch (e) {
    eroarePagina("Nu pot citi lista sesiunilor: " + e.message);
    lista = [];
  }
  const sel = $("f-profil");
  const ales = sel.value;
  const profile = [...new Set(lista.map((s) => s.profil))].sort();
  sel.innerHTML = "";
  sel.append(el("option", { value: "", text: "toate" }), ...profile.map((p) => el("option", { value: p, text: p })));
  sel.value = profile.includes(ales) ? ales : "";
  deseneazaLista();
}

function deseneazaLista() {
  const fc = $("f-conditie").value, fp = $("f-profil").value, fn = $("f-nota").value.trim().toLowerCase();
  const vizibile = lista.filter((s) => (!fc || s.conditie === fc) && (!fp || s.profil === fp)
    && (!fn || (s.nota || "").toLowerCase().includes(fn)));
  const corp = $("corp-lista");
  corp.innerHTML = "";
  if (!vizibile.length) {
    corp.append(el("tr", {}, el("td", { colspan: 10, class: "gol", text: lista.length
      ? "Nicio sesiune nu se potrivește cu filtrele." : "Nu există sesiuni salvate." })));
  }
  for (const s of vizibile) {
    const steaguri = Object.entries(s.steaguri || {});
    const total = steaguri.reduce((a, [, n]) => a + n, 0);
    const titluSteaguri = steaguri.map(([n, c]) => `${numeSteag(n)}: ${c}`).join("\n");
    const c = (eticheta_, atr, ...copii) => el("td", { ...atr, "data-eticheta": eticheta_ }, ...copii);
    const tr = el("tr", { onclick: (ev) => { if (!ev.target.closest("a")) location.hash = "#" + s.id; } },
      c("Data", {}, el("a", { href: "#" + s.id, text: dataRo(s.start) })),
      c("Profil", { text: s.profil }),
      c("Condiție", {}, insignaConditie(s.conditie)),
      c("Durată", { class: "fara-rupere", text: durata(s.durata_s) }),
      c("Rânduri", { class: "nr", text: s.randuri === null || s.randuri === undefined ? "–" : nr(s.randuri, 7) }),
      c("Cicluri/s", { class: "nr", text: nr(s.cicluri_pe_s, 3) }),
      c("Steaguri", { title: titluSteaguri || null, text: total ? String(total) : "0" }),
      c("Notă", { class: "nota", text: s.nota || "" }),
      c("Motiv oprire", { text: s.motiv_oprire || "" }),
      c("Stare", { class: "stare-rand" }, insignaStare(s.stare),
        s.eroare ? el("span", { class: "eticheta rosu", title: s.eroare, text: "eroare la citire" }) : null));
    corp.append(tr);
  }
  $("numar-sesiuni").textContent = lista.length ? `${vizibile.length} din ${lista.length} sesiuni` : "";
}

// ---------- detaliu ----------
async function incarcaDetaliu(id, tab) {
  const jeton = ++jetonNav;
  eroarePagina("");
  tabCurent = FILE.some(([k]) => k === tab) ? tab : "rezumat";
  $("t-detaliu").textContent = "Se încarcă…";
  $("antet-detaliu").textContent = "";
  $("file").innerHTML = "";
  $("continut-tab").innerHTML = "";
  try {
    const t0 = performance.now();
    const d = await (await api("/api/sesiuni/" + encodeURIComponent(id))).json();
    if (jeton !== jetonNav) return;
    detaliu = { id, date: d, ms: Math.round(performance.now() - t0), jurnal: null };
  } catch (e) {
    if (jeton !== jetonNav) return;
    detaliu = null;
    $("t-detaliu").textContent = "Sesiune";
    eroarePagina(`Nu pot deschide sesiunea ${id}: ${e.message}`);
    return;
  }
  deseneazaAntet();
  deseneazaFile();
  deseneazaTab();
}

function deseneazaAntet() {
  const { id, date } = detaliu;
  const s = date.sesiune || {};
  $("t-detaliu").textContent = `${s.profil || id.split("_").slice(2).join("_")} · ${dataRo(s.start || id.replace(/^(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2}).*/, "$1T$2:$3"))}`;
  const a = $("antet-detaliu");
  a.innerHTML = "";
  a.append(insignaConditie(s.conditie), insignaStare(date.stare) || el("span", { class: "eticheta", text: "finalizată" }),
    el("span", { text: `Durată: ${durata(date.rezumat && date.rezumat.durata_s)}` }));
}

function deseneazaFile() {
  const f = $("file");
  f.innerHTML = "";
  FILE.forEach(([k, text], i) => f.append(el("button", {
    type: "button", role: "tab", id: "tab-" + k, "aria-selected": String(k === tabCurent),
    "aria-controls": "continut-tab", tabindex: k === tabCurent ? "0" : "-1", text,
    onclick: () => alegeTab(k),
    onkeydown: (ev) => {
      const pas = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0;
      if (!pas) return;
      ev.preventDefault();
      const nou = FILE[(i + pas + FILE.length) % FILE.length][0];
      alegeTab(nou);
      $("tab-" + nou).focus();
    },
  })));
}

function alegeTab(k) {
  tabCurent = k;
  history.replaceState(null, "", `#${detaliu.id}/${k}`);
  deseneazaFile();
  deseneazaTab();
}

function deseneazaTab() {
  const c = $("continut-tab");
  c.setAttribute("aria-labelledby", "tab-" + tabCurent);
  c.innerHTML = "";
  const f = { rezumat: tabRezumat, evenimente: tabEvenimente, erori: tabErori, instantaneu: tabInstantaneu,
    jurnal: tabJurnal, fisiere: tabFisiere }[tabCurent];
  c.append(...[].concat(f(detaliu.date)));
}

// --- Rezumat ---
function tabRezumat(d) {
  const s = d.sesiune || {}, st = s.statistici || {}, rz = d.rezumat || {}, col = d.coloane || {};
  const rez = [];
  const avert = [];
  if (d.stare === "în desfășurare") avert.push(["Sesiunea rulează încă; datele se văd la momentul încărcării. Apasă „Reîmprospătează”.", false]);
  if (d.stare === "întreruptă") avert.push(["Sesiunea a fost întreruptă brusc (fără oprire curată); ultimul rând poate lipsi.", false]);
  const steag = st.steaguri || {};
  if ((st.erori || 0) > 0) avert.push([`Au fost ${st.erori} erori de citire în timpul sesiunii.`, true]);
  if (steag.conexiune_pierduta) avert.push([`Conexiunea s-a pierdut de ${steag.conexiune_pierduta} ori în timpul sesiunii.`, true]);
  for (const [t, rosu] of avert) rez.push(el("p", { class: "avertisment-bloc" + (rosu ? " rosu" : ""), text: t }));

  const dl = el("dl", { class: "stare lat-dl" });
  const rand = (k, v) => dl.append(el("dt", { text: k }), el("dd", {}, v === null || v === undefined || v === "" ? "–" : v));
  rand("Profil", s.profil);
  rand("Condiție", insignaConditie(s.conditie));
  rand("Notă", s.nota);
  rand("Început", s.start ? dataRo(s.start, true) : null);
  rand("Sfârșit", s.stop ? dataRo(s.stop, true) : null);
  rand("Durată", durata(rz.durata_s));
  rand("Rânduri", rz.randuri === undefined ? null : nr(rz.randuri, 7));
  rand("Segmente (fișiere de date)", s.segmente);
  const ciclS = s.stop ? st.cicluri_pe_s : (rz.durata_s > 0 ? rz.randuri / rz.durata_s : null);
  rand("Cicluri pe secundă", ciclS === undefined || ciclS === null ? null : nr(ciclS, 3));
  rand("Motiv oprire", s.motiv_oprire);
  if (rz.tmot_start !== undefined) rand("Temperatura motorului la început / la sfârșit", `${nr(rz.tmot_start)} °C → ${nr(rz.tmot_stop)} °C`);
  rand("Sursa de date", s.sursa);
  rand("Calculator (ECU)", s.ecu);
  rez.push(el("div", { class: "sectiune" }, el("h3", { text: "Sesiunea" }), dl));

  const sg = Object.entries(steag);
  rez.push(el("div", { class: "sectiune" }, el("h3", { text: "Steaguri" }),
    sg.length ? tabel(["Steag", ["Număr", true]], sg.sort((a, b) => b[1] - a[1]).map(([n, c]) =>
      el("tr", {}, el("td", {}, numeSteag(n), n !== numeSteag(n) ? el("span", { class: "mic", text: `  (${n})` }) : null),
        el("td", { class: "nr", text: String(c) })))) : gol("Niciun steag în această sesiune.")));

  const aliasuri = Object.keys(rz.coloane || {});
  const ordine = Object.keys(dict.coloane);
  aliasuri.sort((a, b) => {
    const ia = ordine.indexOf(a), ib = ordine.indexOf(b);
    return (ia < 0 ? 1e6 : ia) - (ib < 0 ? 1e6 : ib) || a.localeCompare(b);
  });
  const randuriMm = [];
  let grupAnterior = null;
  for (const a of aliasuri) {
    const g = (dict.coloane[a] || {}).grup || "Altele";
    if (g !== grupAnterior) {
      randuriMm.push(el("tr", { class: "grup-rand" }, el("th", { colspan: 5, text: g })));
      grupAnterior = g;
    }
    const m = rz.coloane[a];
    randuriMm.push(el("tr", {},
      el("td", { title: a, text: eticheta(a) }),
      el("td", { class: "nr", text: nr(m.min) }), el("td", { class: "nr", text: nr(m.medie) }),
      el("td", { class: "nr", text: nr(m.max) }), el("td", { text: unitateColoana(a, col) })));
  }
  rez.push(el("div", { class: "sectiune" }, el("h3", { text: "Mărimi: minim / medie / maxim" }),
    aliasuri.length ? tabel(["Mărime", ["Minim", true], ["Medie", true], ["Maxim", true], "Unitate"], randuriMm)
      : gol("Sesiunea nu are rânduri de date.")));

  const joburi = Object.entries(st.joburi || {});
  rez.push(el("div", { class: "sectiune" }, el("h3", { text: "Joburi citite" }),
    joburi.length ? tabel(["Job", ["Apeluri", true], ["Erori", true], ["ms în medie", true]], joburi.map(([n, j]) =>
      el("tr", {}, el("td", { title: n, text: dict.joburi[n] || n }), el("td", { class: "nr", text: nr(j.n, 7) }),
        el("td", { class: "nr", text: nr(j.erori, 7) }), el("td", { class: "nr", text: nr(j.ms_medie, 4) }))))
      : gol("Fără statistici de joburi (sesiune neînchisă).")));
  return rez;
}

// --- Evenimente ---
let filtruEv = "";
function tabEvenimente(d) {
  const ev = d.evenimente || [];
  const tipuri = [...new Set(ev.map((e) => e.tip))];
  const sel = el("select", { id: "f-tip", onchange: (e) => { filtruEv = e.target.value; umpleEv(); } },
    el("option", { value: "", text: `toate (${ev.length})` }),
    tipuri.map((t) => el("option", { value: t, text: `${t} (${ev.filter((e) => e.tip === t).length})` })));
  sel.value = tipuri.includes(filtruEv) ? filtruEv : "";
  filtruEv = sel.value;
  const corp = el("tbody", { id: "corp-ev" });
  const radacina = [el("div", { class: "filtre" }, el("label", {}, "Tip eveniment", sel)),
    el("p", { class: "mic", id: "numar-ev", role: "status" }),
    el("div", { class: "derulare" }, el("table", { class: "tabel" },
      el("thead", {}, el("tr", {}, el("th", { class: "nr", text: "Timp" }), el("th", { text: "Ora" }),
        el("th", { text: "Tip" }), el("th", { text: "Detalii" }))), corp))];
  function umpleEv() {
    corp.innerHTML = "";
    const v = ev.filter((e) => !filtruEv || e.tip === filtruEv);
    for (const e of v) {
      const clasa = { steag: "galben", eroare: "rosu", marcaj: "verde" }[e.tip] || "";
      corp.append(el("tr", {}, el("td", { class: "nr fara-rupere", title: `${nr(e.t_rel_s)} s`, text: minSec(e.t_rel_s) }),
        el("td", { class: "fara-rupere", text: oraRo(e.t_iso) }),
        el("td", {}, el("span", { class: "eticheta " + clasa, text: e.tip })),
        el("td", { text: e.detalii })));
    }
    if (!v.length) corp.append(el("tr", {}, el("td", { colspan: 4, class: "gol", text: "Niciun eveniment." })));
    const n = document.getElementById("numar-ev");
    if (n) n.textContent = `${v.length} evenimente. „Timp” = minute:secunde de la start.`;
  }
  queueMicrotask(umpleEv);
  return radacina;
}

// --- Erori ---
function numeMoment(m) {
  if (m === "start") return "La start";
  if (m === "stop") return "La stop";
  if (/^\d+$/.test(m)) return `La interval (${Math.round(Number(m) / 60)} min)`;
  if (m.startsWith("cerere")) return "La cerere";
  return m;
}

function tabErori(d) {
  const citiri = d.erori || [];
  if (!citiri.length) return gol("Sesiunea nu are citiri de erori.");
  const rez = [];
  const noi = new Set(citiri.flatMap((c) => c.erori.filter((e) => e.nou).map((e) => e.nr))).size;
  rez.push(el("p", { class: noi ? "avertisment-bloc rosu" : "mic",
    text: noi ? `Erori apărute după start: ${noi} (marcate „NOU”).` : "Nicio eroare nouă față de citirea de la start." }));
  for (const c of citiri) {
    const sec = el("div", { class: "sectiune" },
      el("h3", {}, numeMoment(c.moment), el("span", { class: "mic", text: `  ${oraRo(c.t_iso)} · ${minSec(c.t_rel_s)} de la start` }),
        c.ok === false ? el("span", { class: "eticheta rosu", text: " citire eșuată" }) : null));
    if (!c.erori.length) sec.append(gol("Nicio eroare în memorie."));
    for (const e of c.erori) {
      const bloc = el("div", { class: "eroare-bloc" + (e.nou ? " nou" : "") },
        el("h4", {}, `Eroarea ${e.nr} (0x${Number(e.nr).toString(16).toUpperCase()}) `,
          e.nou ? el("span", { class: "eticheta rosu", text: "NOU" }) : null),
        el("p", { text: e.text || "(fără text)" }),
        e.simptom ? el("p", { class: "mic", text: "Simptom: " + e.simptom }) : null,
        e.stare ? el("p", { class: "mic", text: "Stare: " + e.stare }) : null);
      const det = detaliiEroare(e.detalii || []);
      if (det) bloc.append(det);
      sec.append(bloc);
    }
    rez.push(sec);
  }
  return rez;
}

function detaliiEroare(seturi) {
  const randuri = [];
  seturi.forEach((s, i) => {
    const parti = [];
    if (s.F_UW_KM !== undefined) parti.push(`kilometraj ${nr(s.F_UW_KM, 7)} km`);
    for (let k = 1; k <= 4; k++) {
      if (s["F_UW" + k + "_TEXT"] !== undefined) {
        parti.push(`${s["F_UW" + k + "_TEXT"]}: ${nr(s["F_UW" + k + "_WERT"])} ${unitate(s["F_UW" + k + "_EINH"])}`.trim());
      }
    }
    if (i === 0) {
      for (const [k, t] of Object.entries(dict.erori_detalii)) {
        if (["F_UW_KM", "F_UW_ANZ"].includes(k)) continue;
        if (s[k] !== undefined && s[k] !== "" && s[k] !== "--") parti.push(`${t}: ${s[k]}`);
      }
    }
    if (parti.length) randuri.push(el("li", {}, parti.join(" · ")));
  });
  if (!randuri.length) return null;
  return el("details", {}, el("summary", { text: "Condiții la apariția erorii" }),
    el("ul", {}, randuri));
}

// --- Instantaneu ---
function esteVin(cheie, val) {
  return RE_CHEIE_VIN.test(cheie) || (typeof val === "string" && RE_VIN.test(val) && /\d/.test(val) && /[A-Z]/.test(val));
}

function valoareCelula(cheie, val, unit) {
  if (typeof val === "boolean") return val ? "da" : "nu";
  if (cheie.endsWith("_EIN")) return val === 1 || val === true ? "da" : val === 0 ? "nu" : String(val);
  // doar măsurătorile (_WERT) se rotunjesc; indexurile, anii și codurile rămân exact ca în fișier
  const text = typeof val === "number" && cheie.endsWith("_WERT") ? nr(val) : String(val);
  return unit ? `${text} ${unit}` : text;
}

function tabInstantaneu(d) {
  const inst = d.instantaneu;
  if (!inst) return gol("Sesiunea nu are instantaneu la start (profilul nu cere unul sau citirea a eșuat).");
  const cartele = [];
  for (const [job, r] of Object.entries(inst.joburi || {})) {
    const randuri = [];
    (r.seturi || []).forEach((set, i) => {
      if (i > 0) randuri.push(el("tr", { class: "grup-rand" }, el("th", { colspan: 3, text: `Setul ${i + 1}` })));
      for (const [cheie, val] of Object.entries(set)) {
        if (cheie.endsWith("_EINH")) continue;
        const unit = unitate(set[cheie.replace(/_WERT$/, "_EINH")]);
        const eticheta_ = dict.stat[cheie] || cheie;
        let celula;
        if (esteVin(cheie, val)) {
          const text = String(val);
          const span = el("span", { text: "•".repeat(17) });
          const buton = el("button", { type: "button", class: "mic-buton", "aria-pressed": "false", text: "Arată",
            onclick: () => {
              const ascuns = buton.getAttribute("aria-pressed") === "false";
              span.textContent = ascuns ? text : "•".repeat(17);
              buton.setAttribute("aria-pressed", String(ascuns));
              buton.textContent = ascuns ? "Ascunde" : "Arată";
            } });
          celula = el("td", { class: "val" }, span, buton);
        } else {
          celula = el("td", { class: "val", text: valoareCelula(cheie, val, cheie.endsWith("_WERT") ? unit : "") });
        }
        randuri.push(el("tr", {}, el("td", { text: eticheta_ }), celula, el("td", { class: "tehnic", text: cheie })));
      }
    });
    const carte = el("div", { class: "carte" },
      el("h3", {}, dict.joburi[job] || job, " ",
        el("span", { class: "eticheta " + (r.ok === false ? "rosu" : "verde"), text: r.ok === false ? "eșuat" : "reușit" })),
      el("p", { class: "tehnic", text: `Job: ${job} · stare: ${r.status || "–"} · seturi: ${(r.seturi || []).length}` }),
      randuri.length ? el("div", { class: "derulare" }, el("table", { class: "tabel" }, el("tbody", {}, randuri)))
        : gol("Fără valori."));
    const tehnic = el("button", { type: "button", class: "mic-buton", "aria-pressed": "false", text: "Arată detalii tehnice",
      onclick: () => {
        const on = carte.classList.toggle("arata-tehnic");
        tehnic.setAttribute("aria-pressed", String(on));
        tehnic.textContent = on ? "Ascunde detaliile tehnice" : "Arată detalii tehnice";
      } });
    carte.insertBefore(tehnic, carte.children[1]);
    cartele.push(carte);
  }
  return [el("p", { class: "mic", text: `Citit la ${dataRo(inst.t_iso, true)}. Câmpurile cu VIN sunt ascunse până apeși „Arată”.` }),
    cartele.length ? el("div", { class: "cartele" }, cartele) : gol("Instantaneul e gol.")];
}

// --- Jurnal ---
function tabJurnal() {
  const zona = el("pre", { class: "text-jurnal", tabindex: "0", "aria-label": "Jurnalul sesiunii" }, "Se încarcă…");
  const numar = el("p", { class: "mic", role: "status" });
  const cauta = el("input", { type: "search", placeholder: "caută în jurnal", "aria-label": "Caută în jurnal" });
  const id = detaliu.id;
  function arata() {
    const j = detaliu && detaliu.id === id ? detaliu.jurnal : null;
    if (j === null) return;
    const q = cauta.value.trim().toLowerCase();
    const linii = j.split(/\r?\n/);
    const v = q ? linii.filter((l) => l.toLowerCase().includes(q)) : linii;
    const taiat = v.length > 5000;
    zona.textContent = v.length ? v.slice(0, 5000).join("\n") : "Nicio linie.";
    numar.textContent = `${v.length} din ${linii.length} linii` + (taiat ? " (se afișează primele 5000; restrânge căutarea)" : "");
  }
  cauta.addEventListener("input", arata);
  if (detaliu.jurnal !== null) queueMicrotask(arata);
  else {
    api(`/api/sesiuni/${encodeURIComponent(id)}/jurnal`).then((r) => r.text()).then((t) => {
      if (detaliu && detaliu.id === id) { detaliu.jurnal = t; arata(); }
    }).catch((e) => { zona.textContent = "Nu pot citi jurnalul: " + e.message; });
  }
  return [el("div", { class: "filtre" }, el("label", {}, "Căutare", cauta)), numar, zona];
}

// --- Fișiere ---
function marime(b) {
  if (b < 1024) return `${b} B`;
  if (b < 1048576) return `${(b / 1024).toLocaleString("ro-RO", { maximumFractionDigits: 1 })} KB`;
  return `${(b / 1048576).toLocaleString("ro-RO", { maximumFractionDigits: 2 })} MB`;
}

function tabFisiere(d) {
  const id = encodeURIComponent(d.id);
  const mesaj = el("span", { class: "mic", role: "status" });
  const copiaza = el("button", { type: "button", text: "Copiază calea", onclick: async () => {
    try { await navigator.clipboard.writeText(d.folder); mesaj.textContent = "Copiat."; }
    catch (e) { mesaj.textContent = "Nu pot copia automat; selectează calea și copiaz-o."; }
  } });
  return [
    el("div", { class: "sectiune" }, el("h3", { text: "Folderul sesiunii" }),
      el("div", { class: "cale-btn" }, el("code", { text: d.folder }), copiaza, mesaj)),
    el("div", { class: "sectiune" }, el("h3", { text: "Fișiere" }),
      tabel(["Nume", ["Dimensiune", true], "Descărcare"], (d.fisiere || []).map((f) => el("tr", {},
        el("td", { text: f.nume }), el("td", { class: "nr", text: marime(f.bytes) }),
        el("td", {}, f.descarcabil ? el("a", { href: `/api/sesiuni/${id}/fisier/${encodeURIComponent(f.nume)}`,
          download: f.nume, text: "Descarcă" }) : "–"))))),
  ];
}

// ---------- navigare ----------
function ruta() {
  const h = decodeURIComponent(location.hash.replace(/^#/, ""));
  const [id, tab] = h.split("/");
  if (!id) {
    $("vedere-detaliu").hidden = true;
    $("vedere-lista").hidden = false;
    document.title = "Sesiuni – Logger BMW E90";
    detaliu = null;
    incarcaLista();
    return;
  }
  $("vedere-lista").hidden = true;
  $("vedere-detaliu").hidden = false;
  document.title = "Sesiune – Logger BMW E90";
  window.scrollTo(0, 0);
  incarcaDetaliu(id, tab);
}

async function porneste() {
  try {
    const d = await (await fetch("/nume_ro.json")).json();
    dict = { ...dict, ...d };
  } catch (e) { /* fără dicționar: se afișează numele brute */ }
  for (const id of ["f-conditie", "f-profil"]) $(id).addEventListener("change", deseneazaLista);
  $("f-nota").addEventListener("input", deseneazaLista);
  $("reimprospateaza-lista").addEventListener("click", incarcaLista);
  $("reimprospateaza-detaliu").addEventListener("click", () => { if (detaliu) incarcaDetaliu(detaliu.id, tabCurent); });
  $("inapoi").addEventListener("click", (ev) => { ev.preventDefault(); location.hash = ""; });
  window.addEventListener("hashchange", ruta);
  ruta();
}

porneste();
