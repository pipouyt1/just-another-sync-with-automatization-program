"""Genera las traducciones de todos los clientes a partir de las tablas tools/i18n_*.py:

  portal y editor   -> hub/i18n.js                        (tablas A y B)
  agente de Windows -> dentro de hub/agent.py             (tabla C, entre las marcas <i18n-agente>)
  app de Android    -> android/app/src/main/assets/i18n.json (tabla D)
  instalador        -> dentro de installer/hub_setup.py   (tabla E, entre las marcas <i18n-instalador>)

    python tools/build_i18n.py

Cada fila es (español, inglés, portugués, pirata). Las claves se comparan sin distinguir mayúsculas."""
import importlib, json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUB = HERE.parent
sys.path.insert(0, str(HERE))


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def table(*mods):
    data = {"en": {}, "pt": {}, "pi": {}}
    n = 0
    for name in mods:
        m = importlib.import_module(name)
        for var in dir(m):
            if len(var) == 1 and var.isupper() and isinstance(getattr(m, var), list):
                for es, en, pt, pi in getattr(m, var):
                    k = norm(es)
                    data["en"][k], data["pt"][k], data["pi"][k] = en, pt, pi
                    n += 1
    return data, n


def dumps(d):
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def engine(data):
    return (HERE / "i18n_engine.js").read_text(encoding="utf8").replace("/*DATA*/{}", dumps(data))


def inject(path, tag, body):
    s = path.read_text(encoding="utf8")
    a, b = f"# <{tag}>", f"# </{tag}>"
    i, j = s.index(a) + len(a), s.index(b)
    path.write_text(s[:i] + "\n" + body + "\n" + s[j:], encoding="utf8")


def main():
    d, n = table("i18n_a", "i18n_b", "i18n_f", "i18n_g")
    (HUB / "i18n.js").write_text(engine(d), encoding="utf8")
    print(f"portal: {n} filas -> i18n.js")

    d, n = table("i18n_c")
    js = engine(d)
    assert "'''" not in js
    inject(HUB / "agent.py", "i18n-agente", f"I18N_DATA = {dumps(d)!r}\nI18N_JS = r'''{js}'''")
    print(f"agente: {n} filas -> agent.py")

    d, n = table("i18n_d")
    out = HUB.parent / "android" / "app" / "src" / "main" / "assets"
    out.mkdir(parents=True, exist_ok=True)
    (out / "i18n.json").write_text(dumps(d), encoding="utf8")
    print(f"android: {n} filas -> assets/i18n.json")

    d, n = table("i18n_e")
    inject(HUB / "installer" / "hub_setup.py", "i18n-instalador", f"I18N_DATA = {dumps(d)!r}")
    print(f"instalador: {n} filas -> hub_setup.py")


if __name__ == "__main__":
    main()
