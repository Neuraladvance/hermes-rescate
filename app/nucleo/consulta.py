# -*- coding: utf-8 -*-
"""Consultas de solo lectura para el chat: lista blanca, sin efectos.

El modelo puede pedir «CONSULTA: <comando>» y el programa lo ejecuta SOLO si el
comando es de lectura. Se revisa cada tramo de la tubería por separado y se
rechaza cualquier verbo que cambie algo. Quien decide si se ejecuta es el técnico:
siempre se pide confirmación antes.
"""
import re

from . import util

LARGO_MAXIMO = 300
TIMEOUT = 40
SALIDA_MAXIMA = 4000

# Verbos que solo LEEN. Se comparan con el primer término de cada tramo del comando.
PERMITIDOS = [
    r"get-[a-z]+", r"test-[a-z]+", r"resolve-[a-z]+", r"measure-[a-z]+",
    r"select-[a-z]+", r"where-[a-z]+", r"sort-[a-z]+", r"format-[a-z]+",
    r"convertto-[a-z]+", r"out-string", r"out-host",
    r"ipconfig", r"ping", r"pathping", r"tracert", r"nslookup", r"arp",
    r"netstat", r"route\s+print", r"whoami", r"hostname", r"ver",
    r"systeminfo", r"tasklist", r"query", r"quser",
    r"sc\s+query", r"sc\s+qdescription", r"sc\s+qc",
    r"reg\s+query", r"schtasks\s+/query",
    r"netsh\s+wlan\s+show", r"netsh\s+interface\s+show", r"net\s+use",
    r"net\s+share", r"net\s+view", r"net\s+statistics",
    r"powercfg\s+(/query|/a|/batteryreport|/energy|/sleepstudy|/list|/devicequery|/requests|/availablesleepstates)",
    r"winget\s+(list|search|show)", r"wmic",
    r"dir", r"type", r"where", r"more", r"findstr", r"tree",
    r"chkdsk\s+[a-z]:\s*$", r"cipher\s+/c", r"fsutil\s+(volume|file)\s+\w+",
    r"bcdedit\s+/enum", r"vssadmin\s+list", r"wbadmin\s+get",
]

# Cualquier verbo o trozo que MODIFICA. Se comprueba sobre todo el comando.
PROHIBIDOS = [
    r"remove-", r"set-", r"new-", r"add-", r"start-", r"stop-", r"restart-",
    r"enable-", r"disable-", r"clear-", r"rename-", r"move-", r"copy-",
    r"invoke-", r"install-", r"uninstall-", r"register-", r"unregister-",
    r"out-file", r"export-", r"import-", r"update-", r"mount-", r"dismount-",
    r"\bdel\b", r"\berase\b", r"\brd\b", r"\brmdir\b", r"\bmkdir\b", r"\bmd\b",
    r"\bformat\s+[a-z]:", r"\bdiskpart\b", r"\bdiskperf\b", r"\bshutdown\b",
    r"\btaskkill\b", r"\bsc\s+(config|create|delete|start|stop)\b",
    r"\breg\s+(add|delete|import|copy)\b", r"\bnet\s+(user|localgroup|start|stop|accounts)\b",
    r"\bwinget\s+(install|uninstall|upgrade|source)\b",
    r"\b(sfc|dism|chkdsk\s+[a-z]:\s*/[fr])\b", r"\bbcdedit\s+/set\b",
    r"\bicacls\b", r"\btakeown\b", r"\bcacls\b", r"\bsetx\b",
    r"\bschtasks\s+/(create|delete|change|run|end)\b",
    r"\bpowercfg\s+/(setactive|hibernate|change|restoredefaultschemes)\b",
    r"\bnetsh\s+.*\b(set|add|delete)\b",
    r"\b(curl|wget|invoke-webrequest|invoke-restmethod|start-bitstransfer|bitsadmin)\b",
    r"\b(git|pip|npm|node|python|powershell|cmd|pwsh|bash|wsl|ssh|scp)\b",
    r"\b(sudo|runas)\b", r"\|.*\b(sh|bash)\b", r"\biex\b", r"\bforeach-object\s*\{",
    r"::", r"\$\(.*\)",
]


def _tramos(comando):
    """Parte por tuberías y punto y coma, devolviendo el primer término de cada tramo."""
    partes = re.split(r"\s*[|;]\s*", comando)
    return [p.strip() for p in partes if p.strip()]


def permitida(comando):
    """(True, "") si es de solo lectura, o (False, motivo)."""
    texto = (comando or "").strip()
    if not texto:
        return False, "comando vacío"
    if len(texto) > LARGO_MAXIMO:
        return False, "comando demasiado largo (máximo %d caracteres)" % LARGO_MAXIMO
    minusculas = texto.lower()
    for patron in PROHIBIDOS:
        if re.search(patron, minusculas):
            limpio = (patron.replace("\\b", "").replace("\\s", " ")
                      .replace(".*", "…").replace("(", "").replace(")", "")
                      .strip("|\\ "))
            return False, "contiene algo que modifica el equipo («%s»)" % limpio
    for tramo in _tramos(texto):
        if not any(re.match(patron, tramo, re.IGNORECASE) for patron in PERMITIDOS):
            return False, "no es una consulta de solo lectura: «%s»" % tramo[:60]
    return True, ""


def ejecutar(comando, timeout=TIMEOUT):
    """Ejecuta la consulta y devuelve (ok, salida_recortada)."""
    valido, motivo = permitida(comando)
    if not valido:
        return False, "No permitido: %s." % motivo
    codigo, salida, error = util.ps(comando, timeout=timeout)
    juntas = ((salida or "") + ("\n" + error if error else "")).strip()
    if not juntas:
        return codigo == 0, "(sin salida)"
    if len(juntas) > SALIDA_MAXIMA:
        juntas = juntas[:SALIDA_MAXIMA] + "\n… (recortado, %d caracteres más)" % (
            len(juntas) - SALIDA_MAXIMA)
    return codigo == 0, juntas


def sugerencias():
    """Ejemplos para el prompt del modelo."""
    return ("Get-Process <nombre>; Get-Service <nombre>; Get-EventLog -LogName System -Newest 20; "
            "ipconfig /all; netstat -ano; Get-NetTCPConnection; Get-CimInstance Win32_DiskDrive; "
            "tasklist; sc query <servicio>; powercfg /batteryreport; winget list")
