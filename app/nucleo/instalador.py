# -*- coding: utf-8 -*-
"""Instalacion de actualizaciones de Windows y de programas (winget)."""
import json
import os
import subprocess
import time

from . import util

CATALOGO_PROGRAMAS = [
    {"id": "Google.Chrome", "nombre": "Google Chrome", "para": "navegador"},
    {"id": "Mozilla.Firefox", "nombre": "Mozilla Firefox", "para": "navegador alternativo"},
    {"id": "7zip.7zip", "nombre": "7-Zip", "para": "abrir comprimidos"},
    {"id": "VideoLAN.VLC", "nombre": "VLC", "para": "reproductor multimedia"},
    {"id": "Adobe.Acrobat.Reader.64-bit", "nombre": "Adobe Reader", "para": "leer PDF"},
    {"id": "LibreOffice.LibreOffice", "nombre": "LibreOffice", "para": "ofimática gratuita"},
    {"id": "TheDocumentFoundation.LibreOffice", "nombre": "LibreOffice (alt.)", "para": "ofimática"},
    {"id": "zoom.us.Zoom", "nombre": "Zoom", "para": "videollamadas"},
    {"id": "Microsoft.Teams", "nombre": "Microsoft Teams", "para": "trabajo"},
    {"id": "WhatsApp.WhatsApp", "nombre": "WhatsApp", "para": "mensajería"},
    {"id": "AnyDeskSoftwareGmbH.AnyDesk", "nombre": "AnyDesk", "para": "soporte remoto"},
    {"id": "Notepad++.Notepad++", "nombre": "Notepad++", "para": "editor de texto"},
    {"id": "Microsoft.PowerToys", "nombre": "PowerToys", "para": "utilidades de Windows"},
    {"id": "OBSProject.OBSStudio", "nombre": "OBS Studio", "para": "grabar pantalla"},
    {"id": "CPUID.CPU-Z", "nombre": "CPU-Z", "para": "diagnóstico de hardware"},
    {"id": "CrystalDewWorld.CrystalDiskInfo", "nombre": "CrystalDiskInfo", "para": "salud del disco"},
]


# ------------------------------------------------------------------ winget
def winget_disponible():
    rc, out, err = util.ejecutar(["winget", "--version"], timeout=30)
    if rc == 0:
        return (out or err or "").strip().splitlines()[0] if (out or err) else "winget"
    # En sesiones nuevas winget puede existir pero no estar en el PATH
    candidato = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "winget.exe")
    if os.path.exists(candidato):
        rc2, out2, _ = util.ejecutar([candidato, "--version"], timeout=30)
        if rc2 == 0:
            return (out2 or "").strip().splitlines()[0]
    return None


def _winget(args, timeout=900):
    rc, out, err = util.ejecutar(["winget"] + args, timeout=timeout)
    return rc, (out or ""), (err or "")


def buscar(termino, limite=15):
    """Busca paquetes en winget. Devuelve lista de dicts."""
    rc, out, err = _winget(["search", termino, "--accept-source-agreements",
                            "--disable-interactivity"], timeout=120)
    if rc != 0 and not out:
        return []
    filas = []
    for linea in out.splitlines():
        if not linea.strip() or linea.lstrip().startswith(("-", "Name", "Nombre")):
            continue
        partes = linea.split()
        if len(partes) < 3:
            continue
        # winget alinea columnas: id en la 2a, version en la 3a
        identificador = None
        for i, trozo in enumerate(partes):
            if "." in trozo and trozo not in ("...",) and i > 0 and not trozo[0].isdigit():
                identificador = trozo
                indice = i
                break
        if not identificador:
            continue
        nombre = " ".join(partes[:indice])
        version = partes[indice + 1] if len(partes) > indice + 1 else ""
        filas.append({"nombre": nombre, "id": identificador, "version": version})
        if len(filas) >= limite:
            break
    return filas


def instalar(paquete_id, timeout=1800):
    """Instala un paquete. Devuelve (ok, salida)."""
    rc, out, err = _winget(["install", "--id", paquete_id, "--exact", "--silent",
                            "--accept-package-agreements", "--accept-source-agreements",
                            "--disable-interactivity"], timeout=timeout)
    texto = (out + "\n" + err).strip()
    ok = rc == 0
    return ok, texto[-1500:]


# ------------------------------------------------------------------ Windows Update
def actualizar_windows(solo_drivers=False, aviso=None, maximo_s=7200):
    """Instala actualizaciones con actualizar.ps1, mostrando progreso.

    Devuelve dict con el resultado final del script.
    """
    aviso = aviso or (lambda *_: None)
    carpeta = util.ruta("logs", "tmp")
    os.makedirs(carpeta, exist_ok=True)
    salida = os.path.join(carpeta, "actualizar.json")
    if os.path.exists(salida):
        os.remove(salida)

    argumentos = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                  "-File", os.path.join(util.PS_DIR, "actualizar.ps1"), "-Salida", salida]
    if solo_drivers:
        argumentos.append("-SoloDrivers")

    proceso = subprocess.Popen(argumentos, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              creationflags=util.CREATE_NO_WINDOW)
    t0 = time.time()
    ultima_fase = None
    while True:
        if proceso.poll() is not None:
            break
        if time.time() - t0 > maximo_s:
            proceso.kill()
            return {"completo": False, "error": "tiempo máximo alcanzado (%d s)" % maximo_s}
        estado = _leer(salida)
        if estado:
            fase = estado.get("fase")
            if fase and fase != ultima_fase:
                ultima_fase = fase
                hechas = len(estado.get("hechas") or [])
                fallidas = len(estado.get("fallidas") or [])
                aviso("%s  [%d hechas, %d fallidas]" % (fase, hechas, fallidas))
        time.sleep(2)

    estado = _leer(salida) or {}
    estado["_segundos"] = round(time.time() - t0, 1)
    estado["_rc"] = proceso.returncode
    return estado


def _leer(ruta):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
