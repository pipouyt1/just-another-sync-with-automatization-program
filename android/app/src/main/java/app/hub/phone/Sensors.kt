package app.hub.phone

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.os.Environment
import android.os.StatFs

/** Lecturas del teléfono que no necesitan permisos especiales. */
object Sensors {
    fun read(c: Context): Map<String, Any> {
        val out = mutableMapOf<String, Any>()
        try {
            val i = c.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            if (i != null) {
                out["charging"] = if (i.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) != 0) "sí" else "no"
                val t = i.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Int.MIN_VALUE)
                if (t != Int.MIN_VALUE) out["battery_temp"] = t / 10.0
            }
        } catch (e: Exception) {
        }
        try {
            val s = StatFs(Environment.getDataDirectory().path)
            if (s.blockCountLong > 0) out["storage"] = Math.round((1.0 - s.availableBlocksLong.toDouble() / s.blockCountLong) * 1000) / 10.0
        } catch (e: Exception) {
        }
        try {
            val m = ActivityManager.MemoryInfo()
            (c.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager).getMemoryInfo(m)
            if (m.totalMem > 0) out["ram_free"] = Math.round(m.availMem.toDouble() / m.totalMem * 1000) / 10.0
        } catch (e: Exception) {
        }
        try {
            val cm = c.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val caps = cm.getNetworkCapabilities(cm.activeNetwork)
            out["net_type"] = when {
                caps == null -> "sin red"
                caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
                caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "datos"
                caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "cable"
                else -> "otra"
            }
        } catch (e: Exception) {
        }
        return out
    }
}
