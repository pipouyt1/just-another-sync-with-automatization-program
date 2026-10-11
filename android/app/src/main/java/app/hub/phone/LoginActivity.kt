package app.hub.phone

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

class LoginActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Store.token(this) != null) {
            startActivity(Intent(this, MainActivity::class.java))
            finish()
            overridePendingTransition(0, 0)
            return
        }
        setContentView(R.layout.activity_login)
        L.apply(this, findViewById(android.R.id.content))
        L.picker(this, findViewById(R.id.col))
        Motion.bars(this)
        Motion.pressAll(findViewById(android.R.id.content))
        Motion.stagger(findViewById<android.view.ViewGroup>(R.id.col))
        val url = findViewById<EditText>(R.id.url)
        val user = findViewById<EditText>(R.id.user)
        val pw = findViewById<EditText>(R.id.pw)
        val err = findViewById<TextView>(R.id.err)
        val go = findViewById<Button>(R.id.go)
        val server = findViewById<com.google.android.material.button.MaterialButtonToggleGroup>(R.id.server)
        val urlBox = findViewById<View>(R.id.urlBox)
        val serverHint = findViewById<TextView>(R.id.serverHint)
        val saved = Store.url(this)
        url.setText(if (saved.isEmpty() || saved == CLOUD_URL) "http://" else saved)
        server.check(if (saved.isEmpty() || saved == CLOUD_URL) R.id.btnCloud else R.id.btnLocal)
        fun cloud() = server.checkedButtonId == R.id.btnCloud
        fun refresh() {
            urlBox.visibility = if (cloud()) View.GONE else View.VISIBLE
            serverHint.text = if (cloud()) L.t(this, "usa el servicio en la nube de hub ({0})", CLOUD_URL.removePrefix("https://"))
            else L.t(this, "escribe la dirección de tu propio servidor, por ejemplo http://192.168.1.10:8765")
        }
        server.addOnButtonCheckedListener { _, _, _ -> refresh() }
        refresh()
        user.setText(Store.user(this))

        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)

        go.setOnClickListener {
            val base = if (cloud()) CLOUD_URL else Api.normalize(url.text.toString())
            val u = user.text.toString().trim().lowercase()
            val p = pw.text.toString()
            err.text = L.t(this, "conectando…")
            go.isEnabled = false
            Thread {
                try {
                    val (token, name, debug) = Api.login(base, u, p)
                    Store.save(this, base, name, token)
                    Store.setDebugger(this, debug)
                    runOnUiThread {
                        startActivity(Intent(this, MainActivity::class.java))
                        finish()
                        Motion.forward(this)
                    }
                } catch (e: Exception) {
                    runOnUiThread {
                        err.text = L.t(this, e.message ?: "error")
                        go.isEnabled = true
                    }
                }
            }.start()
        }
    }
}
