# -*- coding: utf-8 -*-
"""Agente IA opcional. Sin clave configurada el programa funciona igual; esto solo
anade conversacion y explicacion de los hallazgos.

Reglas que aplica siempre:
 - Seudonimiza el equipo (nombre, usuario, dominio, serie, MAC, IP) ANTES de enviar.
 - Avisa de que datos salen y espera confirmacion.
 - Solo puede ejecutar acciones del catalogo de reparaciones.
"""
import json
import os
import re
import urllib.error
import urllib.request

from . import reparaciones, util

DEFECTO = {
    "endpoint": "",
    "modelo": "",
    "clave": "",
    "temperatura": 0.2,
    "max_tokens": 1200,
    "aviso_privacidad": True,
}

SISTEMA = """Eres un técnico experto en reparación de ordenadores Windows, trabajando desde un
USB de diagnóstico. Hablas español, de forma directa y técnica, sin relleno ni alarmismo.
Tienes delante los datos reales de UN equipo (auditoría adjunta).

Reglas:
- Responde corto (máximo 12 líneas) salvo que pidan detalle.
- Distingue lo que es un problema real de lo que es información normal. No alarmes.
- Solo puedes ejecutar acciones del CATÁLOGO. No inventes comandos ni rutas.
- Cuando quieras ejecutar una acción, escribe en una línea aparte exactamente:
  ACCION: id_de_la_accion
  (una por línea, solo si de verdad hace falta). El programa pedirá confirmación al técnico.
- Si falta un dato para decidir, dilo en vez de suponer.
- Nada de consejos genéricos de manual: usa los datos del equipo.
"""


# ------------------------------------------------------------------ configuracion
def config():
    datos = dict(DEFECTO)
    try:
        with open(util.CONFIG, "r", encoding="utf-8") as f:
            archivo = json.load(f)
    except Exception:
        archivo = {}
    bloque = archivo.get("ia") or {}
    datos.update({k: v for k, v in bloque.items() if k in DEFECTO})
    datos["endpoint"] = os.environ.get("RESCATE_IA_ENDPOINT", datos["endpoint"]).rstrip("/")
    datos["modelo"] = os.environ.get("RESCATE_IA_MODELO", datos["modelo"])
    datos["clave"] = os.environ.get("RESCATE_IA_CLAVE", datos["clave"])
    return datos


def guardar_config(**cambios):
    try:
        with open(util.CONFIG, "r", encoding="utf-8") as f:
            archivo = json.load(f)
    except Exception:
        archivo = {}
    archivo.setdefault("ia", {}).update(cambios)
    os.makedirs(os.path.dirname(util.CONFIG), exist_ok=True)
    with open(util.CONFIG, "w", encoding="utf-8") as f:
        json.dump(archivo, f, ensure_ascii=False, indent=2)
    return archivo["ia"]


def disponible():
    cfg = config()
    return bool(cfg["endpoint"] and cfg["modelo"] and cfg["clave"])


# ------------------------------------------------------------------ seudonimizacion
class Seudonimo:
    """Sustituye identificadores por marcadores y los restaura en la respuesta."""

    def __init__(self, datos):
        self.mapa = {}
        so = datos.get("so") or {}
        candidatos = [
            ("EQUIPO", datos.get("equipo")),
            ("USUARIO", datos.get("usuario")),
            ("DOMINIO", datos.get("dominio")),
            ("SERIE", so.get("serie")),
        ]
        for marca, valor in candidatos:
            if valor and len(str(valor)) > 2 and str(valor).upper() not in ("SYSTEM", "N/A", "DEFAULT"):
                self.mapa[str(valor)] = "[%s]" % marca
        indice_mac = indice_ip = 0
        for adaptador in (datos.get("red") or {}).get("adaptadores") or []:
            mac = (adaptador.get("mac") or "").strip()
            if mac and len(mac) >= 11:
                indice_mac += 1
                self.mapa[mac] = "[MAC%d]" % indice_mac
            for ip in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", str(adaptador.get("ip") or "")):
                if ip in self.mapa:
                    continue
                indice_ip += 1
                self.mapa[ip] = "[IP%d]" % indice_ip
        for entrada in ((datos.get("hosts") or {}).get("muestra") or []):
            for ip in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", str(entrada)):
                if ip not in self.mapa:
                    indice_ip += 1
                    self.mapa[ip] = "[IP%d]" % indice_ip
        # los mas largos primero, para no romper cadenas parciales
        self._orden = sorted(self.mapa.items(), key=lambda kv: -len(kv[0]))

    def aplicar(self, texto):
        if not texto:
            return texto
        for valor, marca in self._orden:
            texto = texto.replace(valor, marca)
        return texto

    def restaurar(self, texto):
        if not texto:
            return texto
        for valor, marca in self._orden:
            texto = texto.replace(marca, valor)
        return texto

    def resumen(self):
        return ", ".join("%s → %s" % (marca, "dato real") for marca in sorted(set(self.mapa.values())))


