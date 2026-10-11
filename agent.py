"""Agente de Hub: manda RAM/CPU/tiempo encendido y, en Windows, vive en la barra de tareas.

  Windows : python agent.py [URL] [usuario]          (icono en la bandeja + ventana)
  Linux/Mac: python3 agent.py URL usuario --headless  (solo envia metricas, pide la contraseña)
Requiere: pip install aiohttp psutil   (Windows ademas: pystray pillow; para ver widgets: PySide6)"""
import argparse, asyncio, base64, getpass, glob, hashlib, io, json, os, platform, queue, sys, threading, time, uuid, webbrowser
from pathlib import Path
import aiohttp, psutil

CONFIG = Path(os.environ.get("HUB_AGENT_HOME") or Path(os.environ.get("APPDATA", Path.home())) / "HubAgent") / "config.json"
AGENT_VERSION = "1.5"
CLOUD_URL = "https://untilted-devices-app.fly.dev"   # servicio en la nube que se ofrece al iniciar sesion (o un servidor propio)   # nivel de funciones de este agente: debe igualar los dos primeros numeros de la version del servidor
UPDATE_LOCK_DAYS = 21   # tras 3 semanas con una actualizacion grande pendiente, el agente deja de funcionar hasta actualizar
DEVICE_ID = hashlib.sha1(f"{platform.node()}-{uuid.getnode()}".encode()).hexdigest()[:16]
UNIT = {"ram": "%", "cpu": "%", "uptime": " h", "steam_hours": " h", "steam_hours2w": " h", "battery": "%",
        "heart_rate": " lpm", "sleep_hours": " h", "distance_km": " km", "calories": " kcal", "disk": "%", "gpu": "%",
        "net_down": " KB/s", "net_up": " KB/s", "cpu_temp": " °C", "volume": "%", "storage": "%", "ram_free": "%", "battery_temp": " °C",
        "root_cpu_temp": " °C", "root_bat_current": " mA", "root_bat_voltage": " mV", "root_cpu_freq": " MHz"}


