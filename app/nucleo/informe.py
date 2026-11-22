# -*- coding: utf-8 -*-
"""Genera el informe: HTML autocontenido (imprimible), Markdown y JSON crudo."""
import html
import json
import os
import time

from . import diagnostico, reparaciones, util

VERSION = "1.0"
COLOR = {diagnostico.CRITICO: "#b42318", diagnostico.AVISO: "#b54708",
         diagnostico.INFO: "#175cd3", "ok": "#067647"}
FONDO = {diagnostico.CRITICO: "#fef3f2", diagnostico.AVISO: "#fffaeb",
         diagnostico.INFO: "#eff8ff", "ok": "#ecfdf3"}


def _e(texto):
    return html.escape("" if texto is None else str(texto))


def _rec(texto, n=140):
    """Recorta avisando con puntos suspensivos (un corte seco parece un fallo de maquetación)."""
    texto = "" if texto is None else str(texto).strip()
    texto = texto.replace("\n", " ")
    return texto if len(texto) <= n else texto[:n].rstrip() + "…"


def _equipo_nombre(so):
    """Evita repetir la marca cuando el modelo ya la incluye («Lenovo Lenovo ThinkPad»)."""
    fabricante = (so.get("fabricante") or "").strip()
    modelo = (so.get("modelo") or "").strip()
    if not fabricante:
        return modelo or "Equipo"
    if modelo.lower().startswith(fabricante.lower()):
        return modelo
    return ("%s %s" % (fabricante, modelo)).strip()


