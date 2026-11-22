# -*- coding: utf-8 -*-
"""Cifrado de secretos con contraseña: scrypt + ChaCha20 + HMAC-SHA256.

Solo biblioteca estándar (un USB no puede depender de pip). ChaCha20 es el cifrador
de flujo del RFC 8439; va autenticado con HMAC-SHA256 (cifrar-y-luego-autenticar),
así que una contraseña incorrecta o un fichero manipulado se detectan en vez de
devolver basura.

Formato del fichero (JSON de una línea, texto plano apto para FAT32)?
    {
      "formato": "rescate-secreto/1",
      "kdf": "scrypt",
      "n": 16384, "r": 8, "p": 1, "sal": "<b64>",
      "nonce": "<b64>", "mac": "<b64>", "ct": "<b64>"
    }
"""
import base64
import hashlib
import hmac
import json
import os
import struct

MASCARA = 0xFFFFFFFF
CONSTANTES = (0x61707865, 0x3320646E, 0x79622D32, 0x6B206574)  # "expand 32-byte k"


def _rotar(v, n):
    return ((v << n) & MASCARA) | (v >> (32 - n))


def _ronda(x, a, b, c, d):
    x[a] = (x[a] + x[b]) & MASCARA
    x[d] = _rotar(x[d] ^ x[a], 16)
    x[c] = (x[c] + x[d]) & MASCARA
    x[b] = _rotar(x[b] ^ x[c], 12)
    x[a] = (x[a] + x[b]) & MASCARA
    x[d] = _rotar(x[d] ^ x[a], 8)
    x[c] = (x[c] + x[d]) & MASCARA
    x[b] = _rotar(x[b] ^ x[c], 7)


def _bloque(clave, contador, nonce):
    """Un bloque de 64 bytes del flujo ChaCha20 (RFC 8439, sección 2.3)."""
    if len(clave) != 32:
        raise ValueError("la clave ChaCha20 debe tener 32 bytes")
    if len(nonce) != 12:
        raise ValueError("el nonce ChaCha20 debe tener 12 bytes")
    inicial = list(CONSTANTES) + list(struct.unpack("<8I", clave))
    inicial += [contador & MASCARA]
    inicial += list(struct.unpack("<3I", nonce))
    x = list(inicial)
    for _ in range(10):  # 20 rondas = 10 dobles rondas
        _ronda(x, 0, 4, 8, 12)
        _ronda(x, 1, 5, 9, 13)
        _ronda(x, 2, 6, 10, 14)
        _ronda(x, 3, 7, 11, 15)
        _ronda(x, 0, 5, 10, 15)
        _ronda(x, 1, 6, 11, 12)
        _ronda(x, 2, 7, 8, 13)
        _ronda(x, 3, 4, 9, 14)
    return struct.pack("<16I", *[(x[i] + inicial[i]) & MASCARA for i in range(16)])


def cha20(clave, nonce, datos, contador=1):
    """Cifra (o descifra: es simétrico) con ChaCha20."""
    salida = bytearray()
    for posicion in range(0, len(datos), 64):
        trozo = datos[posicion:posicion + 64]
        flujo = _bloque(clave, contador, nonce)
        salida.extend(bytes(a ^ b for a, b in zip(trozo, flujo)))
        contador += 1
    return bytes(salida)


def _derivar(password, sal, n, r, p):
    try:
        material = hashlib.scrypt(password, salt=sal, n=n, r=r, p=p, dklen=64,
                                  maxmem=256 * 1024 * 1024)
    except (ValueError, MemoryError):
        raise ValueError("no se pudo derivar la clave (parámetros scrypt no válidos)")
    return material[:32], material[32:]


