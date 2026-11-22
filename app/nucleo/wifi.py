# -*- coding: utf-8 -*-
"""Conexion a redes WiFi conocidas (hotspot del movil) sin escribir nada a mano.

La clave se guarda ofuscada en config/wifi.json. Ojo: es ofuscacion, no cifrado
fuerte. Quien tenga el USB y este codigo puede recuperarla.
"""
import base64
import hashlib
import json
import os
import socket
import time
from xml.sax.saxutils import escape

from . import util

_SAL = b"HERMES-RESCATE-wifi-v1"
_ARCHIVO = util.ruta("config", "wifi.json")


# ------------------------------------------------------------------ ofuscacion
def _flujo(semilla, n):
    salida = bytearray()
    i = 0
    while len(salida) < n:
        salida += hashlib.sha256(semilla + i.to_bytes(4, "big")).digest()
        i += 1
    return bytes(salida[:n])


def ofuscar(texto):
    if not texto:
        return ""
    datos = texto.encode("utf-8")
    flujo = _flujo(_SAL, len(datos))
    return "obf:" + base64.b64encode(bytes(a ^ b for a, b in zip(datos, flujo))).decode("ascii")


def desofuscar(valor):
    if not valor:
        return ""
    if not valor.startswith("obf:"):
        return valor
    try:
        datos = base64.b64decode(valor[4:])
        flujo = _flujo(_SAL, len(datos))
        return bytes(a ^ b for a, b in zip(datos, flujo)).decode("utf-8")
    except Exception:
        return ""


# ------------------------------------------------------------------ configuracion
DEFECTO = {
    "redes": [],
    "nota": "Añade aquí las redes WiFi del técnico. Cada entrada: "
            "{\"nombre\": \"Mi hotspot\", \"ssid\": \"Mi hotspot\", "
            "\"clave\": \"la-contraseña\", \"prioridad\": 1}. "
            "También puedes hacerlo desde el menú, opción 3, escaneando y guardando.",
}


