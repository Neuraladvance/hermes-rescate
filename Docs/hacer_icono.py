# -*- coding: utf-8 -*-
"""Genera icono.ico de HERMES-RESCATE a partir de Docs/icono.html.

Cada tamano se dibuja de verdad a su resolucion (Chrome headless), no se reescala,
para que el icono se vea nitido a 16, 32 y 48 px en el Explorador de Windows.

Uso:  runtime\\python\\python.exe Docs\\hacer_icono.py
"""
import os
import shutil
import struct
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(RAIZ, "Docs", "icono.html")
TEMPORAL = os.path.join(RAIZ, "Docs", "_iconos")
DESTINO = os.path.join(RAIZ, "icono.ico")
TAMANOS = (16, 32, 48, 256)

CANDIDATOS_CHROME = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def navegador():
    for ruta in CANDIDATOS_CHROME:
        if os.path.exists(ruta):
            return ruta
    encontrado = shutil.which("chrome") or shutil.which("msedge")
    return encontrado


def renderizar(navegador_ruta):
    os.makedirs(TEMPORAL, exist_ok=True)
    imagenes = []
    for tamano in TAMANOS:
        salida = os.path.join(TEMPORAL, "icono%d.png" % tamano)
        if os.path.exists(salida):
            os.remove(salida)
        argumentos = [
            navegador_ruta, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--default-background-color=00000000", "--force-device-scale-factor=1",
            "--window-size=%d,%d" % (tamano, tamano),
            "--screenshot=" + salida,
            "file:///" + HTML.replace("\\", "/") + "?t=%d" % tamano,
        ]
        subprocess.run(argumentos, capture_output=True, timeout=90)
        if not os.path.exists(salida):
            raise RuntimeError("No se pudo renderizar el icono de %d px" % tamano)
        with open(salida, "rb") as f:
            datos = f.read()
        if datos[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("La captura de %d px no es un PNG" % tamano)
        ancho, alto = struct.unpack(">II", datos[16:24])
        imagenes.append((tamano, ancho, alto, datos))
        print("  %3d px  -> %5d bytes" % (tamano, len(datos)))
    return imagenes


def construir_ico(imagenes, ruta):
    """ICO con entradas PNG (soportado por Windows Vista y posteriores)."""
    cabecera = struct.pack("<HHH", 0, 1, len(imagenes))
    desplazamiento = 6 + 16 * len(imagenes)
    entradas, cuerpos = b"", b""
    for tamano, ancho, alto, datos in imagenes:
        campo = 0 if tamano >= 256 else tamano
        entradas += struct.pack("<BBBBHHII", campo, campo, 0, 0, 1, 32, len(datos), desplazamiento)
        desplazamiento += len(datos)
        cuerpos += datos
    with open(ruta, "wb") as f:
        f.write(cabecera + entradas + cuerpos)


def main():
    navegador_ruta = navegador()
    if not navegador_ruta:
        print("ERROR: no encuentro Chrome ni Edge para renderizar el icono.")
        return 1
    print("Navegador: %s" % navegador_ruta)
    imagenes = renderizar(navegador_ruta)
    construir_ico(imagenes, DESTINO)
    print("\nIcono escrito: %s (%d bytes, %d tamanos)"
          % (DESTINO, os.path.getsize(DESTINO), len(imagenes)))
    shutil.rmtree(TEMPORAL, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