def _fecha_legible(iso):
    if not iso:
        return "?"
    try:
        return time.strftime("%d/%m/%Y %H:%M", time.strptime(str(iso)[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return str(iso)


def _barra(pct, color):
    pct = max(0.0, min(100.0, float(pct or 0)))
    return ('<div class="barra"><div class="relleno" style="width:%.1f%%;background:%s"></div></div>'
            % (pct, color))


CSS = """
*{box-sizing:border-box}
body{margin:0;padding:28px 20px 60px;background:#f5f6f8;color:#101828;
 font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
.hoja{max-width:960px;margin:0 auto;background:#fff;border-radius:14px;padding:34px 38px 44px;
 box-shadow:0 1px 3px rgba(16,24,40,.08),0 8px 24px rgba(16,24,40,.06)}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.3px}
h2{font-size:17px;margin:34px 0 12px;padding-bottom:7px;border-bottom:1px solid #eaecf0;letter-spacing:-.1px}
h3{font-size:14px;margin:20px 0 8px;color:#475467;text-transform:uppercase;letter-spacing:.06em}
.sub{color:#667085;font-size:14px;margin:0}
.badge{display:inline-block;padding:6px 14px;border-radius:999px;font-weight:600;font-size:14px}
.tarjetas{display:flex;gap:12px;margin:22px 0 6px;flex-wrap:wrap}
.tarjeta{flex:1 1 150px;border:1px solid #eaecf0;border-radius:10px;padding:12px 14px}
.tarjeta .num{font-size:26px;font-weight:700;line-height:1.1}
.tarjeta .eti{font-size:12px;color:#667085;text-transform:uppercase;letter-spacing:.05em}
table{width:100%;border-collapse:collapse;font-size:14px;margin:8px 0 4px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid #eaecf0;vertical-align:top;
 overflow-wrap:anywhere;word-break:break-word}
th{color:#475467;font-weight:600;font-size:12.5px;text-transform:uppercase;letter-spacing:.04em;background:#fcfcfd}
tr:last-child td{border-bottom:none}
table.fija{table-layout:fixed}
table.fija col{min-width:0}
.hall{border-left:4px solid #ccc;background:#fafafa;border-radius:0 8px 8px 0;padding:11px 14px;margin:10px 0}
.hall .t{font-weight:600;margin-bottom:3px}
.hall .d{color:#475467;font-size:14px}
.chips{margin-top:7px}
.chip{display:inline-block;font-size:12px;background:#fff;border:1px solid #d0d5dd;border-radius:999px;
 padding:2px 9px;margin:2px 4px 0 0;color:#344054}
.barra{height:8px;background:#eaecf0;border-radius:999px;overflow:hidden;margin-top:5px}
.barra .relleno{height:100%;border-radius:999px}
.ok{color:#067647}.malo{color:#b42318}.medio{color:#b54708}
code{background:#f2f4f7;padding:1px 5px;border-radius:4px;font-size:13px}
details{margin:8px 0}
summary{cursor:pointer;color:#175cd3;font-size:14px}
pre{background:#f9fafb;border:1px solid #eaecf0;border-radius:8px;padding:10px;overflow:auto;font-size:12.5px}
.pie{margin-top:40px;padding-top:14px;border-top:1px solid #eaecf0;color:#98a2b3;font-size:12.5px}
@media print{body{background:#fff;padding:0}.hoja{box-shadow:none;border-radius:0;padding:0}h2{page-break-after:avoid}
 .hall,table,tr{page-break-inside:avoid}}
"""


def _hallazgos_html(hallazgos):
    if not hallazgos:
        return '<p class="ok">No se ha detectado ningún problema.</p>'
    partes = []
    for x in hallazgos:
        color = COLOR.get(x["severidad"], "#667085")
        chips = ""
        for rid in x.get("reparaciones") or []:
            r = reparaciones.obtener(rid)
            if r:
                chips += '<span class="chip">%s</span>' % _e(r["nombre"])
        extra = ""
        datos = x.get("datos") or {}
        if datos.get("detalle") and isinstance(datos["detalle"], list):
            filas = "".join("<tr><td>%s</td><td>%s</td></tr>" % (_e(d.get("nombre")), _e(d.get("texto")))
                            for d in datos["detalle"] if isinstance(d, dict))
            if filas:
                extra += "<table><tr><th>Concepto</th><th>Tamaño</th></tr>%s</table>" % filas
        if datos.get("dispositivos"):
            filas = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                            % (_e(d.get("nombre")), _e(d.get("clase")), _e(d.get("estado")))
                            for d in datos["dispositivos"] if isinstance(d, dict))
            if filas:
                extra += "<table><tr><th>Dispositivo</th><th>Clase</th><th>Estado</th></tr>%s</table>" % filas
        if datos.get("incidentes"):
            filas = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                            % (_e(d.get("id")), _e(_fecha_legible(d.get("fecha"))),
                               _e(_rec(d.get("texto"), 110)))
                            for d in datos["incidentes"] if isinstance(d, dict))
            if filas:
                extra += "<table><tr><th>Código</th><th>Fecha</th><th>Detalle</th></tr>%s</table>" % filas
        if datos.get("top"):
            filas = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                            % (_e(d.get("origen")), _e(d.get("id")), _e(d.get("veces")))
                            for d in datos["top"] if isinstance(d, dict))
            if filas:
                extra += "<table><tr><th>Origen</th><th>Evento</th><th>Veces</th></tr>%s</table>" % filas
        partes.append(
            '<div class="hall" style="border-left-color:%s;background:%s">'
            '<div class="t">%s</div><div class="d">%s</div>%s%s</div>'
            % (color, FONDO.get(x["severidad"], "#fafafa"), _e(x["titulo"]), _e(x["detalle"]), extra,
               ('<div class="chips">%s</div>' % chips) if chips else ""))
    return "".join(partes)


def _tabla(filas, cabeceras, anchos=None):
    cab = "".join("<th>%s</th>" % _e(c) for c in cabeceras)
    cuerpo = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in fila) for fila in filas)
    if anchos and len(anchos) == len(cabeceras):
        grupo = "<colgroup>%s</colgroup>" % "".join('<col style="width:%s">' % a for a in anchos)
        return '<table class="fija">%s<tr>%s</tr>%s</table>' % (grupo, cab, cuerpo)
    return "<table><tr>%s</tr>%s</table>" % (cab, cuerpo)