# ------------------------------------------------------------------ contexto
def contexto(datos, hallazgos, resumen):
    """Resumen compacto y legible del equipo para el modelo (seudonimizado despues)."""
    so = datos.get("so") or {}
    lento = datos.get("lento") or {}
    lineas = [
        "FICHA: %s %s | %s build %s | CPU %s | RAM %s GB (%s%% usada) | uptime %s h"
        % (so.get("fabricante"), so.get("modelo"), so.get("nombre"), so.get("build"),
           (datos.get("cpu") or {}).get("nombre"), so.get("ram_total_gb"),
           so.get("ram_uso_pct"), so.get("uptime_horas")),
        "ACTIVACION: %s" % ((datos.get("activacion") or {}).get("descripcion")),
        "VEREDICTO: %s (%s)" % (resumen.get("titulo"), resumen.get("cuenta")),
        "",
        "HALLAZGOS:",
    ]
    for h in hallazgos:
        lineas.append("- [%s] %s — %s" % (h["severidad"], h["titulo"], h["detalle"]))
        if h.get("reparaciones"):
            nombres = [reparaciones.obtener(r)["nombre"] for r in h["reparaciones"] if reparaciones.obtener(r)]
            lineas.append("  acciones sugeridas: %s" % ", ".join(nombres))
    lineas.append("")
    lineas.append("VOLUMENES: %s" % ", ".join(
        "%s %s GB (libre %s GB, %s%%)" % (v.get("letra"), v.get("gb"), v.get("libre_gb"), v.get("libre_pct"))
        for v in datos.get("volumenes") or []))
    lineas.append("DISCOS: %s" % ", ".join(
        "%s %s GB %s salud=%s" % (d.get("modelo"), d.get("gb"), d.get("medio"), d.get("salud"))
        for d in datos.get("discos_fisicos") or []))
    bateria = datos.get("bateria") or {}
    if bateria.get("presente"):
        lineas.append("BATERIA: salud %s%% (%s de %s mWh)"
                      % (bateria.get("salud_pct"), bateria.get("capacidad_mwh"), bateria.get("diseno_mwh")))
    defen = lento.get("defender") or {}
    if defen:
        lineas.append("DEFENDER: activo=%s tiempo_real=%s firmas_hace=%s dias"
                      % (defen.get("activo"), defen.get("tiempo_real"), defen.get("firmas_dias")))
    if lento.get("wu_total") is not None:
        lineas.append("ACTUALIZACIONES PENDIENTES: %s (criticas: %s)"
                      % (lento.get("wu_total"), lento.get("wu_criticas")))
    incidentes = datos.get("incidentes") or []
    if incidentes:
        lineas.append("INCIDENTES 30d: %s" % "; ".join(
            "%s %s" % (i.get("id"), (i.get("texto") or "")[:70]) for i in incidentes[:5]))
    red = (datos.get("red") or {}).get("conectividad") or {}
    lineas.append("RED: %s" % ", ".join("%s=%s" % (k, v) for k, v in red.items()))
    parados = datos.get("servicios_parados") or []
    if parados:
        lineas.append("SERVICIOS AUTO DETENIDOS: %s" % ", ".join(
            str(s.get("nombre")) for s in parados[:10]))
    programas = (datos.get("programas") or {}).get("grandes") or []
    if programas:
        lineas.append("PROGRAMAS QUE MAS OCUPAN: %s" % ", ".join(
            "%s (%.0f MB)" % (p.get("nombre"), float(p.get("mb") or 0)) for p in programas[:8]))
    basura = datos.get("basura") or []
    if basura:
        lineas.append("ESPACIO RECUPERABLE: %s" % ", ".join(
            "%s %s" % (b.get("nombre"), b.get("texto")) for b in basura))
    lineas.append("")
    lineas.append("CATALOGO DE ACCIONES DISPONIBLES (id — nombre — riesgo):")
    for r in reparaciones.CATALOGO.values():
        if r["nivel"] < 3:
            lineas.append("  %s — %s — %s%s"
                          % (r["id"], r["nombre"], reparaciones.NIVELES[r["nivel"]],
                             " (necesita administrador)" if r["admin"] else ""))
    return "\n".join(lineas)


