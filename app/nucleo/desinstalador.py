# -*- coding: utf-8 -*-
"""Desinstalación profunda: busca y limpia los restos que deja el desinstalador.

Imita lo que hace Revo Uninstaller: foto del sistema antes, desinstalación, foto
después y comparación. Lo que queda se clasifica y, si algo es compartido con otro
programa, se avisa y NO se toca por defecto. Los restos no se borran: se mueven a
una cuarentena y las claves de registro se exportan a un .reg antes de eliminarlas.
"""
import json
import os
import re
import shutil
import time

from . import util

# Carpetas y claves que nunca se tocan, aunque el nombre coincida.
INTOCABLES = {
    "common files", "windows", "microsoft", "package cache", "installer", "temp",
    "programs", "packages", "public", "desktop", "documents", "default",
    "microsoft shared", "windowsapps", "modifiablewindowsapps", "intel",
    "nvidia corporation", "amd", "realtek", "hp", "dell", "lenovo",
    "google", "mozilla", "adobe", "commonfiles", "system32", "syswow64",
}

# Palabras que no sirven para identificar un programa.
VACIAS = {"the", "and", "for", "pro", "home", "free", "version", "edition", "setup",
          "installer", "update", "updater", "client", "desktop", "app", "application",
          "microsoft", "windows", "corporation", "inc", "ltd", "gmbh", "software"}


def _normal(texto):
    return re.sub(r"[^a-z0-9]+", " ", (texto or "").lower()).strip()


def _tokens(*textos):
    """Palabras significativas de los nombres dados."""
    salida = set()
    for texto in textos:
        for palabra in _normal(texto).split():
            if len(palabra) > 2 and palabra not in VACIAS:
                salida.add(palabra)
    return salida


