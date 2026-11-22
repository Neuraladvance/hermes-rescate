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


def _limpio(texto):
    """winget llena la salida de barras de progreso: dejar el texto legible."""
    malos = [n for n in range(0, 9)] + [11, 12] + [n for n in range(14, 32)]
    tabla = {n: None for n in malos}
    return (texto or "").translate(tabla).strip()


def _winget_con_progreso(args, aviso=None, timeout=1800):
    """Ejecuta winget enseñando lo que va pasando, no al final.

    Devuelve (rc, texto_completo). Los mensajes se pasan a «aviso» según llegan:
    buscar, descargar (con porcentaje), verificar, instalar, terminar.
    """
    aviso = aviso or (lambda *_: None)
    proceso = subprocess.Popen(
        ["winget"] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=util.CREATE_NO_WINDOW, env=util._entorno())
    trozos, pendiente = [], ""
    ultimo_aviso = ""
    porcentaje_visto = -10
    descargando = False
    inicio = time.time()
    while True:
        bloque = proceso.stdout.read(1)
        if not bloque:
            break
        if time.time() - inicio > timeout:
            proceso.kill()
            trozos.append("tiempo de espera agotado")
            break
        caracter = bloque.decode("utf-8", "replace")
        if caracter not in (chr(13), chr(10)):
            pendiente += caracter
            continue
        linea = _limpio(pendiente)
        pendiente = ""
        if not linea:
            continue
        trozos.append(linea)
        bajo = linea.lower()
        mensaje = None
        if "already installed" in bajo or "ya está instalado" in bajo:
            mensaje = "Ese programa ya está instalado; compruebo si hay versión nueva."
        elif "no available upgrade" in bajo or "no newer package" in bajo:
            mensaje = "No hay versión más nueva: no hay nada que instalar."
        elif "found " in bajo:
            mensaje = "Paquete encontrado: %s" % linea.split("Found ", 1)[-1][:90]
        elif descargando and "%" in linea:
            porcentaje = None
            for trozo in linea.replace("%", " % ").split():
                if trozo.isdigit() and 0 <= int(trozo) <= 100:
                    porcentaje = int(trozo)
            if porcentaje is not None and porcentaje >= porcentaje_visto + 10:
                porcentaje_visto = porcentaje
                mensaje = "Descargando... %d%%" % porcentaje
        elif "downloading" in bajo or "descargando" in bajo:
            descargando = True
            porcentaje = None
            for trozo in linea.replace("%", " % ").split():
                if trozo.isdigit() and 0 <= int(trozo) <= 100:
                    porcentaje = int(trozo)
            if porcentaje is not None and porcentaje >= porcentaje_visto + 10:
                porcentaje_visto = porcentaje
                mensaje = "Descargando… %d%%" % porcentaje
            elif porcentaje is None:
                mensaje = "Descargando el instalador…"
        elif "verified" in bajo or "hash" in bajo:
            mensaje = "Descarga verificada (hash correcto)."
        elif "starting package install" in bajo or "iniciando" in bajo:
            descargando = False
            mensaje = "Instalando (puede salir el aviso de Windows)…"
        elif "successfully installed" in bajo or "instalado correctamente" in bajo:
            mensaje = "Instalado."
        elif "uninstall" in bajo and ("success" in bajo or "correctamente" in bajo):
            mensaje = "Desinstalado."
        elif "cancel" in bajo or "0x800704c7" in bajo:
            mensaje = "Windows ha cancelado la operación (suele ser el aviso de permisos)."
        elif "no applicable" in bajo or "no package found" in bajo:
            mensaje = "winget no encuentra un instalador aplicable."
        if mensaje and mensaje != ultimo_aviso:
            ultimo_aviso = mensaje
            aviso(mensaje)
    linea = _limpio(pendiente)
    if linea:
        trozos.append(linea)
    proceso.wait()
    return proceso.returncode, chr(10).join(trozos)


