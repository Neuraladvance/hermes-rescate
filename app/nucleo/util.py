# -*- coding: utf-8 -*-
"""Utilidades comunes: rutas, ejecucion de PowerShell, registro y consola."""
import base64
import ctypes
import json
import os
import subprocess
import sys
import time
from datetime import datetime

# ------------------------------------------------------------------ rutas
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAIZ = os.path.dirname(APP_DIR)


def ruta(*partes):
    return os.path.join(RAIZ, *partes)


INFORMES = ruta("informes")
LOGS = ruta("logs")
CONFIG = ruta("config", "config.json")
PS_DIR = os.path.join(APP_DIR, "ps")

for _d in (INFORMES, LOGS):
    try:
        os.makedirs(_d, exist_ok=True)
    except Exception:
        pass

CREATE_NO_WINDOW = 0x08000000


# ------------------------------------------------------------------ consola
def preparar_consola():
    """UTF-8 en la consola para que acentos y simbolos salgan bien."""
    try:
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def color(texto, codigo="", habilitado=True):
    if not habilitado:
        return texto
    return "\033[%sm%s\033[0m" % (codigo, texto) if codigo else texto


def habilitar_ansi():
    """Activa secuencias ANSI en la consola clasica de Windows."""
    try:
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        modo = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(modo)):
            k.SetConsoleMode(h, modo.value | 0x0004)
            return True
    except Exception:
        pass
    return False


VERDE, ROJO, AMARILLO, AZUL, GRIS, CIAN, NEGRITA = "92", "91", "93", "94", "90", "96", "1"


# ------------------------------------------------------------------ registro
_LOG = None


def log(msg, nivel="INFO"):
    global _LOG
    linea = "[%s] %-5s %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), nivel, msg)
    print(linea) if nivel == "ERROR" else None
    try:
        if _LOG is None:
            _LOG = open(os.path.join(LOGS, "rescate_%s.log" % datetime.now().strftime("%Y%m%d")),
                        "a", encoding="utf-8")
        _LOG.write(linea + "\n")
        _LOG.flush()
    except Exception:
        pass


# ------------------------------------------------------------------ sistema
def es_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _entorno():
    e = dict(os.environ)
    e["PYTHONIOENCODING"] = "utf-8"
    e["PSModulePath"] = os.environ.get(
        "PSModulePath",
        r"C:\Windows\system32\WindowsPowerShell\v1.0\Modules")
    return e


def ejecutar(argumentos, timeout=120, cwd=None):
    """Ejecuta un programa y devuelve (rc, stdout, stderr) como texto."""
    try:
        p = subprocess.run(argumentos, capture_output=True, timeout=timeout,
                           creationflags=CREATE_NO_WINDOW, cwd=cwd, env=_entorno())
        salida = _decodificar(p.stdout)
        err = _decodificar(p.stderr)
        return p.returncode, salida, err
    except subprocess.TimeoutExpired:
        return 124, "", "Tiempo de espera agotado (%ss)" % timeout
    except FileNotFoundError as exc:
        return 127, "", "No encontrado: %s" % exc
    except Exception as exc:  # pragma: no cover
        return 1, "", "Error al ejecutar: %s" % exc


def _decodificar(b):
    if not b:
        return ""
    for cp in ("utf-8", "cp850", "cp1252", "latin-1"):
        try:
            return b.decode(cp)
        except Exception:
            continue
    return b.decode("ascii", "replace")


def ps(script, timeout=120):
    """Ejecuta PowerShell sin ventana. -EncodedCommand evita problemas de comillas."""
    b64 = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ejecutar(["powershell.exe", "-NoProfile", "-NonInteractive",
                     "-ExecutionPolicy", "Bypass", "-EncodedCommand", b64], timeout=timeout)


def ps_json(script, timeout=120):
    """Ejecuta PowerShell y devuelve el objeto JSON que imprima, o None."""
    envoltura = ("$ErrorActionPreference='SilentlyContinue';"
                 "$ProgressPreference='SilentlyContinue';"
                 "$WarningAction='SilentlyContinue';" + script)
    rc, out, err = ps(envoltura, timeout=timeout)
    out = (out or "").strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except Exception:
        # puede venir con basura delante: buscamos el primer { o [
        for i, c in enumerate(out):
            if c in "{[":
                try:
                    return json.loads(out[i:])
                except Exception:
                    break
        return None


def ps_archivo(nombre_ps1, parametros=None, timeout=300):
    """Lanza un .ps1 de app/ps/ y devuelve (rc, salida)."""
    ruta_ps1 = os.path.join(PS_DIR, nombre_ps1)
    args = ["powershell.exe", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", ruta_ps1]
    if parametros:
        args += parametros
    return ejecutar(args, timeout=timeout)


def tamano_carpeta(ruta_carpeta, maximo_seg=25.0):
    """Suma de bytes REALES en disco (GetCompressedFileSize: no cuenta marcadores online)."""
    try:
        k = ctypes.windll.kernel32
        GetCompressedFileSizeW = k.GetCompressedFileSizeW
        GetCompressedFileSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
        GetCompressedFileSizeW.restype = ctypes.c_ulong
    except Exception:
        GetCompressedFileSizeW = None

    total = 0
    ficheros = 0
    t0 = time.time()
    for base, _dirs, archivos in os.walk(ruta_carpeta, onerror=lambda e: None):
        if time.time() - t0 > maximo_seg:
            break
        for a in archivos:
            p = os.path.join(base, a)
            try:
                if GetCompressedFileSizeW is not None:
                    alto = ctypes.c_ulong(0)
                    bajo = GetCompressedFileSizeW(p, ctypes.byref(alto))
                    tam = (alto.value << 32) | (bajo & 0xFFFFFFFF)
                    if tam in (0xFFFFFFFFFFFFFFFF,):
                        tam = 0
                else:
                    tam = os.path.getsize(p)
            except Exception:
                continue
            total += tam
            ficheros += 1
    return total, ficheros


def humano(bytes_):
    try:
        n = float(bytes_)
    except Exception:
        return "?"
    for unidad in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unidad == "TB":
            return ("%.1f %s" % (n, unidad)) if unidad != "B" else ("%d B" % n)
        n /= 1024.0
    return "?"
