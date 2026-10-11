# versiones

Formato: `MAYOR.MENOR` o `MAYOR.MENOR.PARCHE`.

- **PARCHE** (1.3 -> 1.3.1): cambios cosmeticos del sitio. Las apps y agentes siguen funcionando igual.
- **MENOR/MAYOR** (1.3 -> 1.4): el servidor cambia algo que los clientes (app de Android, agente de Windows) deben
  implementar (sensores nuevos, bloqueo de cuenta...). Los clientes con version anterior se avisan como «actualizacion grande».

Un cliente esta al dia si sus dos primeros numeros son iguales o mayores que los del servidor.

## 1.5.1
Parche sobre la 1.5: solo cambia el servidor y el portal; las apps y agentes siguen funcionando igual.
- Páginas nuevas en Material 3 Expressive: 404, error de la api (ruta que no existe o método no permitido) y respuesta correcta de la api. Solo las ven los navegadores; la app, el agente y `curl` siguen recibiendo JSON. Los enlaces `/?view=auto` abren la pestaña «automatizar».
- Modo de depuración: abrir esas páginas desde el menú, y enviar una **nota** (barra de arriba; se puede ignorar y caduca) o un **aviso importante** (ventana al abrir el portal, incluso sin sesión; no expira hasta que se cancele).
- Modo mantenimiento (desde el modo de depuración): pantalla «estamos en mantenimiento» para los usuarios normales, con hora fija de regreso o sin hora (indefinido). Los depuradores siguen entrando y pueden terminarlo al instante; se termina solo a la hora fijada. Mientras dura, la api, los webhooks y las consultas de conexiones se pausan (503) y no se borra nada.

## 1.5
Actualización grande (desde la 1.4). Los clientes (app de Android y agente de Windows) necesitan la 1.5.
- Automatizaciones: avisos por webhook (Discord o genérico) cuando una variable cumple una condición (igual, distinto, mayor, menor, contiene, cambia…). Una sola vez al cumplirse, con espera mínima entre avisos. Si hay un dispositivo del dueño conectado con la versión 1.5, el aviso sale desde él (sirve para redes locales); si no, sale del servidor (solo https públicas, con protección contra SSRF).
- Pestaña «conexiones»: conecta tu cuenta de Steam y tu usuario de Roblox una vez en el portal; el servidor consulta sus datos públicos (aunque no haya ningún PC encendido) y los ofrece como variables. Solo datos públicos, nunca contraseñas.
- «automatizar» y «api» son ahora una sola pestaña con dos secciones (automatizaciones y llaves api).
- PC (agente): uso del disco, red (subida y bajada), temperatura de la CPU, uso de la GPU, procesos abiertos, volumen del sistema y sesión bloqueada.
- Teléfono (app): cargando, almacenamiento usado, RAM libre, tipo de conexión y temperatura de la batería.
- Teléfonos con root (Magisk), beta y solo lectura: temperatura de la CPU, corriente, voltaje y ciclos de la batería y frecuencia de la CPU. Al abrir la app se avisa de que se detectó root y se puede pedir el acceso o ignorarlo.
- Modo de depuración (solo para depuradores: la primera cuenta del servidor, y las que ella autorice): probar popups y avisos, simular versiones y una cuenta vacía, avisos globales, ver el estado del servidor y moderar cuentas (avisar, cerrar sesión, dar depuración, banear, restaurar y eliminar definitivamente), y editor del changelog por versión.
- Pantalla de «cuenta suspendida»: el baneo cierra sesiones, bloquea el nombre, y prohíbe las ip y dispositivos de la cuenta (nunca ip locales ni de depuradores). Los datos se conservan 30 días por si hay que restaurarla.
- Novedades: botón de destellos arriba (junto a cerrar sesión) con este changelog, un botón por versión y su texto al lado.

## 1.4.4
- Idiomas: español, inglés, portugués y pirata en el portal, el editor, la app de Android, el agente de Windows y el instalador. Se detecta el idioma del sistema y se cambia desde el login y ajustes. Las traducciones están en tools/i18n_*.py (python tools/build_i18n.py las regenera).

## 1.4.3
- Instalador de Windows (`HubSetup.exe`, ruta `/instalar.exe`): instala Python, las librerias y el agente solo, con
  accesos directos y sin consola. El portal lo ofrece en «añadir dispositivo → Windows».
- `APK_URL` e `INSTALLER_URL` (variables de entorno): si se definen, `/hub.apk` e `/instalar.exe` redirigen a esa URL
  (por ejemplo GitHub Releases) y el servidor no gasta ancho de banda en archivos pesados.

## 1.4.2
- En Fly.io el limite de intentos de inicio de sesion se aplica por IP real del cliente (antes todas las personas compartian la IP del proxy).

## 1.4.1
- Eliminar un equipo conectado ya es posible: se revoca su sesion y se le manda la orden `kick` para que cierre sesion al
  instante. Los clientes sin esa orden tambien se desconectan (su sesion deja de ser valida) en cuanto reintentan conectar.

## 1.4
- Boton «actualizar» por equipo en el aviso de actualizacion del portal: el servidor manda la orden `update_now` al agente
  de Windows (se actualiza y reinicia solo) o a la app de Android (abre el instalador o avisa con una notificacion).
  Los clientes 1.3 no entienden esa orden: para ellos el aviso ofrece la descarga manual.

## 1.3
- Sistema de versiones y avisos de actualizacion (app de Android y agente de Windows).
- Ajustes de cuenta, bloqueo con 2.ª clave, llaves de seguridad, ocultar informacion, popups.
