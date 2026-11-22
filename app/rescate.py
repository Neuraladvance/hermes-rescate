# -*- coding: utf-8 -*-
"""HERMES-RESCATE: agente portatil de auditoria y reparacion de PCs Windows.

Uso:
  Rescate.bat                  menu interactivo
  Rescate.bat --auditar        auditoria completa + informe (sin preguntar)
  Rescate.bat --auto           auditoria + reparaciones seguras recomendadas
  Rescate.bat --reparar ID     ejecuta una reparacion del catalogo
  Rescate.bat --listar         lista el catalogo
  Rescate.bat --wifi           conecta al WiFi/hotspot configurado
  Rescate.bat --actualizar     instala las actualizaciones de Windows
  Rescate.bat --drivers        instala solo controladores desde Windows Update
  Rescate.bat --instalar X     instala un programa por id de winget o nombre
  Rescate.bat --chat           conversacion con la IA (si esta configurada)
  Rescate.bat --estado         estado rapido del equipo y del programa
Opciones: --sin-lento (omite Defender/BitLocker/actualizaciones), --si (no preguntar)
"""
import ctypes
import datetime
import getpass
import json
import os
import socket
import sys
import webbrowser

RAIZ_APP = os.path.dirname(os.path.abspath(__file__))
if RAIZ_APP not in sys.path:
    sys.path.insert(0, RAIZ_APP)

from nucleo import auditoria, diagnostico, informe, reparaciones, util  # noqa: E402

C = util
ANCHO = 78
VERSION = "1.0"


# ------------------------------------------------------------------ pintado
def titulo(texto):
    print("\n" + C.color("─" * ANCHO, C.GRIS))
    print(C.color(" " + texto, C.NEGRITA + ";" + C.CIAN))
    print(C.color("─" * ANCHO, C.GRIS))


def paso(texto):
    print(C.color("  · ", C.GRIS) + texto)


def bien(texto):
    print(C.color("  ✓ ", C.VERDE) + texto)


def mal(texto):
    print(C.color("  ✗ ", C.ROJO) + texto)


def ojo(texto):
    print(C.color("  ! ", C.AMARILLO) + texto)


def preguntar(texto, defecto="s"):
    try:
        respuesta = input("  %s [%s/%s]: " % (texto, "S" if defecto == "s" else "s",
                                              "s" if defecto == "s" else "N")).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not respuesta:
        return defecto == "s"
    return respuesta.startswith("s")


# ------------------------------------------------------------------ admin
def es_admin():
    return util.es_admin()


def relanzar_admin():
    """Se relanza elevado con UAC pidiendo la misma orden."""
    if es_admin():
        return False
    ejecutable = sys.executable
    argumentos = " ".join('"%s"' % a if " " in a else a for a in sys.argv)
    try:
        resultado = ctypes.windll.shell32.ShellExecuteW(None, "runas", ejecutable, argumentos, RAIZ_APP, 1)
        return resultado > 32
    except Exception as exc:
        mal("No se pudo pedir elevación: %s" % exc)
        return False


# ------------------------------------------------------------------ auditoria
def ejecutar_auditoria(con_lento=True):
    inicio = util.time.time() if hasattr(util, "time") else 0
    print(C.color("\n  Analizando el equipo. Tarda unos 30 segundos: no cierres esta ventana.", C.GRIS))
    datos = auditoria.auditar(con_lento=con_lento, aviso=lambda m: paso(m))
    datos["_inicio"] = inicio
    hallazgos, resumen = diagnostico.evaluar(datos)
    return datos, hallazgos, resumen


def pintar_veredicto(datos, hallazgos, resumen):
    so = datos.get("so") or {}
    veredicto = resumen["veredicto"]
    color = {diagnostico.CRITICO: C.ROJO, diagnostico.AVISO: C.AMARILLO}.get(veredicto, C.VERDE)
    titulo("Resultado")
    print("  %s · %s · %s" % (datos.get("equipo"), so.get("nombre"), so.get("modelo")))
    print("  %s" % C.color(resumen["titulo"].upper(), color + ";" + C.NEGRITA))
    print("  %d críticos · %d a revisar · %d informativos"
          % (resumen["cuenta"].get("critico", 0), resumen["cuenta"].get("aviso", 0),
             resumen["cuenta"].get("info", 0)))
    print()
    for x in hallazgos:
        marca = {diagnostico.CRITICO: C.color("●", C.ROJO),
                 diagnostico.AVISO: C.color("●", C.AMARILLO),
                 diagnostico.INFO: C.color("●", C.AZUL)}.get(x["severidad"], "·")
        print("  %s %s" % (marca, x["titulo"]))
        if x["severidad"] != diagnostico.INFO:
            print("     " + C.color(x["detalle"][:150], C.GRIS))


def informar(datos, hallazgos, resumen, ejecuciones=None):
    rutas = informe.generar(datos, hallazgos, resumen, ejecuciones)
    titulo("Informe guardado")
    print("  HTML : %s" % rutas["html"])
    print("  MD   : %s" % rutas["md"])
    if rutas.get("json"):
        print("  Datos: %s" % rutas["json"])
    return rutas