def cifrar(texto, password, n=16384, r=8, p=1):
    """Devuelve el texto cifrado (JSON) listo para guardar en disco."""
    if not password:
        raise ValueError("hace falta una contraseña")
    if isinstance(texto, str):
        texto = texto.encode("utf-8")
    sal, nonce = os.urandom(16), os.urandom(12)
    clave_cifrado, clave_mac = _derivar(password.encode("utf-8"), sal, n, r, p)
    criptograma = cha20(clave_cifrado, nonce, texto, 1)
    cabecera = b"rescate-secreto/1|%d|%d|%d|" % (n, r, p) + sal + nonce
    mac = hmac.new(clave_mac, cabecera + criptograma, hashlib.sha256).digest()
    return json.dumps({
        "formato": "rescate-secreto/1",
        "kdf": "scrypt",
        "n": n, "r": r, "p": p,
        "sal": base64.b64encode(sal).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "mac": base64.b64encode(mac).decode(),
        "ct": base64.b64encode(criptograma).decode(),
    }, ensure_ascii=False)


def descifrar(sobre, password):
    """Devuelve el texto claro. ValueError si la contraseña no es o está manipulado."""
    if isinstance(sobre, (bytes, bytearray)):
        sobre = sobre.decode("utf-8")
    try:
        datos = json.loads(sobre)
    except ValueError:
        raise ValueError("el fichero cifrado no tiene el formato esperado")
    if datos.get("formato") != "rescate-secreto/1" or datos.get("kdf") != "scrypt":
        raise ValueError("versión de fichero cifrado no soportada")
    sal = base64.b64decode(datos["sal"])
    nonce = base64.b64decode(datos["nonce"])
    mac_esperado = base64.b64decode(datos["mac"])
    criptograma = base64.b64decode(datos["ct"])
    n, r, p = int(datos["n"]), int(datos["r"]), int(datos["p"])
    clave_cifrado, clave_mac = _derivar(password.encode("utf-8"), sal, n, r, p)
    cabecera = b"rescate-secreto/1|%d|%d|%d|" % (n, r, p) + sal + nonce
    if not hmac.compare_digest(
            hmac.new(clave_mac, cabecera + criptograma, hashlib.sha256).digest(),
            mac_esperado):
        raise ValueError("contraseña incorrecta o fichero manipulado")
    return cha20(clave_cifrado, nonce, criptograma, 1).decode("utf-8")


# ------------------------------------------------------------------ autocontrol
def _autoprueba():
    """Vectores oficiales del RFC 8439; si fallan, no se usa el cifrado."""
    clave = bytes(range(32))
    nonce = bytes.fromhex("000000090000004a00000000")
    esperado = ("10f1e7e4d13b5915500fdd1fa32071c4"
                "c7d1f4c733c068030422aa9ac3d46c4e"
                "d2826446079faa0914c2d705d98b02a2"
                "b5129cd1de164eb9cbd083e8a2503c4e")
    obtenido = _bloque(clave, 1, nonce).hex()
    if obtenido != esperado:
        raise AssertionError("ChaCha20 no coincide con el RFC 8439")
    # RFC 8439 §2.4.2: cifrado de "Ladies and Gentlemen of the class of '99..."
    # Ojo: ese vector usa OTRO nonce (000000000000004a00000000), no el del bloque.
    nonce_cifrado = bytes.fromhex("000000000000004a00000000")
    claro = (b"Ladies and Gentlemen of the class of '99: If I could offer you "
             b"only one tip for the future, sunscreen would be it.")
    cifrado = cha20(clave, nonce_cifrado, claro, 1)
    if cifrado.hex()[:32] != "6e2e359a2568f98041ba0728dd0d6981":
        raise AssertionError("el cifrado ChaCha20 no coincide con el RFC 8439 (§2.4.2)")
    # Ida y vuelta con contraseña.
    for prueba in ("sk-or-v1-ejemplo-de-clave", "ñandú€ カ", ""):
        if descifrar(cifrar(prueba, "contraseña-de-prueba"), "contraseña-de-prueba") != prueba:
            raise AssertionError("fallo de ida y vuelta")
    # Contraseña incorrecta debe fallar, no devolver basura.
    try:
        descifrar(cifrar("secreto", "buena"), "mala")
    except ValueError:
        pass
    else:
        raise AssertionError("una contraseña incorrecta NO fue rechazada")
    return True


if __name__ == "__main__":
    print("autoprueba:", "OK (RFC 8439 + ida y vuelta + rechazo de contraseña)"
          if _autoprueba() else "FALLO")
