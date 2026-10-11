package app.hub.phone

import android.app.Activity
import android.content.Context
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.TextView
import com.google.android.material.button.MaterialButton
import com.google.android.material.textfield.TextInputLayout
import org.json.JSONObject
import java.util.Locale

/** Idiomas de la app: español (el texto original), inglés, portugués y pirata. La clave de cada traducción es el texto en español
 *  (sin distinguir mayúsculas); la tabla sale de tools/i18n_d.py y vive en assets/i18n.json. */
object L {
    val LANGS = listOf("es", "en", "pt", "pi")
    val NAMES = mapOf("es" to "Español", "en" to "English", "pt" to "Português", "pi" to "Pirata ☠")
    private var data: JSONObject? = null
    private val patterns = HashMap<String, List<Pair<Regex, String>>>()
    private val space = Regex("\\s+")
    private val slot = Regex("\\{(\\d)\\}")

    fun lang(c: Context): String {
        val saved = Store.lang(c)
        if (saved in LANGS) return saved
        return when (Locale.getDefault().language) {
            "en" -> "en"
            "pt" -> "pt"
            else -> "es"
        }
    }

    fun set(c: Context, l: String) {
        if (l in LANGS) Store.setLang(c, l)
    }

    private fun load(c: Context): JSONObject {
        data?.let { return it }
        val j = try {
            JSONObject(c.applicationContext.assets.open("i18n.json").bufferedReader().use { it.readText() })
        } catch (e: Exception) {
            JSONObject()
        }
        data = j
        return j
    }

    private fun pats(l: String, d: JSONObject): List<Pair<Regex, String>> = patterns.getOrPut(l) {
        val out = ArrayList<Pair<Regex, String>>()
        for (k in d.keys()) {
            if (!slot.containsMatchIn(k)) continue
            val rx = k.split(slot).joinToString("(.+?)") { Regex.escape(it) }
            out.add(Pair(Regex("^$rx$", RegexOption.IGNORE_CASE), d.getString(k)))
        }
        out.sortedByDescending { it.first.pattern.length }
    }

    /** Traduce un texto fijo; {0}, {1}... se rellenan con `args`. Si no hay traducción, devuelve el mismo texto. */
    fun t(c: Context, text: String, vararg args: Any?): String {
        var out = text
        val l = lang(c)
        if (l != "es") {
            val d = load(c).optJSONObject(l)
            if (d != null) {
                val core = text.trim().replace(space, " ")
                val key = core.lowercase()
                if (d.has(key)) out = d.getString(key)
                else for ((re, tpl) in pats(l, d)) {
                    val m = re.matchEntire(core) ?: continue
                    out = tpl.replace(slot) { m.groupValues[it.groupValues[1].toInt() + 1] }
                    break
                }
            }
        }
        args.forEachIndexed { i, a -> out = out.replace("{$i}", a.toString()) }
        return out
    }

    /** Traduce todos los textos de una pantalla ya inflada (textos y pistas de los campos). */
    fun apply(c: Context, v: View) {
        if (v is TextInputLayout) v.hint = v.hint?.toString()?.let { t(c, it) }
        else if (v is TextView && v !is EditText && v.text.isNotEmpty() && v.getTag(R.id.lang_skip) == null) v.text = t(c, v.text.toString())
        if (v is ViewGroup) for (i in 0 until v.childCount) apply(c, v.getChildAt(i))
    }

    /** Añade una fila con los cuatro idiomas; al elegir uno, la pantalla se recrea. */
    fun picker(a: Activity, into: ViewGroup) {
        val row = android.widget.LinearLayout(a)
        row.orientation = android.widget.LinearLayout.HORIZONTAL
        val cur = lang(a)
        for (l in LANGS) {
            val b = MaterialButton(a, null, if (l == cur) com.google.android.material.R.attr.materialButtonStyle
            else com.google.android.material.R.attr.materialButtonOutlinedStyle)
            b.text = NAMES[l]
            b.isAllCaps = false
            b.textSize = 12f
            b.insetTop = 0
            b.insetBottom = 0
            b.setTag(R.id.lang_skip, true)   // los nombres de los idiomas no se traducen
            b.layoutParams = android.widget.LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginEnd = 6 }
            b.setOnClickListener {
                if (l != cur) {
                    set(a, l)
                    a.recreate()
                }
            }
            row.addView(b)
        }
        into.addView(row)
    }
}
