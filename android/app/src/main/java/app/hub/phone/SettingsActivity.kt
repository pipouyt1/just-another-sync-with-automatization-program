package app.hub.phone

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.Button
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.health.connect.client.PermissionController
import com.google.android.material.materialswitch.MaterialSwitch
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.text.DateFormat
import java.util.Date

class SettingsActivity : AppCompatActivity() {
    private val ui = Handler(Looper.getMainLooper())
    private lateinit var info: TextView
    private val tick = object : Runnable {
        override fun run() {
            info.text = describe()
            ui.postDelayed(this, 1000)
        }
    }

    private val perms = registerForActivityResult(PermissionController.createRequestPermissionResultContract()) {
        CoroutineScope(Dispatchers.IO).launch { Health.read(this@SettingsActivity, force = true) }
    }

    private fun describe(): String {
        val time = { t: Long -> if (t == 0L) "—" else DateFormat.getTimeInstance(DateFormat.MEDIUM).format(Date(t)) }
        return buildString {
            val c = this@SettingsActivity
            append(L.t(c, "cuenta: {0}", Store.user(c)) + "\n")
            append(L.t(c, "hub: {0}", Store.url(c)) + "\n")
            append(L.t(c, "versión: app v{0} · hub v{1}", Ver.client(c), Store.serverVersion(c) ?: "?") + "\n\n")
            append(L.t(c, if (Status.connected) "● conectado al hub" else "● sin conexión con el hub") + "\n")
            if (Status.error.isNotEmpty() && !Status.connected) append("   ${L.t(c, Status.error)}\n")
            append(L.t(c, "último envío: {0}", time(Status.lastSend)) + "\n")
            if (Store.rootGranted(c)) append(L.t(c, "root: acceso concedido (beta, solo lectura)") + "\n")
            append("\n")
            append(L.t(c, "health connect: {0}", L.t(c, Status.health.ifEmpty { "sin leer todavía" })) + "\n")
            if (Status.healthAt != 0L) append(L.t(c, "última lectura: {0}", time(Status.healthAt)))
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)
        L.apply(this, findViewById(android.R.id.content))
        L.picker(this, findViewById(R.id.col))
        Motion.bars(this)
        Motion.pressAll(findViewById(android.R.id.content))
        Motion.stagger(findViewById<android.view.ViewGroup>(R.id.col))
        info = findViewById(R.id.info)
        val sw = findViewById<MaterialSwitch>(R.id.share)
        sw.isChecked = Store.share(this)
        sw.setOnCheckedChangeListener { _, on ->
            Store.setShare(this, on)
            val i = Intent(this, DataService::class.java)
            if (on) ContextCompat.startForegroundService(this, i) else stopService(i)
        }
        findViewById<Button>(R.id.health).setOnClickListener {
            if (Health.available(this)) perms.launch(Health.PERMS)
            else startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=com.google.android.apps.healthdata")))
        }
        val healthBtn = findViewById<Button>(R.id.health)
        Thread {
            if (Root.detected()) runOnUiThread {   // solo aparece en teléfonos con root
                val b = com.google.android.material.button.MaterialButton(this, null, com.google.android.material.R.attr.materialButtonOutlinedStyle)
                b.text = L.t(this, "acceso root (beta)")
                b.isAllCaps = false
                b.layoutParams = healthBtn.layoutParams
                b.setOnClickListener { Root.prompt(this, force = true) }
                val parent = healthBtn.parent as android.view.ViewGroup
                parent.addView(b, parent.indexOfChild(healthBtn) + 1)
            }
        }.start()
        findViewById<Button>(R.id.logout).setOnClickListener {
            stopService(Intent(this, DataService::class.java))
            Store.clearToken(this)
            StateStore.clear(this)
            WidgetRenderer.refreshAll(applicationContext)
            startActivity(Intent(this, LoginActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK or Intent.FLAG_ACTIVITY_NEW_TASK))
            finish()
        }
        findViewById<Button>(R.id.back).setOnClickListener { finish() }
        onBackPressedDispatcher.addCallback(this, object : androidx.activity.OnBackPressedCallback(true) {
            override fun handleOnBackPressed() = finish()
        })
    }

    override fun onResume() {
        super.onResume()
        ui.post(tick)
    }

    override fun finish() {
        super.finish()
        Motion.back(this)
    }

    override fun onPause() {
        ui.removeCallbacks(tick)
        super.onPause()
    }
}