def cargar():
    try:
        with open(_ARCHIVO, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except Exception:
        datos = dict(DEFECTO)
        guardar(datos)
    datos.setdefault("redes", [])
    return datos


def guardar(datos):
    os.makedirs(os.path.dirname(_ARCHIVO), exist_ok=True)
    with open(_ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


def configurar(nombre, ssid, clave, prioridad=1):
    datos = cargar()
    for red in datos["redes"]:
        if red.get("nombre", "").lower() == nombre.lower() or red.get("ssid") == ssid:
            red.update({"nombre": nombre, "ssid": ssid, "clave": ofuscar(clave), "prioridad": prioridad})
            break
    else:
        datos["redes"].append({"nombre": nombre, "ssid": ssid, "clave": ofuscar(clave), "prioridad": prioridad})
    datos["redes"].sort(key=lambda r: r.get("prioridad", 9))
    guardar(datos)
    return datos["redes"]


# ------------------------------------------------------------------ estado
def adaptador_wifi():
    """Devuelve el estado del adaptador WiFi o None si no hay ninguno usable."""
    rc, out, err = util.ejecutar(["netsh", "wlan", "show", "interfaces"], timeout=20)
    texto = (out or "") + (err or "")
    if rc != 0 or "no hay" in texto.lower() or "no wireless" in texto.lower():
        return None
    for linea in texto.splitlines():
        limpia = linea.strip()
        if limpia.lower().startswith(("name", "nombre")):
            return {"interfaz": limpia.split(":", 1)[-1].strip()}
    return {"interfaz": "?"} if texto.strip() else None


def escanear():
    """Redes visibles: [{ssid, senal, autenticacion}]."""
    rc, out, _ = util.ejecutar(["netsh", "wlan", "show", "networks", "mode=bssid"], timeout=35)
    redes = []
    actual = None
    for linea in (out or "").splitlines():
        limpia = linea.strip()
        if limpia.lower().startswith("ssid ") and "bssid" not in limpia.lower():
            actual = {"ssid": limpia.split(":", 1)[-1].strip(), "senal": None, "autenticacion": None}
            redes.append(actual)
        elif actual is not None and ":" in limpia:
            clave, _, valor = limpia.partition(":")
            clave, valor = clave.strip().lower(), valor.strip()
            if clave in ("signal", "señal", "senal"):
                actual["senal"] = valor
            elif clave in ("authentication", "autenticación", "autenticacion"):
                actual["autenticacion"] = valor
    vistos, salida = set(), []
    for r in redes:
        if r["ssid"] and r["ssid"] not in vistos:
            vistos.add(r["ssid"])
            salida.append(r)
    return salida


def _hay_internet(timeout=2.0):
    for host, puerto in (("1.1.1.1", 443), ("8.8.8.8", 53)):
        try:
            s = socket.create_connection((host, puerto), timeout=timeout)
            s.close()
            return True
        except Exception:
            continue
    return False


# ------------------------------------------------------------------ conexion
def _perfil_xml(ssid, clave, autenticacion="WPA2PSK"):
    ssid_x = escape(ssid)
    hex_ssid = ssid.encode("utf-8").hex().upper()
    if not clave:
        seguridad = ("<authEncryption><authentication>open</authentication>"
                     "<encryption>none</encryption><useOneX>false</useOneX></authEncryption>")
    else:
        seguridad = (
            "<authEncryption><authentication>%s</authentication><encryption>AES</encryption>"
            "<useOneX>false</useOneX></authEncryption>"
            "<sharedKey><keyType>passPhrase</keyType><protected>false</protected>"
            "<keyMaterial>%s</keyMaterial></sharedKey>" % (autenticacion, escape(clave)))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">\n'
        ' <name>%s</name>\n'
        ' <SSIDConfig><SSID><hex>%s</hex><name>%s</name></SSID></SSIDConfig>\n'
        ' <connectionType>ESS</connectionType>\n'
        ' <connectionMode>auto</connectionMode>\n'
        ' <MSM><security>%s</security></MSM>\n'
        '</WLANProfile>\n' % (ssid_x, hex_ssid, ssid_x, seguridad))


def conectar(ssid, clave, espera_s=25, aviso=None):
    """Crea el perfil y conecta. Devuelve (ok, mensaje)."""
    aviso = aviso or (lambda *_: None)
    if adaptador_wifi() is None:
        return False, ("No hay adaptador WiFi utilizable en este equipo (o le faltan los "
                       "controladores). Usa cable, o comparte la conexión del móvil por USB.")

    carpeta = util.ruta("logs", "tmp")
    os.makedirs(carpeta, exist_ok=True)
    ruta_xml = os.path.join(carpeta, "perfil_wlan.xml")

    intentos = ("WPA2PSK", "WPA3SAE") if clave else ("open",)
    ultimo = ""
    for autenticacion in intentos:
        aviso("Creando perfil WiFi (%s) para «%s»..." % (autenticacion, ssid))
        with open(ruta_xml, "w", encoding="utf-8") as f:
            f.write(_perfil_xml(ssid, clave, autenticacion))
        util.ejecutar(["netsh", "wlan", "delete", "profile", "name=%s" % ssid], timeout=20)
        rc, out, err = util.ejecutar(
            ["netsh", "wlan", "add", "profile", "filename=%s" % ruta_xml, "user=current"], timeout=30)
        if rc != 0:
            ultimo = (out or err or "").strip()[:200]
            continue

        aviso("Conectando a «%s»..." % ssid)
        util.ejecutar(["netsh", "wlan", "connect", "name=%s" % ssid, "ssid=%s" % ssid], timeout=30)
        limite = time.time() + espera_s
        while time.time() < limite:
            if _hay_internet():
                return True, "Conectado a «%s» y con salida a internet." % ssid
            time.sleep(1.5)
        ultimo = "el perfil se creó pero no se llegó a tener internet"

    estado = estado_conexion()
    return False, ("No se pudo conectar a «%s». %s%s" %
                   (ssid, ultimo, (" Estado: " + estado) if estado else ""))


def estado_conexion():
    rc, out, _ = util.ejecutar(["netsh", "wlan", "show", "interfaces"], timeout=20)
    ssid = ""
    for linea in (out or "").splitlines():
        limpia = linea.strip()
        if limpia.lower().startswith("ssid") and "bssid" not in limpia.lower():
            ssid = limpia.split(":", 1)[-1].strip()
    internet = _hay_internet()
    if ssid and internet:
        return "conectado a «%s» con internet" % ssid
    if ssid:
        return "conectado a «%s» pero sin internet" % ssid
    return "" if internet else "sin WiFi conectada"
