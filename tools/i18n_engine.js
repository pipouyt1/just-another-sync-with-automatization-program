/* Traduce el sitio: español (original), inglés, portugués y pirata.
 * El texto del programa está escrito en español; aquí se busca cada texto (sin distinguir mayúsculas) en la tabla del idioma
 * elegido y se sustituye. Funciona sobre el DOM (incluido lo que se crea después) y sobre toast/confirm.
 * Los datos del usuario (nombres de variables, equipos, etc.) no se tocan. Generado por tools/build_i18n.py. */
(function (g) {
  "use strict";
  const LANGS = ["es", "en", "pt", "pi"];
  const NAMES = { es: "Español", en: "English", pt: "Português", pi: "Pirata ☠" };
  const DATA = /*DATA*/{};
  const norm = s => String(s).replace(/\s+/g, " ").trim().toLowerCase();
  const pats = {};
  let lang = "es";
  const missing = new Set();

  function compile(l) {
    if (pats[l]) return pats[l];
    const out = pats[l] = [];
    const d = DATA[l] || {};
    for (const k in d) {
      if (!/\{\d\}/.test(k)) continue;
      const esc = k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\\\{(\d)\\\}/g, "(.+?)");
      out.push([new RegExp("^" + esc + "$", "i"), d[k]]);
    }
    out.sort((a, b) => b[0].source.length - a[0].source.length);
    return out;
  }

  /* tr: traduce un texto completo; si no hay traducción devuelve el mismo texto */
  function tr(s) {
    if (lang === "es" || s == null) return s;
    s = String(s);
    const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(s), core = m[2].replace(/\s+/g, " ");
    if (!core) return s;
    const d = DATA[lang] || {};
    const n = core.toLowerCase();
    if (Object.prototype.hasOwnProperty.call(d, n)) return m[1] + d[n] + m[3];
    for (const [re, t] of compile(lang)) {
      const x = re.exec(core);
      if (x) return m[1] + t.replace(/\{(\d)\}/g, (_, i) => x[+i + 1] ?? "") + m[3];
    }
    return s;
  }

  const SKIP = ".vname,.vval,.dname,.wt,.u,.sh span,.pkrow span,.tok b,.tok i,[translate=no],script,style,textarea,code,pre,#stage";
  const ATTRS = ["placeholder", "title", "aria-label", "alt"];
  const skipEl = el => !el || (el.closest && el.closest(SKIP));
  const hasWords = s => /[A-Za-zÀ-ÿ]{3,}/.test(s);

  function doText(n) {
    const p = n.parentElement;
    if (!p || skipEl(p)) return;
    const meta = n.__i18n;
    const src = meta && n.nodeValue === meta.out ? meta.src : n.nodeValue;
    const out = lang === "es" ? src : tr(src);
    if (out !== n.nodeValue) n.nodeValue = out;
    n.__i18n = { src, out };
    if (lang !== "es" && out === src && hasWords(src)) missing.add(src.trim());
  }

  function doAttr(el, a) {
    if (skipEl(el)) return;
    const v = el.getAttribute(a);
    if (v == null) return;
    const meta = (el.__i18na = el.__i18na || {})[a];
    const src = meta && v === meta.out ? meta.src : v;
    const out = lang === "es" ? src : tr(src);
    if (out !== v) el.setAttribute(a, out);
    el.__i18na[a] = { src, out };
  }

  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) return doText(root);
    if (root.nodeType !== 1) return;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    let n = root.nodeType === 1 ? root : w.nextNode();
    const visit = x => {
      if (x.nodeType === 3) doText(x);
      else for (const a of ATTRS) if (x.hasAttribute && x.hasAttribute(a)) doAttr(x, a);
    };
    visit(root);
    while ((n = w.nextNode())) visit(n);
  }

  let obs = null;
  function start() {
    if (obs || !document.body) return;
    obs = new MutationObserver(ms => {
      for (const m of ms) {
        if (m.type === "childList") m.addedNodes.forEach(walk);
        else if (m.type === "characterData") doText(m.target);
        else if (m.type === "attributes") doAttr(m.target, m.attributeName);
      }
    });
    obs.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    walk(document.body);
  }

  function apply() {
    document.documentElement.setAttribute("lang", lang === "pi" ? "es" : lang);
    document.documentElement.setAttribute("data-lang", lang);
    g.HUB_LANG = lang;
    if (document.body) walk(document.body);
    document.title = lang === "es" ? "hub" : tr("hub");
  }

  function detect() {
    if (LANGS.includes(g.HUB_FORCE_LANG)) return g.HUB_FORCE_LANG;               // lo fija el agente de Windows
    try { if (g.HubApp && g.HubApp.lang && LANGS.includes(g.HubApp.lang())) return g.HubApp.lang(); } catch (e) { /* ignorar */ }   // la app de Android manda
    try {
      const s = localStorage.getItem("lang");
      if (LANGS.includes(s)) return s;
    } catch (e) { /* sin almacenamiento */ }
    for (const l of navigator.languages || [navigator.language || "es"]) {
      const c = String(l).slice(0, 2).toLowerCase();
      if (c === "en" || c === "pt" || c === "es") return c;
    }
    return "es";
  }

  function setLang(l, save) {
    if (!LANGS.includes(l)) return;
    lang = l;
    if (save !== false) try { if (g.HubApp && g.HubApp.setLang) g.HubApp.setLang(l); } catch (e) { /* ignorar */ }
    if (save !== false) try { localStorage.setItem("lang", l); } catch (e) { /* ignorar */ }
    apply();
    (g.HubI18n.listeners || []).forEach(f => { try { f(l); } catch (e) { /* ignorar */ } });
  }

  const locale = () => ({ es: "es", en: "en", pt: "pt-BR", pi: "es" }[lang]);

  // confirm() y alert() de texto fijo
  for (const f of ["confirm", "alert"]) {
    const orig = g[f] && g[f].bind(g);
    if (orig) g[f] = m => orig(tr(m));
  }

  lang = detect();
  g.HUB_LANG = lang;
  g.HubI18n = { tr, T: tr, setLang, lang: () => lang, LANGS, NAMES, locale, missing, listeners: [], data: DATA };
  document.documentElement.setAttribute("data-lang", lang);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => { apply(); start(); });
  else { apply(); start(); }
})(window);
