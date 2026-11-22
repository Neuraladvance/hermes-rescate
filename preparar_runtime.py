# -*- coding: utf-8 -*-
"""Descarga el Python portátil (embebido) que necesita HERMES-RESCATE.

El repositorio no incluye 21 MB de binarios: se bajan de python.org la primera vez.
Uso:  python preparar_runtime.py
"""
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

VERSION = "3.11.9"
URL = "https://www.python.org/ftp/python/%s/python-%s-embed-amd64.zip" % (VERSION, VERSION)
RAIZ = os.path.dirname(os.path.abspath(__file__))
DESTINO = os.path.join(RAIZ, "runtime", "python")
TEMPORAL = os.path.join(RAIZ, "runtime", "_py.zip")


def tamano_legible(bytes_):
    for unidad in ("B", "KB", "MB"):
        if bytes_ < 1024 or unidad == "MB":
            return "%.1f %s" % (bytes_, unidad)
        bytes_ /= 1024.0


def descargar():
    os.makedirs(os.path.join(RAIZ, "runtime"), exist_ok=True)
    print("Descargando Python %s embebido (amd64)..." % VERSION)
    print("  %s" % URL)
    with urllib.request.urlopen(URL, timeout=120) as respuesta, open(TEMPORAL, "wb") as f:
        shutil.copyfileobj(respuesta, f)
    bytes_ = os.path.getsize(TEMPORAL)
    if bytes_ < 5 * 1024 * 1024:
        raise RuntimeError("La descarga parece incompleta (%s)" % tamano_legible(bytes_))
    print("  Descargado: %s" % tamano_legible(bytes_))
    with open(TEMPORAL, "rb") as f:
        print("  sha256: %s" % hashlib.sha256(f.read()).hexdigest())


def extraer():
    if os.path.isdir(DESTINO):
        shutil.rmtree(DESTINO)
    os.makedirs(DESTINO)
    with zipfile.ZipFile(TEMPORAL) as z:
        z.extractall(DESTINO)
    os.remove(TEMPORAL)
    print("  Extraído en runtime/python/")


def comprobar():
    python = os.path.join(DESTINO, "python.exe")
    if not os.path.exists(python):
        raise RuntimeError("No aparece runtime/python/python.exe")
    resultado = subprocess.run([python, "-c", "import sys, json, urllib.request; print(sys.version)"],
                               capture_output=True, text=True, timeout=120)
    if resultado.returncode != 0:
        raise RuntimeError("El runtime no arranca: %s" % resultado.stderr[:300])
    print("  Runtime listo: %s" % resultado.stdout.strip())


def main():
    print("=" * 70)
    print(" HERMES-RESCATE · preparación del runtime portátil")
    print("=" * 70)
    if os.path.exists(os.path.join(DESTINO, "python.exe")):
        print("Ya hay un runtime en runtime/python/. Se va a sustituir por una copia limpia.")
    try:
        descargar()
        extraer()
        comprobar()
    except Exception as exc:
        print("\nERROR: %s" % exc)
        print("Descarga el ZIP a mano desde %s y descomprímelo en runtime/python/" % URL)
        return 1
    print("\nListo. Ahora ejecuta Rescate.bat (o Rescate-como-admin.bat).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
