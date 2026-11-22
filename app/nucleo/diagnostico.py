# -*- coding: utf-8 -*-
"""Motor de diagnostico determinista: datos -> hallazgos + acciones recomendadas.

Funciona sin IA y sin internet. Cada hallazgo puede apuntar a reparaciones del
catalogo. Nada de alarmismo: se distingue lo que hay que arreglar de lo que solo
es informacion.
"""
CRITICO = "critico"
AVISO = "aviso"
INFO = "info"

ORDEN = {CRITICO: 0, AVISO: 1, INFO: 2}
ETIQUETA = {CRITICO: "Crítico", AVISO: "Revisar", INFO: "Información"}


def _n(valor, defecto=0.0):
    try:
        if valor is None:
            return defecto
        return float(valor)
    except (TypeError, ValueError):
        return defecto


def _h(valor):
    return valor is not None and str(valor).strip() != ""


def _halla(hallazgos, hid, severidad, titulo, detalle, reparaciones=None, datos=None):
    hallazgos.append({
        "id": hid,
        "severidad": severidad,
        "titulo": titulo,
        "detalle": detalle,
        "reparaciones": reparaciones or [],
        "datos": datos or {},
    })


def evaluar(datos):
    """Devuelve (hallazgos, resumen)."""
    h = []
    if not datos or not datos.get("so"):
        _halla(h, "sin_datos", CRITICO, "No se pudo leer el sistema",
               "La auditoría no devolvió datos del sistema operativo. Puede ser un equipo "
               "con WMI dañado o una política que lo bloquea.")
        return h, _resumen(h)

    so = datos.get("so") or {}
    admin = bool(datos.get("admin"))

    # ---------------------------------------------------------------- activacion
    act = datos.get("activacion") or {}
    if _h(act) and _n(act.get("estado"), -1) != 1:
        _halla(h, "activacion", AVISO, "Windows no está activado",
               "%s. Sin activar, Windows limita la personalización y puede dejar de recibir "
               "algunas actualizaciones." % (act.get("descripcion") or "estado desconocido"))

    # ---------------------------------------------------------------- discos
    for disco in datos.get("discos") or []:
        nombre = disco.get("modelo") or "disco"
        if disco.get("fallo_previsto") is True:
            _halla(h, "disco_fallo", CRITICO, "El disco avisa de fallo inminente",
                   "%s (%s GB) tiene el aviso SMART de fallo activo. Hay que copiar los datos "
                   "y sustituirlo." % (nombre, disco.get("gb")),
                   datos=disco)
        if _h(disco.get("estado")) and str(disco.get("estado")).upper() not in ("OK", "UNKNOWN"):
            _halla(h, "disco_estado", AVISO, "Disco con estado anómalo",
                   "%s informa estado «%s»." % (nombre, disco.get("estado")), datos=disco)

    for fisico in datos.get("discos_fisicos") or []:
        salud = str(fisico.get("salud") or "").lower()
        if salud and salud not in ("healthy", "saludable", "unknown", ""):
            _halla(h, "disco_salud", CRITICO, "Disco marcado como no saludable",
                   "%s: salud «%s», estado «%s»." % (fisico.get("modelo"), fisico.get("salud"),
                                                    fisico.get("operativo")),
                   reparaciones=["instrucciones_disco"], datos=fisico)

    lento = datos.get("lento") or {}
    for d in lento.get("desgaste") or []:
        desgaste = _n(d.get("desgaste_pct"), -1)
        if desgaste >= 90:
            _halla(h, "desgaste_disco", CRITICO, "Disco al final de su vida útil",
                   "%s con %s%% de desgaste (%s horas encendido). Los SSD se vuelven "
                   "inestables al llegar al 100%%: conviene sustituirlo ya."
                   % (d.get("modelo"), int(desgaste), d.get("horas_encendido") or "?"))
        elif desgaste >= 80:
            _halla(h, "desgaste_disco", AVISO, "Disco con desgaste alto",
                   "%s con %s%% de desgaste. vigilar y planificar sustitución."
                   % (d.get("modelo"), int(desgaste)))
        temp = _n(d.get("temperatura"), 0)
        if temp and temp > 65:
            _halla(h, "disco_temperatura", AVISO, "Disco caliente",
                   "%s a %s °C. Revisar ventilación." % (d.get("modelo"), int(temp)))

    for vol in datos.get("volumenes") or []:
        letra = vol.get("letra") or "?"
        libre_pct = _n(vol.get("libre_pct"))
        libre_gb = _n(vol.get("libre_gb"))
        if libre_gb < 2 or libre_pct < 5:
            _halla(h, "disco_lleno", CRITICO, "Disco %s prácticamente lleno" % letra,
                   "Quedan %s GB libres de %s GB (%.0f%%). Con menos del 5%% Windows se "
                   "vuelve inestable: no puede actualizar ni usar memoria virtual."
                   % (vol.get("libre_gb"), vol.get("gb"), libre_pct),
                   reparaciones=["limpiar_temp", "vaciar_papelera", "limpiar_wu",
                                 "optimizar_winsxs"], datos=vol)
        elif libre_pct < 12 or libre_gb < 12:
            _halla(h, "disco_justo", AVISO, "Poco espacio libre en %s" % letra,
                   "Quedan %s GB libres de %s GB (%.0f%%)." % (vol.get("libre_gb"), vol.get("gb"), libre_pct),
                   reparaciones=["limpiar_temp", "vaciar_papelera", "limpiar_wu"], datos=vol)

    # ---------------------------------------------------------------- memoria / cpu
    uso_ram = _n(so.get("ram_uso_pct"))
    if uso_ram >= 92:
        _halla(h, "ram_alta", AVISO, "Memoria RAM al límite",
               "%.0f%% de %s GB en uso. Con la RAM llena Windows recurre al disco y todo va lento."
               % (uso_ram, so.get("ram_total_gb")),
               reparaciones=["reiniciar_explorer"])

    # ---------------------------------------------------------------- actualizaciones
    if datos.get("reinicio_pendiente"):
        _halla(h, "reinicio_pendiente", INFO, "Hay un reinicio pendiente",
               "Windows tiene cambios que no se aplican hasta reiniciar (instalación o "
               "actualización a medias).")
    criticas = int(_n(lento.get("wu_criticas")))
    total_wu = int(_n(lento.get("wu_total")))
    if criticas > 0:
        _halla(h, "actualizaciones_criticas", AVISO,
               "%d actualizaciones importantes pendientes" % criticas,
               "Windows Update tiene %d actualizaciones marcadas como importantes o críticas "
               "(de %d en total)." % (criticas, total_wu), reparaciones=["abrir_windows_update"])
    elif total_wu > 0:
        _halla(h, "actualizaciones", INFO, "%d actualizaciones pendientes" % total_wu,
               "Ninguna marcada como crítica.", reparaciones=["abrir_windows_update"])
    elif lento.get("wu_nota"):
        _halla(h, "actualizaciones_sin_datos", INFO, "No se pudo consultar Windows Update",
               str(lento.get("wu_nota"))[:200])

    # ---------------------------------------------------------------- seguridad
    defen = lento.get("defender") or {}
    if defen and not defen.get("error"):
        if not defen.get("activo") or not defen.get("tiempo_real"):
            _halla(h, "defender_apagado", CRITICO, "Antivirus de Windows desactivado",
                   "Servicio %s, protección en tiempo real %s. El equipo está sin protección activa."
                   % ("activo" if defen.get("servicio") else "parado",
                      "activada" if defen.get("tiempo_real") else "desactivada"),
                   reparaciones=["activar_defender", "defender_firmas"])
        dias = _n(defen.get("firmas_dias"), 0)
        if dias >= 7:
            _halla(h, "defender_firmas", AVISO, "Firmas de antivirus de hace %d días" % int(dias),
                   "Las definiciones no se actualizan desde hace %d días." % int(dias),
                   reparaciones=["defender_firmas"])
        escaneo = _n(defen.get("escaneo_completo_dias"), 0)
        if escaneo >= 30:
            _halla(h, "defender_escaneo", INFO,
                   "Sin análisis completo desde hace %s días" % int(escaneo),
                   "Un análisis completo detecta lo que el tiempo real deja pasar.",
                   reparaciones=["defender_escaneo"])
    elif not admin:
        _halla(h, "defender_sin_datos", INFO, "Estado del antivirus no comprobado",
               "Requiere ejecutar como administrador.")

    for fw in datos.get("firewall") or []:
        if fw.get("activo") is False:
            _halla(h, "firewall_apagado", AVISO,
                   "Cortafuegos desactivado en el perfil %s" % fw.get("perfil"),
                   "El perfil «%s» no filtra tráfico entrante." % fw.get("perfil"),
                   reparaciones=["activar_firewall"])

    antivirus = datos.get("antivirus") or []
    if antivirus:
        nombres = ", ".join(a.get("nombre", "?") for a in antivirus if a.get("nombre"))
        if nombres:
            _halla(h, "antivirus_presente", INFO, "Antivirus instalado: %s" % nombres,
                   "Registrado en el Centro de seguridad de Windows.")

    # ---------------------------------------------------------------- estabilidad
    incidentes = int(_n(datos.get("incidentes_total")))
    lista_inc = datos.get("incidentes") or []
    pantallazos = [i for i in lista_inc if int(_n(i.get("id"))) == 1001]
    apagones = [i for i in lista_inc if int(_n(i.get("id"))) in (41, 6008)]
    if len(pantallazos) >= 2:
        _halla(h, "pantallazos", CRITICO, "%d pantallazos azules en 30 días" % len(pantallazos),
               "El equipo se cae solo (evento 1001). Antes de cambiar hardware, comprobar disco y "
               "controladores recientes.",
               reparaciones=["sfc_scan", "dism_restore", "chkdsk_scan"],
               datos={"incidentes": pantallazos[:5]})
    elif pantallazos:
        _halla(h, "pantallazo_uno", AVISO, "Un pantallazo azul en 30 días",
               "Un solo fallo puede ser puntual (driver, memoria). Se anota para ver si se repite.",
               reparaciones=["sfc_scan"], datos={"incidentes": pantallazos[:5]})
    if len(apagones) >= 5:
        _halla(h, "apagones", AVISO, "%d apagones o cortes súbitos en 30 días" % len(apagones),
               "Eventos 41/6008: el equipo se apagó sin cerrar Windows. Suele ser el botón de "
               "encendido mantenido, batería agotada o sobrecalentamiento; si no, revisar la fuente.",
               datos={"incidentes": apagones[:5]})
    elif apagones:
        _halla(h, "apagones_pocos", INFO, "%d apagón(es) registrados en 30 días" % len(apagones),
               "Sin pantallazos azules asociados.", datos={"incidentes": apagones[:3]})
    dispositivos = datos.get("dispositivos_error") or []
    if dispositivos:
        lista = ", ".join((d.get("nombre") or d.get("clase") or "?") for d in dispositivos[:5])
        _halla(h, "dispositivos_error", AVISO,
               "%d dispositivos con error" % len(dispositivos),
               "Windows no tiene controlador válido o el hardware falla: %s" % lista,
               reparaciones=["rescan_dispositivos"], datos={"dispositivos": dispositivos[:10]})

    parados = [s for s in (datos.get("servicios_parados") or []) if not s.get("trigger")]
    del_sistema = [s for s in parados
                   if "\\windows\\" in str(s.get("ruta") or "").lower()]
    if del_sistema:
        nombres = ", ".join((s.get("nombre") or "?") for s in del_sistema[:6])
        _halla(h, "servicios_parados", AVISO,
               "%d servicio%s del sistema detenido%s"
               % (len(del_sistema), "" if len(del_sistema) == 1 else "s",
                  "" if len(del_sistema) == 1 else "s"),
               "Son servicios propios de Windows marcados como automáticos y no están "
               "corriendo: %s%s" % (nombres, "…" if len(del_sistema) > 6 else ""),
               datos={"servicios": del_sistema[:15]})
    terceros = [s for s in parados if s not in del_sistema]
    if terceros:
        nombres = ", ".join((s.get("nombre") or "?") for s in terceros[:6])
        _halla(h, "servicios_terceros", INFO,
               "%d servicios de programas instalados detenidos" % len(terceros),
               "No son de Windows (actualizadores de Dropbox, Google, HP…). Suele ser normal: %s%s"
               % (nombres, "…" if len(terceros) > 6 else ""))

    total_eventos = int(_n(datos.get("eventos_sistema_total")))
    if total_eventos >= 200:
        _halla(h, "muchos_eventos", INFO, "Registro con muchos errores repetidos",
               "Se han analizado %d errores de los últimos 7 días; abajo los más repetidos "
               "(no todos son fallos reales: DistributedCOM y TPM-WMI son ruido habitual)."
               % total_eventos,
               datos={"top": (datos.get("eventos_sistema") or [])[:6]})

    # ---------------------------------------------------------------- red
    red = datos.get("red") or {}
    conn = red.get("conectividad") or {}
    if red.get("adaptadores"):
        if conn.get("internet_443") is False and conn.get("microsoft_443") is False:
            _halla(h, "sin_internet", AVISO, "Sin salida a internet",
                   "No hay conexión TCP a 1.1.1.1:443 ni a microsoft.com:443. Si el equipo "
                   "debería tener red, revisar cable/WiFi, IP y DNS.",
                   reparaciones=["flush_dns", "renovar_ip", "reset_winsock"])
        elif conn.get("microsoft_443") is False:
            _halla(h, "internet_parcial", INFO, "Salida a internet parcial",
                   "Hay conexión a 1.1.1.1 pero no a microsoft.com. Puede ser DNS o un filtro.")
    else:
        _halla(h, "sin_red", INFO, "Sin adaptadores de red activos",
               "No hay ninguna interfaz con IP. Normal si el equipo está sin cable.")

    proxy = datos.get("proxy") or {}
    if proxy.get("activo"):
        _halla(h, "proxy", INFO, "Proxy configurado en el sistema",
               "Servidor: %s. Si nadie lo puso, puede impedir la navegación."
               % (proxy.get("servidor") or "?"), reparaciones=["reset_proxy"])

    hosts = datos.get("hosts") or {}
    if _n(hosts.get("entradas")) > 20:
        _halla(h, "hosts", INFO, "%d entradas en el fichero hosts" % int(_n(hosts.get("entradas"))),
               "Es mucho para un equipo doméstico. Si no las has puesto tú (VPN, Tailscale), "
               "pueden redirigir dominios a otro sitio.", reparaciones=["limpiar_hosts"],
               datos={"muestra": hosts.get("muestra") or []})

    # ---------------------------------------------------------------- energia / bateria
    bateria = datos.get("bateria") or {}
    salud = _n(bateria.get("salud_pct"), -1)
    if bateria.get("presente") and salud >= 0:
        if salud < 55:
            _halla(h, "bateria_agotada", AVISO, "Batería agotada (%s%%)" % salud,
                   "Capacidad real %s mWh frente a %s mWh de diseño (%s ciclos). "
                   "Aguanta muy poco: hay que sustituirla."
                   % (bateria.get("capacidad_mwh"), bateria.get("diseno_mwh"), bateria.get("ciclos")),
                   datos=bateria)
        elif salud < 80:
            _halla(h, "bateria_desgastada", INFO, "Batería con desgaste (%s%%)" % salud,
                   "Capacidad real %s mWh de %s mWh de diseño."
                   % (bateria.get("capacidad_mwh"), bateria.get("diseno_mwh")), datos=bateria)

    energia = datos.get("energia") or {}
    if energia.get("inicio_rapido") and not energia.get("hibernacion_activa"):
        pass
    if energia.get("inicio_rapido"):
        _halla(h, "inicio_rapido", INFO, "Inicio rápido activado",
               "El apagado no es completo: el equipo guarda el estado del núcleo. Puede provocar "
               "fallos raros tras apagar (tintes de pantalla, dispositivos que no arrancan).",
               reparaciones=["desactivar_inicio_rapido"])

    uptime = _n(so.get("uptime_horas"))
    if uptime >= 14 * 24:
        _halla(h, "uptime", INFO, "Sin reiniciar desde hace %d días" % int(uptime / 24),
               "Un reinicio limpio libera memoria y aplica cambios pendientes.")

    # ---------------------------------------------------------------- mantenimiento
    winre = datos.get("winre") or {}
    if winre.get("habilitado") is False:
        _halla(h, "sin_winre", AVISO, "Sin entorno de recuperación (WinRE)",
               "Si Windows no arranca, este equipo no podrá repararse solo: habría que usar "
               "un USB de arranque.", reparaciones=["habilitar_winre"])
    elif winre.get("habilitado") is None:
        _halla(h, "winre_sin_datos", INFO, "Estado de WinRE no comprobado",
               "Requiere administrador.")

    rest = datos.get("restauracion") or {}
    if rest.get("deshabilitada"):
        _halla(h, "sin_restauracion", AVISO, "Restauración del sistema desactivada",
               "No hay red de seguridad: si una actualización o un programa rompe Windows, no "
               "se puede volver atrás.", reparaciones=["activar_restauracion"])
    elif not (rest.get("puntos") or []):
        _halla(h, "sin_puntos", INFO, "Sin puntos de restauración",
               "La restauración está activa pero no hay ningún punto guardado.",
               reparaciones=["punto_restauracion"])

    tpm = datos.get("tpm") or {}
    if tpm.get("presente") and not tpm.get("listo"):
        _halla(h, "tpm", INFO, "TPM presente pero no listo",
               "Algunas funciones (BitLocker, Windows Hello, actualizaciones de firmware) "
               "pueden fallar.")
    if datos.get("secure_boot") is False:
        _halla(h, "secure_boot", INFO, "Arranque seguro desactivado",
               "Windows 11 lo exige; con él apagado se puede arrancar software no firmado.")

    cuentas = datos.get("cuentas") or {}
    if _n(cuentas.get("admins_total")) > 3:
        _halla(h, "admins", INFO, "%d cuentas administrador" % int(_n(cuentas.get("admins_total"))),
               "Cuanto menos cuentas con permisos totales, mejor: %s"
               % ", ".join(cuentas.get("admins") or []))

    # ---------------------------------------------------------------- espacio recuperable
    basura = datos.get("basura") or []
    total_basura = sum(b.get("bytes", 0) for b in basura)
    if total_basura > 5 * 1024 ** 3:
        _halla(h, "basura", AVISO, "%s recuperables sin borrar nada tuyo" % _texto(total_basura),
               "Temporales, caché de actualizaciones y papelera. Se puede limpiar sin riesgo.",
               reparaciones=["limpiar_temp", "vaciar_papelera", "limpiar_wu"],
               datos={"detalle": basura})

    # ---------------------------------------------------------------- arranque / software
    arranque = datos.get("arranque") or []
    if len(arranque) >= 15:
        _halla(h, "muchos_inicios", INFO, "%d programas al arrancar" % len(arranque),
               "Cada uno suma segundos al encender y consume memoria.",
               datos={"programas": [a.get("nombre") for a in arranque[:12]]})

    progs = datos.get("programas") or {}
    if _n(progs.get("total")) >= 180:
        _halla(h, "muchos_programas", INFO, "%d programas instalados" % int(_n(progs.get("total"))),
               "Normal en un equipo de trabajo; si hay software que no se usa, desinstalarlo "
               "ahorra espacio y conflictos.")

    if not admin:
        _halla(h, "sin_admin", INFO, "Auditoría ejecutada sin privilegios",
               "No se pudieron comprobar BitLocker, desgaste del disco ni el estado de WinRE. "
               "Para un informe completo, ejecutar como administrador.")

    h.sort(key=lambda x: ORDEN.get(x["severidad"], 9))
    return h, _resumen(h)


def _texto(bytes_):
    valor = float(bytes_ or 0)
    for unidad in ("B", "KB", "MB", "GB", "TB"):
        if valor < 1024 or unidad == "TB":
            return ("%.1f %s" % (valor, unidad)) if unidad != "B" else ("%d B" % valor)
        valor /= 1024.0
    return "?"


def _resumen(hallazgos):
    cuenta = {CRITICO: 0, AVISO: 0, INFO: 0}
    for x in hallazgos:
        cuenta[x["severidad"]] = cuenta.get(x["severidad"], 0) + 1
    if cuenta[CRITICO]:
        veredicto, titulo = CRITICO, "Requiere intervención"
    elif cuenta[AVISO]:
        veredicto, titulo = AVISO, "Funciona, con puntos a corregir"
    else:
        veredicto, titulo = "ok", "Sin problemas detectados"
    return {"veredicto": veredicto, "titulo": titulo, "cuenta": cuenta,
            "total": len(hallazgos)}


def recomendadas(hallazgos):
    """Ids de reparacion unicos, en orden de severidad."""
    vistos = []
    for hallazgo in hallazgos:
        for rid in hallazgo.get("reparaciones") or []:
            if rid not in vistos:
                vistos.append(rid)
    return vistos