# <i18n-agente>
I18N_DATA = '{"en":{"idioma":"language","salir":"quit","abrir":"open","abrir portal":"open portal","editar widgets (portal)":"edit widgets (portal)","mover widgets":"move widgets","compartir actividad (app activa)":"share activity (active app)","conectar steam…":"connect steam…","conectar roblox…":"connect roblox…","iniciar con windows":"start with windows","cerrar sesión":"sign out","hub: en línea":"hub: online","hub: sin conexión":"hub: offline","hub: sin sesión":"hub: signed out","sin conexión":"offline","en línea":"online","sin sesión":"signed out","mías":"mine","compartidas":"shared","servicios":"services","servicios ▾":"services ▾","steam":"steam","roblox":"roblox","conectar steam":"connect steam","conectar roblox":"connect roblox","widgets del escritorio…":"desktop widgets…","entra al portal para administrar más opciones":"go to the portal to manage more options","inicia sesión para ver tus variables y enviar los datos de este pc.":"sign in to see your variables and send this pc\'s data.","iniciar sesión":"sign in","no se pudo conectar con el hub.":"could not connect to the hub.","reintentar conexión":"retry connection","se reintenta solo cada 5 segundos.":"it retries by itself every 5 seconds.","aún no tienes variables.":"you have no variables yet.","créalas en el portal.":"create them in the portal.","nada compartido contigo todavía.":"nothing shared with you yet.","de {0}":"from {0}","cancelar":"cancel","cerrar":"close","guardar":"save","guardar y probar":"save and test","eliminar":"delete","quitar":"remove","probando…":"testing…","conectando…":"connecting…","un momento…":"one moment…","nuevo valor:":"new value:","compartir variable":"share variable","compartida con (solo lectura):":"shared with (read-only):","todavía con nadie.":"with nobody yet.","añadir usuario":"add user","usuario":"username","contraseña":"password","dirección del hub":"hub address","servicio en la nube":"cloud service","servidor local":"local server","escribe la dirección de tu propio servidor, por ejemplo http://192.168.1.10:8765":"type the address of your own server, for example http://192.168.1.10:8765","usa el servicio en la nube de hub ({0})":"uses hub\'s cloud service ({0})","conectar {0}":"connect {0}","api key (gratis en steamcommunity.com/dev/apikey)":"api key (free at steamcommunity.com/dev/apikey)","tu id numérica o nombre de perfil":"your numeric id or profile name","tu nombre de usuario":"your username","da el juego actual y las horas jugadas (totales y de las últimas 2 semanas). para ver las horas, pon «detalles del juego» en público en tu perfil de steam.":"gives the current game and the hours played (total and last 2 weeks). to see the hours, set «game details» to public in your steam profile.","solo datos públicos: amigos, seguidores y visitas a los juegos que creaste. el tiempo jugado se mide con «compartir actividad» en el menú del icono.":"public data only: friends, followers and visits to the games you made. play time is measured with «share activity» in the icon menu.","los datos se guardan solo en este pc y los consulta este programa; el hub nunca los ve. deja los campos vacíos para desactivarlo.":"the data is saved only on this pc and queried by this program; the hub never sees it. leave the fields empty to turn it off.","¿cerrar sesión? este pc dejará de enviar datos y los widgets se ocultarán.":"sign out? this pc will stop sending data and the widgets will be hidden.","¿eliminar «{0}»?":"delete «{0}»?","sin respuesta":"no response","actualización grande":"major update","tu dispositivo no tiene la versión más reciente y las nuevas funciones no funcionarán, actualiza el cliente para disfrutar de la actualización al 100%.":"your device doesn\'t have the latest version and the new features won\'t work; update the client to enjoy the update at 100%.","instalar update":"install update","ignorar (no recomendado)":"ignore (not recommended)","actualiza el cliente":"update the client","esta versión es muy antigua y no puede correr en estos estándares, actualiza ahora.":"this version is very old and can\'t run under these standards; update now.","descargando e instalando… el agente se reiniciará solo.":"downloading and installing… the agent will restart by itself.","no se pudo actualizar: {0}":"could not update: {0}","no se pudo actualizar:":"could not update: ","el servidor todavía no tiene el agente nuevo":"the server doesn\'t have the new agent yet","ok (juego actual). tus horas son privadas: en steam pon «detalles del juego» en público":"ok (current game). your hours are private: in steam set «game details» to public","ok":"ok","perfil no encontrado":"profile not found","no existe ese nombre de perfil":"that profile name doesn\'t exist","no existe ese usuario de roblox":"that roblox user doesn\'t exist","escribe los datos para poder probar.":"type the details so it can be tested.","error: {0}":"error: {0}","error":"error","error al iniciar sesión":"error signing in","no se pudo contactar con el servidor":"could not reach the server","usuario o contraseña incorrectos":"wrong username or password","demasiados intentos, espera 5 min":"too many attempts, wait 5 min","no se pudo abrir":"could not open","cuenta bloqueada: desbloquéala en el portal (ajustes)":"account locked: unlock it in the portal (settings)","no existe el usuario «{0}»":"user «{0}» does not exist","ya es tuya":"it\'s already yours","para ver widgets en este pc instala qt: pip install pyside6":"to see widgets on this pc install qt:\\n\\npip install PySide6","widgets":"widgets","hola,":"hello,","versión mayor detectada":"newer version detected","tienes una versión mayor a la del servidor (app {0}, servidor {1}), la app no puede iniciar correctamente en este estándar, desinstala la app y vuelve a instalar la versión oficial":"you have a newer version than the server\'s (app {0}, server {1}); the app can\'t start properly under this standard, uninstall the app and install the official version again","salir de la app":"exit the app","iniciar sesión con cuenta de depuración":"sign in with a debug account"},"pt":{"idioma":"idioma","salir":"sair","abrir":"abrir","abrir portal":"abrir portal","editar widgets (portal)":"editar widgets (portal)","mover widgets":"mover widgets","compartir actividad (app activa)":"compartilhar atividade (app ativo)","conectar steam…":"conectar steam…","conectar roblox…":"conectar roblox…","iniciar con windows":"iniciar com o windows","cerrar sesión":"sair","hub: en línea":"hub: online","hub: sin conexión":"hub: sem conexão","hub: sin sesión":"hub: sem sessão","sin conexión":"sem conexão","en línea":"online","sin sesión":"sem sessão","mías":"minhas","compartidas":"compartilhadas","servicios":"serviços","servicios ▾":"serviços ▾","steam":"steam","roblox":"roblox","conectar steam":"conectar steam","conectar roblox":"conectar roblox","widgets del escritorio…":"widgets da área de trabalho…","entra al portal para administrar más opciones":"entre no portal para gerenciar mais opções","inicia sesión para ver tus variables y enviar los datos de este pc.":"entre para ver suas variáveis e enviar os dados deste pc.","iniciar sesión":"entrar","no se pudo conectar con el hub.":"não foi possível conectar ao hub.","reintentar conexión":"tentar conectar de novo","se reintenta solo cada 5 segundos.":"tenta de novo sozinho a cada 5 segundos.","aún no tienes variables.":"você ainda não tem variáveis.","créalas en el portal.":"crie-as no portal.","nada compartido contigo todavía.":"nada compartilhado com você ainda.","de {0}":"de {0}","cancelar":"cancelar","cerrar":"fechar","guardar":"salvar","guardar y probar":"salvar e testar","eliminar":"excluir","quitar":"remover","probando…":"testando…","conectando…":"conectando…","un momento…":"um momento…","nuevo valor:":"novo valor:","compartir variable":"compartilhar variável","compartida con (solo lectura):":"compartilhada com (somente leitura):","todavía con nadie.":"com ninguém ainda.","añadir usuario":"adicionar usuário","usuario":"usuário","contraseña":"senha","dirección del hub":"endereço do hub","servicio en la nube":"serviço na nuvem","servidor local":"servidor local","escribe la dirección de tu propio servidor, por ejemplo http://192.168.1.10:8765":"digite o endereço do seu próprio servidor, por exemplo http://192.168.1.10:8765","usa el servicio en la nube de hub ({0})":"usa o serviço na nuvem do hub ({0})","conectar {0}":"conectar {0}","api key (gratis en steamcommunity.com/dev/apikey)":"api key (grátis em steamcommunity.com/dev/apikey)","tu id numérica o nombre de perfil":"seu id numérico ou nome de perfil","tu nombre de usuario":"seu nome de usuário","da el juego actual y las horas jugadas (totales y de las últimas 2 semanas). para ver las horas, pon «detalles del juego» en público en tu perfil de steam.":"informa o jogo atual e as horas jogadas (totais e das últimas 2 semanas). para ver as horas, deixe «detalhes do jogo» público no seu perfil da steam.","solo datos públicos: amigos, seguidores y visitas a los juegos que creaste. el tiempo jugado se mide con «compartir actividad» en el menú del icono.":"apenas dados públicos: amigos, seguidores e visitas aos jogos que você criou. o tempo jogado é medido com «compartilhar atividade» no menu do ícone.","los datos se guardan solo en este pc y los consulta este programa; el hub nunca los ve. deja los campos vacíos para desactivarlo.":"os dados ficam salvos só neste pc e são consultados por este programa; o hub nunca os vê. deixe os campos vazios para desativar.","¿cerrar sesión? este pc dejará de enviar datos y los widgets se ocultarán.":"sair? este pc deixará de enviar dados e os widgets serão ocultados.","¿eliminar «{0}»?":"excluir «{0}»?","sin respuesta":"sem resposta","actualización grande":"atualização grande","tu dispositivo no tiene la versión más reciente y las nuevas funciones no funcionarán, actualiza el cliente para disfrutar de la actualización al 100%.":"seu dispositivo não tem a versão mais recente e as novas funções não vão funcionar; atualize o cliente para aproveitar a atualização a 100%.","instalar update":"instalar atualização","ignorar (no recomendado)":"ignorar (não recomendado)","actualiza el cliente":"atualize o cliente","esta versión es muy antigua y no puede correr en estos estándares, actualiza ahora.":"esta versão é muito antiga e não pode rodar nesses padrões; atualize agora.","descargando e instalando… el agente se reiniciará solo.":"baixando e instalando… o agente reiniciará sozinho.","no se pudo actualizar: {0}":"não foi possível atualizar: {0}","no se pudo actualizar:":"não foi possível atualizar: ","el servidor todavía no tiene el agente nuevo":"o servidor ainda não tem o agente novo","ok (juego actual). tus horas son privadas: en steam pon «detalles del juego» en público":"ok (jogo atual). suas horas são privadas: na steam deixe «detalhes do jogo» público","ok":"ok","perfil no encontrado":"perfil não encontrado","no existe ese nombre de perfil":"esse nome de perfil não existe","no existe ese usuario de roblox":"esse usuário do roblox não existe","escribe los datos para poder probar.":"digite os dados para poder testar.","error: {0}":"erro: {0}","error":"erro","error al iniciar sesión":"erro ao entrar","no se pudo contactar con el servidor":"não foi possível contatar o servidor","usuario o contraseña incorrectos":"usuário ou senha incorretos","demasiados intentos, espera 5 min":"muitas tentativas, espere 5 min","no se pudo abrir":"não foi possível abrir","cuenta bloqueada: desbloquéala en el portal (ajustes)":"conta bloqueada: desbloqueie no portal (configurações)","no existe el usuario «{0}»":"o usuário «{0}» não existe","ya es tuya":"já é sua","para ver widgets en este pc instala qt: pip install pyside6":"para ver widgets neste pc instale o qt:\\n\\npip install PySide6","widgets":"widgets","hola,":"olá,","versión mayor detectada":"versão maior detectada","tienes una versión mayor a la del servidor (app {0}, servidor {1}), la app no puede iniciar correctamente en este estándar, desinstala la app y vuelve a instalar la versión oficial":"você tem uma versão maior que a do servidor (app {0}, servidor {1}); o app não consegue iniciar corretamente neste padrão, desinstale o app e instale a versão oficial novamente","salir de la app":"sair do app","iniciar sesión con cuenta de depuración":"entrar com conta de depuração"},"pi":{"idioma":"Lengua de pirata","salir":"Zarpar","abrir":"Abrir","abrir portal":"Abrir el puerto","editar widgets (portal)":"Editar banderas (puerto)","mover widgets":"Mover banderas","compartir actividad (app activa)":"Compartir actividad (barco activo)","conectar steam…":"Conectar Steam…","conectar roblox…":"Conectar Roblox…","iniciar con windows":"Zarpar con Windows","cerrar sesión":"Abandonar el barco","hub: en línea":"Hub: en alta mar","hub: sin conexión":"Hub: a la deriva","hub: sin sesión":"Hub: sin tripulación","sin conexión":"a la deriva","en línea":"En alta mar","sin sesión":"Sin tripulación","mías":"Mías","compartidas":"Compartidas","servicios":"Servicios","servicios ▾":"Servicios ▾","steam":"Steam","roblox":"Roblox","conectar steam":"Conectar Steam","conectar roblox":"Conectar Roblox","widgets del escritorio…":"Banderas del escritorio…","entra al portal para administrar más opciones":"Entra al puerto para gestionar más opciones","inicia sesión para ver tus variables y enviar los datos de este pc.":"Sube a bordo para ver tu botín y enviar los datos de este navío.","iniciar sesión":"Subir a bordo","no se pudo conectar con el hub.":"No hay forma de llegar al hub.","reintentar conexión":"Reintentar conexión","se reintenta solo cada 5 segundos.":"Se reintenta solo cada 5 segundos.","aún no tienes variables.":"¡Ni un doblón!","créalas en el portal.":"Créalo en el puerto.","nada compartido contigo todavía.":"Nadie ha compartido su botín contigo todavía.","de {0}":"de {0}","cancelar":"Cancelar","cerrar":"Cerrar","guardar":"Guardar","guardar y probar":"Guardar y probar","eliminar":"¡Al agua!","quitar":"Quitar","probando…":"Probando…","conectando…":"Conectando…","un momento…":"Un momento…","nuevo valor:":"Nuevo valor:","compartir variable":"Compartir botín","compartida con (solo lectura):":"Compartida con (solo catalejo):","todavía con nadie.":"Todavía con nadie.","añadir usuario":"Añadir pirata","usuario":"Nombre de pirata","contraseña":"Contraseña secreta","dirección del hub":"Dirección del hub","servicio en la nube":"Servicio en las nubes","servidor local":"Puerto propio","escribe la dirección de tu propio servidor, por ejemplo http://192.168.1.10:8765":"Escribe la dirección de tu propio puerto, por ejemplo http://192.168.1.10:8765","usa el servicio en la nube de hub ({0})":"Usa el servicio en las nubes de hub ({0})","conectar {0}":"Conectar {0}","api key (gratis en steamcommunity.com/dev/apikey)":"Api key (gratis en steamcommunity.com/dev/apikey)","tu id numérica o nombre de perfil":"Tu id numérica o nombre de perfil","tu nombre de usuario":"Tu nombre de pirata","da el juego actual y las horas jugadas (totales y de las últimas 2 semanas). para ver las horas, pon «detalles del juego» en público en tu perfil de steam.":"Da el juego actual y las horas jugadas (totales y de las últimas 2 semanas). Para ver las horas, pon «detalles del juego» en público en tu perfil de Steam.","solo datos públicos: amigos, seguidores y visitas a los juegos que creaste. el tiempo jugado se mide con «compartir actividad» en el menú del icono.":"Solo datos públicos: camaradas, seguidores y visitas a los juegos que creaste. El tiempo jugado se mide con «Compartir actividad» en el menú del icono.","los datos se guardan solo en este pc y los consulta este programa; el hub nunca los ve. deja los campos vacíos para desactivarlo.":"Los datos se guardan solo en este navío y los consulta este programa; el hub nunca los ve. Deja los campos vacíos para desactivarlo.","¿cerrar sesión? este pc dejará de enviar datos y los widgets se ocultarán.":"¿Abandonar el barco? Este navío dejará de enviar datos y las banderas se ocultarán.","¿eliminar «{0}»?":"¿Tirar «{0}» por la borda?","sin respuesta":"Sin respuesta","actualización grande":"¡Gran reparación!","tu dispositivo no tiene la versión más reciente y las nuevas funciones no funcionarán, actualiza el cliente para disfrutar de la actualización al 100%.":"Tu navío no tiene la versión más reciente y las nuevas funciones no funcionarán, ¡repara el cliente para disfrutar la reparación al 100%!","instalar update":"¡Instalar reparación!","ignorar (no recomendado)":"Ignorar (no recomendado, grumete)","actualiza el cliente":"¡Repara el cliente!","esta versión es muy antigua y no puede correr en estos estándares, actualiza ahora.":"Esta versión es más vieja que el Pez Espada y no navega en estos mares, ¡repara ahora!","descargando e instalando… el agente se reiniciará solo.":"Descargando e instalando… el agente se reiniciará solo.","no se pudo actualizar: {0}":"No se pudo reparar: {0}","no se pudo actualizar:":"No se pudo reparar: ","el servidor todavía no tiene el agente nuevo":"El puerto todavía no tiene el agente nuevo","ok (juego actual). tus horas son privadas: en steam pon «detalles del juego» en público":"Vale (juego actual). Tus horas son privadas: en Steam pon «detalles del juego» en público","ok":"¡Vale!","perfil no encontrado":"Perfil no encontrado","no existe ese nombre de perfil":"No existe ese nombre de perfil","no existe ese usuario de roblox":"No existe ese pirata de Roblox","escribe los datos para poder probar.":"Escribe los datos para poder probar.","error: {0}":"¡Error!: {0}","error":"¡Error!","error al iniciar sesión":"Error al subir a bordo","no se pudo contactar con el servidor":"¡No hay forma de contactar al puerto!","usuario o contraseña incorrectos":"¡Nombre o contraseña erróneos, polizón!","demasiados intentos, espera 5 min":"¡Demasiados intentos! Espera 5 min en la bodega","no se pudo abrir":"No se pudo abrir","cuenta bloqueada: desbloquéala en el portal (ajustes)":"Cofre con candado: ábrelo en el portal (Timón)","no existe el usuario «{0}»":"No existe el pirata «{0}»","ya es tuya":"¡Ya es tuya, capitán!","para ver widgets en este pc instala qt: pip install pyside6":"Para ver banderas en este navío instala Qt:\\n\\npip install PySide6","widgets":"Banderas","hola,":"¡Ahoy,","versión mayor detectada":"¡Versión mayor detectada!","tienes una versión mayor a la del servidor (app {0}, servidor {1}), la app no puede iniciar correctamente en este estándar, desinstala la app y vuelve a instalar la versión oficial":"Tienes una versión mayor a la del servidor (app {0}, servidor {1}), la app no puede zarpar correctamente en este estándar, desinstala la app y vuelve a instalar la versión oficial","salir de la app":"Zarpar de la app","iniciar sesión con cuenta de depuración":"Subir a bordo con cofre de depuración"}}'
I18N_JS = r'''/* Traduce el sitio: español (original), inglés, portugués y pirata.
 * El texto del programa está escrito en español; aquí se busca cada texto (sin distinguir mayúsculas) en la tabla del idioma
 * elegido y se sustituye. Funciona sobre el DOM (incluido lo que se crea después) y sobre toast/confirm.
 * Los datos del usuario (nombres de variables, equipos, etc.) no se tocan. Generado por tools/build_i18n.py. */
(function (g) {
  "use strict";
  const LANGS = ["es", "en", "pt", "pi"];
  const NAMES = { es: "Español", en: "English", pt: "Português", pi: "Pirata ☠" };
  const DATA = {"en":{"idioma":"language","salir":"quit","abrir":"open","abrir portal":"open portal","editar widgets (portal)":"edit widgets (portal)","mover widgets":"move widgets","compartir actividad (app activa)":"share activity (active app)","conectar steam…":"connect steam…","conectar roblox…":"connect roblox…","iniciar con windows":"start with windows","cerrar sesión":"sign out","hub: en línea":"hub: online","hub: sin conexión":"hub: offline","hub: sin sesión":"hub: signed out","sin conexión":"offline","en línea":"online","sin sesión":"signed out","mías":"mine","compartidas":"shared","servicios":"services","servicios ▾":"services ▾","steam":"steam","roblox":"roblox","conectar steam":"connect steam","conectar roblox":"connect roblox","widgets del escritorio…":"desktop widgets…","entra al portal para administrar más opciones":"go to the portal to manage more options","inicia sesión para ver tus variables y enviar los datos de este pc.":"sign in to see your variables and send this pc's data.","iniciar sesión":"sign in","no se pudo conectar con el hub.":"could not connect to the hub.","reintentar conexión":"retry connection","se reintenta solo cada 5 segundos.":"it retries by itself every 5 seconds.","aún no tienes variables.":"you have no variables yet.","créalas en el portal.":"create them in the portal.","nada compartido contigo todavía.":"nothing shared with you yet.","de {0}":"from {0}","cancelar":"cancel","cerrar":"close","guardar":"save","guardar y probar":"save and test","eliminar":"delete","quitar":"remove","probando…":"testing…","conectando…":"connecting…","un momento…":"one moment…","nuevo valor:":"new value:","compartir variable":"share variable","compartida con (solo lectura):":"shared with (read-only):","todavía con nadie.":"with nobody yet.","añadir usuario":"add user","usuario":"username","contraseña":"password","dirección del hub":"hub address","servicio en la nube":"cloud service","servidor local":"local server","escribe la dirección de tu propio servidor, por ejemplo http://192.168.1.10:8765":"type the address of your own server, for example http://192.168.1.10:8765","usa el servicio en la nube de hub ({0})":"uses hub's cloud service ({0})","conectar {0}":"connect {0}","api key (gratis en steamcommunity.com/dev/apikey)":"api key (free at steamcommunity.com/dev/apikey)","tu id numérica o nombre de perfil":"your numeric id or profile name","tu nombre de usuario":"your username","da el juego actual y las horas jugadas (totales y de las últimas 2 semanas). para ver las horas, pon «detalles del juego» en público en tu perfil de steam.":"gives the current game and the hours played (total and last 2 weeks). to see the hours, set «game details» to public in your steam profile.","solo datos públicos: amigos, seguidores y visitas a los juegos que creaste. el tiempo jugado se mide con «compartir actividad» en el menú del icono.":"public data only: friends, followers and visits to the games you made. play time is measured with «share activity» in the icon menu.","los datos se guardan solo en este pc y los consulta este programa; el hub nunca los ve. deja los campos vacíos para desactivarlo.":"the data is saved only on this pc and queried by this program; the hub never sees it. leave the fields empty to turn it off.","¿cerrar sesión? este pc dejará de enviar datos y los widgets se ocultarán.":"sign out? this pc will stop sending data and the widgets will be hidden.","¿eliminar «{0}»?":"delete «{0}»?","sin respuesta":"no response","actualización grande":"major update","tu dispositivo no tiene la versión más reciente y las nuevas funciones no funcionarán, actualiza el cliente para disfrutar de la actualización al 100%.":"your device doesn't have the latest version and the new features won't work; update the client to enjoy the update at 100%.","instalar update":"install update","ignorar (no recomendado)":"ignore (not recommended)","actualiza el cliente":"update the client","esta versión es muy antigua y no puede correr en estos estándares, actualiza ahora.":"this version is very old and can't run under these standards; update now.","descargando e instalando… el agente se reiniciará solo.":"downloading and installing… the agent will restart by itself.","no se pudo actualizar: {0}":"could not update: {0}","no se pudo actualizar:":"could not update: ","el servidor todavía no tiene el agente nuevo":"the server doesn't have the new agent yet","ok (juego actual). tus horas son privadas: en steam pon «detalles del juego» en público":"ok (current game). your hours are private: in steam set «game details» to public","ok":"ok","perfil no encontrado":"profile not found","no existe ese nombre de perfil":"that profile name doesn't exist","no existe ese usuario de roblox":"that roblox user doesn't exist","escribe los datos para poder probar.":"type the details so it can be tested.","error: {0}":"error: {0}","error":"error","error al iniciar sesión":"error signing in","no se pudo contactar con el servidor":"could not reach the server","usuario o contraseña incorrectos":"wrong username or password","demasiados intentos, espera 5 min":"too many attempts, wait 5 min","no se pudo abrir":"could not open","cuenta bloqueada: desbloquéala en el portal (ajustes)":"account locked: unlock it in the portal (settings)","no existe el usuario «{0}»":"user «{0}» does not exist","ya es tuya":"it's already yours","para ver widgets en este pc instala qt: pip install pyside6":"to see widgets on this pc install qt:\n\npip install PySide6","widgets":"widgets","hola,":"hello,","versión mayor detectada":"newer version detected","tienes una versión mayor a la del servidor (app {0}, servidor {1}), la app no puede iniciar correctamente en este estándar, desinstala la app y vuelve a instalar la versión oficial":"you have a newer version than the server's (app {0}, server {1}); the app can't start properly under this standard, uninstall the app and install the official version again","salir de la app":"exit the app","iniciar sesión con cuenta de depuración":"sign in with a debug account"},"pt":{"idioma":"idioma","salir":"sair","abrir":"abrir","abrir portal":"abrir portal","editar widgets (portal)":"editar widgets (portal)","mover widgets":"mover widgets","compartir actividad (app activa)":"compartilhar atividade (app ativo)","conectar steam…":"conectar steam…","conectar roblox…":"conectar roblox…","iniciar con windows":"iniciar com o windows","cerrar sesión":"sair","hub: en línea":"hub: online","hub: sin conexión":"hub: sem conexão","hub: sin sesión":"hub: sem sessão","sin conexión":"sem conexão","en línea":"online","sin sesión":"sem sessão","mías":"minhas","compartidas":"compartilhadas","servicios":"serviços","servicios ▾":"serviços ▾","steam":"steam","roblox":"roblox","conectar steam":"conectar steam","conectar roblox":"conectar roblox","widgets del escritorio…":"widgets da área de trabalho…","entra al portal para administrar más opciones":"entre no portal para gerenciar mais opções","inicia sesión para ver tus variables y enviar los datos de este pc.":"entre para ver suas variáveis e enviar os dados deste pc.","iniciar sesión":"entrar","no se pudo conectar con el hub.":"não foi possível conectar ao hub.","reintentar conexión":"tentar conectar de novo","se reintenta solo cada 5 segundos.":"tenta de novo sozinho a cada 5 segundos.","aún no tienes variables.":"você ainda não tem variáveis.","créalas en el portal.":"crie-as no portal.","nada compartido contigo todavía.":"nada compartilhado com você ainda.","de {0}":"de {0}","cancelar":"cancelar","cerrar":"fechar","guardar":"salvar","guardar y probar":"salvar e testar","eliminar":"excluir","quitar":"remover","probando…":"testando…","conectando…":"conectando…","un momento…":"um momento…","nuevo valor:":"novo valor:","compartir variable":"compartilhar variável","compartida con (solo lectura):":"compartilhada com (somente leitura):","todavía con nadie.":"com ninguém ainda.","añadir usuario":"adicionar usuário","usuario":"usuário","contraseña":"senha","dirección del hub":"endereço do hub","servicio en la nube":"serviço na nuvem","servidor local":"servidor local","escribe la dirección de tu propio servidor, por ejemplo http://192.168.1.10:8765":"digite o endereço do seu próprio servidor, por exemplo http://192.168.1.10:8765","usa el servicio en la nube de hub ({0})":"usa o serviço na nuvem do hub ({0})","conectar {0}":"conectar {0}","api key (gratis en steamcommunity.com/dev/apikey)":"api key (grátis em steamcommunity.com/dev/apikey)","tu id numérica o nombre de perfil":"seu id numérico ou nome de perfil","tu nombre de usuario":"seu nome de usuário","da el juego actual y las horas jugadas (totales y de las últimas 2 semanas). para ver las horas, pon «detalles del juego» en público en tu perfil de steam.":"informa o jogo atual e as horas jogadas (totais e das últimas 2 semanas). para ver as horas, deixe «detalhes do jogo» público no seu perfil da steam.","solo datos públicos: amigos, seguidores y visitas a los juegos que creaste. el tiempo jugado se mide con «compartir actividad» en el menú del icono.":"apenas dados públicos: amigos, seguidores e visitas aos jogos que você criou. o tempo jogado é medido com «compartilhar atividade» no menu do ícone.","los datos se guardan solo en este pc y los consulta este programa; el hub nunca los ve. deja los campos vacíos para desactivarlo.":"os dados ficam salvos só neste pc e são consultados por este programa; o hub nunca os vê. deixe os campos vazios para desativar.","¿cerrar sesión? este pc dejará de enviar datos y los widgets se ocultarán.":"sair? este pc deixará de enviar dados e os widgets serão ocultados.","¿eliminar «{0}»?":"excluir «{0}»?","sin respuesta":"sem resposta","actualización grande":"atualização grande","tu dispositivo no tiene la versión más reciente y las nuevas funciones no funcionarán, actualiza el cliente para disfrutar de la actualización al 100%.":"seu dispositivo não tem a versão mais recente e as novas funções não vão funcionar; atualize o cliente para aproveitar a atualização a 100%.","instalar update":"instalar atualização","ignorar (no recomendado)":"ignorar (não recomendado)","actualiza el cliente":"atualize o cliente","esta versión es muy antigua y no puede correr en estos estándares, actualiza ahora.":"esta versão é muito antiga e não pode rodar nesses padrões; atualize agora.","descargando e instalando… el agente se reiniciará solo.":"baixando e instalando… o agente reiniciará sozinho.","no se pudo actualizar: {0}":"não foi possível atualizar: {0}","no se pudo actualizar:":"não foi possível atualizar: ","el servidor todavía no tiene el agente nuevo":"o servidor ainda não tem o agente novo","ok (juego actual). tus horas son privadas: en steam pon «detalles del juego» en público":"ok (jogo atual). suas horas são privadas: na steam deixe «detalhes do jogo» público","ok":"ok","perfil no encontrado":"perfil não encontrado","no existe ese nombre de perfil":"esse nome de perfil não existe","no existe ese usuario de roblox":"esse usuário do roblox não existe","escribe los datos para poder probar.":"digite os dados para poder testar.","error: {0}":"erro: {0}","error":"erro","error al iniciar sesión":"erro ao entrar","no se pudo contactar con el servidor":"não foi possível contatar o servidor","usuario o contraseña incorrectos":"usuário ou senha incorretos","demasiados intentos, espera 5 min":"muitas tentativas, espere 5 min","no se pudo abrir":"não foi possível abrir","cuenta bloqueada: desbloquéala en el portal (ajustes)":"conta bloqueada: desbloqueie no portal (configurações)","no existe el usuario «{0}»":"o usuário «{0}» não existe","ya es tuya":"já é sua","para ver widgets en este pc instala qt: pip install pyside6":"para ver widgets neste pc instale o qt:\n\npip install PySide6","widgets":"widgets","hola,":"olá,","versión mayor detectada":"versão maior detectada","tienes una versión mayor a la del servidor (app {0}, servidor {1}), la app no puede iniciar correctamente en este estándar, desinstala la app y vuelve a instalar la versión oficial":"você tem uma versão maior que a do servidor (app {0}, servidor {1}); o app não consegue iniciar corretamente neste padrão, desinstale o app e instale a versão oficial novamente","salir de la app":"sair do app","iniciar sesión con cuenta de depuración":"entrar com conta de depuração"},"pi":{"idioma":"Lengua de pirata","salir":"Zarpar","abrir":"Abrir","abrir portal":"Abrir el puerto","editar widgets (portal)":"Editar banderas (puerto)","mover widgets":"Mover banderas","compartir actividad (app activa)":"Compartir actividad (barco activo)","conectar steam…":"Conectar Steam…","conectar roblox…":"Conectar Roblox…","iniciar con windows":"Zarpar con Windows","cerrar sesión":"Abandonar el barco","hub: en línea":"Hub: en alta mar","hub: sin conexión":"Hub: a la deriva","hub: sin sesión":"Hub: sin tripulación","sin conexión":"a la deriva","en línea":"En alta mar","sin sesión":"Sin tripulación","mías":"Mías","compartidas":"Compartidas","servicios":"Servicios","servicios ▾":"Servicios ▾","steam":"Steam","roblox":"Roblox","conectar steam":"Conectar Steam","conectar roblox":"Conectar Roblox","widgets del escritorio…":"Banderas del escritorio…","entra al portal para administrar más opciones":"Entra al puerto para gestionar más opciones","inicia sesión para ver tus variables y enviar los datos de este pc.":"Sube a bordo para ver tu botín y enviar los datos de este navío.","iniciar sesión":"Subir a bordo","no se pudo conectar con el hub.":"No hay forma de llegar al hub.","reintentar conexión":"Reintentar conexión","se reintenta solo cada 5 segundos.":"Se reintenta solo cada 5 segundos.","aún no tienes variables.":"¡Ni un doblón!","créalas en el portal.":"Créalo en el puerto.","nada compartido contigo todavía.":"Nadie ha compartido su botín contigo todavía.","de {0}":"de {0}","cancelar":"Cancelar","cerrar":"Cerrar","guardar":"Guardar","guardar y probar":"Guardar y probar","eliminar":"¡Al agua!","quitar":"Quitar","probando…":"Probando…","conectando…":"Conectando…","un momento…":"Un momento…","nuevo valor:":"Nuevo valor:","compartir variable":"Compartir botín","compartida con (solo lectura):":"Compartida con (solo catalejo):","todavía con nadie.":"Todavía con nadie.","añadir usuario":"Añadir pirata","usuario":"Nombre de pirata","contraseña":"Contraseña secreta","dirección del hub":"Dirección del hub","servicio en la nube":"Servicio en las nubes","servidor local":"Puerto propio","escribe la dirección de tu propio servidor, por ejemplo http://192.168.1.10:8765":"Escribe la dirección de tu propio puerto, por ejemplo http://192.168.1.10:8765","usa el servicio en la nube de hub ({0})":"Usa el servicio en las nubes de hub ({0})","conectar {0}":"Conectar {0}","api key (gratis en steamcommunity.com/dev/apikey)":"Api key (gratis en steamcommunity.com/dev/apikey)","tu id numérica o nombre de perfil":"Tu id numérica o nombre de perfil","tu nombre de usuario":"Tu nombre de pirata","da el juego actual y las horas jugadas (totales y de las últimas 2 semanas). para ver las horas, pon «detalles del juego» en público en tu perfil de steam.":"Da el juego actual y las horas jugadas (totales y de las últimas 2 semanas). Para ver las horas, pon «detalles del juego» en público en tu perfil de Steam.","solo datos públicos: amigos, seguidores y visitas a los juegos que creaste. el tiempo jugado se mide con «compartir actividad» en el menú del icono.":"Solo datos públicos: camaradas, seguidores y visitas a los juegos que creaste. El tiempo jugado se mide con «Compartir actividad» en el menú del icono.","los datos se guardan solo en este pc y los consulta este programa; el hub nunca los ve. deja los campos vacíos para desactivarlo.":"Los datos se guardan solo en este navío y los consulta este programa; el hub nunca los ve. Deja los campos vacíos para desactivarlo.","¿cerrar sesión? este pc dejará de enviar datos y los widgets se ocultarán.":"¿Abandonar el barco? Este navío dejará de enviar datos y las banderas se ocultarán.","¿eliminar «{0}»?":"¿Tirar «{0}» por la borda?","sin respuesta":"Sin respuesta","actualización grande":"¡Gran reparación!","tu dispositivo no tiene la versión más reciente y las nuevas funciones no funcionarán, actualiza el cliente para disfrutar de la actualización al 100%.":"Tu navío no tiene la versión más reciente y las nuevas funciones no funcionarán, ¡repara el cliente para disfrutar la reparación al 100%!","instalar update":"¡Instalar reparación!","ignorar (no recomendado)":"Ignorar (no recomendado, grumete)","actualiza el cliente":"¡Repara el cliente!","esta versión es muy antigua y no puede correr en estos estándares, actualiza ahora.":"Esta versión es más vieja que el Pez Espada y no navega en estos mares, ¡repara ahora!","descargando e instalando… el agente se reiniciará solo.":"Descargando e instalando… el agente se reiniciará solo.","no se pudo actualizar: {0}":"No se pudo reparar: {0}","no se pudo actualizar:":"No se pudo reparar: ","el servidor todavía no tiene el agente nuevo":"El puerto todavía no tiene el agente nuevo","ok (juego actual). tus horas son privadas: en steam pon «detalles del juego» en público":"Vale (juego actual). Tus horas son privadas: en Steam pon «detalles del juego» en público","ok":"¡Vale!","perfil no encontrado":"Perfil no encontrado","no existe ese nombre de perfil":"No existe ese nombre de perfil","no existe ese usuario de roblox":"No existe ese pirata de Roblox","escribe los datos para poder probar.":"Escribe los datos para poder probar.","error: {0}":"¡Error!: {0}","error":"¡Error!","error al iniciar sesión":"Error al subir a bordo","no se pudo contactar con el servidor":"¡No hay forma de contactar al puerto!","usuario o contraseña incorrectos":"¡Nombre o contraseña erróneos, polizón!","demasiados intentos, espera 5 min":"¡Demasiados intentos! Espera 5 min en la bodega","no se pudo abrir":"No se pudo abrir","cuenta bloqueada: desbloquéala en el portal (ajustes)":"Cofre con candado: ábrelo en el portal (Timón)","no existe el usuario «{0}»":"No existe el pirata «{0}»","ya es tuya":"¡Ya es tuya, capitán!","para ver widgets en este pc instala qt: pip install pyside6":"Para ver banderas en este navío instala Qt:\n\npip install PySide6","widgets":"Banderas","hola,":"¡Ahoy,","versión mayor detectada":"¡Versión mayor detectada!","tienes una versión mayor a la del servidor (app {0}, servidor {1}), la app no puede iniciar correctamente en este estándar, desinstala la app y vuelve a instalar la versión oficial":"Tienes una versión mayor a la del servidor (app {0}, servidor {1}), la app no puede zarpar correctamente en este estándar, desinstala la app y vuelve a instalar la versión oficial","salir de la app":"Zarpar de la app","iniciar sesión con cuenta de depuración":"Subir a bordo con cofre de depuración"}};
  const norm = s => String(s).replace(/\s+/g, " ").trim().toLowerCase();
  const pats = {};
  let lang = "es";
  const missing = new Set();

  function compile(l) {
    if (pats[l]) return pats[l];
    const out = pats[l] = [];
    const d = DATA[l] || {};
    for (const k in d) {
      if (!/\{\d\}/.test(k)) continue;
      const esc = k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\\\{(\d)\\\}/g, "(.+?)");
      out.push([new RegExp("^" + esc + "$", "i"), d[k]]);
    }
    out.sort((a, b) => b[0].source.length - a[0].source.length);
    return out;
  }

  /* tr: traduce un texto completo; si no hay traducción devuelve el mismo texto */
  function tr(s) {
    if (lang === "es" || s == null) return s;
    s = String(s);
    const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(s), core = m[2].replace(/\s+/g, " ");
    if (!core) return s;
    const d = DATA[lang] || {};
    const n = core.toLowerCase();
    if (Object.prototype.hasOwnProperty.call(d, n)) return m[1] + d[n] + m[3];
    for (const [re, t] of compile(lang)) {
      const x = re.exec(core);
      if (x) return m[1] + t.replace(/\{(\d)\}/g, (_, i) => x[+i + 1] ?? "") + m[3];
    }
    return s;
  }

  const SKIP = ".vname,.vval,.dname,.wt,.u,.sh span,.pkrow span,.tok b,.tok i,[translate=no],script,style,textarea,code,pre,#stage";
  const ATTRS = ["placeholder", "title", "aria-label", "alt"];
  const skipEl = el => !el || (el.closest && el.closest(SKIP));
  const hasWords = s => /[A-Za-zÀ-ÿ]{3,}/.test(s);

  function doText(n) {
    const p = n.parentElement;
    if (!p || skipEl(p)) return;
    const meta = n.__i18n;
    const src = meta && n.nodeValue === meta.out ? meta.src : n.nodeValue;
    const out = lang === "es" ? src : tr(src);
    if (out !== n.nodeValue) n.nodeValue = out;
    n.__i18n = { src, out };
    if (lang !== "es" && out === src && hasWords(src)) missing.add(src.trim());
  }

  function doAttr(el, a) {
    if (skipEl(el)) return;
    const v = el.getAttribute(a);
    if (v == null) return;
    const meta = (el.__i18na = el.__i18na || {})[a];
    const src = meta && v === meta.out ? meta.src : v;
    const out = lang === "es" ? src : tr(src);
    if (out !== v) el.setAttribute(a, out);
    el.__i18na[a] = { src, out };
  }

  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) return doText(root);
    if (root.nodeType !== 1) return;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    let n = root.nodeType === 1 ? root : w.nextNode();
    const visit = x => {
      if (x.nodeType === 3) doText(x);
      else for (const a of ATTRS) if (x.hasAttribute && x.hasAttribute(a)) doAttr(x, a);
    };
    visit(root);
    while ((n = w.nextNode())) visit(n);
  }

  let obs = null;
  function start() {
    if (obs || !document.body) return;
    obs = new MutationObserver(ms => {
      for (const m of ms) {
        if (m.type === "childList") m.addedNodes.forEach(walk);
        else if (m.type === "characterData") doText(m.target);
        else if (m.type === "attributes") doAttr(m.target, m.attributeName);
      }
    });
    obs.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    walk(document.body);
  }

  function apply() {
    document.documentElement.setAttribute("lang", lang === "pi" ? "es" : lang);
    document.documentElement.setAttribute("data-lang", lang);
    g.HUB_LANG = lang;
    if (document.body) walk(document.body);
    document.title = lang === "es" ? "hub" : tr("hub");
  }

  function detect() {
    if (LANGS.includes(g.HUB_FORCE_LANG)) return g.HUB_FORCE_LANG;               // lo fija el agente de Windows
    try { if (g.HubApp && g.HubApp.lang && LANGS.includes(g.HubApp.lang())) return g.HubApp.lang(); } catch (e) { /* ignorar */ }   // la app de Android manda
    try {
      const s = localStorage.getItem("lang");
      if (LANGS.includes(s)) return s;
    } catch (e) { /* sin almacenamiento */ }
    for (const l of navigator.languages || [navigator.language || "es"]) {
      const c = String(l).slice(0, 2).toLowerCase();
      if (c === "en" || c === "pt" || c === "es") return c;
    }
    return "es";
  }

  function setLang(l, save) {
    if (!LANGS.includes(l)) return;
    lang = l;
    if (save !== false) try { if (g.HubApp && g.HubApp.setLang) g.HubApp.setLang(l); } catch (e) { /* ignorar */ }
    if (save !== false) try { localStorage.setItem("lang", l); } catch (e) { /* ignorar */ }
    apply();
    (g.HubI18n.listeners || []).forEach(f => { try { f(l); } catch (e) { /* ignorar */ } });
  }

  const locale = () => ({ es: "es", en: "en", pt: "pt-BR", pi: "es" }[lang]);

  // confirm() y alert() de texto fijo
  for (const f of ["confirm", "alert"]) {
    const orig = g[f] && g[f].bind(g);
    if (orig) g[f] = m => orig(tr(m));
  }

  lang = detect();
  g.HUB_LANG = lang;
  g.HubI18n = { tr, T: tr, setLang, lang: () => lang, LANGS, NAMES, locale, missing, listeners: [], data: DATA };
  document.documentElement.setAttribute("data-lang", lang);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => { apply(); start(); });
  else { apply(); start(); }
})(window);
'''
# </i18n-agente>


