package app.hub.phone

import android.app.Activity
import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.RemoteViews
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.button.MaterialButton
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Los widgets de la pantalla de inicio: el mismo widget del editor, dibujado como imagen con el mismo motor (widget.js). */
class HubWidgetProvider : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        ids.forEach { WidgetRenderer.enqueue(context.applicationContext, it) }
    }

    override fun onDeleted(context: Context, ids: IntArray) {
        Store.forgetWidgets(context, ids)
    }
}

object WidgetRenderer {
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor()
    private var lastAll = 0L

    /** Tipos que no se pueden dibujar en una imagen estática: camara, web real, PDF y atajos se omiten. */
    private const val PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:transparent;overflow:hidden}</style></head><body><div id="root"></div>
<script>window.HUB_LANG = "__LANG__"</script>
<script>__JS__</script>
<script>
const S = __STATE__, DEF = __DEF__, NAME = __NAME__;
const UNIT = {ram:"%",cpu:"%",uptime:" h",steam_hours:" h",steam_hours2w:" h",battery:"%",heart_rate:" lpm",sleep_hours:" h",distance_km:" km",calories:" kcal"};
function fmt(v) {
  if (v.kind != "auto") return v.value || "";
  if (!v.online) return __OFFLINE__;
  if (v.value == null) return "—";
  if (v.metric == "apptime") return v.value >= 60 ? Math.floor(v.value / 60) + " h " + v.value % 60 + " min" : v.value + " min";
  return v.value + (UNIT[v.metric] || "");
}
function ctx() {
  const c = {usuario: S.me.user, pc: NAME};
  for (const v of S.variables) if (!v.mine) { const k = (v.name + "").trim().toLowerCase(); if (c[k] === undefined) c[k] = fmt(v); c[(v.owner + "." + v.name).toLowerCase()] = fmt(v); }
  for (const v of S.variables) if (v.mine) c[(v.name + "").trim().toLowerCase()] = fmt(v);
  return c;
}
DEF.objects = (DEF.objects || []).filter(o => o.type == "text" || (o.type == "image" && o.src) || (o.type == "document" && o.asset && o.kind != "pdf"));
HubWidget.render(document.getElementById("root"), DEF, {mode: "view", margin: 0, assetBase: "__BASE__", ctx: ctx, iframes: false});
window.__ready = () => Array.from(document.images).every(i => i.complete) &&
  !Array.from(document.querySelectorAll("pre")).some(p => p.textContent == "cargando…");