# ------------------------------------------------------------------ instantáneas
def instantanea(marca="antes", timeout=300):
    """Foto del sistema (programas, carpetas, servicios, tareas, claves)."""
    salida = os.path.join(util.ruta("logs", "tmp"), "restos_%s.json" % marca)
    os.makedirs(os.path.dirname(salida), exist_ok=True)
    if os.path.exists(salida):
        os.remove(salida)
    util.ps_archivo("restos.ps1", ["-Salida", salida, "-Marca", marca], timeout=timeout)
    if not os.path.exists(salida):
        raise RuntimeError("No se pudo hacer la foto del sistema (%s)" % marca)
    with open(salida, "r", encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------ búsqueda
def buscar_programa(termino):
    """Programas instalados que coincidan con el término (nombre, editor o id)."""
    foto = instantanea("buscar")
    buscado = _normal(termino)
    palabras = [p for p in buscado.split() if len(p) > 2]
    encontrados = []
    for programa in foto.get("programas") or []:
        nombre = _normal(programa.get("nombre"))
        editor = _normal(programa.get("editor"))
        if not nombre:
            continue
        if buscado and (buscado in nombre or nombre in buscado):
            encontrados.append((100, programa))
        elif palabras and all(p in nombre or p in editor for p in palabras):
            encontrados.append((70, programa))
    encontrados.sort(key=lambda x: -x[0])
    return [programa for _, programa in encontrados]


# ------------------------------------------------------------------ restos
def _ruta_relacionada(ruta, programa):
    """¿La carpeta tiene que ver con el programa? (nombre o ubicación declarada)"""
    nombre = _normal(os.path.basename(ruta))
    tokens = _tokens(programa.get("nombre"), programa.get("editor"))
    if not nombre:
        return False
    if any(t in nombre for t in tokens):
        return True
    ubicacion = _normal(programa.get("ubicacion"))
    if ubicacion and _normal(ruta).startswith(ubicacion):
        return True
    return False


def _compartida(ruta, foto, programa):
    """Programas que usan esa carpeta: si hay más de uno, es compartida."""
    ruta_n = _normal(ruta)
    usuarios = []
    for otro in foto.get("programas") or []:
        if otro is programa or otro.get("nombre") == programa.get("nombre"):
            continue
        ubicacion = _normal(otro.get("ubicacion"))
        if ubicacion and (ubicacion.startswith(ruta_n) or ruta_n.startswith(ubicacion)):
            usuarios.append(otro.get("nombre"))
    return usuarios


def restos(programa, antes, despues):
    """Compara las dos fotos y devuelve lo que ha quedado del programa.

    Cada elemento: {tipo, nombre, ruta, compartida (lista), intocable (bool)}.
    """
    salida = []
    carpetas_despues = {c.get("ruta") for c in despues.get("carpetas") or []}
    for carpeta in antes.get("carpetas") or []:
        ruta = carpeta.get("ruta") or ""
        if ruta not in carpetas_despues:      # ya no está: el desinstalador la borró
            continue
        if not _ruta_relacionada(ruta, programa):
            continue
        nombre = (carpeta.get("carpeta") or "").lower()
        salida.append({"tipo": "carpeta", "nombre": carpeta.get("carpeta"), "ruta": ruta,
                       "compartida": _compartida(ruta, despues, programa),
                       "intocable": nombre in INTOCABLES})

    claves_despues = {c.get("clave") for c in despues.get("software") or []}
    tokens = _tokens(programa.get("nombre"), programa.get("editor"))
    for clave in antes.get("software") or []:
        ruta = clave.get("clave") or ""
        if ruta not in claves_despues:
            continue
        nombre = _normal(clave.get("nombre"))
        if nombre and any(t in nombre for t in tokens):
            salida.append({"tipo": "registro", "nombre": clave.get("nombre"), "ruta": ruta,
                           "compartida": [], "intocable": nombre in INTOCABLES})

    for servicio in antes.get("servicios") or []:
        texto = _normal(servicio.get("nombre")) + " " + _normal(servicio.get("visible"))
        if any(t in texto for t in tokens):
            salida.append({"tipo": "servicio", "nombre": servicio.get("visible") or servicio.get("nombre"),
                           "ruta": servicio.get("nombre"), "compartida": [], "intocable": False})

    for tarea in antes.get("tareas") or []:
        texto = _normal(tarea.get("ruta"))
        if any(t in texto for t in tokens):
            salida.append({"tipo": "tarea", "nombre": tarea.get("ruta"), "ruta": tarea.get("ruta"),
                           "compartida": [], "intocable": False})
    return salida


def tamanos(elementos, maximo=12):
    """Rellena el tamaño de las carpetas (las primeras, para no eternizarse)."""
    hechas = 0
    for elemento in elementos:
        if elemento["tipo"] != "carpeta":
            continue
        if hechas >= maximo:
            elemento["mb"] = None
            continue
        try:
            elemento["mb"] = round(util.tamano_carpeta(elemento["ruta"], maximo_seg=12) / 1048576.0, 1)
        except Exception:
            elemento["mb"] = None
        hechas += 1
    return elementos


# ------------------------------------------------------------------ limpieza
def cuarentena(elementos, aviso=None):
    """Mueve carpetas a una cuarentena y exporta las claves. Devuelve (hechos, fallos)."""
    aviso = aviso or (lambda *_: None)
    sello = time.strftime("%Y%m%d-%H%M%S")
    destino = os.path.join(util.ruta("logs"), "cuarentena", sello)
    os.makedirs(destino, exist_ok=True)
    hechos, fallos = [], []
    for elemento in elementos:
        tipo, ruta = elemento["tipo"], elemento.get("ruta") or ""
        try:
            if tipo == "carpeta":
                if not os.path.isdir(ruta):
                    continue
                objetivo = os.path.join(destino, os.path.basename(ruta.rstrip("\\/")))
                if os.path.exists(objetivo):
                    objetivo = objetivo + "_" + str(int(time.time()))
                aviso("Moviendo a cuarentena: %s" % ruta)
                shutil.move(ruta, objetivo)
                hechos.append("%s → cuarentena" % ruta)
            elif tipo == "registro":
                nombre_reg = os.path.join(destino, "registro_%d.reg" % (len(hechos) + 1))
                aviso("Guardando clave antes de borrar: %s" % elemento.get("nombre"))
                util.ps('reg export "%s" "%s" /y' % (ruta.replace("HKEY_LOCAL_MACHINE", "HKLM")
                                                     .replace("HKEY_CURRENT_USER", "HKCU"), nombre_reg),
                        timeout=60)
                util.ps('Remove-Item -LiteralPath "%s" -Recurse -Force' % ruta, timeout=60)
                hechos.append("%s (copia en %s)" % (elemento.get("nombre"), os.path.basename(nombre_reg)))
            elif tipo == "servicio":
                util.ps('sc.exe delete "%s"' % ruta, timeout=60)
                hechos.append("servicio %s eliminado" % ruta)
            elif tipo == "tarea":
                util.ps('Unregister-ScheduledTask -TaskName "%s" -Confirm:$false' % ruta, timeout=60)
                hechos.append("tarea %s eliminada" % ruta)
        except Exception as exc:
            fallos.append("%s: %s" % (elemento.get("nombre"), exc))
    return hechos, fallos
