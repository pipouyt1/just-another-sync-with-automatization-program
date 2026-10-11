package app.hub.phone

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import kotlinx.coroutines.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject

/** Mantiene este telefono conectado al hub como un equipo más y le manda batería y datos de salud cada 30 s. */
class DataService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var job: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("hub", L.t(this, "conexión con el hub"), NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val n: Notification = NotificationCompat.Builder(this, "hub")
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle("hub")
            .setContentText(L.t(this, "enviando datos de este teléfono"))
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        val type = if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0
        ServiceCompat.startForeground(this, 1, n, type)
        if (job?.isActive != true) job = scope.launch { loop() }
        return START_STICKY
    }

    override fun onDestroy() {
        job?.cancel()
        Status.connected = false
        super.onDestroy()
    }

    /** Una automatización del hub pide mandar un webhook desde este teléfono; se contesta con el resultado. */
    private fun fireWebhook(ws: WebSocket, j: JSONObject) {
        scope.launch {
            val out = JSONObject().put("type", "webhook_result").put("id", j.optString("id"))
            val url = j.optString("url")
            if (!url.startsWith("http://") && !url.startsWith("https://")) {
                out.put("ok", false).put("error", "dirección no válida")
            } else try {
                val body = j.optString("body").toRequestBody("application/json".toMediaType())
                val req = Request.Builder().url(url).header("User-Agent", "hub-android").post(body).build()
                Api.http.newBuilder().followRedirects(false).callTimeout(10, java.util.concurrent.TimeUnit.SECONDS).build()
                    .newCall(req).execute().use { r ->
                        out.put("ok", r.code in 200..299).put("status", r.code)
                    }
            } catch (e: Exception) {
                out.put("ok", false).put("error", e.javaClass.simpleName)
            }
            ws.send(out.toString())
        }
    }

    /** El portal pidió actualizar este teléfono: con la app abierta se abre el instalador; si no, una notificación. */
    private fun remoteUpdate() {
        if (Update.state(this) == UpdateState.NONE) return
        val cb = Update.onRemote
        if (cb != null) {
            android.os.Handler(android.os.Looper.getMainLooper()).post { cb() }
            return
        }
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("update", L.t(this, "actualizaciones"), NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(this, 1, Intent(this, MainActivity::class.java).putExtra("update", true)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        nm.notify(2, NotificationCompat.Builder(this, "update").setSmallIcon(R.drawable.ic_stat).setContentTitle(L.t(this, "actualización disponible"))
            .setContentText(L.t(this, "toca para instalar la versión nueva de hub")).setContentIntent(open).setAutoCancel(true).build())
    }

    private suspend fun loop() {
        while (currentCoroutineContext().isActive) {
            val token = Store.token(this)
            if (token == null) {
                stopSelf()
                return
            }
            if (Update.blocked(this)) {   // versión demasiado antigua: no manda datos hasta actualizar
                Status.error = "actualiza la app para volver a enviar datos"
                delay(10_000)
                continue
            }
            try {
                session(token)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Status.error = e.message ?: e.javaClass.simpleName
            }
            Status.connected = false
            delay(5000)
        }
    }

    private suspend fun session(token: String) = coroutineScope {
        val closed = CompletableDeferred<Unit>()
        val ws = Api.http.newWebSocket(Request.Builder().url(Store.wsUrl(this@DataService)).build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                webSocket.send(JSONObject().put("type", "auth").put("token", token).toString())
                webSocket.send(JSONObject().put("type", "hello").put("device_id", Store.deviceId(this@DataService))
                    .put("name", Build.MODEL).put("platform", "Android").put("kind", "agent")
                    .put("client_version", Ver.client(this@DataService)).toString())
                Status.connected = true
                Status.error = ""
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                if (text.contains("\"auth_error\"")) {   // la sesión caducó: hay que volver a iniciar sesión
                    Store.clearToken(this@DataService)
                    Status.error = "la sesión caducó; inicia sesión otra vez"
                    webSocket.close(1000, null)
                    return
                }
                try {
                    val j = JSONObject(text)
                    when (j.optString("type")) {
                        "update_now" -> remoteUpdate()
                        "fire_webhook" -> fireWebhook(webSocket, j)
                        "kick" -> {   // el portal eliminó este teléfono: se cierra la sesión al instante
                            Store.clearToken(this@DataService)
                            StateStore.clear(this@DataService)
                            Status.error = "este teléfono se eliminó de la cuenta"
                            WidgetRenderer.refreshAll(applicationContext)
                            Status.onKicked?.let { cb -> android.os.Handler(android.os.Looper.getMainLooper()).post { cb() } }
                            webSocket.close(1000, null)
                        }
                        "state" -> {   // widgets y variables: los widgets de la pantalla de inicio se redibujan
                            j.optString("version").takeIf { it.isNotEmpty() }?.let { Store.setServerVersion(this@DataService, it) }
                            j.optJSONObject("me")?.let { Store.setDebugger(this@DataService, it.optBoolean("debug")) }
                            StateStore.set(this@DataService, text)
                            WidgetRenderer.refreshAll(applicationContext)
                        }
                        "values" -> {
                            StateStore.applyValues(this@DataService, j)
                            WidgetRenderer.refreshAll(applicationContext, 30_000)
                        }
                    }
                } catch (e: Exception) {
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                closed.complete(Unit)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Status.error = t.message ?: t.javaClass.simpleName
                closed.complete(Unit)
            }
        })
        val sender = launch {
            var next = 0L
            var rootFails = 0
            while (true) {
                if (Update.blocked(this@DataService) || Update.ahead(this@DataService)) ws.close(1000, null)
                if (Status.connected && System.currentTimeMillis() >= next) {
                    val data = JSONObject()
                    Health.battery(this@DataService)?.let { data.put("battery", Math.round(it).toDouble()) }
                    Sensors.read(this@DataService).forEach { (k, v) -> data.put(k, v) }
                    if (Store.rootGranted(this@DataService)) {   // solo lectura; si se revoca, se deja de pedir
                        val r = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { Root.read() }
                        if (r.isEmpty()) {
                            if (++rootFails >= 3) Store.setRootGranted(this@DataService, false)
                        } else {
                            rootFails = 0
                            r.forEach { (k, v) -> data.put(k, v) }
                        }
                    }
                    if (Store.share(this@DataService)) Health.read(this@DataService).forEach { (k, v) -> data.put(k, v) }
                    ws.send(JSONObject().put("type", "metrics").put("data", data).toString())
                    Status.lastSend = System.currentTimeMillis()
                    next = Status.lastSend + 30_000
                }
                delay(1000)
                WidgetRenderer.refreshAll(applicationContext, 60_000)   // mantiene al día la hora de los widgets
            }
        }
        try {
            closed.await()
        } finally {
            sender.cancel()
            ws.cancel()
        }
    }
}