# ------------------------------------------------------------------ llamada
def _peticion(cfg, mensajes, timeout=120):
    cuerpo = json.dumps({
        "model": cfg["modelo"],
        "messages": mensajes,
        "temperature": float(cfg.get("temperatura") or 0.2),
        "max_tokens": int(cfg.get("max_tokens") or 1200),
    }).encode("utf-8")
    peticion = urllib.request.Request(
        cfg["endpoint"] + "/chat/completions", data=cuerpo,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + cfg["clave"]})
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError("El servidor de IA respondió %s: %s" % (exc.code, detalle))
    except Exception as exc:
        raise RuntimeError("No se pudo hablar con el servidor de IA: %s" % exc)
    try:
        return datos["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise RuntimeError("Respuesta inesperada del servidor de IA: %s" % str(datos)[:200])


ACCION_RE = re.compile(r"^\s*ACCI[ÓO]N\s*:\s*([a-z0-9_]+)\s*$", re.IGNORECASE | re.MULTILINE)


def acciones_de(texto):
    return [m.group(1) for m in ACCION_RE.finditer(texto or "")]


class Agente:
    """Conversacion con memoria de la sesion (no guarda nada en disco)."""

    def __init__(self, datos, hallazgos, resumen, cfg=None):
        self.cfg = cfg or config()
        self.seudonimo = Seudonimo(datos)
        self.contexto = self.seudonimo.aplicar(contexto(datos, hallazgos, resumen))
        self.mensajes = [
            {"role": "system", "content": SISTEMA},
            {"role": "system", "content": self.contexto},
        ]

    def preguntar(self, texto):
        """Devuelve (respuesta, acciones_sugeridas)."""
        self.mensajes.append({"role": "user", "content": self.seudonimo.aplicar(texto)})
        if len(self.mensajes) > 24:
            self.mensajes = self.mensajes[:2] + self.mensajes[-20:]
        bruto = _peticion(self.cfg, self.mensajes)
        self.mensajes.append({"role": "assistant", "content": bruto})
        acciones = [a for a in acciones_de(bruto) if reparaciones.obtener(a)]
        return self.seudonimo.restaurar(bruto), acciones

    def aviso_privacidad(self):
        partes = [
            "Se va a enviar a %s (modelo %s) un resumen de este equipo:"
            % (self.cfg["endpoint"], self.cfg["modelo"]),
            " · hardware, versión de Windows, discos, salud de batería",
            " · programas instalados y espacio recuperable",
            " · hallazgos del diagnóstico y errores del registro",
            " · CATÁLOGO de acciones disponibles",
            "",
            "Antes de enviarlo se sustituyen estos identificadores por marcadores:",
            " · %s" % (self.seudonimo.resumen() or "ninguno detectado"),
            "La respuesta se recibe con los datos reales restaurados.",
        ]
        return "\n".join(partes)


def probar(cfg=None):
    """Comprobación rápida de que el endpoint y la clave funcionan."""
    cfg = cfg or config()
    if not disponible():
        return False, "Falta endpoint, modelo o clave en config/config.json (bloque «ia»)."
    try:
        respuesta = _peticion(cfg, [{"role": "user", "content": "Responde solo: OK"}], timeout=60)
        return True, "El servidor de IA responde: %s" % respuesta.strip()[:80]
    except RuntimeError as exc:
        return False, str(exc)