# ------------------------------------------------------------------ reparaciones
def aplicar_recomendadas(datos, hallazgos, resumen, auto=False):
    ids = diagnostico.recomendadas(hallazgos)
    if not ids:
        bien("No hay nada que reparar: el equipo está correcto.")
        return []
    seguras = [i for i in ids if reparaciones.obtener(i) and reparaciones.obtener(i)["nivel"] == 1]
    cambio = [i for i in ids if reparaciones.obtener(i) and reparaciones.obtener(i)["nivel"] == 2]
    manual = [i for i in ids if reparaciones.obtener(i) and reparaciones.obtener(i)["nivel"] == 3]

    titulo("Acciones recomendadas")
    for grupo, etiqueta in ((seguras, "Seguras"), (cambio, "Cambian configuración"), (manual, "Manuales")):
        if not grupo:
            continue
        print(C.color("  %s:" % etiqueta, C.GRIS))
        for rid in grupo:
            r = reparaciones.obtener(rid)
            extra = []
            if r["admin"]:
                extra.append("admin")
            if r["red"]:
                extra.append("internet")
            if r["lento"]:
                extra.append("lento")
            print("    - %-46s %s" % (r["nombre"][:46], C.color("(%s)" % ", ".join(extra), C.GRIS)
                                      if extra else ""))

    ejecuciones = []
    seleccion = list(seguras)
    if cambio:
        print()
        for rid in cambio:
            if auto:
                continue
            r = reparaciones.obtener(rid)
            if preguntar("¿Aplicar «%s»? %s" % (r["nombre"], C.color(r["cuando"], C.GRIS)), "n"):
                seleccion.append(rid)
    for rid in manual:
        r = reparaciones.obtener(rid)
        ojo("Manual: %s (no se ejecuta solo)" % r["nombre"])

    if not seleccion:
        print("\n  No se ha seleccionado ninguna acción.")
        return []

    if any(reparaciones.obtener(i)["nivel"] == 2 for i in seleccion) and es_admin():
        # Si ya se ha elegido crear el punto como una acción más, no se pregunta otra vez.
        ya_incluido = "punto_restauracion" in seleccion
        if (not auto) and not ya_incluido and preguntar(
                "¿Crear un punto de restauración antes? (recomendado)", "s"):
            paso("Creando punto de restauración...")
            registro = reparaciones.ejecutar("punto_restauracion", aviso=paso)
            ejecuciones.append(registro)
            (bien if registro["ok"] else ojo)("Punto de restauración: %s" % registro["mensaje"])

    titulo("Ejecutando")
    for rid in seleccion:
        r = reparaciones.obtener(rid)
        print("  %s %s" % (C.color("▶", C.CIAN), r["nombre"]))
        registro = reparaciones.ejecutar(rid, aviso=lambda m: print("      " + C.color(m, C.GRIS)))
        ejecuciones.append(registro)
        if registro.get("manual"):
            print(registro["detalle"])
        elif registro["ok"]:
            bien("%s (%s)" % (registro["mensaje"], _dur(registro.get("segundos"))))
        else:
            mal("%s (%s)" % (registro["mensaje"], _dur(registro.get("segundos"))))
        print()
    return ejecuciones


def _dur(segundos):
    try:
        segundos = float(segundos or 0)
    except Exception:
        return "?"
    return "%.1f s" % segundos if segundos < 90 else "%.1f min" % (segundos / 60)


# ------------------------------------------------------------------ submenus
def menu_wifi():
    from nucleo import wifi
    titulo("Red WiFi")
    adaptador = wifi.adaptador_wifi()
    if not adaptador:
        mal("Este equipo no tiene adaptador WiFi utilizable (o le faltan los controladores).")
        print("  Alternativas: cable de red, o compartir la conexión del móvil por USB.")
        return
    print("  Estado actual: %s" % (wifi.estado_conexion() or "sin conexión"))
    print("\n  Redes configuradas en este USB:")
    for red in wifi.cargar().get("redes") or []:
        print("    · %-20s (SSID: %s)" % (red.get("nombre"), red.get("ssid")))
    if not (wifi.cargar().get("redes") or []):
        print("    (ninguna todavía: usa la opción de abajo para escanear y guardar la tuya)")
    if preguntar("¿Conectar a la primera configurada?", "s"):
        for red in sorted(wifi.cargar().get("redes") or [], key=lambda r: r.get("prioridad", 9)):
            ok, mensaje = wifi.conectar(red.get("ssid", ""), wifi.desofuscar(red.get("clave", "")), aviso=paso)
            if ok:
                bien(mensaje)
                return
            mal(mensaje)
    if preguntar("¿Ver las redes visibles y conectar a una?", "n"):
        redes = wifi.escanear()
        for i, red in enumerate(redes, 1):
            print("   %2d. %-28s %s" % (i, red.get("ssid"), red.get("senal") or ""))
        try:
            elegida = int(input("  Número (0 para salir): ") or 0)
        except ValueError:
            return
        if 1 <= elegida <= len(redes):
            ssid = redes[elegida - 1]["ssid"]
            clave = input("  Contraseña de «%s»: " % ssid)
            ok, mensaje = wifi.conectar(ssid, clave, aviso=paso)
            (bien if ok else mal)(mensaje)
            if ok and preguntar("¿Guardarla en el USB para la próxima vez?", "s"):
                wifi.configurar(ssid, ssid, clave)
                bien("Guardada (ofuscada) en config/wifi.json")


def _grupo_de(elemento):
    """Normaliza el tipo que devuelve PowerShell (singular) al nombre del grupo."""
    tipo = str(elemento.get("tipo") or "actualizacion").strip().lower()
    return {"actualizacion": "actualizaciones", "actualizaciones": "actualizaciones",
            "controlador": "controladores", "controladores": "controladores",
            "firmware": "firmware"}.get(tipo, "actualizaciones")


