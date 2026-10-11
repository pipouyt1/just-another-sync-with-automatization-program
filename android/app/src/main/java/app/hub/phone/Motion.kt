package app.hub.phone

import android.annotation.SuppressLint
import android.app.Activity
import android.content.res.Configuration
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.animation.OvershootInterpolator
import androidx.core.view.WindowCompat

/** Movimiento estilo material 3 expressive: resortes al pulsar, entradas escalonadas y barras del sistema a juego. */
object Motion {
    private val spring = OvershootInterpolator(2.2f)

    /** Barra de estado y de navegación del color del fondo (no moradas) y con iconos legibles. */
    fun bars(a: Activity) {
        val bg = a.getColor(R.color.bg)
        val night = (a.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
        a.window.statusBarColor = bg
        a.window.navigationBarColor = bg
        val c = WindowCompat.getInsetsController(a.window, a.window.decorView)
        c.isAppearanceLightStatusBars = !night
        c.isAppearanceLightNavigationBars = !night
    }

    /** Al pulsar se encoge y al soltar rebota. */
    @SuppressLint("ClickableViewAccessibility")
    fun press(v: View) {
        v.setOnTouchListener { view, e ->
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> view.animate().scaleX(.94f).scaleY(.94f).setDuration(120).setInterpolator(null).start()
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL ->
                    view.animate().scaleX(1f).scaleY(1f).setDuration(420).setInterpolator(spring).start()
            }
            false
        }
    }

    fun pressAll(root: View) {
        if (root is android.widget.Button || root is com.google.android.material.materialswitch.MaterialSwitch) press(root)
        if (root is ViewGroup) for (i in 0 until root.childCount) pressAll(root.getChildAt(i))
    }

    /** Los hijos entran uno tras otro subiendo con un pequeño rebote. */
    fun stagger(group: ViewGroup, startDelay: Long = 80) {
        for (i in 0 until group.childCount) {
            val c = group.getChildAt(i)
            c.alpha = 0f
            c.translationY = 60f
            c.scaleX = .94f
            c.scaleY = .94f
            c.animate().alpha(1f).translationY(0f).scaleX(1f).scaleY(1f)
                .setStartDelay(startDelay + i * 55L).setDuration(520).setInterpolator(spring).start()
        }
    }

    fun forward(a: Activity) = a.overridePendingTransition(R.anim.enter, R.anim.exit)
    fun back(a: Activity) = a.overridePendingTransition(R.anim.back_enter, R.anim.back_exit)
}