_I18N = None


def norm_key(t):
    return " ".join(str(t).split()).lower()


def detect_lang():
    """Idioma del sistema (es, en o pt); otro cualquiera -> es."""
    try:
        import locale
        code = (locale.getlocale()[0] or locale.getdefaultlocale()[0] or "es")[:2].lower()
    except Exception:
        code = "es"
    return code if code in ("en", "pt", "es") else "es"


def current_lang():
    l = load_config().get("lang")
    return l if l in ("es", "en", "pt", "pi") else detect_lang()


def tr(text, *args):
    """Traduce un texto fijo al idioma elegido (la clave es el texto en español); {0}, {1}... se rellenan con args."""
    global _I18N
    lang = current_lang()
    out = str(text)
    if lang != "es":
        if _I18N is None:
            _I18N = json.loads(I18N_DATA)
        out = _I18N.get(lang, {}).get(norm_key(text), out)
    for i, a in enumerate(args):
        out = out.replace("{%d}" % i, str(a))
    return out


def pythonw():
    """El Python sin ventana de consola (pythonw.exe) junto al actual; si no existe, el actual."""
    w = Path(sys.executable).with_name("pythonw.exe")
    return str(w) if w.exists() else sys.executable


def console_python():
    """El Python normal: lo usan los procesos hijos (con CREATE_NO_WINDOW) porque necesitan stdin/stdout validos."""
    c = Path(sys.executable).with_name("python.exe")
    return str(c) if c.exists() else sys.executable


def make_shortcut():
    """Crea en el escritorio un acceso directo «Hub» que abre el agente sin ventana de consola."""
    import subprocess
    target, here = pythonw(), str(Path(__file__).resolve().parent)
    ps = ("$d=[Environment]::GetFolderPath('Desktop');$s=(New-Object -ComObject WScript.Shell).CreateShortcut(\"$d\\Hub.lnk\");"
          f"$s.TargetPath='{target}';$s.Arguments='\"{Path(__file__).resolve()}\"';$s.WorkingDirectory='{here}';"
          f"$s.IconLocation='{target}';$s.Description='Hub';$s.Save();Write-Output \"$d\\Hub.lnk\"")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, creationflags=0x08000000)
    return out.stdout.strip() or out.stderr.strip()


def ver_level(v):
    import re
    m = re.match(r"(\d+)\.(\d+)", str(v or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def ver_outdated(client, server):
    """True si `client` tiene menos funciones que `server` (se comparan solo los dos primeros numeros)."""
    return ver_level(client) < ver_level(server)


def load_config():
    try:
        return json.loads(CONFIG.read_text("utf-8-sig"))   # tolera el BOM que a veces añade el Bloc de notas
    except (OSError, ValueError):
        return {}


def save_config(patch):
    """Mezcla `patch` con lo guardado; un valor None borra esa clave."""
    cfg = {**load_config(), **patch}
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps({k: v for k, v in cfg.items() if v is not None}), "utf8")


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def greeting(hour):
    return "buenos días" if hour < 12 else "buenas tardes" if hour < 20 else "buenas noches"


def fmt(v):
    if v["kind"] != "auto":
        return v.get("value") or ""
    if not v.get("online"):
        return tr("sin conexión")
    val = v.get("value")
    if val is None:
        return "—"
    if v["metric"] == "apptime":
        return f"{val // 60} h {val % 60} min" if val >= 60 else f"{val} min"
    return f'{val}{UNIT.get(v["metric"], "")}'


SLOW = {}          # lecturas lentas (temperatura, GPU, volumen, bloqueo): las refresca un hilo aparte
NET = {"t": 0.0, "rx": 0, "tx": 0}


def run_quiet(cmd, timeout=8):
    """Ejecuta un comando sin ventana y devuelve su salida (o '' si falla)."""
    import subprocess
    try:
        kw = {"creationflags": 0x08000000} if platform.system() == "Windows" else {}
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, **kw).stdout
    except Exception:
        return ""


def master_volume():
    """Volumen general de Windows (0-100) con la API de audio del sistema; None si no se puede."""
    if platform.system() != "Windows":
        return None
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

    def guid(s):
        return GUID.from_buffer_copy(uuid.UUID(s).bytes_le)

    def call(ptr, idx, *types_and_args):
        vt = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        types = [t for t, _ in types_and_args]
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *types)(vt[idx])(ptr, *[a for _, a in types_and_args])

    ole = ctypes.windll.ole32
    ole.CoInitializeEx(None, 2)
    enum, dev, vol = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    try:
        if ole.CoCreateInstance(ctypes.byref(guid("BCDE0395-E52F-467C-8E3D-C4579291692E")), None, 23,
                                ctypes.byref(guid("A95664D2-9614-4F35-A746-DE8DB63617E6")), ctypes.byref(enum)) != 0:
            return None
        if call(enum, 4, (ctypes.c_int, 0), (ctypes.c_int, 1), (ctypes.POINTER(ctypes.c_void_p), ctypes.byref(dev))) != 0:
            return None
        if call(dev, 3, (ctypes.POINTER(GUID), ctypes.byref(guid("5CDF2C82-841E-4546-9722-0CF74078229A"))), (wintypes.DWORD, 23),
                (ctypes.c_void_p, None), (ctypes.POINTER(ctypes.c_void_p), ctypes.byref(vol))) != 0:
            return None
        level = ctypes.c_float()
        if call(vol, 9, (ctypes.POINTER(ctypes.c_float), ctypes.byref(level))) != 0:
            return None
        return round(level.value * 100)
    except Exception:
        return None
    finally:
        for p in (vol, dev, enum):
            if p.value:
                call(p, 2)


def cpu_temp():
    try:
        t = psutil.sensors_temperatures()   # Linux
        vals = [x.current for lst in t.values() for x in lst if x.current]
        if vals:
            return round(max(vals), 1)
    except Exception:
        pass
    if platform.system() == "Windows":
        out = run_quiet(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                         "(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop | "
                         "Measure-Object CurrentTemperature -Maximum).Maximum"], 15)
        try:
            c = float(out.strip()) / 10 - 273.15
            if 0 < c < 130:
                return round(c, 1)
        except ValueError:
            pass
    return None


def gpu_usage():
    out = run_quiet(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"])
    try:
        return max(float(x) for x in out.split() if x.strip())
    except ValueError:
        pass
    if platform.system() == "Windows":   # cualquier GPU (contadores de rendimiento de Windows 10+)
        out = run_quiet(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                         "(Get-Counter '\\GPU Engine(*engtype_3D)\\Utilization Percentage' -ErrorAction Stop).CounterSamples | "
                         "Measure-Object CookedValue -Sum | Select-Object -ExpandProperty Sum"], 20)
        try:
            return min(100.0, round(float(out.strip().replace(",", ".")), 1))
        except ValueError:
            pass
    return None


def is_locked():
    """Windows: la pantalla de bloqueo (LogonUI) solo existe mientras la sesión está bloqueada."""
    if platform.system() != "Windows":
        return None
    return any((p.info.get("name") or "").lower() == "logonui.exe" for p in psutil.process_iter(["name"]))


def slow_loop():
    n = 0
    while True:
        try:
            lk = is_locked()
            SLOW["locked"] = None if lk is None else "sí" if lk else "no"
            SLOW["volume"] = master_volume()
            if n % 6 == 0:   # cada 30 s
                SLOW["cpu_temp"], SLOW["gpu"] = cpu_temp(), gpu_usage()
        except Exception:
            pass
        n += 1
        time.sleep(5)