</script></body></html>"""

    fun refreshAll(c: Context, minGapMs: Long = 0) {
        val now = System.currentTimeMillis()
        if (now - lastAll < minGapMs) return
        lastAll = now
        val mgr = AppWidgetManager.getInstance(c)
        mgr.getAppWidgetIds(ComponentName(c, HubWidgetProvider::class.java)).forEach { enqueue(c.applicationContext, it) }
    }

    fun hasWidgets(c: Context) =
        AppWidgetManager.getInstance(c).getAppWidgetIds(ComponentName(c, HubWidgetProvider::class.java)).isNotEmpty()

    fun enqueue(c: Context, id: Int) {
        worker.execute {
            try {
                renderOne(c, id)
            } catch (e: Exception) {
                show(c, id, "no se pudo dibujar el widget (${e.javaClass.simpleName})")
            }
        }
    }

    private fun show(c: Context, id: Int, msg: String?, bmp: Bitmap? = null) {
        val rv = RemoteViews(c.packageName, R.layout.widget_view)
        if (bmp != null) {
            rv.setImageViewBitmap(R.id.img, bmp)
            rv.setViewVisibility(R.id.msg, View.GONE)
        } else {
            rv.setTextViewText(R.id.msg, msg?.let { L.t(c, it) })
            rv.setViewVisibility(R.id.msg, View.VISIBLE)
        }
        val open = PendingIntent.getActivity(c, 0, Intent(c, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        rv.setOnClickPendingIntent(R.id.root, open)
        AppWidgetManager.getInstance(c).updateAppWidget(id, rv)
    }

    private fun widgetJs(c: Context): String? {
        val f = File(c.filesDir, "widget.js")
        if (!f.exists() || System.currentTimeMillis() - f.lastModified() > 600_000) {
            try {
                Api.http.newCall(Request.Builder().url(Store.url(c) + "/widget.js").build()).execute().use {
                    if (it.isSuccessful) f.writeText(it.body!!.string())
                }
            } catch (e: Exception) {
            }
        }
        return if (f.exists()) f.readText() else null
    }

    private fun renderOne(c: Context, id: Int) {
        val wid = Store.widgetFor(c, id)
        if (wid < 0) return show(c, id, "toca para elegir un widget")
        if (Store.token(c) == null) return show(c, id, "abre la app e inicia sesión")
        val st = StateStore.get(c) ?: return show(c, id, "abre la app para cargar tus widgets")
        val ws = st.optJSONArray("widgets")
        var def: JSONObject? = null
        for (i in 0 until (ws?.length() ?: 0)) if (ws!!.getJSONObject(i).optInt("id") == wid) def = ws.getJSONObject(i).getJSONObject("data")
        if (def == null) return show(c, id, "este widget ya no existe: vuelve a colocarlo")
        val js = widgetJs(c) ?: return show(c, id, "no se pudo descargar el motor de widgets")

        val w = def.optInt("w", 300)
        val h = def.optInt("h", 150)
        var scale = 2.0
        while (scale > 1.0 && w * scale * h * scale > 1_200_000) scale -= 0.25
        val pw = Math.round(w * scale).toInt()
        val ph = Math.round(h * scale).toInt()
        val esc = { j: Any -> j.toString().replace("</", "<\\/") }
        val html = PAGE.replace("__JS__", js.replace("</script", "<\\/script"))
            .replace("__STATE__", esc(JSONObject().put("me", st.optJSONObject("me")).put("variables", st.optJSONArray("variables"))))
            .replace("__DEF__", esc(def)).replace("__NAME__", JSONObject.quote(android.os.Build.MODEL))
            .replace("__LANG__", L.lang(c)).replace("__OFFLINE__", JSONObject.quote(L.t(c, "sin conexión")))
            .replace("__BASE__", Store.url(c))

        val done = CountDownLatch(1)
        var out: Bitmap? = null
        main.post {
            val wv = WebView(c)
            fun finish(b: Bitmap?) {
                out = b
                wv.destroy()
                done.countDown()
            }
            try {
                wv.setLayerType(View.LAYER_TYPE_SOFTWARE, null)
                wv.setBackgroundColor(0)
                wv.settings.javaScriptEnabled = true
                wv.setInitialScale((scale * 100).toInt())
                wv.measure(View.MeasureSpec.makeMeasureSpec(pw, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(ph, View.MeasureSpec.EXACTLY))
                wv.layout(0, 0, pw, ph)
                var tries = 0
                fun capture() {
                    val b = Bitmap.createBitmap(pw, ph, Bitmap.Config.ARGB_8888)
                    wv.draw(Canvas(b))
                    finish(b)
                }
                fun poll() {
                    wv.evaluateJavascript("window.__ready&&window.__ready()") { r ->
                        if (r == "true" || ++tries >= 12) main.postDelayed({ capture() }, 250) else main.postDelayed({ poll() }, 400)
                    }
                }
                wv.webViewClient = object : WebViewClient() {
                    override fun onPageFinished(view: WebView, url: String) = poll()
                }
                wv.loadDataWithBaseURL(Store.url(c) + "/", html, "text/html", "utf-8", null)
            } catch (e: Exception) {
                finish(null)
            }
        }
        if (!done.await(25, TimeUnit.SECONDS)) return show(c, id, "el widget tardó demasiado en dibujarse")
        show(c, id, if (out == null) "no se pudo dibujar el widget" else null, out)
    }
}

/** Al colocar el widget en la pantalla de inicio: elegir cuál de tus widgets del hub mostrar. */
class WidgetConfigActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setResult(Activity.RESULT_CANCELED)
        val appId = intent?.extras?.getInt(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID)
            ?: AppWidgetManager.INVALID_APPWIDGET_ID
        if (appId == AppWidgetManager.INVALID_APPWIDGET_ID) return finish()
        Motion.bars(this)

        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(56, 120, 56, 56)
        }
        val title = TextView(this).apply {
            text = L.t(this@WidgetConfigActivity, "elige un widget")
            textSize = 30f
            setTypeface(typeface, android.graphics.Typeface.BOLD)
            setPadding(0, 0, 0, 32)
        }
        col.addView(title)
        val st = StateStore.get(this)
        val ws = st?.optJSONArray("widgets")
        if (Store.token(this) == null || st == null || ws == null) {
            col.addView(note(L.t(this, "todavía no hay datos: abre la app, inicia sesión y espera unos segundos; luego vuelve a colocar el widget.")))
        } else if (ws.length() == 0) {
            col.addView(note(L.t(this, "no tienes widgets: crea uno en el portal (pestaña widgets).")))
        } else {
            for (i in 0 until ws.length()) {
                val w = ws.getJSONObject(i)
                col.addView(MaterialButton(this, null, com.google.android.material.R.attr.materialButtonOutlinedStyle).apply {
                    text = w.optString("name")
                    isAllCaps = false
                    textSize = 17f
                    layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 168).apply { bottomMargin = 24 }
                    setOnClickListener {
                        Store.setWidgetFor(this@WidgetConfigActivity, appId, w.optInt("id"))
                        WidgetRenderer.enqueue(applicationContext, appId)
                        setResult(Activity.RESULT_OK, Intent().putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, appId))
                        finish()
                    }
                })
            }
        }
        setContentView(ScrollView(this).apply { addView(col) })
        Motion.pressAll(col)
        Motion.stagger(col)
    }

    private fun note(t: String) = TextView(this).apply {
        text = t
        textSize = 16f
    }
}