def _ficha(datos):
    so = datos.get("so") or {}
    cpu = datos.get("cpu") or {}
    ram = datos.get("ram") or {}
    filas = [
        ("Equipo", _equipo_nombre(so)),
        ("Nombre en red", datos.get("equipo")),
        ("Número de serie", so.get("serie")),
        ("Sistema", "%s (compilación %s, %s)" % (so.get("nombre"), so.get("build"), so.get("arquitectura"))),
        ("Instalado el", _fecha_legible(so.get("instalado"))),
        ("Último arranque", "%s (hace %.0f h)" % (_fecha_legible(so.get("arranque")), float(so.get("uptime_horas") or 0))),
        ("Procesador", "%s · %s núcleos / %s hilos" % (cpu.get("nombre"), cpu.get("nucleos"), cpu.get("hilos"))),
        ("Memoria", "%s GB en %s módulos (%s de %s ranuras)" % (so.get("ram_total_gb"),
                                                               ram.get("ranuras_usadas"),
                                                               ram.get("ranuras_usadas"),
                                                               ram.get("ranuras_totales"))),
        ("Placa base", so.get("placa")),
        ("BIOS", "%s (%s)" % (so.get("bios"), _fecha_legible(so.get("bios_fecha")))),
        ("Activación", "%s · %s" % ((datos.get("activacion") or {}).get("descripcion"),
                                    (datos.get("activacion") or {}).get("canal") or "")),
        ("Auditoría", "%s · %.1f s · %s" % (_fecha_legible(datos.get("generado")),
                                            float(datos.get("_duracion_s") or 0),
                                            "como administrador" if datos.get("admin") else "sin privilegios")),
    ]
    return _tabla([(k, v or "—") for k, v in filas], ["Dato", "Valor"])


def _discos(datos):
    filas = []
    for vol in datos.get("volumenes") or []:
        pct = float(vol.get("libre_pct") or 0)
        color = "#b42318" if pct < 5 else ("#b54708" if pct < 12 else "#067647")
        filas.append([_e(vol.get("letra")), _e(vol.get("etiqueta") or ""), _e(vol.get("fs")),
                      "%s GB" % _e(vol.get("gb")),
                      "%s GB (%.0f%%)%s" % (_e(vol.get("libre_gb")), pct,
                                            _barra(pct, color))])
    html_vol = _tabla(filas, ["Unidad", "Etiqueta", "Formato", "Capacidad", "Libre"])

    fisicos = []
    for d in datos.get("discos_fisicos") or []:
        fisicos.append([_e(d.get("modelo")), _e(d.get("medio")), _e(d.get("bus")),
                        "%s GB" % _e(d.get("gb")), _e(d.get("salud"))])
    if not fisicos:
        for d in datos.get("discos") or []:
            fisicos.append([_e(d.get("modelo")), _e(d.get("tipo")), _e(d.get("interfaz")),
                            "%s GB" % _e(d.get("gb")), _e(d.get("estado"))])
    tabla_fis = _tabla(fisicos, ["Disco", "Tipo", "Conexión", "Capacidad", "Salud"]) if fisicos else ""

    desgaste = ((datos.get("lento") or {}).get("desgaste")) or []
    tabla_desgaste = ""
    if desgaste:
        tabla_desgaste = _tabla(
            [[_e(d.get("modelo")), _e(d.get("salud")),
              ("%s%%" % _e(d.get("desgaste_pct"))) if d.get("desgaste_pct") is not None else "—",
              ("%s °C" % _e(d.get("temperatura"))) if d.get("temperatura") else "—",
              _e(d.get("horas_encendido") or "—")] for d in desgaste],
            ["Disco", "Salud", "Desgaste", "Temperatura", "Horas"])
    return html_vol + "<h3>Discos físicos</h3>" + (tabla_fis or "<p class=sub>Sin datos.</p>") + \
           (("<h3>Desgaste y temperatura</h3>" + tabla_desgaste) if tabla_desgaste else "")


def _bateria(datos):
    b = datos.get("bateria") or {}
    if not b.get("presente"):
        return "<p class=sub>Equipo de sobremesa o sin batería detectada.</p>"
    salud = b.get("salud_pct")
    if salud is None:
        return "<p class=sub>Batería presente; capacidad de diseño no disponible en este equipo.</p>"
    color = "#b42318" if salud < 55 else ("#b54708" if salud < 80 else "#067647")
    return (
        "<p>Salud de la batería: <strong style='color:%s'>%s%%</strong> "
        "(%s mWh reales de %s mWh de diseño).</p>%s"
        "<p class=sub>Carga actual: %s%%%s</p>"
        % (color, salud, b.get("capacidad_mwh"), b.get("diseno_mwh"),
           _barra(salud, color), b.get("carga_pct") if b.get("carga_pct") is not None else "?",
           (" · %s ciclos" % b.get("ciclos")) if b.get("ciclos") is not None else ""))