def _listar_grupo(titulo_grupo, elementos, nota=None):
    """Pinta un grupo de actualizaciones con su tamaño."""
    if not elementos:
        return
    total_mb = sum(float(e.get("mb") or 0) for e in elementos)
    print(C.color("\n  %s (%d · %.1f MB)" % (titulo_grupo, len(elementos), total_mb), C.NEGRITA))
    for e in elementos[:8]:
        print("    · %-62s %6.1f MB" % (str(e.get("titulo"))[:62], float(e.get("mb") or 0)))
    if len(elementos) > 8:
        print(C.color("    … y %d más" % (len(elementos) - 8), C.GRIS))
    if nota:
        print(C.color("    " + nota, C.GRIS))


def menu_actualizar():
    """Busca primero, enseña qué hay por grupos y pregunta grupo a grupo.

    El firmware (BIOS/UEFI) va aparte y por defecto NO se instala: es lo único que
    puede dejar un portátil sin arrancar si se corta la corriente a mitad.
    """
    from nucleo import instalador
    titulo("Actualizaciones de Windows")
    print("  Primero se consulta qué hay pendiente, sin instalar nada.")
    paso("Buscando en Windows Update...")
    consulta = instalador.buscar_actualizaciones()
    if consulta.get("error"):
        mal(consulta["error"])
        return
    pendientes = consulta.get("pendientes") or []
    if not pendientes:
        bien("No hay nada pendiente. Este equipo está al día.")
        return

    grupos = {nombre: [] for nombre in ("actualizaciones", "controladores", "firmware")}
    for elemento in pendientes:
        grupos[_grupo_de(elemento)].append(elemento)

    print()
    _listar_grupo("Actualizaciones de Windows", grupos.get("actualizaciones"))
    _listar_grupo("Controladores", grupos.get("controladores"),
                  "Los de Windows Update son genéricos: si un dispositivo funciona bien, "
                  "puede ir peor después.")
    _listar_grupo("Firmware (BIOS/UEFI)", grupos.get("firmware"),
                  "OJO: si se corta la corriente durante la instalación, el equipo puede "
                  "quedar sin arrancar. Portátil enchufado y con batería.")

    elegir_actualizaciones = elegir_controladores = elegir_firmware = False
    if grupos.get("actualizaciones"):
        elegir_actualizaciones = preguntar(
            "¿Instalar las %d actualizaciones de Windows? (recomendado)"
            % len(grupos["actualizaciones"]), "s")
    if grupos.get("controladores"):
        elegir_controladores = preguntar(
            "¿Instalar los %d controladores? (solo si hay un problema con ese dispositivo)"
            % len(grupos["controladores"]), "n")
    if grupos.get("firmware"):
        elegir_firmware = preguntar(
            "¿Instalar el firmware/BIOS? Deja el portátil ENCHUFADO y con más del 50%% de "
            "batería, y no lo apagues hasta que termine", "n")

    if not (elegir_actualizaciones or elegir_controladores or elegir_firmware):
        print("\n  No se ha seleccionado nada: no se toca el equipo.")
        return

    resultado = instalador.actualizar_windows(
        aviso=paso,
        solo_actualizaciones=elegir_actualizaciones and not (elegir_controladores or elegir_firmware),
        solo_drivers=(elegir_controladores or elegir_firmware) and not elegir_actualizaciones,
        excluir_firmware=not elegir_firmware)
    titulo("Resultado de Windows Update")
    if resultado.get("error"):
        mal(resultado["error"])
        return
    print("  Instaladas: %d   ·   Con problemas: %d"
          % (len(resultado.get("hechas") or []), len(resultado.get("fallidas") or [])))
    for h in resultado.get("hechas") or []:
        bien("%s (%s)" % (h.get("titulo"), h.get("resultado")))
    for f in resultado.get("fallidas") or []:
        mal("%s — %s" % (f.get("titulo"), f.get("motivo")))
    if resultado.get("reinicio_necesario"):
        ojo("Hace falta reiniciar para terminar de aplicar los cambios.")


def menu_instalar():
    from nucleo import instalador
    titulo("Instalar programas")
    version = instalador.winget_disponible()
    if not version:
        mal("Este equipo no tiene winget (Administrador de paquetes de Windows).")
        print("  Se instala solo desde Microsoft Store con la app «Instalador de aplicaciones».")
        print("  Mientras tanto, los programas se pueden descargar a mano.")
        return
    print("  winget %s" % version)
    print("\n  Programas habituales:")
    for i, programa in enumerate(instalador.CATALOGO_PROGRAMAS, 1):
        print("   %2d. %-24s %s" % (i, programa["nombre"], C.color(programa["para"], C.GRIS)))
    print("    b. Buscar por nombre")
    print("    0. Volver")
    eleccion = input("\n  Opción: ").strip().lower()
    if eleccion == "b":
        termino = input("  Buscar: ").strip()
        resultados = instalador.buscar(termino)
        if not resultados:
            mal("Sin resultados.")
            return
        for i, r in enumerate(resultados, 1):
            print("   %2d. %-34s %s" % (i, r["nombre"][:34], C.color(r["id"], C.GRIS)))
        try:
            indice = int(input("  Número a instalar (0 para salir): ") or 0)
        except ValueError:
            return
        if not (1 <= indice <= len(resultados)):
            return
        elegido = resultados[indice - 1]["id"]
    elif eleccion.isdigit() and 1 <= int(eleccion) <= len(instalador.CATALOGO_PROGRAMAS):
        elegido = instalador.CATALOGO_PROGRAMAS[int(eleccion) - 1]["id"]
    else:
        return
    if not preguntar("¿Instalar %s en modo silencioso?" % elegido, "s"):
        return
    paso("Instalando %s (puede tardar varios minutos)..." % elegido)
    ok, salida = instalador.instalar(elegido)
    (bien if ok else mal)("Instalación %s" % ("completada" if ok else "con errores"))
    if not ok:
        print(C.color(salida[-800:], C.GRIS))


