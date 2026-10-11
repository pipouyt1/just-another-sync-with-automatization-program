# Primer despliegue en Fly.io

Todo se hace desde la carpeta `hub` (la que tiene `fly.toml` y `Dockerfile`).

## Antes de empezar
- Cuenta en https://fly.io (te pedirá una tarjeta, aunque el uso de este hub es muy pequeño).
- `hub.apk` debe estar en esta carpeta: es lo que descargan los teléfonos. Si cambias la app de Android,
  recompílala y cópiala aquí **antes** de desplegar.
- `.dockerignore` evita que `hub.db` (tus datos locales) se suba a Fly.

## 1. Instalar la herramienta (flyctl)
En PowerShell:

    iwr https://fly.io/install.ps1 -useb | iex

Cierra y abre la terminal, y comprueba con `fly version`.

## 2. Entrar en tu cuenta

    fly auth login

## 3. Elegir el nombre de la app
Abre `fly.toml` y cambia la primera línea por un nombre único (letras minúsculas, números y guiones):

    app = "mi-hub-crispo"

Tu dirección será `https://mi-hub-crispo.fly.dev`.

## 4. Crear la app y el volumen (donde vive la base de datos)

    fly apps create mi-hub-crispo
    fly volume create hubdata --region dfw --size 1

El nombre del volumen (`hubdata`) y la región (`dfw`) deben coincidir con `fly.toml`.

## 5. Desplegar
Una sola máquina (el hub guarda las conexiones en memoria y el volumen solo existe en una):

    fly deploy --ha=false

Comprueba:

    fly status        # debe haber 1 máquina "started"
    fly logs          # debe decir que el hub arrancó

## 6. Crear tu cuenta y cerrar el registro
1. Abre `https://mi-hub-crispo.fly.dev` y crea tu cuenta (la base de datos empieza vacía; no se copian los datos de tu PC).
2. En `fly.toml`, quita el `#` de la línea `ALLOW_REGISTER = "0"` y vuelve a desplegar:

       fly deploy --ha=false

   Así nadie más puede crear cuentas. Si luego quieres invitar a alguien, comenta la línea y despliega otra vez.

## 7. Conectar tus equipos
- **Teléfono:** abre `https://mi-hub-crispo.fly.dev/hub.apk`, instala, abre la app, escribe esa dirección, tu usuario y contraseña.
  Si ya tenías la app apuntando a tu PC, cierra sesión desde sus ajustes antes.
- **Windows:** en la carpeta del agente:

      python agent.py https://mi-hub-crispo.fly.dev crispo

  Cambiar de dirección cierra la sesión anterior; te pedirá la contraseña una vez.
- Elimina en el portal los equipos viejos que apunten a tu PC.

## 8. Actualizar más adelante
1. Hacemos los cambios; se sube `VERSION` (1.4.1 = cosmético, 1.5 = actualización grande) y, si cambió la app, se recompila `hub.apk`.
2. `fly deploy --ha=false`
3. Si fue una actualización grande, el portal avisa en los equipos desactualizados y ofrece el botón «actualizar».

Los datos y las sesiones se conservan entre despliegues (están en el volumen).

## 9. Copias de seguridad
Descarga la base de datos de vez en cuando:

    fly ssh sftp get /data/hub.db hub-copia.db

o crea una instantánea del volumen:

    fly volumes list
    fly volumes snapshots create <id-del-volumen>

## Problemas comunes
- **`hub.apk` da 404:** no estaba en la carpeta al desplegar. Cópialo y vuelve a desplegar.
- **«app name already taken»:** elige otro nombre en `fly.toml`.
- **Se ven dos máquinas:** `fly scale count 1` (y siempre despliega con `--ha=false`).
- **Las llaves de seguridad no aparecen:** solo funcionan con https y quedan atadas al dominio; si cambias de dirección hay que registrarlas de nuevo.
- **Dominio propio:** `fly certs add hub.tudominio.com`, crea el registro DNS que te indique y espera el certificado. Hazlo antes de registrar llaves de seguridad.

## Archivos pesados fuera de Fly.io (para no pagar tráfico)
El APK (8 MB) y el instalador de Windows (12 MB) se descargan muchas veces. Para que el servidor no gaste tráfico en ellos,
aloja esos dos archivos en **GitHub Releases** (gratis, con enlaces directos) y dile al hub que redirija:

1. Crea un repositorio público en GitHub (por ejemplo `hub-descargas`) y en él una *Release* (Releases → Create a new release,
   con una etiqueta como `v1.4`).
2. Sube a esa release `hub.apk` y `HubSetup.exe`.
3. Los enlaces directos de la última versión son:

       https://github.com/TU-USUARIO/hub-descargas/releases/latest/download/hub.apk
       https://github.com/TU-USUARIO/hub-descargas/releases/latest/download/HubSetup.exe

4. En `fly.toml`, dentro de `[env]`, añade:

       APK_URL = "https://github.com/TU-USUARIO/hub-descargas/releases/latest/download/hub.apk"
       INSTALLER_URL = "https://github.com/TU-USUARIO/hub-descargas/releases/latest/download/HubSetup.exe"

5. `fly deploy --ha=false`. Desde entonces `/hub.apk` e `/instalar.exe` redirigen a GitHub (el servidor solo manda la
   redirección, sin gastar tráfico) y los botones «descargar» y «actualizar» de los equipos siguen funcionando igual.

Para publicar una versión nueva de la app o del instalador, crea otra release con los archivos nuevos: no hace falta
redesplegar el hub (los enlaces `latest` apuntan siempre a la última). Sí hay que subir `VERSION` y desplegar si cambió el sitio.

Evita Google Drive para esto: los enlaces directos fallan con archivos que Google no puede escanear, tiene límites de
descargas y cambia sus reglas. Si prefieres otro sitio, vale cualquier URL https que dé el archivo directamente
(Cloudflare R2, Backblaze B2…).

## El instalador de Windows (HubSetup.exe)
- Está en `hub/installer/` (`hub_setup.py` es el código; `HubSetup.exe` el programa, ~12 MB). Se reconstruye con:

      pip install pyinstaller
      cd installer
      python -m PyInstaller --onefile --windowed --name HubSetup hub_setup.py

  y se copia a `hub/HubSetup.exe` (o se sube a la release de GitHub).
- Instala solo para el usuario (sin administrador) en `%LOCALAPPDATA%\Hub`: reutiliza un Python 3.10-3.13 si ya existe o
  instala Python 3.12 oficial; crea un entorno propio, instala las librerías y descarga `agent.py` del hub.
- Windows mostrará «Windows protegió su PC» porque el .exe no está firmado digitalmente (firmarlo cuesta dinero):
  «Más información» → «Ejecutar de todos modos».
- Para desinstalar: abre `HubSetup.exe` otra vez y pulsa «desinstalar», o ejecútalo con `--uninstall`.
- Si la dirección de la nube cambia (dominio propio), hay que cambiar `CLOUD_URL` en `installer/hub_setup.py`, en `agent.py`
  y en la app de Android, y reconstruir.