def _seguridad(datos):
    lento = datos.get("lento") or {}
    d = lento.get("defender") or {}
    filas = []
    if d and not d.get("error"):
        filas += [
            ("Antivirus activo", "sí" if d.get("activo") else "NO"),
            ("Protección en tiempo real", "sí" if d.get("tiempo_real") else "NO"),
            ("Firmas", "%s (hace %s días)" % (d.get("firmas_version"), d.get("firmas_dias"))),
            ("Último análisis rápido", "hace %s días" % d.get("escaneo_rapido_dias")),
            ("Último análisis completo", "hace %s días" % d.get("escaneo_completo_dias")),
        ]
    elif not datos.get("admin"):
        filas.append(("Antivirus", "no comprobado (requiere administrador)"))
    for a in datos.get("antivirus") or []:
        filas.append(("Antivirus registrado", a.get("nombre")))
    for f in datos.get("firewall") or []:
        filas.append(("Cortafuegos %s" % f.get("perfil"), "activo" if f.get("activo") else "DESACTIVADO"))
    bl = lento.get("bitlocker")
    if isinstance(bl, list):
        for v in bl:
            filas.append(("BitLocker %s" % v.get("volumen"), "%s / %s" % (v.get("estado"), v.get("proteccion"))))
    if datos.get("secure_boot") is not None:
        filas.append(("Arranque seguro", "activado" if datos.get("secure_boot") else "desactivado"))
    tpm = datos.get("tpm") or {}
    if tpm.get("presente"):
        filas.append(("TPM", "presente (%s)" % ("listo" if tpm.get("listo") else "no listo")))
    return _tabla([(k, v) for k, v in filas], ["Elemento", "Estado"]) if filas else "<p class=sub>Sin datos.</p>"


def _actualizaciones(datos):
    lento = datos.get("lento") or {}
    partes = []
    pend = lento.get("wu_pendientes")
    if pend:
        partes.append("<h3>Pendientes (%d)</h3>%s" % (len(pend), _tabla(
            [[_e(p.get("titulo")), _e(p.get("kb") or "—"), _e(p.get("severidad") or "—"),
              ("%.0f MB" % float(p.get("mb") or 0))] for p in pend],
            ["Actualización", "KB", "Severidad", "Tamaño"])))
    elif pend == []:
        partes.append("<p class='ok'>Windows Update no tiene nada pendiente.</p>")
    elif lento.get("wu_nota"):
        partes.append("<p class=sub>No se pudo consultar Windows Update: %s</p>" % _e(lento.get("wu_nota")))
    instaladas = ((datos.get("actualizaciones") or {}).get("instaladas")) or []
    if instaladas:
        partes.append("<h3>Últimas instaladas</h3>%s" % _tabla(
            [[_e(i.get("kb")), _fecha_legible(i.get("fecha"))] for i in instaladas], ["KB", "Fecha"]))
    if datos.get("reinicio_pendiente"):
        partes.append("<p class='medio'><strong>Hay un reinicio pendiente.</strong></p>")
    return "".join(partes) or "<p class=sub>Sin datos.</p>"


def _red(datos):
    red = datos.get("red") or {}
    conn = red.get("conectividad") or {}
    filas = []
    for a in red.get("adaptadores") or []:
        filas.append([_e(a.get("descripcion")), _e(a.get("ip")), _e(a.get("puerta")), _e(a.get("dns")),
                      _e(a.get("mac"))])
    tabla = _tabla(filas, ["Adaptador", "IP", "Puerta", "DNS", "MAC"],
                   anchos=("26%", "24%", "14%", "22%", "14%")) if filas else ""
    estados = " · ".join("%s: %s" % (k, "sí" if v else "NO") for k, v in conn.items())
    return tabla + ("<p class=sub>Conexiones: %s</p>" % _e(estados) if estados else "")