def metrics():
    if "thread" not in SLOW:
        SLOW["thread"] = True
        threading.Thread(target=slow_loop, daemon=True).start()
    out = {"ram": psutil.virtual_memory().percent, "cpu": psutil.cpu_percent(interval=None),
           "uptime": round((time.time() - psutil.boot_time()) / 3600, 1), "procs": len(psutil.pids())}
    try:
        out["disk"] = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\" if platform.system() == "Windows" else "/").percent
        io_ = psutil.net_io_counters()
        now = time.time()
        if NET["t"]:
            dt = max(now - NET["t"], 0.5)
            out["net_down"] = round((io_.bytes_recv - NET["rx"]) / 1024 / dt, 1)
            out["net_up"] = round((io_.bytes_sent - NET["tx"]) / 1024 / dt, 1)
        NET.update(t=now, rx=io_.bytes_recv, tx=io_.bytes_sent)
    except Exception:
        pass
    for k in ("locked", "volume", "cpu_temp", "gpu"):
        if SLOW.get(k) is not None:
            out[k] = SLOW[k]
    return out


def windows_avatar():
    """Busca la imagen incrustada en el archivo .accountpicture-ms de la cuenta de Windows."""
    if platform.system() != "Windows":
        return None
    files = glob.glob(os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                                   "AccountPictures", "*.accountpicture-ms"))
    if not files:
        return None
    data = open(max(files, key=os.path.getmtime), "rb").read()
    found = []
    i = data.find(b"\x89PNG\r\n\x1a\n")
    while i != -1:
        end = data.find(b"IEND", i)
        if end != -1:
            found.append(("png", data[i:end + 8]))
        i = data.find(b"\x89PNG\r\n\x1a\n", i + 8)
    i = data.find(b"\xff\xd8\xff")
    while i != -1:
        end = data.find(b"\xff\xd9", i)
        if end != -1:
            found.append(("jpeg", data[i:end + 2]))
        i = data.find(b"\xff\xd8\xff", i + 3)
    if not found:
        return None
    kind, blob = max(found, key=lambda f: len(f[1]))
    return f"data:image/{kind};base64," + base64.b64encode(blob).decode()


APP_NAMES = {"msedge": "Edge", "chrome": "Chrome", "firefox": "Firefox", "robloxplayerbeta": "roblox", "code": "VS Code",
             "explorer": "Explorador", "discord": "Discord", "spotify": "Spotify", "steam": "steam", "steamwebhelper": "steam"}


def foreground_app():
    """(nombre de la app en primer plano, segundos sin tocar teclado/mouse). Solo el nombre, nunca el titulo."""
    if platform.system() != "Windows":
        return None, 0
    import ctypes
    from ctypes import wintypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    li = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    u.GetLastInputInfo(ctypes.byref(li))
    idle = ((k.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(u.GetForegroundWindow(), ctypes.byref(pid))
    try:
        stem = os.path.splitext(psutil.Process(pid.value).name())[0]
    except (psutil.Error, ValueError):
        return None, idle
    return APP_NAMES.get(stem.lower(), stem[:1] + stem[1:]), idle


def list_cameras():
    """Nombres de las camaras de ESTE PC, sin abrirlas. Necesita PySide6 (si falta, lista vacia)."""
    try:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtMultimedia import QMediaDevices
    except ImportError:
        return []
    app = QGuiApplication(sys.argv[:1])   # Qt exige una aplicacion viva para consultar los dispositivos
    return [d.description() for d in QMediaDevices.videoInputs()]


def err_text(e):
    """Texto de error SIN la URL (las consultas a Steam llevan la API key en la URL)."""
    if isinstance(e, aiohttp.ClientResponseError):
        return f"HTTP {e.status}"
    return str(e) if isinstance(e, ValueError) else type(e).__name__


# ---------------- conexion con el hub ----------------
class Link:
    """Mantiene la sesion con el hub (reconecta sola) y guarda el ultimo estado recibido."""

    def __init__(self, cfg, name, on_change):
        self.base = cfg.get("url", "").rstrip("/")
        self.user, self.token, self.name = cfg.get("user", ""), cfg.get("token"), name
        self.on_change = on_change
        self.state, self.toast, self.ws = None, "", None
        self.server_version = None
        self.debug = False   # la cuenta es depuradora: puede usar un agente más nuevo que el servidor
        self.status = "offline" if self.token else "needs_login"   # ok | offline | needs_login
        self.loop, self.wake, self.ready = None, None, threading.Event()
        self.extra, self.cache, self.last = {}, {}, {"steam": 0, "roblox": 0}   # datos de Steam/Roblox
        self.apptimes, self.apptimes_saved, self.sampled = load_config().get("apptimes") or {}, 0.0, time.time()

    def update_state(self):
        """None (al dia) | 'soft' (hay actualizacion grande) | 'hard' (pendiente hace mas de 3 semanas: bloqueado)."""
        if not self.server_version or not ver_outdated(AGENT_VERSION, self.server_version):
            if load_config().get("update_seen"):
                save_config({"update_seen": None})
            return None
        seen = load_config().get("update_seen")
        if not seen:
            seen = time.time()
            save_config({"update_seen": seen})
        return "hard" if time.time() - seen > UPDATE_LOCK_DAYS * 86400 else "soft"

    def ahead(self):
        """Este agente es de una versión mayor que la del servidor: no puede funcionar bien (salvo con una cuenta de depuración)."""
        return bool(self.state and self.server_version and ver_outdated(self.server_version, AGENT_VERSION) and not self.debug)

    def set_status(self, s):
        if s != self.status:
            self.status = s
            self.on_change()

    async def login(self, base, user, pw):
        base = base.strip().rstrip("/")
        if not base.startswith("http"):
            base = "http://" + base
        try:
            async with aiohttp.ClientSession() as s:
                r = await s.post(base + "/api/login", json={"user": user, "password": pw},
                                 timeout=aiohttp.ClientTimeout(total=10))
                d = await r.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
            raise RuntimeError("no se pudo contactar con el servidor")
        if r.status != 200:
            raise RuntimeError(d.get("error", "error al iniciar sesión"))
        self.base, self.user, self.token = base, d["user"], d["token"]
        self.debug = bool(d.get("debug"))
        save_config({"url": base, "user": self.user, "token": self.token})
        self.set_status("offline")
        self.reconnect()

    def reconnect(self):
        if self.loop:
            self.loop.call_soon_threadsafe(self.wake.set)

    def send(self, obj):
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._send(obj), self.loop)

    async def _send(self, obj):
        if self.ws and not self.ws.closed:
            await self.ws.send_json(obj)

    async def run(self):
        self.loop, self.wake = asyncio.get_running_loop(), asyncio.Event()
        self.ready.set()
        async with aiohttp.ClientSession() as session:
            while True:
                if not self.token:
                    self.set_status("needs_login")
                    await self.wake.wait()
                    self.wake.clear()
                    continue
                try:
                    await self.session(session)
                except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
                    pass
                if self.token:
                    self.set_status("offline")
                try:
                    await asyncio.wait_for(self.wake.wait(), 5)
                except asyncio.TimeoutError:
                    pass
                self.wake.clear()

    async def session(self, session):
        ws = await session.ws_connect(self.base + "/ws", max_msg_size=25 * 2**20, heartbeat=20, timeout=10)
        self.ws = ws
        tasks = []
        try:
            await ws.send_json({"type": "auth", "token": self.token})
            await ws.send_json({"type": "hello", "device_id": DEVICE_ID, "name": self.name,
                                "platform": platform.system(), "kind": "agent",
                                "client_version": AGENT_VERSION})
            asyncio.create_task(self.scan_cameras())   # al conectar, para que el editor ya conozca las camaras
            psutil.cpu_percent(interval=None)  # la primera lectura siempre es 0
            tasks = [asyncio.create_task(self.metrics_loop(ws)), asyncio.create_task(self.services_loop(session))]
            async for m in ws:
                if m.type == aiohttp.WSMsgType.TEXT and not await self.handle(json.loads(m.data)):
                    break
        finally:
            for t in tasks:
                t.cancel()
            self.ws = None

    async def metrics_loop(self, ws):
        while not ws.closed:
            if self.update_state() == "hard" or self.ahead():   # version demasiado antigua (o mas nueva que el servidor): no manda datos
                await asyncio.sleep(5)
                continue
            data = {**metrics(), **self.extra}
            if load_config().get("activity"):    # opt-in: se activa desde el menu del icono
                data.update(self.activity_sample())
            await ws.send_json({"type": "metrics", "data": data})
            await asyncio.sleep(3)

    def activity_sample(self):
        """Suma el tiempo transcurrido a la app activa (si no estas inactivo) y devuelve lo que se manda al hub."""
        now = time.time()
        dt, self.sampled = min(now - self.sampled, 10), now
        app, idle = foreground_app()
        today = time.strftime("%Y-%m-%d")
        if self.apptimes.get("date") != today:   # el contador empieza de cero cada dia
            self.apptimes = {"date": today, "t": {}}
        away = idle > 300
        if app and not away:
            t = self.apptimes["t"]
            t[app] = t.get(app, 0) + dt
        if now - self.apptimes_saved > 60:
            save_config({"apptimes": self.apptimes})
            self.apptimes_saved = now
        return {"app": "inactivo" if away else (app or "—"),
                "apptimes": {k: int(v) for k, v in self.apptimes["t"].items()}}

    async def services_loop(self, session):
        while True:
            try:
                await self.poll_services(session)
            except Exception:
                pass
            await asyncio.sleep(15)

    async def get_json(self, session, url, **kw):
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10), **kw) as r:
            r.raise_for_status()
            return await r.json(content_type=None)

    async def poll_services(self, session, force=False, only=None):
        """Consulta Steam (cada 60 s) y Roblox (cada 5 min) con los datos guardados en ESTE PC; `only` limita a uno.
        Devuelve el estado de cada servicio consultado."""
        cfg, now, res = load_config(), time.time(), {}
        key, sid = cfg.get("steam_key", "").strip(), cfg.get("steam_id", "").strip()
        if only in (None, "steam") and key and sid and (force or now - self.last["steam"] >= 60):
            self.last["steam"] = now
            try:
                res["steam"] = await self.poll_steam(session, key, sid)
            except Exception as e:
                res["steam"] = "error: " + err_text(e)
        user = cfg.get("roblox_user", "").strip()
        if only in (None, "roblox") and user and (force or now - self.last["roblox"] >= 300):
            self.last["roblox"] = now
            try:
                res["roblox"] = await self.poll_roblox(session, user)
            except Exception as e:
                res["roblox"] = "error: " + err_text(e)
        return res

    async def test_services(self, only=None):
        async with aiohttp.ClientSession() as s:
            return await self.poll_services(s, True, only)

    async def poll_steam(self, session, key, sid):
        base = "https://api.steampowered.com"
        if not sid.isdigit():   # nombre de perfil personalizado -> ID numerica
            r = await self.get_json(session, base + "/ISteamUser/ResolveVanityURL/v1/", params={"key": key, "vanityurl": sid})
            sid = r["response"].get("steamid") or ""
            if not sid:
                raise ValueError("no existe ese nombre de perfil")
        r = await self.get_json(session, base + "/ISteamUser/GetPlayerSummaries/v2/", params={"key": key, "steamids": sid})
        if not r["response"]["players"]:
            raise ValueError("perfil no encontrado")
        self.extra["steam_game"] = r["response"]["players"][0].get("gameextrainfo") or "ninguno"
        r = await self.get_json(session, base + "/IPlayerService/GetOwnedGames/v1/",
                                params={"key": key, "steamid": sid, "include_played_free_games": 1})
        games = r["response"].get("games")
        if games is None:
            return "ok (juego actual). tus horas son privadas: en steam pon «detalles del juego» en público"
        self.extra["steam_hours"] = round(sum(g.get("playtime_forever", 0) for g in games) / 60, 1)
        self.extra["steam_hours2w"] = round(sum(g.get("playtime_2weeks", 0) for g in games) / 60, 1)
        return "ok"

    async def poll_roblox(self, session, user):
        if self.cache.get("roblox_name") != user:
            async with session.post("https://users.roblox.com/v1/usernames/users", timeout=aiohttp.ClientTimeout(total=10),
                                    json={"usernames": [user], "excludeBannedUsers": True}) as r:
                r.raise_for_status()
                d = await r.json()
            if not d["data"]:
                raise ValueError("no existe ese usuario de roblox")
            self.cache.update(roblox_name=user, roblox_id=d["data"][0]["id"])
        uid = self.cache["roblox_id"]
        for k in ("friends", "followers"):
            self.extra["roblox_" + k] = (await self.get_json(session, f"https://friends.roblox.com/v1/users/{uid}/{k}/count"))["count"]
        games = (await self.get_json(session, f"https://games.roblox.com/v2/users/{uid}/games",
                                     params={"accessFilter": "Public", "limit": 50, "sortOrder": "Asc"}))["data"]
        ids = ",".join(str(g["id"]) for g in games)
        self.extra["roblox_visits"] = sum(g.get("visits", 0) for g in (await self.get_json(
            session, "https://games.roblox.com/v1/games", params={"universeIds": ids}))["data"]) if ids else 0
        return "ok"

    async def fire_webhook(self, m):
        url = str(m.get("url", ""))
        res = {"ok": False, "error": "dirección no válida"}
        if url.startswith(("http://", "https://")):
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.post(url, data=str(m.get("body", "")).encode("utf-8"), allow_redirects=False,
                                      timeout=aiohttp.ClientTimeout(total=10),
                                      headers={"Content-Type": "application/json", "User-Agent": "hub-agent"}) as r:
                        await r.content.read(512)
                        res = {"ok": 200 <= r.status < 300, "status": r.status}
            except Exception as e:
                res = {"ok": False, "error": err_text(e)}
        await self._send({"type": "webhook_result", "id": m.get("id"), **res})

    async def handle(self, m):
        t = m.get("type")
        if t in ("auth_error", "kick"):   # sesion invalida, o el portal eliminó este equipo: se cierra sesion
            self.token, self.state = None, None
            save_config({"url": self.base, "user": self.user, "token": None})
            self.set_status("needs_login")
            return False
        if t == "state":
            self.state = m
            self.server_version = m.get("version")
            self.debug = bool((m.get("me") or {}).get("debug"))
            self.status = "ok"
            self.on_change()
        elif t == "values" and self.state:
            for vid, v in m["vars"].items():
                for x in self.state["variables"]:
                    if str(x["id"]) == vid:
                        x["value"], x["online"] = v["value"], v["online"]
            self.on_change()
        elif t == "toast":
            self.toast = m["text"]
            self.on_change()
        elif t == "fire_webhook":   # una automatizacion del hub pide mandar un webhook desde este PC (sirve tambien para tu red local)
            asyncio.create_task(self.fire_webhook(m))
        elif t == "update_now":   # el portal pide actualizar este agente
            if self.update_state():
                try:
                    await asyncio.get_running_loop().run_in_executor(None, install_update, self.base, self.server_version)
                except Exception as e:
                    self.toast = "no se pudo actualizar: " + (str(e) or type(e).__name__)
                    self.on_change()
        elif t == "locked":   # la cuenta tiene el bloqueo activo: hay que desbloquearla desde el portal
            self.toast = "cuenta bloqueada: desbloquéala en el portal (ajustes)"
            self.on_change()
        elif t == "want_avatar":
            img = await asyncio.get_running_loop().run_in_executor(None, windows_avatar)
            if img:
                await self._send({"type": "avatar", "data": img})
        elif t == "scan_cameras":   # el editor del portal pide la lista de camaras de este PC
            asyncio.create_task(self.scan_cameras())
        return True

    async def scan_cameras(self):
        """Pregunta a Qt (en un proceso aparte, sin abrir ninguna camara) cuales hay y se lo cuenta al hub."""
        if not WidgetHost.available():
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                console_python(), os.path.abspath(__file__), "--list-cameras", stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, creationflags=0x08000000 if platform.system() == "Windows" else 0)
            out, _ = await asyncio.wait_for(proc.communicate(), 25)
            names = json.loads(out.decode("utf-8").strip().splitlines()[-1])
        except Exception:
            return
        await self._send({"type": "cameras", "list": names})


# ---------------- barra de tareas (solo Windows) ----------------
CARD, LINE, GREEN, GREEN_LINE, RED, BG = "#99d9ea", "#00a8f3", "#b5e61d", "#22b14c", "#e8141c", "#7093c0"


PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:transparent;overflow:hidden;user-select:none;-webkit-user-select:none}
</style></head><body><div id="root"></div>
<script>window.HUB_LANG = '__LANG__'</script>
<script>__JS__</script>
<script>
const C = HubWidget.render(document.getElementById('root'), __DEF__,
  {mode: 'view', margin: __M__, assetBase: '__BASE__', ctx: () => window.__ctx || {}, iframes: false});
