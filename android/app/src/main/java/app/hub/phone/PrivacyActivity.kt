package app.hub.phone

import android.os.Bundle
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/** Pantalla que Health Connect abre para explicar qué se hace con los datos. */
class PrivacyActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val t = TextView(this)
        t.setPadding(48, 96, 48, 48)
        t.textSize = 16f
        t.text = L.t(this, "esta app lee de health connect tus pasos, distancia, calorías activas, sueño y último pulso de hoy " +
            "solo para enviarlos al hub que tú elegiste, como variables de tu cuenta. " +
            "no se guardan en otro sitio ni se comparten con nadie salvo con las cuentas con las que tú compartas esas variables en el portal.")
        setContentView(t)
    }
}