def _estabilidad(datos):
    partes = []
    incidentes = datos.get("incidentes") or []
    if incidentes:
        partes.append("<h3>Cierres inesperados (%d en 30 días)</h3>%s" % (len(incidentes), _tabla(
            [[_e(i.get("id")), _fecha_legible(i.get("fecha")), _e(_rec(i.get("texto"), 110))]
             for i in incidentes[:10]], ["Código", "Fecha", "Detalle"])))
    eventos = datos.get("eventos_sistema") or []
    if eventos:
        partes.append("<h3>Errores más repetidos (7 días)</h3>%s" % _tabla(
            [[_e(e.get("origen")), _e(e.get("id")), _e(e.get("veces")), _fecha_legible(e.get("ultimo")),
              _e(_rec(e.get("muestra"), 150))] for e in eventos],
            ["Origen", "Evento", "Veces", "Último", "Mensaje"],
            anchos=("26%", "9%", "9%", "19%", "37%")))
    devs = datos.get("dispositivos_error") or []
    if devs:
        partes.append("<h3>Dispositivos con error</h3>%s" % _tabla(
            [[_e(d.get("nombre")), _e(d.get("clase")), _e(d.get("estado"))] for d in devs],
            ["Dispositivo", "Clase", "Estado"]))
    return "".join(partes) or "<p class='ok'>Sin incidentes ni dispositivos con error.</p>"


def _ejecuciones(ejecuciones):
    if not ejecuciones:
        return ""
    filas = []
    for e in ejecuciones:
        estado = ("<span class=ok>hecho</span>" if e.get("ok")
                  else "<span class=malo>no aplicado</span>")
        filas.append([_e(e.get("nombre") or e.get("id")), estado, _e(e.get("mensaje")),
                      "%.1f s" % float(e.get("segundos") or 0)])
    return "<h2>Qué se ha ejecutado</h2>" + _tabla(filas, ["Acción", "Resultado", "Detalle", "Duración"])


def _anexo(datos):
    partes = []
    progs = datos.get("programas") or {}
    if progs.get("grandes"):
        partes.append("<h3>Programas que más ocupan</h3>%s" % _tabla(
            [[_e(p.get("nombre")), _e(p.get("version")), "%.0f MB" % float(p.get("mb") or 0)]
             for p in progs["grandes"]], ["Programa", "Versión", "Tamaño"],
            anchos=("55%", "20%", "25%")))
    arranque = datos.get("arranque") or []
    if arranque:
        partes.append("<h3>Programas al arrancar (%d)</h3>%s" % (len(arranque), _tabla(
            [[_e(a.get("nombre")), _e(_rec(a.get("comando"), 160)), _e(a.get("ubicacion"))]
             for a in arranque], ["Nombre", "Comando", "Ubicación"],
            anchos=("20%", "52%", "28%"))))
    basura = datos.get("basura") or []
    if basura:
        partes.append("<h3>Espacio recuperable</h3>%s" % _tabla(
            [[_e(b.get("nombre")), _e(b.get("ruta")), _e(b.get("texto"))] for b in basura],
            ["Categoría", "Ruta", "Tamaño"], anchos=("26%", "46%", "28%")))
    errores = datos.get("errores") or []
    if errores:
        partes.append("<h3>Incidencias de la propia auditoría</h3><pre>%s</pre>"
                      % _e("\n".join(str(x) for x in errores)))
    return "".join(partes) or "<p class=sub>Sin anexo.</p>"


def _recomendadas_html(hallazgos):
    vistos = []
    for x in hallazgos:
        for rid in x.get("reparaciones") or []:
            if rid not in vistos:
                vistos.append(rid)
    filas = []
    for rid in vistos:
        r = reparaciones.obtener(rid)
        if not r:
            continue
        requisitos = []
        if r["admin"]:
            requisitos.append("administrador")
        if r["red"]:
            requisitos.append("internet")
        if r["lento"]:
            requisitos.append("lento")
        filas.append([_e(r["nombre"]), _e(reparaciones.NIVELES[r["nivel"]]), _e(", ".join(requisitos) or "—"),
                      _e(r["cuando"])])
    if not filas:
        return ""
    return "<h2>Acciones recomendadas</h2>" + _tabla(filas, ["Acción", "Riesgo", "Necesita", "Cuándo"])