def menu_catalogo(datos=None, hallazgos=None, resumen=None):
    titulo("Catálogo de reparaciones")
    grupos = reparaciones.por_categoria()
    indice = []
    for categoria in sorted(grupos):
        print(C.color("\n  %s" % categoria.upper(), C.GRIS))
        for r in grupos[categoria]:
            indice.append(r["id"])
            requisitos = []
            if r["admin"]:
                requisitos.append("admin")
            if r["red"]:
                requisitos.append("internet")
            print("   %2d. %-44s %-18s %s"
                  % (len(indice), r["nombre"][:44], reparaciones.NIVELES[r["nivel"]],
                     C.color(", ".join(requisitos), C.GRIS)))
    print("\n   0. Volver")
    entrada = input("\n  Número (o varios separados por coma): ").strip()
    if not entrada or entrada == "0":
        return []
    seleccion = []
    for trozo in entrada.replace(" ", ",").split(","):
        if trozo.isdigit() and 1 <= int(trozo) <= len(indice):
            seleccion.append(indice[int(trozo) - 1])
    ejecuciones = []
    for rid in seleccion:
        r = reparaciones.obtener(rid)
        if r["nivel"] == 3:
            print("\n  %s\n%s" % (C.color(r["nombre"], C.CIAN + ";" + C.NEGRITA), r["que"]))
            registro = reparaciones.ejecutar(rid)
            print(registro["detalle"])
            continue
        riesgo = "SEGURO" if r["nivel"] == 1 else "CAMBIA CONFIGURACIÓN"
        if r["nivel"] == 2 and not preguntar("%s (%s). ¿Continuar?" % (r["nombre"], riesgo), "n"):
            continue
        print("  %s %s" % (C.color("▶", C.CIAN), r["nombre"]))
        registro = reparaciones.ejecutar(rid, aviso=lambda m: print("      " + C.color(m, C.GRIS)))
        ejecuciones.append(registro)
        (bien if registro["ok"] else mal)("%s (%s)" % (registro["mensaje"], _dur(registro.get("segundos"))))
    return ejecuciones


def _desbloquear_ia():
    """Si la clave está cifrada en el USB, pide la contraseña. Devuelve la config o None."""
    from nucleo import ia
    cfg = ia.config()
    if not ia.hay_clave_cifrada() or ia.desbloqueada():
        return cfg
    titulo("Clave de IA protegida")
    print("  La clave de este USB está cifrada. Escribe la contraseña para usarla.")
    print(C.color("  La contraseña está apuntada en la carpeta KEYS del técnico:", C.GRIS))
    print(C.color("    hermes-rescate-USB-contrasena_<fecha>.txt", C.GRIS))
    print(C.color("  Deja en blanco para seguir SIN inteligencia artificial "
                  "(todo lo demás funciona).", C.GRIS))
    for intento in (1, 2, 3):
        try:
            password = getpass.getpass("  contraseña del USB (%d/3): " % intento)
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if not password.strip():
            ojo("Se sigue sin IA: auditoría, reparaciones e informes funcionan igual.")
            return None
        try:
            meta = ia.desbloquear(password)
        except RuntimeError as exc:
            mal(str(exc))
            continue
        extra = ""
        if meta.get("caduca"):
            extra = " · caduca el %s" % meta["caduca"][:10]
        bien("Clave descifrada en memoria%s." % extra)
        return ia.config()
    mal("No se pudo descifrar. El resto del programa funciona igual sin IA.")
    return None


def _cifrar_clave_pedida(clave, meta=None):
    """Pide contraseña y guarda la clave cifrada en config/ia.dat."""
    from nucleo import ia
    meta = meta or {}
    for _ in range(3):
        try:
            una = getpass.getpass("  contraseña para cifrar (mínimo 8 caracteres): ")
            otra = getpass.getpass("  repite la contraseña: ")
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if len(una) < 8:
            ojo("Demasiado corta: usa al menos 8 caracteres.")
            continue
        if una != otra:
            mal("No coinciden.")
            continue
        ruta = ia.cifrar_clave(clave, una,
                               caduca=meta.get("caduca") or None,
                               nombre=meta.get("nombre") or "HERMES-RESCATE-USB")
        ia.guardar_config(clave="")
        bien("Clave cifrada en %s" % ruta)
        ojo("Sin esa contraseña la clave NO se puede recuperar. Apúntala en un sitio seguro.")
        return True
    mal("No se cifró: la clave sigue en config/config.json en claro.")
    return False