def buscar(termino, limite=15):
    """Busca paquetes en winget. Devuelve lista de dicts."""
    rc, out, err = _winget(["search", termino, "--accept-source-agreements",
                            "--disable-interactivity"], timeout=120)
    if rc != 0 and not out:
        return []
    filas = []
    ruido = ("no package found", "no se encontr", "no installed", "no se ha encontrado",
             "no se encontraron", "try again", "no applicable", "no packages")
    for linea in out.splitlines():
        if not linea.strip() or linea.lstrip().startswith(("-", "Name", "Nombre")):
            continue
        if any(trozo in linea.lower() for trozo in ruido):
            continue
        partes = linea.split()
        if len(partes) < 3:
            continue
        # winget alinea columnas: id en la 2a, version en la 3a
        identificador = None
        for i, trozo in enumerate(partes):
            if ("." in trozo and not trozo.endswith(".") and trozo not in ("...",)
                    and i > 0 and not trozo[0].isdigit()):
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


def instalar(paquete_id, timeout=1800, aviso=None):
    """Instala un paquete enseñando el progreso. Devuelve (ok, salida)."""
    if not id_valido(paquete_id):
        return False, "Identificador de paquete no válido: %r" % paquete_id
    rc, texto = _winget_con_progreso(
        ["install", "--id", paquete_id, "--exact", "--silent",
         "--accept-package-agreements", "--accept-source-agreements",
         "--disable-interactivity"], aviso=aviso, timeout=timeout)
    bajo = texto.lower()
    if "already installed" in bajo or "no available upgrade" in bajo or "no newer package" in bajo:
        return True, "Ya estaba instalado y no hay versión más nueva." + chr(10) + texto[-1500:]
    return rc == 0, texto[-2000:]


# ------------------------------------------------------------------ Windows Update
def id_valido(paquete_id):
    """Un id de winget: letras, numeros, punto, guion, guion bajo y mas. Nada mas."""
    import re
    return bool(re.match(r"^[A-Za-z0-9._+-]{2,120}$", (paquete_id or "").strip()))


def desinstalar(paquete_id, timeout=900, aviso=None):
    """Desinstala un paquete enseñando el progreso. Devuelve (ok, salida)."""
    if not id_valido(paquete_id):
        return False, "Identificador de paquete no válido: %r" % paquete_id
    rc, texto = _winget_con_progreso(
        ["uninstall", "--id", paquete_id, "--exact", "--silent",
         "--disable-interactivity"], aviso=aviso, timeout=timeout)
    return rc == 0, texto[-2000:]


def _ejecutar_ps(salida, argumentos_extra, aviso, maximo_s, seguir_fase=True):
    """Lanza actualizar.ps1 y devuelve el JSON final. Compartido por buscar e instalar."""
    if os.path.exists(salida):
        os.remove(salida)
    argumentos = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                  "-File", os.path.join(util.PS_DIR, "actualizar.ps1"), "-Salida", salida]
    argumentos.extend(argumentos_extra)
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
        if seguir_fase and aviso:
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


def buscar_actualizaciones(maximo_s=900):
    """Busca lo que hay pendiente SIN instalar y lo clasifica (no necesita admin)."""
    salida = os.path.join(util.ruta("logs", "tmp"), "buscar_actualizaciones.json")
    os.makedirs(os.path.dirname(salida), exist_ok=True)
    return _ejecutar_ps(salida, ["-SoloBuscar"], None, maximo_s, seguir_fase=False)


def actualizar_windows(solo_drivers=False, aviso=None, maximo_s=7200,
                       solo_actualizaciones=False, excluir_firmware=False,
                       solo_descargar=False):
    """Instala con actualizar.ps1, mostrando progreso.

    Los grupos (actualizaciones / controladores / firmware) se pueden filtrar: la
    interfaz pregunta por separado porque el firmware es el que puede dejar el
    equipo sin arrancar si se corta la corriente.
    """
    aviso = aviso or (lambda *_: None)
    carpeta = util.ruta("logs", "tmp")
    os.makedirs(carpeta, exist_ok=True)
    salida = os.path.join(carpeta, "actualizar.json")

    extra = []
    if solo_drivers:
        extra.append("-SoloDrivers")
    if solo_actualizaciones:
        extra.append("-SoloActualizaciones")
    if excluir_firmware:
        extra.append("-ExcluirFirmware")
    if solo_descargar:
        extra.append("-SoloDescargar")
    return _ejecutar_ps(salida, extra, aviso, maximo_s)


def _leer(ruta):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