def construir_html(datos, hallazgos, resumen, ejecuciones=None):
    so = datos.get("so") or {}
    resumen = resumen or {}
    veredicto = resumen.get("veredicto") or "ok"
    color = COLOR.get(veredicto if veredicto != "ok" else "ok", "#067647")
    cuenta = resumen.get("cuenta") or {}
    tarjetas = (
        '<div class="tarjetas">'
        '<div class="tarjeta" style="border-color:#fecdca"><div class="num malo">%d</div>'
        '<div class="eti">Críticos</div></div>'
        '<div class="tarjeta" style="border-color:#fedf89"><div class="num medio">%d</div>'
        '<div class="eti">A revisar</div></div>'
        '<div class="tarjeta" style="border-color:#d1e9ff"><div class="num" style="color:#175cd3">%d</div>'
        '<div class="eti">Informativos</div></div>'
        '<div class="tarjeta"><div class="num">%s</div><div class="eti">Espacio recuperable</div></div>'
        '</div>'
        % (cuenta.get("critico", 0), cuenta.get("aviso", 0), cuenta.get("info", 0),
           _e(_humano(sum(b.get("bytes", 0) for b in (datos.get("basura") or []))))))

    return """<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Informe · %s · %s</title><style>%s</style></head><body><div class="hoja">
<h1>Informe de revisión del equipo</h1>
<p class="sub">%s · %s · %s</p>
<p style="margin-top:16px"><span class="badge" style="color:%s;background:%s">%s</span></p>
%s
<h2>Resumen</h2>
<p>%s</p>
%s
%s
%s
<h2>Ficha del equipo</h2>
%s
<h2>Almacenamiento</h2>
%s
<h2>Batería</h2>
%s
<h2>Seguridad</h2>
%s
<h2>Actualizaciones</h2>
%s
<h2>Red</h2>
%s
<h2>Estabilidad</h2>
%s
<h2>Anexo</h2>
%s
<div class="pie">Generado por HERMES-RESCATE v%s · %s · duración de la auditoría %.1f s · %s<br>
HERMES-RESCATE es un proyecto de <a href="https://neuraladvance.net">Neuraladvance.net</a>,
licencia MIT. Se entrega «tal cual», sin garantía: úsalo solo en equipos propios o con
autorización de su responsable, y haz copia de seguridad antes de reparar.</div>
</div></body></html>
""" % (
        _e(datos.get("equipo")), _e(time.strftime("%d/%m/%Y")),
        CSS,
        _e(_equipo_nombre(so)),
        _e(datos.get("equipo")),
        _e(_fecha_legible(datos.get("generado"))),
        color, FONDO.get(veredicto if veredicto != "ok" else "ok", "#ecfdf3"),
        _e(resumen.get("titulo") or resumen.get("veredicto") or "sin datos"),
        tarjetas,
        _e(_parrafo_resumen(hallazgos, resumen)),
        _ejecuciones(ejecuciones or []),
        _hallazgos_html(hallazgos),
        _recomendadas_html(hallazgos),
        _ficha(datos),
        _discos(datos),
        _bateria(datos),
        _seguridad(datos),
        _actualizaciones(datos),
        _red(datos),
        _estabilidad(datos),
        _anexo(datos),
        VERSION, _e(time.strftime("%d/%m/%Y %H:%M")), float(datos.get("_duracion_s") or 0),
        "con permisos de administrador" if datos.get("admin") else "sin permisos de administrador",
    )


def _parrafo_resumen(hallazgos, resumen):
    criticos = [x["titulo"] for x in hallazgos if x["severidad"] == diagnostico.CRITICO]
    avisos = [x["titulo"] for x in hallazgos if x["severidad"] == diagnostico.AVISO]
    if criticos:
        cuantos = ("un punto crítico" if len(criticos) == 1
                   else "%d puntos críticos" % len(criticos))
        cola = (" Además hay %d aviso(s) menor(es)." % len(avisos)) if avisos else ""
        return ("Hay %s que requiere intervención: %s.%s"
                % (cuantos, "; ".join(criticos[:4]) + ("…" if len(criticos) > 4 else ""), cola))
    if avisos:
        cuantos = "un punto a revisar" if len(avisos) == 1 else "%d puntos a revisar" % len(avisos)
        return ("El equipo funciona. Hay %s: %s."
                % (cuantos, "; ".join(avisos[:4]) + ("…" if len(avisos) > 4 else "")))
    return "No se ha encontrado nada que impida el funcionamiento normal del equipo."


