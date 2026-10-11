package app.hub.phone

import android.content.Context
import android.provider.Settings
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/** Servicio en la nube que se ofrece al iniciar sesión (el otro camino es escribir la dirección de un servidor propio). */
const val CLOUD_URL = "https://untilted-devices-app.fly.dev"

/** Lo guardado en el telefono: direccion del hub, usuario, sesion y si se comparten datos. */
object Store {
    private fun p(c: Context) = c.getSharedPreferences("hub", Context.MODE_PRIVATE)

    fun url(c: Context): String = p(c).getString("url", "") ?: ""
    fun user(c: Context): String = p(c).getString("user", "") ?: ""
    fun token(c: Context): String? = p(c).getString("token", null)
    fun share(c: Context): Boolean = p(c).getBoolean("share", true)
    fun setShare(c: Context, on: Boolean) = p(c).edit().putBoolean("share", on).apply()

    fun save(c: Context, url: String, user: String, token: String) =
        p(c).edit().putString("url", url).putString("user", user).putString("token", token).apply()

    fun clearToken(c: Context) = p(c).edit().remove("token").remove("debugger").apply()

    fun lang(c: Context): String = p(c).getString("lang", "") ?: ""
    fun setLang(c: Context, l: String) = p(c).edit().putString("lang", l).apply()

    fun rootIgnored(c: Context): Boolean = p(c).getBoolean("root_ignored", false)
    fun setRootIgnored(c: Context, on: Boolean) = p(c).edit().putBoolean("root_ignored", on).apply()
    fun rootGranted(c: Context): Boolean = p(c).getBoolean("root_granted", false)
    fun setRootGranted(c: Context, on: Boolean) = p(c).edit().putBoolean("root_granted", on).apply()

    fun isDebugger(c: Context): Boolean = p(c).getBoolean("debugger", false)
    fun setDebugger(c: Context, on: Boolean) = p(c).edit().putBoolean("debugger", on).apply()

    fun serverVersion(c: Context): String? = p(c).getString("server_version", null)
    fun setServerVersion(c: Context, v: String) = p(c).edit().putString("server_version", v).apply()
    fun outdatedSince(c: Context): Long = p(c).getLong("outdated_since", 0)
    fun setOutdatedSince(c: Context, t: Long) = p(c).edit().putLong("outdated_since", t).apply()

    fun widgetFor(c: Context, appWidgetId: Int): Int = p(c).getInt("w_$appWidgetId", -1)
    fun setWidgetFor(c: Context, appWidgetId: Int, id: Int) = p(c).edit().putInt("w_$appWidgetId", id).apply()
    fun forgetWidgets(c: Context, ids: IntArray) = p(c).edit().also { e -> ids.forEach { e.remove("w_$it") } }.apply()

    fun wsUrl(c: Context): String = url(c).replaceFirst("http", "ws") + "/ws"

    /** Identificador estable de este telefono (no cambia al reinstalar, no es reversible). */
    fun deviceId(c: Context): String {
        val id = Settings.Secure.getString(c.contentResolver, Settings.Secure.ANDROID_ID) ?: "x"
        return MessageDigest.getInstance("SHA-1").digest("android-$id".toByteArray())
            .joinToString("") { "%02x".format(it) }.take(16)
    }
}

/** Estado en vivo que lee la pantalla de ajustes. */
object Status {
    @Volatile var connected = false
    @Volatile var lastSend = 0L
    @Volatile var error = ""
    @Volatile var onKicked: (() -> Unit)? = null   // la pantalla principal lo fija mientras esta abierta
    @Volatile var health = ""
    @Volatile var healthAt = 0L
}

object Api {
    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS)
        .pingInterval(20, TimeUnit.SECONDS)
        .build()

    fun normalize(raw: String): String {
        var u = raw.trim().trimEnd('/')
        if (!u.startsWith("http://") && !u.startsWith("https://")) u = "http://$u"
        return u
    }

    /** Devuelve (token, usuario, es depurador) o lanza una excepcion con el texto para mostrar. Llamar fuera del hilo principal. */
    fun login(base: String, user: String, password: String): Triple<String, String, Boolean> {
        val body = JSONObject().put("user", user).put("password", password).toString()
            .toRequestBody("application/json".toMediaType())
        val req = Request.Builder().url("$base/api/login").post(body).build()
        val res = try {
            http.newCall(req).execute()
        } catch (e: Exception) {
            throw RuntimeException("no se pudo contactar con el servidor")
        }
        res.use {
            val text = it.body?.string() ?: ""
            val j = try { JSONObject(text) } catch (e: Exception) { JSONObject() }
            if (!it.isSuccessful) throw RuntimeException(j.optString("error", "error al iniciar sesión"))
            return Triple(j.getString("token"), j.getString("user"), j.optBoolean("debug"))
        }
    }
}

/** Último estado que mandó el hub (widgets y variables); lo usan los widgets del teléfono aunque la app esté cerrada. */
object StateStore {
    private var cache: JSONObject? = null

    @Synchronized
    fun get(c: Context): JSONObject? {
        cache?.let { return it }
        return try {
            JSONObject(java.io.File(c.filesDir, "state.json").readText()).also { cache = it }
        } catch (e: Exception) {
            null
        }
    }

    @Synchronized
    fun set(c: Context, text: String) {
        val j = JSONObject(text)
        j.optJSONObject("me")?.remove("avatar")   // la foto no hace falta y pesa
        cache = j
        save(c)
    }

    /** Mensaje «values»: actualiza solo los valores en vivo de las variables automáticas. */
    @Synchronized
    fun applyValues(c: Context, msg: JSONObject) {
        val st = cache ?: get(c) ?: return
        val vars = st.optJSONArray("variables") ?: return
        val upd = msg.optJSONObject("vars") ?: return
        for (i in 0 until vars.length()) {
            val v = vars.getJSONObject(i)
            val n = upd.optJSONObject(v.optInt("id").toString()) ?: continue
            v.put("value", n.opt("value")).put("online", n.opt("online"))
        }
        save(c)
    }

    fun clear(c: Context) {
        cache = null
        java.io.File(c.filesDir, "state.json").delete()
    }

    private fun save(c: Context) {
        try {
            java.io.File(c.filesDir, "state.json").writeText(cache.toString())
        } catch (e: Exception) {
        }
    }
}
