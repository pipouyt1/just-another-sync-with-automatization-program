package app.hub.phone

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import com.google.android.material.button.MaterialButton
import okhttp3.Request
import org.json.JSONObject
import java.io.File

/** Versiones «MAYOR.MENOR[.PARCHE]»: solo importan los dos primeros numeros. */
object Ver {
    fun level(v: String?): Pair<Int, Int> {
        val m = Regex("""^(\d+)\.(\d+)""").find(v ?: "") ?: return Pair(0, 0)
        return Pair(m.groupValues[1].toInt(), m.groupValues[2].toInt())
    }

    fun outdated(client: String?, server: String?): Boolean {
        val a = level(client)
        val b = level(server)
        return a.first < b.first || (a.first == b.first && a.second < b.second)
    }

    /** La app es de una versión mayor que la del servidor. */
    fun ahead(client: String?, server: String?) = outdated(server, client)

    fun client(c: Context): String = try {
        c.packageManager.getPackageInfo(c.packageName, 0).versionName ?: "0.0"
    } catch (e: Exception) {
        "0.0"
    }
}

enum class UpdateState { NONE, SOFT, HARD }

object Update {
    private const val LOCK_DAYS = 21L   // tras 3 semanas con la actualización pendiente, la app se bloquea
    @Volatile var softShown = false
    @Volatile var onRemote: (() -> Unit)? = null   // la pantalla principal lo fija mientras esta abierta

    fun state(c: Context): UpdateState {
        val sv = Store.serverVersion(c)
        if (sv == null || !Ver.outdated(Ver.client(c), sv)) {
            Store.setOutdatedSince(c, 0)
            return UpdateState.NONE
        }
        var since = Store.outdatedSince(c)
        if (since == 0L) {
            since = System.currentTimeMillis()
            Store.setOutdatedSince(c, since)
        }
        return if (System.currentTimeMillis() - since > LOCK_DAYS * 86_400_000L) UpdateState.HARD else UpdateState.SOFT
    }

    fun blocked(c: Context) = state(c) == UpdateState.HARD

    /** App más nueva que el servidor: no puede funcionar bien, salvo con una cuenta de depuración. */
    fun ahead(c: Context): Boolean {
        val sv = Store.serverVersion(c) ?: return false
        return Ver.ahead(Ver.client(c), sv) && !Store.isDebugger(c)
    }

    @Volatile var aheadShown = false

    /** Pregunta al servidor su versión (sin sesión). Llamar fuera del hilo principal. */
    fun fetchServerVersion(c: Context) {
        try {
            Api.http.newCall(Request.Builder().url(Store.url(c) + "/api/version").build()).execute().use {
                if (it.isSuccessful) {
                    val v = JSONObject(it.body?.string() ?: "{}").optString("version")
                    if (v.isNotEmpty()) Store.setServerVersion(c, v)
                }
            }
        } catch (e: Exception) {
        }
    }

    /** Descarga el APK del servidor, comprueba que es esta misma app y abre el instalador de Android. */
    fun install(a: Activity, status: (String) -> Unit) {
        if (!a.packageManager.canRequestPackageInstalls()) {
            Toast.makeText(a, L.t(a, "permite instalar apps desde «hub» y vuelve a pulsar «instalar update»"), Toast.LENGTH_LONG).show()
            a.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + a.packageName)))
            return
        }
        status(L.t(a, "descargando…"))
        Thread {
            try {
                val f = File(a.cacheDir, "update/hub.apk")
                f.parentFile?.mkdirs()
                Api.http.newCall(Request.Builder().url(Store.url(a) + "/hub.apk").build()).execute().use { r ->
                    if (!r.isSuccessful) throw RuntimeException(L.t(a, "el servidor no tiene la app ({0})", r.code))
                    f.outputStream().use { out -> r.body!!.byteStream().copyTo(out) }
                }
                val pi = a.packageManager.getPackageArchiveInfo(f.path, 0) ?: throw RuntimeException(L.t(a, "el archivo descargado no es una app válida"))
                if (pi.packageName != a.packageName) throw RuntimeException(L.t(a, "el archivo descargado no es esta app"))
                if (Ver.outdated(pi.versionName, Store.serverVersion(a))) throw RuntimeException(L.t(a, "el servidor todavía no tiene la app nueva"))
                a.runOnUiThread {
                    status(L.t(a, "abriendo el instalador…"))
                    val uri = FileProvider.getUriForFile(a, a.packageName + ".files", f)
                    a.startActivity(
                        Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    )
                }
            } catch (e: Exception) {
                a.runOnUiThread { status(L.t(a, "no se pudo actualizar: {0}", e.message ?: e.javaClass.simpleName)) }
            }
        }.start()
    }
}

/** Pantalla que bloquea la app cuando la actualización lleva más de 3 semanas pendiente. */
class UpdateActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Motion.bars(this)
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = android.view.Gravity.CENTER_VERTICAL
            setPadding(72, 72, 72, 72)
        }
        col.addView(TextView(this).apply {
            text = L.t(this@UpdateActivity, "actualiza el cliente")
            textSize = 32f
            setTypeface(typeface, android.graphics.Typeface.BOLD)
            setPadding(0, 0, 0, 24)
        })
        col.addView(TextView(this).apply {
            text = L.t(this@UpdateActivity, "esta versión es muy antigua y no puede correr en estos estándares, actualiza ahora.")
            textSize = 17f
            setPadding(0, 0, 0, 40)
        })
        val msg = TextView(this).apply {
            textSize = 14f
            setPadding(0, 24, 0, 0)
        }
        col.addView(MaterialButton(this).apply {
            text = L.t(this@UpdateActivity, "instalar update")
            isAllCaps = false
            textSize = 17f
            layoutParams = LinearLayout.LayoutParams(-1, 168)
            setOnClickListener { Update.install(this@UpdateActivity) { msg.text = it } }
        })
        col.addView(msg)
        setContentView(col)
        Motion.pressAll(col)
        Motion.stagger(col)
        onBackPressedDispatcher.addCallback(this, object : androidx.activity.OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {}   // no se puede cerrar
        })
    }

    override fun onResume() {
        super.onResume()
        if (Update.state(this) != UpdateState.HARD) finish()
    }
}