def _humano(bytes_):
    valor = float(bytes_ or 0)
    for unidad in ("B", "KB", "MB", "GB", "TB"):
        if valor < 1024 or unidad == "TB":
            return ("%.1f %s" % (valor, unidad)) if unidad != "B" else ("%d B" % valor)
        valor /= 1024.0
    return "?"


def construir_markdown(datos, hallazgos, resumen, ejecuciones=None):
    so = datos.get("so") or {}
    lineas = [
        "# Informe de revisión · %s" % datos.get("equipo"),
        "",
        "**%s %s** · %s · %s" % (so.get("fabricante") or "", so.get("modelo") or "", so.get("nombre") or "",
                                 _fecha_legible(datos.get("generado"))),
        "",
        "## Veredicto: %s" % (resumen.get("titulo") or resumen.get("veredicto") or "sin datos"),
        "",
        "| Críticos | A revisar | Informativos |", "|---:|---:|---:|",
        "| %d | %d | %d |" % ((resumen.get("cuenta") or {}).get("critico", 0),
                              (resumen.get("cuenta") or {}).get("aviso", 0),
                              (resumen.get("cuenta") or {}).get("info", 0)),
        "",
        "## Hallazgos",
        "",
    ]
    for x in hallazgos:
        marca = {diagnostico.CRITICO: "🔴", diagnostico.AVISO: "🟡", diagnostico.INFO: "🔵"}.get(x["severidad"], "")
        lineas.append("%s **%s** — %s" % (marca, x["titulo"], x["detalle"]))
        if x.get("reparaciones"):
            nombres = [reparaciones.obtener(r)["nombre"] for r in x["reparaciones"] if reparaciones.obtener(r)]
            if nombres:
                lineas.append("  - Acción: %s" % ", ".join(nombres))
        lineas.append("")
    if ejecuciones:
        lineas += ["## Qué se ha ejecutado", ""]
        for e in ejecuciones:
            lineas.append("- %s %s — %s" % ("✅" if e.get("ok") else "❌",
                                            e.get("nombre") or e.get("id"), e.get("mensaje")))
        lineas.append("")
    lineas += ["## Ficha", "",
               "- Equipo: %s %s (serie %s)" % (so.get("fabricante"), so.get("modelo"), so.get("serie")),
               "- Sistema: %s build %s, instalado %s" % (so.get("nombre"), so.get("build"),
                                                         _fecha_legible(so.get("instalado"))),
               "- CPU: %s" % (datos.get("cpu") or {}).get("nombre"),
               "- RAM: %s GB" % so.get("ram_total_gb"),
               "- Auditoría: %.1f s, %s" % (float(datos.get("_duracion_s") or 0),
                                            "admin" if datos.get("admin") else "sin admin"),
               "", "_Generado por HERMES-RESCATE v%s_" % VERSION]
    return "\n".join(lineas)


def generar(datos, hallazgos, resumen, ejecuciones=None, carpeta=None):
    carpeta = carpeta or util.INFORMES
    os.makedirs(carpeta, exist_ok=True)
    sello = time.strftime("%Y%m%d-%H%M")
    equipo = "".join(c for c in (datos.get("equipo") or "equipo") if c.isalnum() or c in "-_")[:24]
    base = os.path.join(carpeta, "%s_%s" % (equipo, sello))

    rutas = {"html": base + ".html", "md": base + ".md", "json": base + ".json"}
    with open(rutas["html"], "w", encoding="utf-8") as f:
        f.write(construir_html(datos, hallazgos, resumen, ejecuciones))
    with open(rutas["md"], "w", encoding="utf-8") as f:
        f.write(construir_markdown(datos, hallazgos, resumen, ejecuciones))
    try:
        with open(rutas["json"], "w", encoding="utf-8") as f:
            json.dump({"datos": datos, "hallazgos": hallazgos, "resumen": resumen,
                       "ejecuciones": ejecuciones or []},
                      f, ensure_ascii=False, indent=1, default=str)
    except Exception as exc:
        rutas["json"] = None
        util.log("No se pudo escribir el JSON del informe: %s" % exc, "ERROR")
    return rutas