def _guia_clave(cfg=None):
    """Explica cómo conseguir una clave gratuita y la guarda si el usuario quiere."""
    from nucleo import ia
    titulo("Activar el chat (gratis y opcional)")
    if ia.hay_clave_cifrada() or ia.clave_efectiva(cfg):
        # Ya hay clave: este asistente sobra y confunde (lleva a pegar otra encima).
        bien("Este USB YA tiene una clave de IA guardada.")
        print("  Si está cifrada, solo hace falta la contraseña cuando abras el chat.")
        print("  Para usar otra clave distinta:  Rescate.bat --ia-clave")
        print("  Para cambiar la contraseña:     Rescate.bat --ia-contrasena")
        return
    print("  Todo lo demás del programa funciona sin esto. El chat usa los modelos")
    print("  gratuitos de OpenRouter: cuestan 0 y no hay que pagar nada.")
    print()
    print("  PASOS (2 minutos, sin tarjeta)")
    print("    1. Abre https://openrouter.ai/keys")
    print("    2. Entra o crea la cuenta (con Google vale).")
    print("    3. Pulsa «Create key» y ponle un nombre, p. ej. «USB rescate».")
    print("    4. Copia el valor: empieza por sk-or-v1- y solo se muestra una vez.")
    print()
    print("  La clave es personal: no la comparta ni la publique.")
    print()
    if preguntar("¿Abrir la página de OpenRouter en el navegador?", "s"):
        try:
            webbrowser.open("https://openrouter.ai/keys")
            bien("Página abierta.")
        except Exception as exc:
            ojo("No se pudo abrir el navegador: %s" % exc)
    print()
    if not preguntar("¿Pegar aquí la clave ahora? (no se verá en pantalla)", "s"):
        print("  Cuando la tengas: Rescate.bat --ia-clave")
        return
    try:
        clave = getpass.getpass("  clave: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not clave:
        ojo("No has pegado nada: no se ha cambiado nada.")
        print("  Cuando la tengas: Rescate.bat --ia-clave")
        return
    if not clave.startswith("sk-"):
        ojo("No empieza por «sk-»: la guardo igual, pero revisa que no falte un trozo.")
    endpoint = (cfg or {}).get("endpoint") or "https://openrouter.ai/api/v1"
    ia.guardar_config(endpoint=endpoint, clave=clave)
    bien("Guardada en config/config.json")
    if preguntar("¿Cifrarla con contraseña? (recomendado si el USB puede perderse)", "s"):
        if _cifrar_clave_pedida(clave):
            print()
            cfg = _desbloquear_ia() or ia.config()
    print()
    cfg = ia.config()
    ok, mensaje = ia.probar(cfg)
    print(mensaje)
    (bien if ok else ojo)("Chat listo." if ok else
                         "Se ha guardado, aunque ahora mismo no responde ningún modelo.")


def menu_chat(datos, hallazgos, resumen):
    from nucleo import ia
    titulo("Hablar con la IA")
    cfg = _desbloquear_ia()
    if cfg is None:
        # En blanco = "sigo sin IA". Solo se ofrece crear una clave si de verdad no hay.
        if ia.hay_clave_cifrada():
            ojo("Sigues sin IA, como pediste. Si quieres el chat, repite la opción 7 y "
                "escribe la contraseña del USB.")
        else:
            _guia_clave(cfg)
        return
    if not ia.disponible():
        mal("La IA no está configurada (y no hace falta para nada de lo anterior).")
        print()
        _guia_clave(cfg)
        return
    agente = ia.Agente(datos, hallazgos, resumen, cfg)
    print("  Cadena de modelos: %s" % " → ".join(ia.modelos(cfg)))
    print("  Si uno falla (tope diario, modelo retirado), salta al siguiente.")
    print(agente.aviso_privacidad())
    if not preguntar("¿Enviar este resumen y empezar la conversación?", "n"):
        print("  Cancelado: no se ha enviado nada.")
        return
    print("\n  Escribe tu pregunta. «salir» para terminar, «accion <id>» para ejecutar una del catálogo.\n")
    while True:
        try:
            texto = input(C.color("  tú › ", C.CIAN)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not texto or texto.lower() in ("salir", "exit", "quit"):
            return
        if texto.lower().startswith("accion "):
            rid = texto.split(None, 1)[1].strip()
            _ejecutar_con_confirmacion(rid)
            continue
        try:
            respuesta, acciones = agente.preguntar(texto)
        except RuntimeError as exc:
            mal(str(exc))
            continue
        if agente.ultimos_errores:
            ojo("Respondió %s (fallaron: %s)"
                % (agente.ultimo_modelo,
                   ", ".join(m for m, _ in agente.ultimos_errores)))
        print("\n" + "\n".join("  " + linea for linea in respuesta.splitlines()) + "\n")
        for rid in acciones:
            r = reparaciones.obtener(rid)
            if r and preguntar("La IA propone «%s». ¿Ejecutarla?" % r["nombre"], "n"):
                _ejecutar_con_confirmacion(rid)


def _ejecutar_con_confirmacion(rid):
    r = reparaciones.obtener(rid)
    if not r:
        mal("Esa acción no existe en el catálogo: %s" % rid)
        return
    if r["nivel"] == 3:
        print(r["que"])
        print(reparaciones.ejecutar(rid)["detalle"])
        return
    registro = reparaciones.ejecutar(rid, aviso=lambda m: print("      " + C.color(m, C.GRIS)))
    (bien if registro["ok"] else mal)("%s (%s)" % (registro["mensaje"], _dur(registro.get("segundos"))))


# ------------------------------------------------------------------ menu
def cabecera():
    so = {}
    try:
        rc, out, _ = util.ejecutar(["cmd", "/c", "ver"], timeout=10)
    except Exception:
        out = ""
    print(C.color("\n  HERMES-RESCATE 1.0", C.NEGRITA + ";" + C.CIAN)
          + C.color("  ·  auditoría y reparación de equipos Windows", C.GRIS))
    print(C.color("  " + "═" * (ANCHO - 2), C.GRIS))
    print(C.color("  Proyecto de Neuraladvance.net · licencia MIT · aviso legal: opción 9", C.GRIS))
    print("  Equipo: %s   Usuario: %s   Admin: %s"
          % (os.environ.get("COMPUTERNAME"), os.environ.get("USERNAME"),
             C.color("sí", C.VERDE) if es_admin() else C.color("NO", C.AMARILLO)))
    try:
        from nucleo import wifi
        estado = wifi.estado_conexion()
        print("  Red: %s" % (estado or "sin conexión"))
    except Exception:
        pass
    print("  USB: %s" % os.path.dirname(RAIZ_APP))


# ------------------------------------------------------------------ aviso legal
TEXTO_AVISO = """
  EL USO DE ESTE PROGRAMA ES BAJO LA RESPONSABILIDAD ÚNICA Y EXCLUSIVA DE QUIEN
  LO EJECUTA. Nadie más responde de lo que se haga con él ni de las consecuencias
  en el equipo.

  HERMES-RESCATE es un proyecto de Neuraladvance.net (https://neuraladvance.net),
  publicado con licencia MIT.

  Se entrega «tal cual», SIN GARANTÍA de ningún tipo. Modifica la configuración
  del sistema cuando se le pide: haz copia de seguridad de los datos antes de
  usarlo y úsalo solo en equipos propios o con autorización expresa del
  responsable del equipo.

  Los informes y registros contienen datos del equipo auditado (nombre, usuario,
  número de serie, MAC, IP, programas y eventos). Quien ejecuta el programa es
  el responsable de custodiarlos y de cumplir el RGPD si procede. El autor del
  software no recibe ni almacena esos datos.

  El aviso completo (garantías, terceros, límites de la IA y responsabilidad)
  está en el fichero DISCLAIMER.md que viaja en este mismo USB.

  Desarrollado con asistencia de IA (modelo DeepSeek a través del agente Hermes)
  y probado en equipos reales.
"""


def menu_aviso():
    titulo("DISCLAIMER · Aviso legal y créditos")
    print(TEXTO_AVISO)
    ruta = os.path.join(util.RAIZ, "DISCLAIMER.md")
    if os.path.exists(ruta):
        print("  Fichero completo: %s" % ruta)
        if preguntar("¿Abrirlo con el programa predeterminado?", "n"):
            try:
                os.startfile(ruta)
            except Exception as exc:
                mal("No se pudo abrir: %s" % exc)
    else:
        ojo("No encuentro DISCLAIMER.md en el USB (debería estar junto a Rescate.bat).")
    ultimas = _aceptaciones()[-1:]
    if ultimas:
        fila = ultimas[0]
        print("  Última decisión registrada: %s · %s · %s"
              % (fila.get("decision"), fila.get("equipo_nombre"), fila.get("fecha")))


def _huella_equipo():
    """Equipo + usuario, para no repetir el aviso en la misma máquina."""
    try:
        nombre = socket.gethostname()
    except Exception:
        nombre = "desconocido"
    try:
        usuario = getpass.getuser()
    except Exception:
        usuario = "desconocido"
    return "%s|%s" % (nombre.lower(), usuario.lower())


def _aceptaciones():
    try:
        with open(util.RUTA_ACEPTACIONES, "r", encoding="utf-8") as f:
            return [json.loads(linea) for linea in f if linea.strip()]
    except Exception:
        return []


def _ya_aceptado():
    """Ya no se usa para saltar el aviso: ahora se pide en CADA ejecución.

    Se conserva el registro como auditoría (quién aceptó, cuándo y desde dónde).
    """
    huella = _huella_equipo()
    ultima = None
    for fila in _aceptaciones():
        if fila.get("equipo") == huella and fila.get("version") == VERSION:
            ultima = fila.get("decision")
    return ultima == "ACEPTO"


def _registrar_aceptacion(decision, origen="inicio"):
    """Deja constancia en logs/aceptaciones.jsonl (una línea JSON por decisión)."""
    os.makedirs(util.LOGS, exist_ok=True)
    fila = {
        "fecha": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "equipo": _huella_equipo(),
        "equipo_nombre": socket.gethostname(),
        "usuario": getpass.getuser(),
        "version": VERSION,
        "decision": decision,
        "origen": origen,
        "carpeta": util.RAIZ,
    }
    try:
        with open(util.RUTA_ACEPTACIONES, "a", encoding="utf-8") as f:
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")
    except Exception as exc:
        ojo("No se pudo registrar la decisión en el log: %s" % exc)
    return fila


def puerta_disclaimer(automatico=False):
    """Muestra el aviso y exige ACEPTO **en cada ejecución**.

    No se recuerda la aceptación anterior a propósito: el aviso es un recordatorio de
    que el programa modifica el sistema y de que el riesgo es de quien lo usa. Cada
    decisión queda registrada en logs/aceptaciones.jsonl.

    `automatico` (orden --acepto) responde ACEPTO sin preguntar, para ejecuciones
    desatendidas; queda registrado con origen «parametro».
    """
    if automatico:
        _registrar_aceptacion("ACEPTO", origen="parametro")
        print(C.color("\n  Aviso aceptado por parámetro (--acepto).", C.GRIS))
        return True
    linea = C.color("  " + "═" * (ANCHO - 2), C.AMARILLO)
    print()
    print(linea)
    print(C.color("  DISCLAIMER · AVISO LEGAL", C.NEGRITA + (C.AMARILLO or "")))
    print(C.color("  LEE ESTO ANTES DE USAR EL PROGRAMA", C.AMARILLO))
    print(linea)
    print(TEXTO_AVISO)
    print(C.color("  ── No se puede continuar sin aceptar. ──", C.GRIS))
    ruta = os.path.join(util.RAIZ, "DISCLAIMER.md")
    if os.path.exists(ruta):
        print("  Texto completo: %s" % ruta)
    print()
    print("  Escribe %s para continuar o %s para salir: si no aceptas el DISCLAIMER."
          % (C.color("S", C.VERDE), C.color("N", C.ROJO)))
    while True:
        try:
            respuesta = input(C.color("  › ", C.NEGRITA)).strip().upper()
        except (EOFError, KeyboardInterrupt):
            print()
            respuesta = "N"
        if respuesta == "S":
            _registrar_aceptacion("ACEPTO")
            bien("Aceptado. Registrado en logs/aceptaciones.jsonl")
            print()
            return True
        if respuesta in ("N", ""):
            _registrar_aceptacion("REHUSO")
            mal("Rehusado: el programa no se usará.")
            print("  Decisión registrada en logs/aceptaciones.jsonl")
            print()
            return False
        print("  Respuesta no válida: escribe S (sí) o N (no).")


def menu_principal():
    datos = hallazgos = resumen = None
    while True:
        cabecera()
        print(C.color("  " + "─" * (ANCHO - 2), C.GRIS))
        if not es_admin():
            print("  " + C.color("A. Reiniciar como administrador", C.AMARILLO)
                  + C.color("  (necesario para la mayoría de reparaciones)", C.GRIS))
        print("  1. Revisar el equipo y generar informe")
        print("  2. Reparar lo recomendado")
        print("  3. Conectar al WiFi del técnico (hotspot)")
        print("  4. Instalar actualizaciones de Windows")
        print("  5. Instalar programas")
        print("  6. Catálogo de reparaciones")
        print("  7. Hablar con la IA")
        print("  8. Abrir la carpeta de informes")
        print("  9. DISCLAIMER · Aviso legal y créditos")
        print("  0. Salir")
        try:
            opcion = input(C.color("\n  Opción: ", C.NEGRITA)).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if opcion == "0":
            return 0
        if opcion == "a":
            if not relanzar_admin():
                ojo("No se pudo elevar (o ya eres administrador).")
            continue
        if opcion == "1":
            datos, hallazgos, resumen = ejecutar_auditoria()
            pintar_veredicto(datos, hallazgos, resumen)
            informar(datos, hallazgos, resumen)
        elif opcion == "2":
            if datos is None:
                datos, hallazgos, resumen = ejecutar_auditoria()
                pintar_veredicto(datos, hallazgos, resumen)
            ejecuciones = aplicar_recomendadas(datos, hallazgos, resumen)
            if ejecuciones:
                informar(datos, hallazgos, resumen, ejecuciones)
        elif opcion == "3":
            menu_wifi()
        elif opcion == "4":
            menu_actualizar()
        elif opcion == "5":
            menu_instalar()
        elif opcion == "6":
            ejecuciones = menu_catalogo()
            if ejecuciones and datos is not None:
                informar(datos, hallazgos, resumen, ejecuciones)
        elif opcion == "7":
            if datos is None:
                datos, hallazgos, resumen = ejecutar_auditoria()
                pintar_veredicto(datos, hallazgos, resumen)
            menu_chat(datos, hallazgos, resumen)
        elif opcion == "8":
            os.startfile(util.INFORMES)
        elif opcion == "9":
            menu_aviso()
        else:
            ojo("Opción no válida.")


def menu_estado():
    from nucleo import wifi, instalador, ia
    titulo("Estado")
    print("  Admin        : %s" % ("sí" if es_admin() else "NO"))
    print("  Windows      : %s" % (os.environ.get("OS")))
    print("  USB          : %s" % os.path.dirname(RAIZ_APP))
    print("  WiFi         : %s" % (wifi.estado_conexion() or "sin red"))
    print("  winget       : %s" % (instalador.winget_disponible() or "no disponible"))
    print("  IA           : %s" % ("configurada (%s)" % ia.config()["modelo"] if ia.disponible()
                                 else "sin configurar (el programa funciona igual)"))
    print("  Informes     : %s" % util.INFORMES)
    print("  Redes WiFi   : %s" % ", ".join(r.get("ssid") or "?" for r in wifi.cargar().get("redes") or []))


# ------------------------------------------------------------------ CLI
def main():
    util.preparar_consola()
    util.habilitar_ansi()
    argumentos = sys.argv[1:]
    sin_lento = "--sin-lento" in argumentos
    automatico = "--si" in argumentos or "--auto" in argumentos

    if "--aviso" in argumentos:
        menu_aviso()
        return 0
    if "--olvidar-acepto" in argumentos:
        ojo("Ya no hace falta: el aviso sale en CADA ejecución.")
        return 0
    if not puerta_disclaimer(automatico="--acepto" in argumentos):
        return 2
    if "--estado" in argumentos:
        menu_estado()
        return 0
    if "--ia-contrasena" in argumentos:
        from nucleo import ia
        titulo("Cambiar la contraseña de la clave cifrada")
        if not ia.hay_clave_cifrada():
            mal("No hay ninguna clave cifrada (config/ia.dat) en este USB.")
            return 1
        print("  Se pide la contraseña actual para poder volver a cifrar con la nueva.")
        try:
            actual = getpass.getpass("  contraseña actual: ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        try:
            meta = ia.desbloquear(actual)
        except RuntimeError as exc:
            mal(str(exc))
            return 1
        clave = ia.clave_efectiva()
        if not clave:
            mal("No se pudo leer la clave descifrada.")
            return 1
        bien("Clave descifrada. Ahora escribe la contraseña nueva.")
        return 0 if _cifrar_clave_pedida(clave, meta) else 1

    if "--ia-clave" in argumentos:
        from nucleo import ia
        titulo("Guardar la clave de IA")
        print("  Pega la clave de OpenRouter (empieza por sk-or-v1-). No se verá al escribirla.")
        try:
            clave = getpass.getpass("  clave: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if not clave:
            mal("No has pegado nada.")
            return 1
        ia.guardar_config(clave=clave)
        bien("Guardada en config/config.json")
        if preguntar("¿Cifrarla con contraseña (recomendado en un USB)?", "s"):
            _cifrar_clave_pedida(clave)
        return 0
    if "--ia-cifrar" in argumentos:
        from nucleo import ia
        titulo("Cifrar la clave de IA del USB")
        cfg = ia.config()
        if ia.hay_clave_cifrada():
            ojo("Ya existe config/ia.dat: se sobrescribirá con la clave y contraseña nuevas.")
        if not cfg.get("clave"):
            mal("No hay ninguna clave en claro en config/config.json para cifrar.")
            print("  Guarda primero la clave con: Rescate.bat --ia-clave")
            return 1
        return 0 if _cifrar_clave_pedida(cfg["clave"]) else 1
    if "--ia-probar" in argumentos:
        from nucleo import ia
        titulo("Prueba de la cadena de modelos")
        cfg = _desbloquear_ia() or ia.config()
        print("  endpoint: %s" % (cfg["endpoint"] or "(vacío)"))
        print("  clave   : %s" % ("cifrada en el USB (descifrada)" if ia.desbloqueada()
                                  else ("en claro en config.json" if cfg["clave"] else "NO configurada")))
        print("  cadena  : %s" % (" → ".join(ia.modelos(cfg)) or "(ningún modelo)"))
        print()
        ok, mensaje = ia.probar(cfg)
        print(mensaje)
        print()
        (bien if ok else mal)("Modelo operativo." if ok else "Ningún modelo disponible ahora mismo.")
        return 0 if ok else 1
    if "--listar" in argumentos:
        titulo("Catálogo de reparaciones")
        for categoria, lista in sorted(reparaciones.por_categoria().items()):
            print(C.color("\n  %s" % categoria.upper(), C.GRIS))
            for r in lista:
                print("   %-22s %-44s %s" % (r["id"][:22], r["nombre"][:44],
                                             reparaciones.NIVELES[r["nivel"]]))
        return 0
    if "--wifi" in argumentos:
        menu_wifi()
        return 0
    if "--buscar-actualizaciones" in argumentos:
        from nucleo import instalador
        titulo("Windows Update · solo consulta")
        consulta = instalador.buscar_actualizaciones()
        if consulta.get("error"):
            mal(consulta["error"])
            return 1
        pendientes = consulta.get("pendientes") or []
        if not pendientes:
            bien("No hay nada pendiente.")
            return 0
        for nombre in ("actualizaciones", "controladores", "firmware"):
            elementos = [e for e in pendientes if _grupo_de(e) == nombre]
            _listar_grupo({"actualizaciones": "Actualizaciones de Windows",
                           "controladores": "Controladores",
                           "firmware": "Firmware (BIOS/UEFI)"}[nombre], elementos)
        print()
        print("  Total: %d elementos · %.1f MB"
              % (len(pendientes), sum(float(e.get("mb") or 0) for e in pendientes)))
        print("  (no se ha instalado nada)")
        return 0
    if "--actualizar" in argumentos or "--drivers" in argumentos:
        from nucleo import instalador
        solo_drivers = "--drivers" in argumentos
        con_firmware = "--con-firmware" in argumentos
        if con_firmware and not solo_drivers:
            ojo("El firmware solo se instala con --drivers --con-firmware.")
        paso("Instalando %s (puede tardar mucho)..."
             % ("controladores" if solo_drivers else "actualizaciones y controladores"))
        resultado = instalador.actualizar_windows(solo_drivers=solo_drivers, aviso=paso,
                                                  excluir_firmware=not con_firmware)
        if resultado.get("error"):
            mal(resultado["error"])
            return 1
        bien("%d instaladas, %d con problemas"
             % (len(resultado.get("hechas") or []), len(resultado.get("fallidas") or [])))
        if resultado.get("excluir_firmware"):
            ojo("Firmware/BIOS excluido a propósito (usa --con-firmware para incluirlo).")
        return 0
    if "--instalar" in argumentos:
        from nucleo import instalador
        indice = argumentos.index("--instalar")
        paquete = argumentos[indice + 1] if len(argumentos) > indice + 1 else ""
        if not paquete:
            mal("Falta el id del paquete. Ejemplo: --instalar 7zip.7zip")
            return 2
        paso("Instalando %s..." % paquete)
        ok, salida = instalador.instalar(paquete)
        (bien if ok else mal)("Instalación %s" % ("completada" if ok else "con errores"))
        if not ok:
            print(salida[-800:])
        return 0 if ok else 1
    if "--reparar" in argumentos:
        indice = argumentos.index("--reparar")
        ids = argumentos[indice + 1].split(",") if len(argumentos) > indice + 1 else []
        ejecuciones = []
        for rid in ids:
            print("  ▶ %s" % rid)
            registro = reparaciones.ejecutar(rid, aviso=lambda m: print("      " + m))
            ejecuciones.append(registro)
            (bien if registro["ok"] else mal)("%s (%s)" % (registro["mensaje"], _dur(registro.get("segundos"))))
        return 0 if all(e["ok"] for e in ejecuciones) else 1

    if "--auditar" in argumentos or "--auto" in argumentos or argumentos:
        datos, hallazgos, resumen = ejecutar_auditoria(con_lento=not sin_lento)
        pintar_veredicto(datos, hallazgos, resumen)
        ejecuciones = []
        if "--auto" in argumentos:
            ejecuciones = aplicar_recomendadas(datos, hallazgos, resumen, auto=automatico)
        rutas = informar(datos, hallazgos, resumen, ejecuciones)
        print("\n  Informe: %s" % rutas["html"])
        return 0

    try:
        return menu_principal()
    except KeyboardInterrupt:
        print("\n  Interrumpido.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
