/* Dibuja un widget con HTML/CSS. Lo usan dos sitios, para que se vean IDENTICOS:
 *   - el editor del portal       -> mode "edit"  (los objetos pesados salen como marcadores)
 *   - las ventanas del escritorio -> mode "view"  (camara, PDF, atajos... funcionan de verdad)
 * Nunca se usa innerHTML con datos del usuario: todo va por textContent / atributos. */
(function (g) {
  "use strict";
  // palabras de {saludo}/{dia}/{fecha} segun el idioma (window.HUB_LANG: es | en | pt | pi); por defecto español
  const LANGS = {
    es: { dias: ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"],
          meses: ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
          sal: ["buenos días", "buenas tardes", "buenas noches"] },
    en: { dias: ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"],
          meses: ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
          sal: ["good morning", "good afternoon", "good evening"] },
    pt: { dias: ["domingo", "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado"],
          meses: ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
          sal: ["bom dia", "boa tarde", "boa noite"] },
    pi: { dias: ["domingo de ron", "lunes de grog", "martes de abordaje", "miércoles de botín", "jueves de tormenta", "viernes de tesoro", "sábado de taberna"],
          meses: ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
          sal: ["¡Buen día, marinero!", "¡Buena tarde, grumete!", "¡Buena noche, lobo de mar!"] },
  };
  const INTERACTIVE = ["shortcut", "website", "document"];
  const pad = n => String(n).padStart(2, "0");

  function builtins() {
    const d = new Date(), h = d.getHours(), L = LANGS[g.HUB_LANG] || LANGS.es;
    const v = {
      saludo: h < 12 ? L.sal[0] : h < 20 ? L.sal[1] : L.sal[2],
      hora: pad(h) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds()),
      fecha: d.getDate() + " " + L.meses[d.getMonth()] + " " + d.getFullYear(),
      dia: L.dias[d.getDay()],
    };
    // alias para escribirlos en otros idiomas: {greeting} {time} {date} {day} / {saudacao} {data}
    v.greeting = v.saudacao = v.saludo; v.time = v.hora; v.date = v.data = v.fecha; v.day = v.dia;
    return v;
  }
  // {nombre} -> valor; lo desconocido se deja tal cual para que el error se vea
  function expand(text, ctx) {
    return String(text).replace(/\{([^{}]+)\}/g, (m, k) => {
      const v = ctx[k.trim().toLowerCase()];
      return v === undefined ? m : v;
    });
  }
  function rgba(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return "rgba(" + (n >> 16 & 255) + "," + (n >> 8 & 255) + "," + (n & 255) + "," + a + ")";
  }
  function el(tag, css, text) {
    const e = document.createElement(tag);
    if (css) e.style.cssText = css;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function assetUrl(src, base) { return src.startsWith("asset:") ? base + "/asset/" + src.slice(6) : src; }
  function host(url) { try { return new URL(url).hostname; } catch (e) { return url; } }
  const isInteractive = def => (def.objects || []).some(o => INTERACTIVE.includes(o.type));

  function placeholder(icon, label) {
    const p = el("div", "width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;" +
      "background:rgba(0,0,0,.25);color:#fff;font:14px Segoe UI,sans-serif;text-align:center;gap:4px;overflow:hidden");
    p.append(el("div", "font-size:28px", icon), el("div", "padding:0 8px;word-break:break-all", label));
    return p;
  }

  /* render(root, def, opts): opts = { mode, margin, assetBase, ctx: () => ({nombre: valor}), iframes }
     Devuelve { tick() } para refrescar los textos (hora, variables) sin reconstruir nada. */
  function render(root, def, opts) {
    opts = opts || {};
    const M = opts.margin || 0, edit = opts.mode === "edit", base = opts.assetBase || "";
    const ctxFn = opts.ctx || (() => ({}));
    root.textContent = "";
    root.style.cssText = "position:relative;width:" + (def.w + 2 * M) + "px;height:" + (def.h + 2 * M) + "px";
    const box = el("div", "position:absolute;box-sizing:border-box;overflow:hidden;left:" + M + "px;top:" + M + "px;width:" +
      def.w + "px;height:" + def.h + "px;border-radius:" + def.radius + "px;border:" + def.borderw + "px solid " + def.border);
    // El fondo va en su propia capa para poder hacerle un hueco donde el escritorio dibuja una web real:
    // esa web queda por debajo de esta página y, sin hueco, el fondo translúcido la oscurecería.
    const fill = rgba(def.bg, def.opacity / 100);
    const holes = edit || opts.iframes ? [] : (def.objects || []).filter(o => o.type === "website" && o.url);
    if (!holes.length) box.style.background = fill;
    else {
      // sin máscaras CSS (rompen el video): se pinta el fondo en celdas que dejan libres los huecos
      const W = def.w - 2 * def.borderw, H = def.h - 2 * def.borderw;
      const cut = (lo, hi, v) => Math.max(lo, Math.min(hi, v));
      const xs = [...new Set([0, W, ...holes.flatMap(o => [cut(0, W, o.x), cut(0, W, o.x + o.w)])])].sort((a, b) => a - b);
      const ys = [...new Set([0, H, ...holes.flatMap(o => [cut(0, H, o.y), cut(0, H, o.y + o.h)])])].sort((a, b) => a - b);
      for (let i = 0; i < xs.length - 1; i++) for (let j = 0; j < ys.length - 1; j++) {
        const cx = (xs[i] + xs[i + 1]) / 2, cy = (ys[j] + ys[j + 1]) / 2;
        if (holes.some(o => cx > o.x && cx < o.x + o.w && cy > o.y && cy < o.y + o.h)) continue;
        box.append(el("div", "position:absolute;left:" + xs[i] + "px;top:" + ys[j] + "px;width:" + (xs[i + 1] - xs[i]) + "px;height:" + (ys[j + 1] - ys[j]) + "px;background:" + fill));
      }
    }
    // la sombra va en un hermano para que overflow:hidden de la caja no la recorte
    const shadow = el("div", "position:absolute;left:" + M + "px;top:" + M + "px;width:" + def.w + "px;height:" + def.h +
      "px;border-radius:" + def.radius + "px;" + (def.shadow ? "box-shadow:0 6px " + def.shadow + "px rgba(0,0,0,.55)" : ""));
    root.append(shadow, box);
    const texts = [];

    for (const o of def.objects || []) {
      const c = el("div", "position:absolute;box-sizing:border-box;left:" + o.x + "px;top:" + o.y + "px;width:" + o.w + "px;height:" + o.h + "px;overflow:hidden");
      c.dataset.oid = o.id;
      if (edit) c.style.userSelect = "none";

      if (o.type === "text") {
        c.style.cssText += ";display:flex;flex-direction:column;justify-content:" +
          (o.valign === "middle" ? "center" : o.valign === "bottom" ? "flex-end" : "flex-start") +
          ";text-align:" + o.align + ";color:" + o.color + ";font:" + (o.italic ? "italic " : "") + (o.bold ? "bold " : "") +
          o.size + "px/1.25 '" + o.font + "',sans-serif;white-space:pre-wrap;word-break:break-word";
        const span = el("span");
        c.append(span);
        texts.push([span, o.text]);
      } else if (o.type === "image") {
        const url = o.src ? assetUrl(o.src, base) : "";
        if (url) {
          const i = el("img", "width:100%;height:100%;object-fit:" + o.fit + ";border-radius:" + o.radius + "px;display:block");
          i.src = url; i.draggable = false;
          c.append(i);
        } else c.append(placeholder("🖼️", "sin imagen"));
      } else if (o.type === "document") {
        if (edit || !o.asset) c.append(placeholder(o.kind === "pdf" ? "📕" : "📄", o.name || "sin documento"));
        else if (o.kind === "pdf") {
          const e = el("embed", "width:100%;height:100%;border:0");
          e.type = "application/pdf"; e.src = base + "/asset/" + o.asset + "#toolbar=0&navpanes=0";
          c.append(e);
        } else {
          c.style.overflow = "auto";
          const pre = el("pre", "margin:0;padding:6px;white-space:pre-wrap;word-break:break-word;color:" + o.color + ";font:" + o.size + "px/1.35 'Segoe UI',sans-serif", "cargando…");
          c.append(pre);
          fetch(base + "/asset/" + o.asset).then(r => r.text()).then(t => { pre.textContent = t; }).catch(() => { pre.textContent = "no se pudo cargar el documento"; });
        }
      } else if (o.type === "camera") {
        c.style.borderRadius = o.radius + "px";
        if (edit) c.append(placeholder("📷", o.device ? "cámara: " + o.device : "cámara predeterminada"));
        else {
          const v = el("video", "width:100%;height:100%;object-fit:cover;background:#000" + (o.mirror ? ";transform:scaleX(-1)" : ""));
          v.autoplay = true; v.muted = true; v.playsInline = true;
          c.append(v);
          const fail = why => { console.error("camara: " + why); c.textContent = ""; c.append(placeholder("🚫", "cámara no disponible")); };
          if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) fail("sin soporte");
          else (async () => {
            let s = await navigator.mediaDevices.getUserMedia({ video: true });   // da el permiso y los nombres de las cámaras
            const devs = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "videoinput");
            console.log("camara: disponibles = " + devs.map(d => d.label).join(" | "));   // queda en widgets.log
            const want = (o.device || "").trim().toLowerCase();
            const pick = want && devs.find(d => d.label.toLowerCase().includes(want));
            if (pick && s.getVideoTracks()[0].getSettings().deviceId !== pick.deviceId) {
              s.getTracks().forEach(t => t.stop());
              await new Promise(r => setTimeout(r, 600));   // deja que la primera cámara (p. ej. una capturadora) se libere
              s = await navigator.mediaDevices.getUserMedia({ video: { deviceId: { exact: pick.deviceId } } });
            } else if (want && !pick) console.error("camara: no hay ninguna que contenga «" + o.device + "»; uso la predeterminada");
            v.srcObject = s;
            const tr = s.getVideoTracks()[0];
            console.log("camara: usando «" + tr.label + "» estado=" + tr.readyState + " silenciada=" + tr.muted);
            tr.onmute = () => console.log("camara: la pista se silenció (¿otra app la usa o tiene tapa de privacidad?)");
            tr.onunmute = () => console.log("camara: la pista volvió a emitir");
            tr.onended = () => console.error("camara: la pista terminó");
            v.play().catch(e => console.error("camara: play " + e.name));          })().catch(e => fail(e.name + " " + e.message));
        }
      } else if (o.type === "website") {
        c.style.borderRadius = o.radius + "px";
        if (edit || !opts.iframes) {
          // en el escritorio, la ventana nativa del agente dibuja la web encima de este hueco
          if (edit) c.append(placeholder("🌐", o.url ? host(o.url) : "sin dirección"));
        } else if (o.url) {
          const f = el("iframe", "width:100%;height:100%;border:0;background:#fff");
          f.src = o.url;
          c.append(f);
        }
      } else if (o.type === "shortcut") {
        const b = el("button", "width:100%;height:100%;border:0;cursor:pointer;font:600 " + o.size + "px 'Segoe UI',sans-serif;background:" +
          o.bg + ";color:" + o.color + ";border-radius:" + o.radius + "px", o.label || "acceso directo");
        if (!edit) b.addEventListener("click", () => { location.href = "hubopen://go?t=" + encodeURIComponent(o.target); });
        c.append(b);
      }
      box.append(c);
    }

    function tick() {
      const ctx = Object.assign(builtins(), ctxFn());
      for (const [span, text] of texts) {
        const t = expand(text, ctx);
        if (span.textContent !== t) span.textContent = t;
      }
    }
    tick();
    return { tick, box };
  }

  g.HubWidget = { render, expand, builtins, isInteractive, INTERACTIVE };
})(window);
