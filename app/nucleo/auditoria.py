# -*- coding: utf-8 -*-
"""Orquesta la auditoria: fase rapida + fase lenta + medidas propias (basura, bateria)."""
import json
import os
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET

from . import util

TIMEOUT_RAPIDO = 120
TIMEOUT_LENTO = 120


def _carpeta_trabajo():
    """Preferimos el propio USB (asi el informe viaja con el), con reserva en TEMP."""
    for candidato in (os.path.join(util.LOGS, "tmp"), None):
        try:
            if candidato is None:
                return tempfile.mkdtemp(prefix="rescate_")
            os.makedirs(candidato, exist_ok=True)
            prueba = os.path.join(candidato, ".escritura")
            with open(prueba, "w") as f:
                f.write("x")
            os.remove(prueba)
            return candidato
        except Exception:
            continue
    return tempfile.gettempdir()


def _leer_json(ruta):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _basura():
    """Tamano REAL en disco de las carpetas que se pueden limpiar."""
    usuario = os.environ.get("USERPROFILE") or ""
    sistema = os.environ.get("SystemRoot", r"C:\Windows")
    candidatos = [
        ("Temporales del usuario", os.environ.get("TEMP")),
        ("Temporales de Windows", os.path.join(sistema, "Temp")),
        ("Cache de Windows Update", os.path.join(sistema, "SoftwareDistribution", "Download")),
        ("Prefetch", os.path.join(sistema, "Prefetch")),
        ("Volcados de fallo", os.path.join(sistema, "Minidump")),
        ("Cache de entrega de optimizacion", os.path.join(sistema, "ServiceProfiles",
                                                         "NetworkService", "AppData", "Local",
                                                         "Microsoft", "Windows", "DeliveryOptimization", "Cache")),
        ("Windows.old (instalacion anterior)", os.path.join(os.environ.get("SystemDrive", "C:") + "\\", "Windows.old")),
        ("Papelera de reciclaje", os.environ.get("SystemDrive", "C:") + "\\$Recycle.Bin"),
    ]
    salida = []
    for nombre, ruta in candidatos:
        if not ruta or not os.path.isdir(ruta):
            continue
        bytes_, ficheros = util.tamano_carpeta(ruta, maximo_seg=6.0)
        if ficheros == 0 and bytes_ == 0:
            continue
        salida.append({"nombre": nombre, "ruta": ruta, "bytes": bytes_,
                       "texto": util.humano(bytes_), "ficheros": ficheros})
    salida.sort(key=lambda x: -x["bytes"])
    return salida


def _bateria(carpeta):
    """Salud real de la bateria desde el informe XML nativo de Windows."""
    destino = os.path.join(carpeta, "bateria.xml")
    rc, _out, _err = util.ejecutar(["powercfg", "/batteryreport", "/xml", "/output", destino], timeout=40)
    if not os.path.exists(destino):
        return None
    try:
        arbol = ET.parse(destino)
    except Exception:
        return None
    diseno = capacidad = ciclos = None
    for nodo in arbol.getroot().iter():
        etiqueta = nodo.tag.split("}")[-1]
        texto = (nodo.text or "").strip()
        if not texto:
            continue
        if etiqueta == "DesignCapacity" and diseno is None:
            try:
                diseno = int(texto)
            except ValueError:
                pass
        elif etiqueta == "FullChargeCapacity" and capacidad is None:
            try:
                capacidad = int(texto)
            except ValueError:
                pass
        elif etiqueta == "CycleCount" and ciclos is None:
            try:
                ciclos = int(texto)
            except ValueError:
                pass
    if not diseno or not capacidad:
        return {"diseno_mwh": diseno, "capacidad_mwh": capacidad, "ciclos": ciclos, "salud_pct": None}
    return {
        "diseno_mwh": diseno,
        "capacidad_mwh": capacidad,
        "ciclos": ciclos,
        "salud_pct": round(100.0 * capacidad / diseno, 1),
        "desgaste_pct": round(100.0 - 100.0 * capacidad / diseno, 1),
    }


def auditar(con_lento=True, aviso=None):
    """Devuelve el diccionario completo de datos del equipo."""
    aviso = aviso or (lambda *_: None)
    carpeta = _carpeta_trabajo()
    datos = {"_carpeta_trabajo": carpeta, "_inicio": time.time()}

    aviso("Leyendo hardware, sistema, discos, eventos y red...")
    ruta_rapida = os.path.join(carpeta, "auditoria.json")
    if os.path.exists(ruta_rapida):
        os.remove(ruta_rapida)
    rc, salida, err = util.ps_archivo("auditoria.ps1",
                                      ["-Salida", ruta_rapida], timeout=TIMEOUT_RAPIDO)
    rapida = _leer_json(ruta_rapida)
    if rapida is None:
        progreso = ""
        p = ruta_rapida + ".progreso.txt"
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    progreso = f.read().strip().replace("\n", " | ")
            except Exception:
                pass
        raise RuntimeError(
            "La auditoria no pudo completarse (rc=%s). %s %s Seccion: %s"
            % (rc, (salida or "").strip()[:200], (err or "").strip()[:200], progreso or "?"))
    datos.update(rapida)

    aviso("Midiendo salud de la bateria...")
    bat = _bateria(carpeta)
    if bat:
        datos.setdefault("bateria", {})
        datos["bateria"].update(bat)

    aviso("Midiendo espacio recuperable en disco...")
    datos["basura"] = _basura()

    if con_lento:
        aviso("Consultando Defender, BitLocker, desgaste del disco y actualizaciones (30-60 s)...")
        ruta_lenta = os.path.join(carpeta, "lento.json")
        if os.path.exists(ruta_lenta):
            os.remove(ruta_lenta)
        t0 = time.time()
        rc, salida, err = util.ps_archivo("lento.ps1",
                                          ["-Salida", ruta_lenta], timeout=TIMEOUT_LENTO)
        lento = _leer_json(ruta_lenta)
        datos["lento"] = lento or {"completo": False, "nota": "sin datos (rc=%s)" % rc}
        datos["lento"]["_segundos"] = round(time.time() - t0, 1)

    datos["_fin"] = time.time()
    datos["_duracion_s"] = round(datos["_fin"] - datos["_inicio"], 1)
    return datos


def limpiar_carpeta_trabajo(datos):
    """Borra los ficheros temporales de la auditoria (deja el JSON consolidado)."""
    carpeta = datos.get("_carpeta_trabajo")
    if not carpeta:
        return
    try:
        if os.path.basename(carpeta) == "tmp":
            for nombre in os.listdir(carpeta):
                try:
                    os.remove(os.path.join(carpeta, nombre))
                except Exception:
                    pass
        else:
            shutil.rmtree(carpeta, ignore_errors=True)
    except Exception:
        pass
