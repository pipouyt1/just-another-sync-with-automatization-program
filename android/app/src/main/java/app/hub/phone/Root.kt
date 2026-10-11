package app.hub.phone

import android.app.Activity
import android.content.Context
import android.widget.Toast
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Datos extra para teléfonos con root (Magisk). SOLO LECTURA: `su` ejecuta únicamente el guion fijo de abajo, que lee
 * archivos de /sys; nunca recibe texto de la red ni del usuario y no modifica nada del sistema.
 */
object Root {
    private val SU_PATHS = listOf("/system/bin/su", "/system/xbin/su", "/sbin/su", "/su/bin/su", "/system/sbin/su", "/vendor/bin/su", "/product/bin/su")

    /** Lecturas fijas de solo lectura: una línea `clave=valor` por dato. */
    private const val SCRIPT = """
b=/sys/class/power_supply/battery
echo cur=${'$'}(cat ${'$'}b/current_now 2>/dev/null)
echo volt=${'$'}(cat ${'$'}b/voltage_now 2>/dev/null)
echo cyc=${'$'}(cat ${'$'}b/cycle_count 2>/dev/null)
for z in /sys/class/thermal/thermal_zone*; do echo tz=${'$'}(cat ${'$'}z/type 2>/dev/null):${'$'}(cat ${'$'}z/temp 2>/dev/null); done
for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq; do echo freq=${'$'}(cat ${'$'}f 2>/dev/null); done
"""

    @Volatile var shownThisRun = false

    /** ¿Parece que el teléfono tiene root? Busca `su` sin ejecutarlo (así no se pide permiso todavía). */
    fun detected(): Boolean {
        if (SU_PATHS.any { File(it).exists() }) return true
        return try {
            val p = ProcessBuilder("sh", "-c", "command -v su").redirectErrorStream(true).start()
            p.waitFor(2, TimeUnit.SECONDS)
            p.inputStream.bufferedReader().readText().trim().isNotEmpty()
        } catch (e: Exception) {
            false
        }
    }

    private fun run(): String? = try {
        val p = ProcessBuilder("su", "-c", SCRIPT).redirectErrorStream(true).start()
        val out = StringBuilder()
        val t = Thread { out.append(p.inputStream.bufferedReader().readText()) }.apply { start() }
        if (!p.waitFor(6, TimeUnit.SECONDS)) {
            p.destroyForcibly()
            null
        } else {
            t.join(1000)
            out.toString()
        }
    } catch (e: Exception) {
        null
    }

    /** Pide el acceso (Magisk muestra su aviso). Devuelve si quedó concedido. */
    fun request(c: Context): Boolean {
        val out = run()
        val ok = out != null && out.contains("cur=")
        Store.setRootGranted(c, ok)
        return ok
    }

    /** Lecturas de root; vacío si no hay acceso. */
    fun read(): Map<String, Double> {
        val out = run() ?: return emptyMap()
        val res = mutableMapOf<String, Double>()
        var temp = 0.0
        var freq = 0.0
        for (line in out.lines()) {
            val k = line.substringBefore('=', "")
            val v = line.substringAfter('=', "").trim()
            when (k) {
                "cur" -> v.toDoubleOrNull()?.let { res["root_bat_current"] = if (Math.abs(it) > 20000) it / 1000 else it }
                "volt" -> v.toDoubleOrNull()?.let { res["root_bat_voltage"] = if (it > 20000) it / 1000 else it }
                "cyc" -> v.toDoubleOrNull()?.let { if (it >= 0) res["root_bat_cycles"] = it }
                "freq" -> v.toDoubleOrNull()?.let { freq = Math.max(freq, it / 1000) }
                "tz" -> {
                    val type = v.substringBefore(':').lowercase()
                    val raw = v.substringAfter(':', "").toDoubleOrNull() ?: continue
                    val c = if (Math.abs(raw) >= 1000) raw / 1000 else raw / 10   // milésimas de grado, o décimas
                    if (c in 10.0..120.0 && Regex("cpu|soc|tsens|cluster|big|little|mtktscpu").containsMatchIn(type)) temp = Math.max(temp, c)
                }
            }
        }
        if (temp > 0) res["root_cpu_temp"] = Math.round(temp * 10) / 10.0
        if (freq > 0) res["root_cpu_freq"] = Math.round(freq).toDouble()
        return res
    }

    /** Aviso al abrir la app (o desde ajustes con `force`): root detectado. */
    fun prompt(a: Activity, force: Boolean = false) {
        if (a.isFinishing) return
        if (!force && (shownThisRun || Store.rootIgnored(a) || Store.rootGranted(a))) return
        shownThisRun = true
        MaterialAlertDialogBuilder(a)
            .setTitle(L.t(a, "root detectado"))
            .setMessage(L.t(a, "no te preocupes, no bloquearemos la app ni nada de eso, de hecho, tienes más funciones desbloqueadas por rootear tu teléfono. si las quieres usar tienes que aprobar acceso root a esta app"))
            .setPositiveButton(L.t(a, "preguntar por acceso root")) { _, _ ->
                Thread {
                    val ok = request(a)
                    a.runOnUiThread {
                        Toast.makeText(a, L.t(a, if (ok) "acceso root concedido" else "no se concedió el acceso root"), Toast.LENGTH_LONG).show()
                    }
                }.start()
            }
            .setNegativeButton(L.t(a, "ignorar y no mostrar más")) { _, _ -> Store.setRootIgnored(a, true) }
            .show()
    }
}