window.__ctx = __CTX__;
window.setCtx = c => { window.__ctx = c; C.tick(); };
window.setMove = on => { document.getElementById('root').style.outline = on ? '3px dashed #00a8f3' : 'none'; };
setInterval(() => C.tick(), 1000);
</script></body></html>"""


def install_update(base, server_version):
    """Descarga el agent.py del servidor, lo valida, reemplaza este archivo y reinicia el agente."""
    import re, shutil, subprocess, urllib.request
    text = urllib.request.urlopen(base + "/agent.py", timeout=30).read().decode("utf-8")
    compile(text, "agent.py", "exec")   # que al menos sea Python valido
    m = re.search(r'^AGENT_VERSION = "([\d.]+)"', text, re.M)
    if not m or ver_outdated(m.group(1), server_version):
        raise ValueError("el servidor todavía no tiene el agente nuevo")
    path = os.path.abspath(__file__)
    shutil.copy2(path, path + ".bak")
    tmp = path + ".new"
    Path(tmp).write_text(text, "utf-8")
    os.replace(tmp, path)
    args, skip = [], False
    for a in sys.argv[1:]:   # la contraseña no se vuelve a pasar: la sesion ya esta guardada
        if skip:
            skip = False
        elif a == "--password":
            skip = True
        else:
            args.append(a)
    flags = 0x00000008 | 0x00000200 if platform.system() == "Windows" else 0   # DETACHED_PROCESS | NEW_PROCESS_GROUP
    subprocess.Popen([pythonw(), path] + args, creationflags=flags, close_fds=True)
    os._exit(0)


def run_widget_host():
    """Proceso aparte (Qt necesita el hilo principal): dibuja cada widget como una ventana transparente con
    contenido web. Recibe ordenes del agente por stdin, una linea JSON cada una."""
    import ctypes, urllib.request
    from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, QUrl, QUrlQuery, Signal
    from PySide6.QtGui import QColor, QPainterPath, QRegion
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QWidget

    MARGIN = 28   # espacio alrededor del widget para que quepa su sombra
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    user32 = ctypes.windll.user32
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]

    def log(*a):
        print(*a, file=sys.stderr, flush=True)

    def open_target(t):
        t = (t or "").strip()
        if not t:
            return
        try:
            if t.lower().startswith(("http://", "https://")):
                webbrowser.open(t)
            else:
                os.startfile(t)
        except Exception as e:
            log("no se pudo abrir", t, repr(e))

    class Page(QWebEnginePage):
        def __init__(self, parent):
            super().__init__(parent)
            try:    # Qt >= 6.8
                self.permissionRequested.connect(self.on_permission)
            except AttributeError:
                self.featurePermissionRequested.connect(
                    lambda origin, f: self.setFeaturePermission(origin, f, QWebEnginePage.PermissionGrantedByUser))

        def on_permission(self, perm):
            # solo la webcam, y solo para la pagina del widget (origen http://localhost que fijamos nosotros)
            if perm.permissionType().name == "MediaVideoCapture":
                perm.grant()
            else:
                perm.deny()

        def acceptNavigationRequest(self, url, nav_type, is_main):
            if url.scheme() == "hubopen":   # los botones «Acceso directo» navegan a hubopen://go?t=...
                open_target(QUrlQuery(url).queryItemValue("t", QUrl.ComponentFormattingOption.FullyDecoded))
                return False
            return not (is_main and nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked)

        def javaScriptConsoleMessage(self, level, msg, line, src):
            if level.name in ("ErrorMessageLevel", "InfoMessageLevel") and (level.name == "ErrorMessageLevel" or msg.startswith("camara")):
                log("JS:", msg, "linea", line)

    class WidgetWin(QWebEngineView):
        def __init__(self, wid):
            super().__init__()
            self.wid, self.rev, self.base, self.ontop, self.ct, self.sites = wid, None, None, None, True, []
            self.setPage(Page(self))
            self.page().setBackgroundColor(QColor(0, 0, 0, 0))
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            self.setStyleSheet("background: transparent")
            st = self.page().settings()
            for attr in ("PluginsEnabled", "PdfViewerEnabled"):   # el visor de PDF es un plugin
                if hasattr(QWebEngineSettings.WebAttribute, attr):
                    st.setAttribute(getattr(QWebEngineSettings.WebAttribute, attr), True)

        def raise_sites(self):
            for s in self.sites:   # las webs reales van por encima del contenido del widget
                s.raise_()

        def hwnd(self):
            return int(self.winId())

        def set_flags(self, ontop):
            if ontop == self.ontop:
                return
            self.ontop = ontop
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool |
                                (Qt.WindowType.WindowStaysOnTopHint if ontop else Qt.WindowType.WindowStaysOnBottomHint))

        def set_click_through(self, on):
            """Los clics atraviesan el widget (no estorba al escritorio), salvo que tenga objetos interactivos."""
            if not self.isVisible():
                return
            ex = user32.GetWindowLongPtrW(self.hwnd(), -20)
            user32.SetWindowLongPtrW(self.hwnd(), -20, (ex | 0x20) if on else (ex & ~0x20))

        def load(self, wd, base, js, ctx):
            data = wd["data"]
            self.rev, self.base = wd["rev"], base
            self.setFixedSize(data["w"] + 2 * MARGIN, data["h"] + 2 * MARGIN)
            esc = lambda o: json.dumps(o).replace("</", "<\\/")
            self.setHtml(PAGE.replace("__LANG__", current_lang()).replace("__JS__", js).replace("__DEF__", esc(data)).replace("__CTX__", esc(ctx))
                         .replace("__M__", str(MARGIN)).replace("__BASE__", base), QUrl("http://localhost/"))
            for s in self.sites:
                s.deleteLater()
            self.sites = []
            for o in data["objects"]:   # una web real necesita su propia ventana web, encima del resto
                if o["type"] == "website" and o["url"]:
                    v = QWebEngineView(self)
                    v.page().setBackgroundColor(QColor("white"))   # sin esto heredaria el fondo transparente del widget
                    v.setGeometry(MARGIN + o["x"], MARGIN + o["y"], o["w"], o["h"])
                    v.setUrl(QUrl(o["url"]))
                    path = QPainterPath()
                    path.addRoundedRect(0, 0, o["w"], o["h"], o["radius"], o["radius"])
                    v.setMask(QRegion(path.toFillPolygon().toPolygon()))
                    v.show()
                    self.sites.append(v)
            # interactivo = tiene algo que recibir clics o rueda (atajo, web, documento)
            self.ct = not any(o["type"] in ("shortcut", "website") or (o["type"] == "document" and o["asset"])
                              for o in data["objects"])

    class Host(QObject):
        cmd = Signal(object)

        def __init__(self):
            super().__init__()
            self.wins, self.pos, self.ctx, self.move, self.js, self.drag = {}, {}, {}, False, {}, None
            self.cmd.connect(self.on_cmd)
            app.installEventFilter(self)
            # Qt recrea la capa interna del widget al cargar y la pone encima de las webs: las volvemos a subir
            self.raiser = QTimer()
            self.raiser.timeout.connect(lambda: [w.raise_sites() for w in self.wins.values()])
            self.raiser.start(1000)

        def widget_js(self, base):
            if base not in self.js:
                self.js[base] = urllib.request.urlopen(base + "/widget.js", timeout=10).read().decode("utf-8")
            return self.js[base]

        def on_cmd(self, c):
            try:
                t = c.get("t")
                if t == "defs":
                    self.apply_defs(c["base"], c["widgets"])
                elif t == "ctx":
                    self.ctx = c["ctx"]
                    for w in self.wins.values():
                        w.page().runJavaScript("window.setCtx&&setCtx(" + json.dumps(self.ctx).replace("</", "<\\/") + ")")
                elif t == "move":
                    self.move = bool(c["on"])
                    for w in self.wins.values():
                        self.refresh_mode(w)
                elif t == "grab":   # depuracion: guarda lo que dibuja cada widget (sirve para comparar con la pantalla real)
                    for wid, w in self.wins.items():
                        w.grab().save(f'{c["prefix"]}{wid}.png')
                elif t == "quit":
                    app.quit()
            except Exception as e:
                log("error en orden", repr(e))

        def refresh_mode(self, w):
            w.set_click_through(w.ct and not self.move)
            w.page().runJavaScript("window.setMove&&setMove(%s)" % ("true" if self.move else "false"))
            if self.move:
                w.raise_()

        def apply_defs(self, base, widgets):
            ids = {wd["id"] for wd in widgets}
            for wid in [i for i in self.wins if i not in ids]:
                w = self.wins.pop(wid)
                w.close()
                w.deleteLater()
            js = self.widget_js(base)
            for wd in widgets:
                w = self.wins.get(wd["id"])
                if w is None:
                    w = self.wins[wd["id"]] = WidgetWin(wd["id"])
                    w.loadFinished.connect(lambda ok, w=w: (self.refresh_mode(w), w.raise_sites()))   # reaplica el modo y sube las webs cuando la página ya cargó
                    n = len(self.pos)
                    self.pos.setdefault(wd["id"], QPoint(80 + 40 * n, 100 + 40 * n))   # la posicion NO se guarda
                if w.rev != wd["rev"] or w.base != base:
                    first = not w.isVisible()
                    w.set_flags(bool(wd["data"]["ontop"]))
                    w.load(wd, base, js, self.ctx)
                    if first:
                        w.move(self.pos[wd["id"]])
                    w.show()
                    if not wd["data"]["ontop"]:
                        user32.SetWindowPos(w.hwnd(), 1, 0, 0, 0, 0, 0x13)   # HWND_BOTTOM: detras de las apps
                    self.refresh_mode(w)

        def eventFilter(self, obj, ev):
            """Modo mover: arrastrar cualquier widget con el boton izquierdo; no se envia nada a la web."""
            if not self.move or not isinstance(obj, QWidget):
                return False
            t = ev.type()
            if t not in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease):
                return False
            win = obj.window()
            if not isinstance(win, WidgetWin):
                return False
            g = ev.globalPosition().toPoint()
            if t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                self.drag = (win, g, win.pos())
            elif t == QEvent.Type.MouseMove and self.drag and self.drag[0] is win:
                win.move(self.drag[2] + (g - self.drag[1]))
                self.pos[win.wid] = win.pos()
            elif t == QEvent.Type.MouseButtonRelease:
                self.drag = None
            return True

    host = Host()

    def reader():
        import io
        for line in io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8"):
            try:
                host.cmd.emit(json.loads(line))
            except ValueError:
                pass
        host.cmd.emit({"t": "quit"})   # el agente se cerro: nos vamos con el
    threading.Thread(target=reader, daemon=True).start()
    log("host de widgets listo")
    app.exec()


TRAY_PAGE = r'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<script>window.HUB_FORCE_LANG='__LANG__'</script><script>__I18N__</script>
<style>
:root{--bg:#fef7ff;--surf:#f3edf7;--surf-hi:#ece6f0;--on:#1d1b20;--on-var:#49454f;--outline:#79747e;--outline-var:#cac4d0;
 --pri:#6750a4;--on-pri:#fff;--pri-c:#eaddff;--on-pri-c:#21005d;--sec-c:#e8def8;--on-sec-c:#1d192b;--ter-c:#ffd8e4;--on-ter-c:#31111d;
 --ok:#1b6e3c;--ok-c:#c8f2d4;--err:#b3261e;--err-c:#f9dedc;--warn:#8a5100;--warn-c:#ffdea6;--on-warn-c:#2b1800;--scrim:#1d1b2073;--shadow:#0000004d}
@media(prefers-color-scheme:dark){:root{--bg:#141218;--surf:#211f26;--surf-hi:#2b2930;--on:#e6e0e9;--on-var:#cac4d0;--outline:#938f99;--outline-var:#49454f;
 --pri:#d0bcff;--on-pri:#381e72;--pri-c:#4f378b;--on-pri-c:#eaddff;--sec-c:#4a4458;--on-sec-c:#e8def8;--ter-c:#633b48;--on-ter-c:#ffd8e4;
 --ok:#7fdc9c;--ok-c:#12432a;--err:#f2b8b5;--err-c:#601410;--warn:#ffb951;--warn-c:#5c3b00;--on-warn-c:#ffdea6;--scrim:#000a;--shadow:#0009}}
*{box-sizing:border-box}
[hidden]{display:none!important}
html,body{margin:0;height:100%;background:transparent;overflow:hidden}
body{font:14px/1.4 "Roboto Flex",Roboto,"Segoe UI",system-ui,sans-serif;color:var(--on);text-transform:lowercase;user-select:none;-webkit-user-select:none}
button{font:inherit;color:inherit;border:0;background:none;cursor:pointer;padding:0;text-transform:lowercase}
input{font:inherit;color:inherit;text-transform:none;user-select:text;-webkit-user-select:text}
html[data-lang=pi] body,html[data-lang=pi] button{text-transform:none}
.u{text-transform:none}
#card{position:absolute;inset:14px;background:var(--bg);border-radius:32px 32px 12px 32px;
 display:flex;flex-direction:column;padding:20px 16px 16px;overflow:hidden;border:1px solid var(--outline-var)}

/* cabecera */
.head{display:flex;align-items:center;gap:12px;padding:0 6px}
.head h1{flex:1;margin:0;font-size:27px;line-height:1.1;font-weight:500;letter-spacing:-.3px;min-width:0}
.head h1 b{font-weight:500;text-transform:none;overflow-wrap:anywhere}
.av{width:54px;height:54px;flex:none;border-radius:58% 42% 55% 45%/50% 58% 42% 50%;background:var(--ter-c);color:var(--on-ter-c);
 display:grid;place-items:center;font-size:24px;font-weight:500;overflow:hidden;text-transform:uppercase}
.av img{width:100%;height:100%;object-fit:cover}
.srow{display:flex;align-items:center;gap:8px;padding:12px 6px 4px;flex-wrap:wrap}
.chip{display:inline-flex;align-items:center;gap:7px;padding:6px 13px;border-radius:999px;font-size:13px;font-weight:500;background:var(--surf-hi);color:var(--on-var)}
.chip i{width:9px;height:9px;border-radius:50%;background:var(--outline)}
.chip.ok{background:var(--ok-c);color:var(--ok)}.chip.ok i{background:var(--ok)}
.chip.bad{background:var(--err-c);color:var(--err)}.chip.bad i{background:var(--err)}
.tb{padding:6px 12px;border-radius:999px;font-size:13px;font-weight:500;color:var(--on-var)}
.tb:hover{background:var(--surf-hi)}
.sp{flex:1}

/* filtro */
.seg{display:flex;margin:10px 4px 6px;background:var(--surf);border-radius:999px;padding:4px;gap:4px}
.seg button{flex:1;padding:8px;border-radius:999px;font-size:13px;font-weight:500;color:var(--on-var)}
.seg button.on{background:var(--pri-c);color:var(--on-pri-c)}

/* lista */
#body{flex:1;overflow:auto;min-height:0;padding:4px 4px 8px;margin:0 -4px}
#body::-webkit-scrollbar{width:6px}#body::-webkit-scrollbar-thumb{background:var(--outline-var);border-radius:6px}
.v{display:flex;align-items:center;gap:8px;padding:14px 8px 14px 18px;margin:8px 0;background:var(--pri-c);color:var(--on-pri-c);border-radius:26px 14px 26px 14px}
.v.c1{background:var(--ter-c);color:var(--on-ter-c);border-radius:14px 26px 14px 26px}
.v.c2{background:var(--sec-c);color:var(--on-sec-c);border-radius:26px 26px 14px 14px}
.vt{flex:1;min-width:0}
.vn{font-size:12px;opacity:.78;text-transform:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.vv{font-size:21px;font-weight:500;line-height:1.2;text-transform:none;overflow-wrap:anywhere;margin-top:1px}
.vo{font-size:12px;opacity:.78;margin-top:2px}.vo b{font-weight:500;text-transform:none}
.ic{display:flex;flex:none}
.ib{width:36px;height:36px;border-radius:50%;display:grid;place-items:center}
.ib:hover{background:#ffffff40}
.ib svg{width:20px;height:20px;fill:currentColor}
.ib.del{color:var(--err)}
.empty{text-align:center;padding:36px 20px;color:var(--on-var)}
.empty .blob{width:76px;height:76px;margin:0 auto 14px;background:var(--sec-c);border-radius:62% 38% 54% 46%/48% 60% 40% 52%;display:grid;place-items:center;color:var(--on-sec-c)}
.empty .blob svg{width:34px;height:34px;fill:currentColor}
.empty h2{margin:0 0 6px;font-size:18px;font-weight:500;color:var(--on)}
.empty p{margin:0 0 16px;font-size:13px}

/* botones */
.btn{padding:12px 22px;border-radius:999px;font-weight:500;font-size:14px;background:var(--sec-c);color:var(--on-sec-c);text-align:center}
.btn:hover{filter:brightness(.96)}
.btn.go{background:var(--pri);color:var(--on-pri)}
.btn.red{background:var(--err-c);color:var(--err)}
.btn.txt{background:none;color:var(--pri)}
.foot{display:grid;gap:8px;padding-top:8px}
.foot .btn{padding:13px}

/* actualizacion */
.upd{background:var(--warn-c);color:var(--on-warn-c);border-radius:22px 22px 22px 8px;padding:14px 16px;margin:10px 4px 0}
.upd b{display:block;font-size:15px;font-weight:500;margin-bottom:4px}.upd p{margin:0 0 10px;font-size:12.5px}
.upd .row{display:flex;gap:6px;flex-wrap:wrap}.upd .btn{padding:9px 16px;font-size:13px;color:var(--on-warn-c)}
.btn.warn{background:var(--warn);color:var(--bg)}
#hard,#ahead{position:absolute;inset:0;background:var(--bg);z-index:5;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:30px;gap:10px}
#hard h2,#ahead h2{margin:0;font-size:24px;font-weight:500}#hard p,#ahead p{margin:0 0 8px;font-size:14px;color:var(--on-var)}
#ahead{z-index:6}#ahead .blob{background:var(--err-c);color:var(--err)}#ahead .btn{width:100%;max-width:300px}
#hard .blob,#ahead .blob{width:84px;height:84px;background:var(--warn-c);color:var(--warn);border-radius:62% 38% 54% 46%/48% 60% 40% 52%;display:grid;place-items:center;margin-bottom:6px}
#hard .blob svg,#ahead .blob svg{width:40px;height:40px;fill:currentColor}
/* hojas (dialogos) */
#scrim{position:absolute;inset:0;background:var(--scrim);display:none;align-items:flex-end;border-radius:inherit}
#scrim.on{display:flex}
#sheet{width:100%;background:var(--surf-hi);border-radius:28px 28px 12px 28px;padding:22px 20px 18px;max-height:92%;overflow:auto}
#sheet h3{margin:0 0 12px;font-size:21px;font-weight:500}
#sheet h3 span{text-transform:none}
.f{margin:10px 0}
.f label{display:block;font-size:12px;color:var(--on-var);margin:0 0 5px 4px}
.f input{width:100%;padding:12px 16px;border-radius:16px;border:1.5px solid var(--outline);background:transparent;outline:0}
.f input:focus{border-color:var(--pri);box-shadow:0 0 0 .5px var(--pri)}
.help{font-size:12.5px;color:var(--on-var);margin:8px 4px}
.msg{min-height:18px;font-size:13px;margin:6px 4px;color:var(--on-var);overflow-wrap:anywhere}
.msg.bad{color:var(--err)}
.acts{display:flex;justify-content:flex-end;gap:6px;margin-top:12px;flex-wrap:wrap}
.sh{display:flex;align-items:center;gap:6px;padding:8px 8px 8px 16px;margin:6px 0;background:var(--sec-c);color:var(--on-sec-c);border-radius:999px}
.sh span{flex:1;text-transform:none;overflow:hidden;text-overflow:ellipsis}
.sh button{width:28px;height:28px;border-radius:50%;font-size:18px;line-height:1}
.sh button:hover{background:#ffffff40}
.menu{display:grid;gap:6px}
.menu button{padding:14px 18px;border-radius:18px;background:var(--sec-c);color:var(--on-sec-c);text-align:left;font-weight:500;font-size:15px}
.menu button:hover{filter:brightness(.96)}
</style></head><body>
<div id="card">
 <div class="head"><h1 id="hello"></h1><div class="av" id="av"></div></div>
 <div class="srow"><span class="chip" id="st"><i></i><span id="stt"></span></span><span class="sp"></span>
  <button class="tb" id="bLang">idioma</button><button class="tb" id="bSvc">servicios ▾</button><button class="tb" id="bOut">cerrar sesión</button></div>
 <div class="upd" id="updSoft" hidden><b>actualización grande</b><p>tu dispositivo no tiene la versión más reciente y las nuevas funciones no funcionarán, actualiza el cliente para disfrutar de la actualización al 100%.</p>
  <div class="row"><button class="btn warn" id="bUpd">instalar update</button><button class="btn" id="bUpdIgn">ignorar (no recomendado)</button></div><p id="updMsg" style="margin:8px 0 0"></p></div>
 <div class="seg" id="seg"><button data-m="mine">mías</button><button data-m="shared">compartidas</button></div>
 <div id="body"></div>
 <div class="foot" id="foot">
  <button class="btn" id="bWid">widgets del escritorio…</button>
  <button class="btn go" id="bPortal">entra al portal para administrar más opciones</button>
 </div>
 <div id="hard" hidden><div class="blob"><svg viewBox="0 0 24 24"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg></div>
  <h2>actualiza el cliente</h2><p>esta versión es muy antigua y no puede correr en estos estándares, actualiza ahora.</p>
  <button class="btn go" id="bHard">instalar update</button><p id="hardMsg"></p></div>
 <div id="ahead" hidden><div class="blob"><svg viewBox="0 0 24 24"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg></div>
  <h2>versión mayor detectada</h2><p id="aheadTxt"></p>
  <button class="btn go" id="bAheadQuit">salir de la app</button><button class="btn" id="bAheadDbg">iniciar sesión con cuenta de depuración</button></div>
 <div id="scrim"><div id="sheet"></div></div>
</div>
<script>
const $=s=>document.querySelector(s);
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function cmd(o){location.href='hubcmd://x?d='+encodeURIComponent(JSON.stringify(o))}
let updIgnored=false;
let S={status:'offline',user:'',base:'',vars:[],cfg:{},toast:'',avatar:''},mode='mine',cur=null,lastSig='';
const ST={ok:['en línea','ok'],offline:['sin conexión','bad'],needs_login:['sin sesión','']};
const IC={edit:'M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z',
 share:'M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z',
 del:'M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z',
 cloud:'M19.35 10.04A7.49 7.49 0 0 0 12 4C9.11 4 6.6 5.64 5.35 8.04A5.994 5.994 0 0 0 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96z',
 list:'M3 13h2v-2H3v2zm0 4h2v-2H3v2zm0-8h2V7H3v2zm4 4h14v-2H7v2zm0 4h14v-2H7v2zM7 7v2h14V7H7z'};
const svg=(k)=>`<svg viewBox="0 0 24 24"><path d="${IC[k]}"/></svg>`;

const CLOUD='__CLOUD__';
const SVC={steam:{title:'steam',fields:[['api key (gratis en steamcommunity.com/dev/apikey)','steam_key','password'],['tu id numérica o nombre de perfil','steam_id','text']],
  help:'da el juego actual y las horas jugadas (totales y de las últimas 2 semanas). para ver las horas, pon «detalles del juego» en público en tu perfil de steam.'},
 roblox:{title:'roblox',fields:[['tu nombre de usuario','roblox_user','text']],
  help:'solo datos públicos: amigos, seguidores y visitas a los juegos que creaste. el tiempo jugado se mide con «compartir actividad» en el menú del icono.'}};

function hello(){return 'hola, <b>'+esc(S.user||'')+'</b>'}
function render(){
  const [t,c]=ST[S.status]||ST.offline;
  $('#hello').innerHTML=hello();
  const up=S.update||{};$('#updSoft').hidden=!(up.state==='soft'&&!updIgnored);$('#hard').hidden=up.state!=='hard';
  $('#ahead').hidden=!up.ahead;if(up.ahead)$('#aheadTxt').textContent='tienes una versión mayor a la del servidor (app '+up.client+', servidor '+up.server+'), la app no puede iniciar correctamente en este estándar, desinstala la app y vuelve a instalar la versión oficial';
  $('#st').className='chip '+c;$('#stt').textContent=t;
  const li=S.status!=='needs_login';
  $('#bSvc').hidden=!li;$('#bOut').hidden=!li;
  const av=$('#av');
  av.innerHTML=S.avatar?`<img src="${esc(S.avatar)}">`:esc((S.user||'?').slice(0,1));
  $('#seg').hidden=S.status!=='ok';
  document.querySelectorAll('#seg button').forEach(b=>b.classList.toggle('on',b.dataset.m===mode));
  const sig=JSON.stringify([S.status,S.base,mode,S.vars]);
  if(sig===lastSig)return;lastSig=sig;
  const body=$('#body'),top=body.scrollTop;
  if(S.status==='needs_login'){
    body.innerHTML=`<div class="empty"><div class="blob">${svg('cloud')}</div><h2>sin sesión</h2><p>inicia sesión para ver tus variables y enviar los datos de este pc.</p><button class="btn go" id="bLogin">iniciar sesión</button></div>`;
    $('#bLogin').onclick=loginSheet;
  }else if(S.status!=='ok'){
    body.innerHTML=`<div class="empty"><div class="blob">${svg('cloud')}</div><h2>no se pudo conectar con el hub.</h2><p class="u">${esc(S.base)}</p><button class="btn go" id="bRe">reintentar conexión</button><p style="margin-top:14px">se reintenta solo cada 5 segundos.</p></div>`;
    $('#bRe').onclick=()=>cmd({c:'reconnect'});
  }else{
    const mine=mode==='mine',items=S.vars.filter(v=>v.mine===mine);
    if(!items.length)body.innerHTML=`<div class="empty"><div class="blob">${svg('list')}</div><h2>${mine?'aún no tienes variables.':'nada compartido contigo todavía.'}</h2><p>${mine?'créalas en el portal.':''}</p></div>`;
    else body.innerHTML=items.map((v,i)=>`<div class="v c${i%3}"><div class="vt"><div class="vn">${esc(v.name)}</div><div class="vv">${esc(v.text)}</div>${mine?'':`<div class="vo">de <b>${esc(v.owner)}</b></div>`}</div>`+
      (mine?`<div class="ic">${v.kind==='manual'?`<button class="ib" data-a="edit" data-i="${v.id}">${svg('edit')}</button>`:''}<button class="ib" data-a="share" data-i="${v.id}">${svg('share')}</button><button class="ib del" data-a="del" data-i="${v.id}">${svg('del')}</button></div>`:'')+`</div>`).join('');
    body.querySelectorAll('.ib').forEach(b=>b.onclick=()=>{const v=S.vars.find(x=>String(x.id)===b.dataset.i);if(!v)return;({edit:editSheet,share:shareSheet,del:delSheet})[b.dataset.a](v)});
  }
  body.scrollTop=top;
}

/* ---- hojas ---- */
function open_(html,refresh){$('#sheet').innerHTML=html;$('#scrim').classList.add('on');cur={refresh};const f=$('#sheet input');if(f){f.focus();f.select&&f.select()}}
function closeSheet(){$('#scrim').classList.remove('on');cur=null}
$('#scrim').onclick=e=>{if(e.target.id==='scrim')closeSheet()};
const pend={};let rid=0;
function call(o){return new Promise(r=>{const id=++rid;pend[id]=r;cmd({...o,rid:id});setTimeout(()=>{if(pend[id]){delete pend[id];r({ok:false,text:'sin respuesta'})}},30000)})}
const field=(l,k,type,val)=>`<div class="f"><label>${l}</label><input data-k="${k}" type="${type||'text'}" value="${esc(val)}" autocomplete="off" spellcheck="false"></div>`;
const vals=()=>{const o={};document.querySelectorAll('#sheet input[data-k]').forEach(i=>o[i.dataset.k]=i.value);return o};
function enter(fn){document.querySelectorAll('#sheet input').forEach(i=>i.onkeydown=e=>{if(e.key==='Enter')fn()})}

function editSheet(v){
  open_(`<h3><span>${esc(v.name)}</span></h3>${field('nuevo valor:','val','text',v.value||'')}<div class="acts"><button class="btn txt" id="x">cancelar</button><button class="btn go" id="ok">guardar</button></div>`);
  const go=()=>{cmd({c:'var_set',id:v.id,value:vals().val});closeSheet()};
  $('#ok').onclick=go;$('#x').onclick=closeSheet;enter(go);
}
function delSheet(v){
  open_(`<h3>eliminar</h3><p class="help" style="font-size:14px">¿eliminar «<span class="u">${esc(v.name)}</span>»?</p><div class="acts"><button class="btn txt" id="x">cancelar</button><button class="btn red" id="ok">eliminar</button></div>`);
  $('#ok').onclick=()=>{cmd({c:'var_delete',id:v.id});closeSheet()};$('#x').onclick=closeSheet;
}
function shareSheet(v){
  const draw=()=>{
    const cv=S.vars.find(x=>x.id===v.id)||v,list=$('#shl');
    list.innerHTML=(cv.shared_with||[]).map(u=>`<div class="sh"><span>${esc(u)}</span><button data-u="${esc(u)}" title="quitar">×</button></div>`).join('')||'<p class="help">todavía con nadie.</p>';
    list.querySelectorAll('button').forEach(b=>b.onclick=()=>cmd({c:'var_unshare',id:v.id,user:b.dataset.u}));
    const m=$('#shm');m.textContent=S.toast||'';m.className='msg bad';
  };
  open_(`<h3>compartir variable</h3><p class="help" style="margin-top:0">compartida con (solo lectura):</p><div id="shl"></div>${field('usuario','u','text','')}<div class="msg bad" id="shm"></div><div class="acts"><button class="btn txt" id="x">cerrar</button><button class="btn go" id="ok">añadir usuario</button></div>`,draw);
  const add=()=>{const u=vals().u.trim();if(!u)return;cmd({c:'clear_toast'});cmd({c:'var_share',id:v.id,user:u});document.querySelector('#sheet input').value=''};
  $('#ok').onclick=add;$('#x').onclick=closeSheet;enter(add);draw();
}
function loginSheet(){
  let cloud=!S.base||S.base===CLOUD;
  open_(`<h3>iniciar sesión</h3><div class="seg" id="srv" style="margin:0 0 8px"><button data-m="cloud">servicio en la nube</button><button data-m="local">servidor local</button></div><p class="help" id="srvHint" style="margin:0 4px 6px"></p><div id="urlBox">${field('dirección del hub','url','text',cloud?'http://':S.base)}</div>${field('usuario','user','text',S.user)}${field('contraseña','pw','password','')}<div class="msg" id="m"></div><div class="acts"><button class="btn txt" id="x">cancelar</button><button class="btn go" id="ok">iniciar sesión</button></div>`);
  const mode=()=>{document.querySelectorAll('#srv button').forEach(b=>b.classList.toggle('on',(b.dataset.m==='cloud')===cloud));
    $('#urlBox').hidden=cloud;$('#srvHint').textContent=cloud?'usa el servicio en la nube de hub ('+CLOUD.replace('https://','')+')':'escribe la dirección de tu propio servidor, por ejemplo http://192.168.1.10:8765'};
  document.querySelectorAll('#srv button').forEach(b=>b.onclick=()=>{cloud=b.dataset.m==='cloud';mode()});mode();
  const go=async()=>{const m=$('#m'),v=vals();m.className='msg';m.textContent='conectando…';const r=await call({c:'login',url:cloud?CLOUD:v.url,user:v.user,pw:v.pw});
    if(r.ok)closeSheet();else{m.className='msg bad';m.textContent=r.text||'error'}};
  $('#ok').onclick=go;$('#x').onclick=closeSheet;enter(go);
  const i=document.querySelector('#sheet input[data-k="'+(S.user?'pw':'user')+'"]');i&&i.focus();
}
function svcSheet(which){
  const d=SVC[which];
  open_(`<h3>conectar ${d.title}</h3>${d.fields.map(f=>field(f[0],f[1],f[2],(S.cfg||{})[f[1]]||'')).join('')}<p class="help">${d.help}<br><br>los datos se guardan solo en este pc y los consulta este programa; el hub nunca los ve. deja los campos vacíos para desactivarlo.</p><div class="msg" id="m"></div><div class="acts"><button class="btn txt" id="x">cancelar</button><button class="btn" id="s">guardar</button><button class="btn go" id="t">guardar y probar</button></div>`);
  const save=async test=>{const m=$('#m');m.className='msg';m.textContent=test?'probando…':'';const r=await call({c:'svc',which,values:vals(),test});
    if(!test&&r.ok)return closeSheet();m.className='msg'+(r.ok?'':' bad');m.textContent=r.text||''};
  $('#t').onclick=()=>save(true);$('#s').onclick=()=>save(false);$('#x').onclick=closeSheet;
}
function svcMenu(){
  open_(`<h3>servicios</h3><div class="menu"><button id="a">steam</button><button id="b">roblox</button></div>`);
  $('#a').onclick=()=>svcSheet('steam');$('#b').onclick=()=>svcSheet('roblox');
}
function outSheet(){
  open_(`<h3>cerrar sesión</h3><p class="help" style="font-size:14px">¿cerrar sesión? este pc dejará de enviar datos y los widgets se ocultarán.</p><div class="acts"><button class="btn txt" id="x">cancelar</button><button class="btn red" id="ok">cerrar sesión</button></div>`);
  $('#ok').onclick=()=>{cmd({c:'logout'});closeSheet()};$('#x').onclick=closeSheet;
}

/* ---- eventos ---- */
document.querySelectorAll('#seg button').forEach(b=>b.onclick=()=>{mode=b.dataset.m;render()});
function langSheet(){
  open_(`<h3>idioma</h3><div class="menu">${HubI18n.LANGS.map(l=>`<button class="u" data-l="${l}">${HubI18n.NAMES[l]}</button>`).join('')}</div>`);
  document.querySelectorAll('#sheet [data-l]').forEach(b=>b.onclick=()=>{cmd({c:'set_lang',lang:b.dataset.l});closeSheet()});
}
$('#bLang').onclick=langSheet;$('#bSvc').onclick=svcMenu;$('#bOut').onclick=outSheet;
async function installUpd(btn,msg){
  btn.disabled=true;msg.textContent='descargando e instalando… el agente se reiniciará solo.';
  const r=await call({c:'update_install'});
  btn.disabled=false;if(!r.ok)msg.textContent='no se pudo actualizar: '+(r.text||'error');
}
$('#bUpd').onclick=e=>installUpd(e.currentTarget,$('#updMsg'));$('#bHard').onclick=e=>installUpd(e.currentTarget,$('#hardMsg'));
$('#bUpdIgn').onclick=()=>{updIgnored=true;render()};
$('#bAheadQuit').onclick=()=>cmd({c:'quit_agent'});
$('#bAheadDbg').onclick=()=>{cmd({c:'logout'});setTimeout(loginSheet,700)};
$('#bPortal').onclick=()=>cmd({c:'open_portal'});
$('#bWid').onclick=()=>cmd({c:'open_editor'});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){cur?closeSheet():cmd({c:'hide'})}});
window.recv=m=>{
  if(m.t==='state'){if(m.lang&&m.lang!==HubI18n.lang())HubI18n.setLang(m.lang,false);S={...S,...m};render();if(cur&&cur.refresh)cur.refresh()}
  else if(m.t==='res'){const f=pend[m.rid];if(f){delete pend[m.rid];f(m)}}
  else if(m.t==='show'){closeSheet();if(m.open)svcSheet(m.open)}
  else if(m.t==='reset')closeSheet();
};
render();
</script></body></html>
'''


def run_tray_ui():
    """Proceso aparte con Qt: la ventana de la bandeja y sus dialogos son una pagina web (material 3 expressive).
    Habla con el agente por lineas JSON: ordenes por stdin, respuestas por stdout."""
    import ctypes
    from PySide6.QtCore import QObject, Qt, QTimer, QUrl, QUrlQuery, Signal
    from PySide6.QtGui import QColor
    from PySide6.QtWebEngineCore import QWebEnginePage
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication

    CARD_W, CARD_H, M = 392, 580, 14   # M: margen transparente para la sombra
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    user32 = ctypes.windll.user32
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    out_lock = threading.Lock()

    def emit(o):
        with out_lock:
            print(json.dumps(o), flush=True)

    class Page(QWebEnginePage):
        def acceptNavigationRequest(self, url, nav_type, is_main):
            if url.scheme() == "hubcmd":   # la pagina nos habla navegando a hubcmd://x?d=<json>
                try:
                    o = json.loads(QUrlQuery(url).queryItemValue("d", QUrl.ComponentFormattingOption.FullyDecoded))
                except ValueError:
                    return False
                if o.get("c") == "hide":
                    win.hide_win()
                else:
                    emit(o)
                return False
            return not (is_main and nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked)

    class Win(QWebEngineView):
        def __init__(self):
            super().__init__()
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setStyleSheet("background: transparent")
            self.setPage(Page(self))
            self.page().setBackgroundColor(QColor(0, 0, 0, 0))
            self.shown_at, self.loaded, self.queue = 0.0, False, []
            self.page().loadFinished.connect(self.on_loaded)
            self.setHtml(TRAY_PAGE.replace("__I18N__", I18N_JS).replace("__LANG__", current_lang()).replace("__CLOUD__", CLOUD_URL), QUrl("http://localhost/"))
            t = QTimer(self)
            t.timeout.connect(self.watch)
            t.start(250)

        def on_loaded(self, ok):
            self.loaded = True
            for js in self.queue:
                self.page().runJavaScript(js)
            self.queue = []
            emit({"c": "ready"})

        def run(self, js):
            if self.loaded:
                self.page().runJavaScript(js)
            else:
                self.queue.append(js)

        def show_win(self):
            g = app.primaryScreen().availableGeometry()
            w, h = CARD_W + 2 * M, min(CARD_H + 2 * M, g.height() - 16)
            self.setFixedSize(w, h)
            self.move(g.x() + g.width() - w, g.y() + g.height() - h - 36)
            self.show()
            self.raise_()
            self.activateWindow()
            user32.SetForegroundWindow(int(self.winId()))
            self.shown_at = time.time()
            emit({"c": "shown"})

        def hide_win(self):
            if self.isVisible():
                self.hide()
                self.run("recv({t:'reset'})")
                emit({"c": "hidden"})

        def watch(self):   # al hacer clic fuera la ventana se oculta sola
            if self.isVisible() and time.time() - self.shown_at > 0.8 and not self.isActiveWindow():
                self.hide_win()

    class Host(QObject):
        line = Signal(str)

    win = Win()
    host = Host()

    def on_line(text):
        try:
            o = json.loads(text)
        except ValueError:
            return
        t = o.get("t")
        if t == "show":
            win.run("recv(" + text + ")")
            win.show_win()
        elif t == "hide":
            win.hide_win()
        elif t == "quit":
            app.quit()
        else:
            win.run("recv(" + text + ")")
    host.line.connect(on_line)

    def reader():
        for raw in sys.stdin:
            host.line.emit(raw)
        host.line.emit('{"t":"quit"}')   # el agente se cerro
    threading.Thread(target=reader, daemon=True).start()
    app.exec()


class TrayUI:
    """Lanza y alimenta el proceso de la ventana de la bandeja (ver run_tray_ui)."""

    def __init__(self, link):
        self.link, self.proc, self.visible, self.hidden_at, self.handler, self.avatar = link, None, False, 0.0, None, None

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        import subprocess
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        log = open(CONFIG.parent / "tray.log", "ab")
        flags = 0x08000000 if platform.system() == "Windows" else 0
        self.proc = subprocess.Popen([console_python(), os.path.abspath(__file__), "--tray-ui"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=log, creationflags=flags)
        threading.Thread(target=self.read, args=(self.proc,), daemon=True).start()

    def read(self, proc):
        for raw in proc.stdout:
            try:
                o = json.loads(raw)
            except ValueError:
                continue
            c = o.get("c")
            if c == "shown":
                self.visible = True
            elif c == "hidden":
                self.visible, self.hidden_at = False, time.time()
            elif c != "ready" and self.handler:
                try:
                    self.handler(o)
                except Exception:
                    pass
        self.visible = False

    def send(self, obj):
        try:
            self.proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except (OSError, ValueError, AttributeError):
            pass

    def push(self, full=False):
        link = self.link
        st = link.state or {}
        cfg = load_config()
        msg = {"t": "state", "status": link.status, "user": link.user, "base": link.base, "toast": link.toast,
               "update": {"state": link.update_state(), "server": link.server_version, "client": AGENT_VERSION, "ahead": link.ahead()}, "lang": current_lang(),
               "cfg": {k: cfg.get(k, "") for k in ("steam_key", "steam_id", "roblox_user")},
               "vars": [{"id": v["id"], "name": v["name"], "text": fmt(v), "value": v.get("value"), "kind": v["kind"],
                         "mine": v["mine"], "owner": v.get("owner", ""), "shared_with": v.get("shared_with", [])}
                        for v in st.get("variables", [])]}
        av = (st.get("me") or {}).get("avatar")
        if full or av != self.avatar:
            msg["avatar"] = av or ""
            self.avatar = av
        self.send(msg)

    def show(self, open_=None):
        if platform.system() == "Windows":
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(self.proc.pid)   # sin esto Windows no deja que otro proceso tome el foco
        self.push(True)
        self.send({"t": "show", "open": open_})

    def stop(self):
        if self.alive():
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()


class WidgetHost:
    """Lanza y alimenta el proceso que dibuja los widgets de ESTE PC. Solo existe mientras haya widgets que mostrar."""

    def __init__(self, link, on_missing):
        self.link, self.on_missing = link, on_missing
        self.proc, self.move, self.sig, self.ctx_sig, self.warned = None, False, None, None, False

    @staticmethod
    def available():
        import importlib.util
        return importlib.util.find_spec("PySide6") is not None

    def wanted(self):
        st = self.link.state
        return [w for w in (st or {}).get("widgets", []) if DEVICE_ID in w["devices"]]

    def build_ctx(self):
        link, ctx = self.link, {"usuario": self.link.user, "pc": self.link.name}
        vs = (link.state or {}).get("variables", [])
        for v in vs:    # compartidas conmigo: por nombre (sin pisar lo integrado) y como {dueño.nombre}
            if not v["mine"]:
                ctx.setdefault(v["name"].strip().lower(), fmt(v))
                ctx[f'{v["owner"]}.{v["name"]}'.lower()] = fmt(v)
        for v in vs:    # las mias ganan a todo
            if v["mine"]:
                ctx[v["name"].strip().lower()] = fmt(v)
        return ctx

    def start(self):
        import subprocess
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        log = open(CONFIG.parent / "widgets.log", "ab")
        flags = 0x08000000 if platform.system() == "Windows" else 0   # CREATE_NO_WINDOW
        self.proc = subprocess.Popen([console_python(), os.path.abspath(__file__), "--widgets-host"], stdin=subprocess.PIPE,
                                     stdout=subprocess.DEVNULL, stderr=log, creationflags=flags)
        self.sig = self.ctx_sig = None
        if self.move:
            self.send({"t": "move", "on": True})

    def send(self, obj):
        try:
            self.proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except (OSError, ValueError, AttributeError):
            self.proc = None   # se cayo: sync() lo vuelve a lanzar

    def sync(self):
        wanted = self.wanted()
        if not wanted:
            return self.stop()
        if not self.available():
            if not self.warned:
                self.warned = True
                self.on_missing("para ver widgets en este pc instala qt:\n\npip install PySide6")
            return
        if self.proc is None or self.proc.poll() is not None:
            self.start()
        sig = (self.link.base, [(w["id"], w["rev"]) for w in wanted])
        ctx = self.build_ctx()
        if ctx != self.ctx_sig:
            self.ctx_sig = ctx
            self.send({"t": "ctx", "ctx": ctx})
        if sig != self.sig:
            self.sig = sig
            self.send({"t": "defs", "base": self.link.base,
                       "widgets": [{"id": w["id"], "rev": w["rev"], "data": w["data"]} for w in wanted]})

    def set_move(self, on):
        self.move = on
        if self.proc:
            self.send({"t": "move", "on": on})

    def stop(self):
        if self.proc:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()
        self.proc, self.sig, self.ctx_sig = None, None, None


def run_tray(link, autoshow):
    import ctypes, tkinter as tk
    from ctypes import wintypes
    import pystray
    from PIL import Image, ImageDraw, ImageTk

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    root.withdraw()
    scale = root.winfo_fpixels("1i") / 96
    FONT, BOLD = ("Segoe UI", 10), ("Segoe UI", 10, "bold")
    q = queue.Queue()
    ui = q.put
    def widgets_missing(msg):
        from tkinter import messagebox
        ui(lambda: messagebox.showwarning("widgets", msg))
    widgets = WidgetHost(link, widgets_missing)
    qt = TrayUI(link) if WidgetHost.available() else None   # ventana nueva (qt); sin PySide6 se usa la de tkinter

    def use_qt():
        return qt is not None and qt.alive()

    def open_editor():
        webbrowser.open(f"{link.base}/editor#token={link.token}" if link.token else link.base)

    def make_icon(status):
        im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((6, 4, 58, 60), 8, fill=(112, 147, 192, 255), outline=(0, 168, 243, 255), width=3)
        cols = [(181, 230, 29), (255, 201, 14), (237, 28, 36), (153, 217, 234)]
        for i in range(2):
            for j in range(3):
                x, y = 16 + i * 18, 14 + j * 13
                d.rectangle((x, y, x + 12, y + 9), fill=cols[(i + j) % 4])
        dot = (34, 177, 76) if status == "ok" else (232, 20, 28)
        d.ellipse((36, 36, 62, 62), fill=dot, outline=(255, 255, 255), width=3)
        return im

    # ---- utilidades de widgets
    def btn(parent, text, cmd, **kw):
        kw = {"bg": CARD, "bd": 3, "relief": "solid", "font": FONT, "cursor": "hand2", "padx": 10, "pady": 3, **kw}
        return tk.Button(parent, text=text, command=cmd, activebackground=kw["bg"], **kw)

    def box(parent, **kw):
        return tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=3, **kw)

    popup = tk.Toplevel(root)
    popup.withdraw()
    popup.overrideredirect(True)
    popup.attributes("-topmost", True)
    popup.configure(bg=BG)
    W, H = int(390 * scale), int(540 * scale)
    S = {"busy": 0, "hidden_at": 0.0, "mode": "mine", "photo": None}

    def centered(win):
        win.update_idletasks()
        win.geometry(f"+{(win.winfo_screenwidth() - win.winfo_width()) // 2}+{(win.winfo_screenheight() - win.winfo_height()) // 3}")

    def dialog(title, build):
        """Ventana modal; build(frame, close) arma el contenido. Mientras esta abierta la bandeja no se oculta."""
        S["busy"] += 1
        d = tk.Toplevel(root)
        d.title(title)
        d.configure(bg=CARD, padx=16, pady=14)
        d.attributes("-topmost", True)
        build(d, d.destroy)
        centered(d)
        d.grab_set()
        d.focus_force()
        root.wait_window(d)
        S["busy"] -= 1

    def ask_text(title, prompt, initial=""):
        out = [None]

        def build(d, close):
            tk.Label(d, text=prompt, bg=CARD, font=FONT).pack(anchor="w")
            e = tk.Entry(d, width=42, font=FONT, bg=CARD, bd=3, relief="solid")
            e.insert(0, initial)
            e.pack(pady=8)
            e.focus_set()
            e.select_range(0, "end")

            def ok(*_):
                out[0] = e.get()
                close()
            e.bind("<Return>", ok)
            row = tk.Frame(d, bg=CARD)
            row.pack(anchor="e")
            btn(row, "guardar", ok, bg=GREEN, highlightbackground=GREEN_LINE).pack(side="left", padx=4)
            btn(row, "cancelar", close).pack(side="left")
        dialog(title, build)
        return out[0]

    def share_dialog(vid):
        def build(d, close):
            lst = tk.Listbox(d, height=5, font=FONT, bg=CARD, bd=3, relief="solid", exportselection=False)
            err = tk.Label(d, text="", bg=CARD, fg="#a00", font=FONT)

            def fill():
                lst.delete(0, "end")
                v = next((x for x in (link.state or {}).get("variables", []) if x["id"] == vid), None)
                for u in (v or {}).get("shared_with", []):
                    lst.insert("end", u)
            tk.Label(d, text="compartida con (solo lectura):", bg=CARD, font=FONT).pack(anchor="w")
            lst.pack(fill="x", pady=6)
            e = tk.Entry(d, font=FONT, bg=CARD, bd=3, relief="solid")
            e.pack(fill="x", pady=4)
            err.pack(anchor="w")

            def add(*_):
                if e.get().strip():
                    link.toast = ""
                    link.send({"type": "var_share", "id": vid, "user": e.get()})
                    e.delete(0, "end")

            def remove():
                for i in lst.curselection():
                    link.send({"type": "var_unshare", "id": vid, "user": lst.get(i)})
            e.bind("<Return>", add)
            row = tk.Frame(d, bg=CARD)
            row.pack(anchor="e", pady=(8, 0))
            btn(row, "añadir usuario", add, bg=GREEN, highlightbackground=GREEN_LINE).pack(side="left", padx=4)
            btn(row, "quitar", remove).pack(side="left", padx=4)
            btn(row, "cerrar", close).pack(side="left")

            def tick():
                if d.winfo_exists():
                    fill()
                    err.config(text=link.toast)
                    d.after(500, tick)
            tick()
        dialog("compartir variable", build)

    def login_dialog():
        def build(d, close):
            fields = {}
            for label, key, val, show in (("dirección del hub", "url", link.base or "http://", ""),
                                          ("usuario", "user", link.user, ""), ("contraseña", "pw", "", "•")):
                tk.Label(d, text=label, bg=CARD, font=FONT).pack(anchor="w")
                e = tk.Entry(d, width=38, font=FONT, bg=CARD, bd=3, relief="solid", show=show)
                e.insert(0, val)
                e.pack(pady=(0, 8))
                fields[key] = e
            err = tk.Label(d, text="", bg=CARD, fg="#a00", font=FONT)
            err.pack(anchor="w")

            def go(*_):
                err.config(text="conectando…")
                d.update()
                try:
                    asyncio.run_coroutine_threadsafe(
                        link.login(fields["url"].get(), fields["user"].get().strip().lower(), fields["pw"].get()),
                        link.loop).result(15)
                    close()
                except Exception as ex:
                    err.config(text=str(ex) or "error")
            fields["pw"].bind("<Return>", go)
            (fields["pw"] if fields["user"].get() else fields["user"]).focus_set()
            btn(d, "iniciar sesión", go, bg=GREEN, highlightbackground=GREEN_LINE).pack(anchor="e")
        dialog("iniciar sesión", build)

    SERVICES = {
        "steam": ("steam", [("api key (gratis en steamcommunity.com/dev/apikey)", "steam_key", "•"),
                            ("tu id numérica o nombre de perfil", "steam_id", "")],
                  "da el juego actual y las horas jugadas (totales y de las últimas 2 semanas). para ver las horas, "
                  "pon «detalles del juego» en público en tu perfil de steam."),
        "roblox": ("roblox", [("tu nombre de usuario", "roblox_user", "")],
                   "solo datos públicos: amigos, seguidores y visitas a los juegos que creaste. "
                   "el tiempo jugado se mide con «compartir actividad» en el menú del icono."),
    }

    def services_dialog(which):
        """Un diálogo por servicio: cada uno con sus campos, su ayuda y su botón de probar."""
        title, fields_def, help_text = SERVICES[which]
        cfg = load_config()

        def build(d, close):
            fields = {}
            for label, key, hide in fields_def:
                tk.Label(d, text=label, bg=CARD, font=FONT).pack(anchor="w")
                e = tk.Entry(d, width=44, font=FONT, bg=CARD, bd=3, relief="solid", show=hide)
                e.insert(0, cfg.get(key, ""))
                e.pack(pady=(0, 8))
                fields[key] = e
            tk.Label(d, bg=CARD, font=("Segoe UI", 9), fg="#333", justify="left", wraplength=380,
                     text=help_text + "\n\nlos datos se guardan solo en este pc y los consulta este programa; "
                                      "el hub nunca los ve. deja los campos vacíos para desactivarlo.").pack(anchor="w", pady=(0, 6))
            msg = tk.Label(d, text="", bg=CARD, font=FONT, justify="left", wraplength=380)
            msg.pack(anchor="w", pady=(0, 6))

            def save(test):
                save_config({k: e.get().strip() for k, e in fields.items()})
                link.cache.clear()
                link.last[which] = 0
                if not test:
                    return close()
                msg.config(text="probando…")
                d.update()
                try:
                    res = asyncio.run_coroutine_threadsafe(link.test_services(which), link.loop).result(25)
                    text = res.get(which, "escribe los datos para poder probar.")
                except Exception as ex:
                    text = "error: " + err_text(ex)
                msg.config(text=text)
            row = tk.Frame(d, bg=CARD)
            row.pack(anchor="e")
            btn(row, "guardar y probar", lambda: save(True), bg=GREEN, highlightbackground=GREEN_LINE).pack(side="left", padx=4)
            btn(row, "guardar", lambda: save(False)).pack(side="left", padx=4)
            btn(row, "cancelar", close).pack(side="left")
        dialog("conectar " + title, build)

    def services_menu(event):
        """El enlace «Servicios» de la ventana abre un menú pequeño para elegir cuál configurar."""
        m = tk.Menu(popup, tearoff=0, font=FONT)
        for key, (title, _, _) in SERVICES.items():
            m.add_command(label=title, command=lambda k=key: services_dialog(k))
        S["busy"] += 1    # mientras el menú está abierto la ventana no se oculta
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()
            S["busy"] -= 1

    # ---- ventana principal
    outer = tk.Frame(popup, bg=CARD, highlightbackground=LINE, highlightthickness=4)
    outer.pack(fill="both", expand=True, padx=0, pady=0)
    head = box(outer)
    head.pack(fill="x", padx=10, pady=(10, 6))
    hello = tk.Label(head, text="", bg=CARD, font=("Segoe UI", 17), anchor="w")
    hello.pack(side="left", padx=10, pady=8)
    avatar = tk.Label(head, bg=CARD)
    avatar.pack(side="right", padx=10, pady=8)
    srow = tk.Frame(outer, bg=CARD)
    srow.pack(fill="x", padx=14)
    status = tk.Label(srow, text="", bg=CARD, font=BOLD, anchor="w")
    status.pack(side="left")
    links = tk.Frame(srow, bg=CARD)
    links.pack(side="right")
    for text, cmd, pad in (("servicios ▾", services_menu, 10), ("cerrar sesión", lambda e: confirm_logout(), 0)):
        lbl = tk.Label(links, text=text, bg=CARD, fg="#1b1b1b", font=("Segoe UI", 9, "underline"), cursor="hand2")
        lbl.bind("<Button-1>", cmd)
        lbl.pack(side="left", padx=(0, pad))
    toggle = btn(outer, "", lambda: (S.update(mode="shared" if S["mode"] == "mine" else "mine"), refresh()))
    portal = btn(outer, "entra al portal para administrar más opciones",
                 lambda: webbrowser.open(f"{link.base}/#token={link.token}" if link.token else link.base),
                 bg="#c3c3c3", highlightbackground="#7f7f7f", bd=3, relief="solid")
    portal.pack(side="bottom", fill="x", padx=10, pady=10)
    wbtn = btn(outer, "widgets del escritorio…", lambda: (hide(), open_editor()))
    body = tk.Frame(outer, bg=CARD)

    def draw_avatar(me):
        size = int(56 * scale)
        if me.get("avatar"):
            try:
                im = Image.open(io.BytesIO(base64.b64decode(me["avatar"].split(",", 1)[1]))).convert("RGBA").resize((size, size))
                mask = Image.new("L", (size, size), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
                im.putalpha(mask)
                S["photo"] = ImageTk.PhotoImage(im)
                avatar.config(image=S["photo"], text="")
                return
            except Exception:
                pass
        from PIL import ImageFont
        big = size * 4  # dibujo grande y reduzco para suavizar el borde
        im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse((6, 6, big - 7, big - 7), fill=CARD, outline="black", width=big // 14)
        try:
            font = ImageFont.truetype("segoeui.ttf", big // 2)
        except OSError:
            font = ImageFont.load_default()
        d.text((big / 2, big / 2), (link.user or "?")[:1], fill="black", font=font, anchor="mm")
        S["photo"] = ImageTk.PhotoImage(im.resize((size, size), Image.LANCZOS))
        avatar.config(image=S["photo"], text="")

    def list_view():
        st = link.state or {"variables": [], "me": {}}
        mine = S["mode"] == "mine"
        items = [v for v in st["variables"] if v["mine"] == mine]
        toggle.config(text="ver variables compartidas conmigo" if mine else "← ver mis variables")
        toggle.pack(side="bottom", fill="x", padx=10, pady=(0, 6), after=portal)
        wbtn.pack(side="bottom", fill="x", padx=10, pady=(0, 6), after=toggle)
        canvas = tk.Canvas(body, bg=CARD, highlightthickness=0)
        inner = tk.Frame(canvas, bg=CARD)
        canvas.pack(fill="both", expand=True)
        win = canvas.create_window(0, 0, window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        if not items:
            tk.Label(inner, bg=CARD, font=FONT, justify="left", wraplength=W - 60,
                     text="nada compartido contigo todavía." if not mine else "aún no tienes variables.\ncréalas en el portal.").pack(pady=20)
        for v in items:
            row = box(inner)
            row.pack(fill="x", pady=4, padx=2)
            label = f'{v["name"]}: {fmt(v)}' + ("" if mine else f'   (de {v["owner"]})')
            tk.Label(row, text=label, bg=CARD, font=FONT, anchor="w", justify="left",
                     wraplength=int(W - 190 * scale)).pack(side="left", padx=8, pady=6, fill="x", expand=True)
            if not mine:
                continue

            def icon(text, cmd, fg="black"):
                b = tk.Label(row, text=text, bg=CARD, fg=fg, font=("Segoe MDL2 Assets", 15), cursor="hand2")
                b.bind("<Button-1>", lambda e: cmd())
                b.pack(side="right", padx=5)
            icon("", lambda v=v: delete(v), RED)               # papelera
            icon("", lambda v=v: share_dialog(v["id"]))        # personas
            if v["kind"] == "manual":
                icon("", lambda v=v: edit(v))                  # lapiz

    def edit(v):
        val = ask_text(v["name"], "nuevo valor:", v.get("value") or "")
        if val is not None:
            link.send({"type": "var_set", "id": v["id"], "value": val})

    def delete(v):
        from tkinter import messagebox
        S["busy"] += 1
        ok = messagebox.askyesno("eliminar", f'¿eliminar «{v["name"]}»?', parent=popup)
        S["busy"] -= 1
        if ok:
            link.send({"type": "var_delete", "id": v["id"]})

    def refresh():
        st = link.status
        hello.config(text=f"hola, {link.user or ''}")
        draw_avatar((link.state or {}).get("me", {}))
        status.config(text={"ok": "●  en línea", "offline": "●  sin conexión", "needs_login": "●  sin sesión"}[st],
                      fg=GREEN_LINE if st == "ok" else RED)
        if st == "needs_login":
            links.pack_forget()
        elif not links.winfo_ismapped():
            links.pack(side="right")
        for w in body.winfo_children():
            w.destroy()
        toggle.pack_forget()
        wbtn.pack_forget()
        body.pack_forget()
        body.pack(fill="both", expand=True, padx=10, pady=6)
        if st == "ok":
            list_view()
        elif st == "needs_login":
            tk.Label(body, text="inicia sesión para ver tus variables\ny enviar los datos de este pc.", bg=CARD, font=FONT).pack(pady=30)
            btn(body, "iniciar sesión", login_dialog, bg=GREEN, highlightbackground=GREEN_LINE).pack()
        else:
            tk.Label(body, text="no se pudo conectar con el hub.", bg=CARD, font=BOLD).pack(pady=(30, 4))
            tk.Label(body, text=link.base, bg=CARD, font=FONT).pack(pady=(0, 14))
            btn(body, "reintentar conexión", link.reconnect, bg=GREEN, highlightbackground=GREEN_LINE).pack()
            tk.Label(body, text="se reintenta solo cada 5 segundos.", bg=CARD, font=("Segoe UI", 9), fg="#333").pack(pady=8)

    def visible():
        return popup.state() == "normal"

    def show():
        refresh()
        rect = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0)  # area de trabajo (sin la barra)
        popup.geometry(f"{W}x{H}+{rect.right - W - 12}+{rect.bottom - H - 12}")
        popup.deiconify()
        popup.lift()
        popup.focus_force()

    def hide():
        popup.withdraw()
        S["hidden_at"] = time.time()

    def toggle_popup():
        if use_qt():
            if qt.visible:
                qt.send({"t": "hide"})
            elif time.time() - qt.hidden_at > 0.4:
                qt.show()
            return
        if visible():
            hide()
        elif time.time() - S["hidden_at"] > 0.4:  # el clic en el icono ya habia ocultado la ventana
            show()

    def check_focus():
        if S["busy"] or not visible():
            return
        try:
            if root.focus_get() is None:
                hide()
        except KeyError:
            pass
    popup.bind("<FocusOut>", lambda e: root.after(150, check_focus))

    # ---- icono de la bandeja
    import winreg
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def autostart_on():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, "HubAgent")
                return True
        except OSError:
            return False

    def set_autostart(on=None):
        """Sin argumento alterna; `on` fuerza encender/apagar. Arranca con pythonw: sin ventana de consola."""
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on is None:
                on = not autostart_on()
            if on:
                winreg.SetValueEx(k, "HubAgent", 0, winreg.REG_SZ, f'"{pythonw()}" "{os.path.abspath(__file__)}"')
            elif autostart_on():
                winreg.DeleteValue(k, "HubAgent")
        save_config({"autostart_set": True})

    def logout():
        link.token, link.state = None, None
        save_config({"url": link.base, "user": link.user, "token": None})
        link.ws and link.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(link.ws.close()))
        link.set_status("needs_login")

    def confirm_logout():
        from tkinter import messagebox
        S["busy"] += 1
        ok = messagebox.askyesno("cerrar sesión", "¿cerrar sesión? este pc dejará de enviar datos y los widgets se ocultarán.", parent=popup)
        S["busy"] -= 1
        if ok:
            logout()

    def open_service(which):
        if use_qt():
            qt.show(which)
        else:
            services_dialog(which)

    def qt_cmd(o):
        """Ordenes que llegan desde la ventana nueva."""
        c = o.get("c")
        if c == "open_portal":
            webbrowser.open(f"{link.base}/#token={link.token}" if link.token else link.base)
        elif c == "open_editor":
            qt.send({"t": "hide"})
            open_editor()
        elif c == "logout":
            ui(logout)
        elif c == "quit_agent":
            ui(quit_all)
        elif c == "reconnect":
            link.reconnect()
        elif c == "clear_toast":
            link.toast = ""
        elif c == "var_set":
            link.send({"type": "var_set", "id": o["id"], "value": o["value"]})
        elif c == "var_delete":
            link.send({"type": "var_delete", "id": o["id"]})
        elif c in ("var_share", "var_unshare"):
            link.send({"type": c, "id": o["id"], "user": o["user"]})
        elif c == "set_lang" and o.get("lang") in ("es", "en", "pt", "pi"):
            save_config({"lang": o["lang"]})
            ui(lang_changed)
        elif c in ("login", "svc", "update_install"):
            threading.Thread(target=qt_job, args=(o,), daemon=True).start()

    def qt_job(o):
        """Tareas lentas (iniciar sesion, probar un servicio): se contestan a la ventana cuando terminan."""
        try:
            if o["c"] == "update_install":
                install_update(link.base, link.server_version)   # si todo va bien, reinicia el proceso y no vuelve
                res = {"ok": True, "text": ""}
            elif o["c"] == "login":
                asyncio.run_coroutine_threadsafe(link.login(o["url"], o["user"].strip().lower(), o["pw"]), link.loop).result(15)
                res = {"ok": True, "text": ""}
            else:
                which = o["which"]
                keys = [k for _, k, _ in SERVICES[which][1]]
                save_config({k: str(o["values"].get(k, "")).strip() for k in keys})
                link.cache.clear()
                link.last[which] = 0
                text = ""
                if o.get("test"):
                    r = asyncio.run_coroutine_threadsafe(link.test_services(which), link.loop).result(25)
                    text = r.get(which, "escribe los datos para poder probar.")
                res = {"ok": True, "text": text}
        except Exception as ex:
            res = {"ok": False, "text": ("error: " + err_text(ex)) if o["c"] == "svc" else (str(ex) or type(ex).__name__)}
        qt.send({"t": "res", "rid": o["rid"], **res})
    if qt:
        qt.handler = qt_cmd

    LANG_NAMES = {"es": "Español", "en": "English", "pt": "Português", "pi": "Pirata ☠"}
    tt = lambda key: (lambda item: tr(key))   # texto del menu: se traduce cada vez que se abre

    def lang_item(code):
        return pystray.MenuItem(LANG_NAMES[code], lambda: (save_config({"lang": code}), ui(lang_changed)),
                                checked=lambda item: current_lang() == code, radio=True)

    icon = pystray.Icon("hub", make_icon(link.status), "Hub", pystray.Menu(
        pystray.MenuItem(tt("abrir"), lambda: ui(toggle_popup), default=True),
        pystray.MenuItem(tt("editar widgets (portal)"), lambda: open_editor()),
        pystray.MenuItem(tt("mover widgets"), lambda: widgets.set_move(not widgets.move), checked=lambda item: widgets.move),
        pystray.MenuItem(tt("compartir actividad (app activa)"),
                         lambda: save_config({"activity": not load_config().get("activity", False)}),
                         checked=lambda item: load_config().get("activity", False)),
        pystray.MenuItem(tt("conectar steam…"), lambda: ui(lambda: open_service("steam"))),
        pystray.MenuItem(tt("conectar roblox…"), lambda: ui(lambda: open_service("roblox"))),
        pystray.MenuItem(tt("abrir portal"), lambda: webbrowser.open(f"{link.base}/#token={link.token}" if link.token else link.base)),
        pystray.MenuItem(tt("iniciar con windows"), lambda: set_autostart(), checked=lambda item: autostart_on()),
        pystray.MenuItem(tt("idioma"), pystray.Menu(*[lang_item(c) for c in ("es", "en", "pt", "pi")])),
        pystray.MenuItem(tt("cerrar sesión"), lambda: ui(logout)),
        pystray.MenuItem(tt("salir"), lambda: ui(quit_all))))

    def lang_changed():
        """Cambió el idioma: se refresca el menu, la ventana y los widgets (el proceso de widgets lo lee al arrancar)."""
        icon.update_menu()
        icon.title = {"ok": tr("hub: en línea"), "offline": tr("hub: sin conexión"), "needs_login": tr("hub: sin sesión")}[link.status]
        if use_qt():
            qt.push(True)
        widgets.stop()
        widgets.sync()

    def quit_all():
        widgets.stop()
        if qt:
            qt.stop()
        icon.stop()
        root.quit()

    def on_change():
        ui(lambda: (icon.__setattr__("icon", make_icon(link.status)),
                    icon.__setattr__("title", {"ok": tr("hub: en línea"), "offline": tr("hub: sin conexión"), "needs_login": tr("hub: sin sesión")}[link.status]),
                    refresh() if visible() else None,
                    qt.push() if use_qt() and qt.visible else None,
                    qt.show() if use_qt() and not qt.visible and (link.update_state() == "hard" or link.ahead()) and time.time() - qt.hidden_at > 60 else None,
                    widgets.sync()))
    link.on_change = on_change

    def pump():
        try:
            while True:
                q.get_nowait()()
        except queue.Empty:
            pass
        root.after(100, pump)
    pump()
    icon.run_detached()
    if "autostart_set" not in load_config():   # primera vez: se activa «iniciar con windows»; el menu del icono lo apaga
        try:
            set_autostart(True)
        except OSError:
            pass
    if qt:
        qt.start()
    if autoshow or link.status == "needs_login":
        root.after(500, lambda: qt.show() if use_qt() else show())
    root.mainloop()


# ---------------- arranque ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?")
    ap.add_argument("user", nargs="?")
    ap.add_argument("--password")
    ap.add_argument("--name", default=platform.node())
    ap.add_argument("--headless", action="store_true", help="sin icono ni ventana (linux/mac)")
    ap.add_argument("--show", action="store_true", help="abrir la ventana al iniciar")
    ap.add_argument("--console", action="store_true", help="no relanzar sin ventana de consola (para depurar)")
    ap.add_argument("--shortcut", action="store_true", help="crear un acceso directo «Hub» en el escritorio (Windows)")
    ap.add_argument("--widgets-host", action="store_true", help=argparse.SUPPRESS)   # uso interno
    ap.add_argument("--tray-ui", action="store_true", help=argparse.SUPPRESS)        # uso interno
    ap.add_argument("--list-cameras", action="store_true", help=argparse.SUPPRESS)   # uso interno
    args = ap.parse_args()
    if args.widgets_host:
        return run_widget_host()
    if args.tray_ui:
        return run_tray_ui()
    if args.list_cameras:
        print(json.dumps(list_cameras(), ensure_ascii=False))
        return

    if args.shortcut:
        print("acceso directo creado:", make_shortcut() if platform.system() == "Windows" else "solo en windows")
        return
    if (platform.system() == "Windows" and not (args.headless or args.console) and
            Path(sys.executable).name.lower() == "python.exe" and pythonw() != sys.executable):
        import subprocess   # abierto con python.exe (doble clic en el .py): se relanza sin ventana de consola y esta se cierra
        subprocess.Popen([pythonw(), os.path.abspath(__file__)] + sys.argv[1:], creationflags=0x00000008 | 0x00000200, close_fds=True)
        return

    cfg = load_config()
    if args.url and args.url.rstrip("/") != cfg.get("url") or (args.user and args.user != cfg.get("user")):
        cfg = {"url": args.url or cfg.get("url", ""), "user": args.user or cfg.get("user", "")}  # otro hub/usuario: sesion nueva
    tray = platform.system() == "Windows" and not args.headless
    link = Link(cfg, args.name, lambda: None if tray else print("estado:", link.status))
    threading.Thread(target=lambda: asyncio.run(link.run()), daemon=True).start()
    link.ready.wait()

    if not link.token and (args.password or not tray):
        if not (link.base and args.user):
            sys.exit("uso: python agent.py url usuario")
        pw = args.password or getpass.getpass("contraseña: ")
        try:
            asyncio.run_coroutine_threadsafe(link.login(link.base or args.url, args.user, pw), link.loop).result(15)
        except Exception as e:
            sys.exit(str(e))
    if tray:
        run_tray(link, args.show)
    else:
        print("conectando… ctrl+c para salir.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
