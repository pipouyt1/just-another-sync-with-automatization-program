package app.hub.phone

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

/** El portal del hub dentro de la app; además arranca el servicio que manda los datos del teléfono. */
class MainActivity : AppCompatActivity() {
    private lateinit var web: WebView
    private var chooser: ValueCallback<Array<Uri>>? = null

    private val picker = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        chooser?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(r.resultCode, r.data))
        chooser = null
    }

    inner class Bridge {
        @JavascriptInterface
        fun lang(): String = L.lang(this@MainActivity)   // el portal usa el idioma de la app

        @JavascriptInterface
        fun setLang(l: String) = L.set(this@MainActivity, l)

        @JavascriptInterface
        fun openSettings() = runOnUiThread {
            startActivity(Intent(this@MainActivity, SettingsActivity::class.java))
            Motion.forward(this@MainActivity)
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val token = Store.token(this)
        if (token == null) {
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }
        Motion.bars(this)
        web = WebView(this)
        web.setBackgroundColor(getColor(R.color.bg))
        web.overScrollMode = android.view.View.OVER_SCROLL_NEVER
        web.isLongClickable = false
        web.setOnLongClickListener { true }
        web.isHapticFeedbackEnabled = false
        setContentView(web)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.addJavascriptInterface(Bridge(), "HubApp")
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: android.webkit.WebResourceRequest): Boolean {
                val base = Uri.parse(Store.url(this@MainActivity)).host
                if (request.url.host == base) return false
                startActivity(Intent(Intent.ACTION_VIEW, request.url))
                return true
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(w: WebView, cb: ValueCallback<Array<Uri>>, p: FileChooserParams): Boolean {
                chooser?.onReceiveValue(null)
                chooser = cb
                return try {
                    picker.launch(p.createIntent())
                    true
                } catch (e: Exception) {
                    chooser = null
                    false
                }
            }
        }
        web.setDownloadListener { url, _, _, _, _ -> startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
        web.loadUrl(Store.url(this) + "/#token=" + token)
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (web.canGoBack()) web.goBack() else finish()
            }
        })
    }

    private fun checkUpdate() {
        Thread {
            Update.fetchServerVersion(this)
            runOnUiThread {
                if (isFinishing) return@runOnUiThread
                if (Update.ahead(this)) {
                    showAhead()
                    return@runOnUiThread
                }
                when (Update.state(this)) {
                    UpdateState.HARD -> startActivity(Intent(this, UpdateActivity::class.java))
                    UpdateState.SOFT -> if (!Update.softShown) {
                        Update.softShown = true
                        com.google.android.material.dialog.MaterialAlertDialogBuilder(this)
                            .setTitle(L.t(this, "actualización grande"))
                            .setMessage(L.t(this, "tu dispositivo no tiene la versión más reciente y las nuevas funciones no funcionarán, actualiza el cliente para disfrutar de la actualización al 100%"))
                            .setCancelable(false)
                            .setPositiveButton(L.t(this, "instalar update")) { _, _ ->
                                Update.install(this) { Toast.makeText(this, it, Toast.LENGTH_LONG).show() }
                            }
                            .setNegativeButton(L.t(this, "ignorar (no recomendado)"), null)
                            .show()
                    }
                    UpdateState.NONE -> {}
                }
            }
        }.start()
    }

    /** Versión mayor que la del servidor: se puede salir, o entrar con una cuenta de depuración. */
    private fun showAhead() {
        if (Update.aheadShown) return
        Update.aheadShown = true
        com.google.android.material.dialog.MaterialAlertDialogBuilder(this)
            .setTitle(L.t(this, "versión mayor detectada"))
            .setMessage(L.t(this, "tienes una versión mayor a la del servidor (app {0}, servidor {1}), la app no puede iniciar correctamente en este estándar, desinstala la app y vuelve a instalar la versión oficial", Ver.client(this), Store.serverVersion(this) ?: "?"))
            .setCancelable(false)
            .setPositiveButton(L.t(this, "salir de la app")) { _, _ ->
                Update.aheadShown = false
                finishAffinity()
            }
            .setNegativeButton(L.t(this, "iniciar sesión con cuenta de depuración")) { _, _ ->
                Update.aheadShown = false
                stopService(Intent(this, DataService::class.java))
                Store.clearToken(this)
                StateStore.clear(this)
                WidgetRenderer.refreshAll(applicationContext)
                startActivity(Intent(this, LoginActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK or Intent.FLAG_ACTIVITY_NEW_TASK))
                finish()
            }
            .show()
    }

    private fun remoteInstall() = Update.install(this) { Toast.makeText(this, it, Toast.LENGTH_LONG).show() }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
    }

    override fun onPause() {
        Update.onRemote = null
        Status.onKicked = null
        super.onPause()
    }

    override fun onResume() {
        super.onResume()
        Update.onRemote = { remoteInstall() }
        Status.onKicked = {   // el portal eliminó este teléfono: a la pantalla de inicio de sesión
            startActivity(Intent(this, LoginActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK or Intent.FLAG_ACTIVITY_NEW_TASK))
            finish()
        }
        if (intent?.getBooleanExtra("update", false) == true) {   // viene de la notificación «actualización disponible»
            intent.removeExtra("update")
            remoteInstall()
        }
        if (Store.token(this) != null) checkUpdate()
        if (Store.token(this) != null && !Root.shownThisRun && !Store.rootIgnored(this) && !Store.rootGranted(this)) {
            Thread { if (Root.detected()) runOnUiThread { Root.prompt(this) } }.start()   // aviso de root detectado
        }
        if (Store.token(this) != null && Store.share(this)) {
            ContextCompat.startForegroundService(this, Intent(this, DataService::class.java))
        }
    }
}
