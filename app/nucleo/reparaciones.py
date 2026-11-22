# -*- coding: utf-8 -*-
"""Catalogo de reparaciones reales, con nivel de riesgo y verificacion posterior.

Niveles: 1 = seguro (limpia o restaura valores por defecto), 2 = cambia
configuracion del sistema (siempre con confirmacion), 3 = manual: el programa NO
lo ejecuta, solo da las instrucciones.
"""
import json
import os
import time

from . import util

NIVELES = {1: "Seguro", 2: "Cambia configuración", 3: "Manual"}

CATALOGO = {}


def _reg(rid, nombre, nivel, que, cuando, accion, admin=False, red=False,
         categoria="Sistema", verifica=None, lento=False):
    CATALOGO[rid] = {
        "id": rid, "nombre": nombre, "nivel": nivel, "que": que, "cuando": cuando,
        "accion": accion, "admin": admin, "red": red, "categoria": categoria,
        "verifica": verifica, "lento": lento,
    }


def _ps(script, timeout=900):
    rc, out, err = util.ps(script, timeout=timeout)
    return rc, (out or "").strip(), (err or "").strip()


def _cola(texto, n=600):
    texto = (texto or "").strip()
    return texto[-n:] if len(texto) > n else texto


# ====================================================================== limpieza
def _limpiar_temp(aviso):
    aviso("Borrando temporales del usuario y de Windows...")
    antes, _ = util.tamano_carpeta(os.environ.get("TEMP", ""), maximo_seg=20)
    antes_w, _ = util.tamano_carpeta(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Temp"),
                                     maximo_seg=20)
    script = r'''
$n = 0; $bloqueados = 0
foreach ($d in @($env:TEMP, "$env:SystemRoot\Temp")) {
    if (-not (Test-Path -LiteralPath $d)) { continue }
    Get-ChildItem -LiteralPath $d -Force -ErrorAction SilentlyContinue | ForEach-Object {
        try { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop; $n++ }
        catch { $bloqueados++ }
    }
}
"eliminados=$n bloqueados=$bloqueados"
'''
    rc, out, err = _ps(script, timeout=300)
    despues, _ = util.tamano_carpeta(os.environ.get("TEMP", ""), maximo_seg=20)
    despues_w, _ = util.tamano_carpeta(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Temp"),
                                       maximo_seg=20)
    liberado = (antes + antes_w) - (despues + despues_w)
    return True, ("Liberados %s. Los ficheros en uso se quedan (se limpian al reiniciar)."
                  % util.humano(liberado)), (out or err)


def _vaciar_papelera(aviso):
    aviso("Vaciando la papelera de reciclaje...")
    antes = 0
    for unidad in ("C:", "D:", "E:"):
        if os.path.exists(unidad + "\\"):
            tam, _ = util.tamano_carpeta(unidad + "\\$Recycle.Bin", maximo_seg=15)
            antes += tam
    script = r'''
$ErrorActionPreference = 'SilentlyContinue'
Clear-RecycleBin -Force -ErrorAction SilentlyContinue
if ($LASTEXITCODE -ne 0) { cmd /c "rd /s /q %SystemDrive%\$Recycle.Bin" 2>$null }
"papelera vaciada"
'''
    rc, out, err = _ps(script, timeout=300)
    despues = 0
    for unidad in ("C:", "D:", "E:"):
        if os.path.exists(unidad + "\\"):
            tam, _ = util.tamano_carpeta(unidad + "\\$Recycle.Bin", maximo_seg=10)
            despues += tam
    return True, "Papelera vaciada: %s liberados." % util.humano(max(0, antes - despues)), (out or err)


def _limpiar_wu(aviso):
    aviso("Vaciando la caché de Windows Update...")
    ruta = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "SoftwareDistribution", "Download")
    antes, _ = util.tamano_carpeta(ruta, maximo_seg=20)
    script = r'''
$ErrorActionPreference = 'SilentlyContinue'
Stop-Service wuauserv -Force
Stop-Service bits -Force
Start-Sleep -Seconds 2
$d = "$env:SystemRoot\SoftwareDistribution\Download"
if (Test-Path $d) { Get-ChildItem -LiteralPath $d -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue }
Start-Service bits
Start-Service wuauserv
"servicios reiniciados"
'''
    rc, out, err = _ps(script, timeout=300)
    despues, _ = util.tamano_carpeta(ruta, maximo_seg=15)
    return True, "%s liberados de caché de actualizaciones." % util.humano(max(0, antes - despues)), (out or err)


def _limpiar_prefetch(aviso):
    aviso("Borrando Prefetch (Windows lo regenera)...")
    script = r'''
$n = 0
Get-ChildItem "$env:SystemRoot\Prefetch\*.pf" -ErrorAction SilentlyContinue | ForEach-Object {
    try { Remove-Item $_.FullName -Force -ErrorAction Stop; $n++ } catch { }
}
"eliminados=$n"
'''
    rc, out, err = _ps(script, timeout=180)
    return True, "Prefetch limpiado: %s" % (out or "hecho"), (out or "")


def _limpiar_volcados(aviso):
    aviso("Borrando volcados de fallo...")
    script = r'''
$n = 0
foreach ($p in @("$env:SystemRoot\Minidump\*", "$env:SystemRoot\MEMORY.DMP", "$env:SystemRoot\LiveKernelReports\*")) {
    Get-Item $p -ErrorAction SilentlyContinue | ForEach-Object {
        try { Remove-Item $_.FullName -Recurse -Force -ErrorAction Stop; $n++ } catch { }
    }
}
"eliminados=$n"
'''
    rc, out, err = _ps(script, timeout=180)
    return True, "Volcados de fallo eliminados: %s" % (out or "hecho"), (out or "")


def _optimizar_winsxs(aviso):
    aviso("Compactando el almacén de componentes (puede tardar 10-20 minutos)...")
    rc, out, err = util.ejecutar(["dism.exe", "/Online", "/Cleanup-Image", "/StartComponentCleanup"],
                                 timeout=2400)
    ok = "correctamente" in (out + err).lower() or "completed successfully" in (out + err).lower()
    return ok, "Limpieza del almacén de componentes terminada." if ok else "DISM no confirmó la limpieza.", _cola(out + err)


# ====================================================================== integridad
def _dism_check(aviso):
    aviso("Comprobando el almacén de componentes...")
    rc, out, err = util.ejecutar(["dism.exe", "/Online", "/Cleanup-Image", "/CheckHealth"], timeout=600)
    texto = (out or "") + (err or "")
    ok = "No se detectaron" in texto or "No component store corruption" in texto or "no se ha detectado" in texto.lower()
    dañado = "reparable" in texto.lower() or "repairable" in texto.lower()
    if ok:
        return True, "Almacén de componentes correcto.", _cola(texto)
    if dañado:
        return False, "Hay daños en la imagen del sistema: se puede reparar con «Reparar imagen del sistema (DISM RestoreHealth)».", _cola(texto)
    return False, "DISM terminó con código %s." % rc, _cola(texto)


def _dism_restore(aviso):
    aviso("Descargando y reparando la imagen del sistema (puede tardar 10-30 minutos)...")
    rc, out, err = util.ejecutar(["dism.exe", "/Online", "/Cleanup-Image", "/RestoreHealth"], timeout=3600)
    texto = (out or "") + (err or "")
    ok = "correctamente" in texto.lower() or "completed successfully" in texto.lower()
    return ok, ("Imagen del sistema reparada." if ok else
                "DISM no pudo reparar la imagen (necesita conexión a internet o medios de instalación)."), _cola(texto)


def _sfc(aviso):
    aviso("Comprobando archivos de sistema con SFC (5-15 minutos)...")
    rc, out, err = util.ejecutar(["sfc.exe", "/scannow"], timeout=3600)
    texto = (out or "") + (err or "")
    limpio = "no ha encontrado ninguna infracci" in texto.lower() or "did not find any integrity" in texto.lower()
    reparado = "reparó correctamente" in texto.lower() or "successfully repaired" in texto.lower()
    if limpio:
        return True, "SFC no encontró archivos dañados.", _cola(texto)
    if reparado:
        return True, "SFC encontró y reparó archivos dañados.", _cola(texto)
    return False, "SFC no pudo reparar todo: revisar CBS.log o ejecutar DISM.", _cola(texto)


def _chkdsk_scan(aviso):
    aviso("Analizando el disco (sin modificar nada)...")
    rc, out, err = util.ejecutar(["chkdsk.exe", os.environ.get("SystemDrive", "C:") + "\\", "/scan"],
                                 timeout=3600)
    texto = (out or "") + (err or "")
    ok = "no se han encontrado problemas" in texto.lower() or "no problems" in texto.lower()
    return ok, ("Disco sin errores en el análisis." if ok else
                "CHKDSK encontró problemas: para repararlos hace falta un análisis con reinicio."), _cola(texto, 900)


# ====================================================================== red
def _flush_dns(aviso):
    aviso("Vaciando la caché de DNS...")
    rc, out, err = util.ejecutar(["ipconfig.exe", "/flushdns"], timeout=60)
    rc2, salida, _ = util.ejecutar(["nslookup", "www.microsoft.com"], timeout=45)
    resuelve = "Address" in salida or "Dirección" in salida or "Name:" in salida
    return resuelve, ("DNS resolviendo correctamente tras vaciar la caché." if resuelve
                      else "Caché vaciada, pero sigue sin resolver nombres: puede ser el DNS del router."), (out or "") + "\n" + (salida or "")[:400]


def _renovar_ip(aviso):
    aviso("Renovando la dirección IP...")
    util.ejecutar(["ipconfig.exe", "/release"], timeout=90)
    util.ejecutar(["ipconfig.exe", "/renew"], timeout=120)
    rc, out, _ = util.ejecutar(["ipconfig.exe", "/all"], timeout=60)
    tiene_ip = "IPv4" in (out or "")
    return tiene_ip, ("IP renovada." if tiene_ip else "No se obtuvo IP: revisar cable/WiFi o el DHCP del router."), _cola(out)


def _reset_winsock(aviso):
    aviso("Restableciendo Winsock...")
    rc, out, err = util.ejecutar(["netsh.exe", "winsock", "reset"], timeout=120)
    return rc == 0, "Winsock restablecido. Necesita reiniciar para aplicarse.", _cola(out + err)


def _reset_tcpip(aviso):
    aviso("Restableciendo la pila TCP/IP...")
    rc, out, err = util.ejecutar(["netsh.exe", "int", "ip", "reset"], timeout=180)
    return rc == 0, "Pila TCP/IP restablecida. Necesita reiniciar.", _cola(out + err)


def _reset_proxy(aviso):
    aviso("Quitando el proxy del sistema...")
    rc, out, err = _ps(r'''
netsh winhttp reset proxy | Out-Null
$k = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
Set-ItemProperty $k -Name ProxyEnable -Value 0 -ErrorAction SilentlyContinue
Remove-ItemProperty $k -Name ProxyServer -ErrorAction SilentlyContinue
"proxy eliminado"
''', timeout=120)
    return True, "Proxy del sistema eliminado.", _cola(out + err)


# ====================================================================== shell / impresion
def _reiniciar_explorer(aviso):
    aviso("Reiniciando el Explorador de Windows...")
    script = r'''
Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
if (-not (Get-Process explorer -ErrorAction SilentlyContinue)) { Start-Process explorer.exe }
Start-Sleep -Seconds 1
if (Get-Process explorer -ErrorAction SilentlyContinue) { "explorer activo" } else { "explorer NO arrancó" }
'''
    rc, out, err = _ps(script, timeout=120)
    return "explorer activo" in (out or ""), ("Explorador reiniciado." if "explorer activo" in (out or "")
                                              else "El Explorador no volvió a arrancar: cerrar sesión y entrar."), _cola(out + err)


def _cache_iconos(aviso):
    aviso("Reconstruyendo la caché de iconos...")
    script = r'''
Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$base = "$env:LOCALAPPDATA\Microsoft\Windows\Explorer"
Get-ChildItem "$base\iconcache*" -Force -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
Get-ChildItem "$base\thumbcache*" -Force -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
Start-Process explorer.exe
"cache borrada"
'''
    rc, out, err = _ps(script, timeout=120)
    return True, "Caché de iconos reconstruida.", _cola(out + err)


def _spooler(aviso):
    aviso("Reiniciando la cola de impresión...")
    script = r'''
Stop-Service spooler -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Remove-Item "$env:SystemRoot\System32\spool\PRINTERS\*" -Force -Recurse -ErrorAction SilentlyContinue
Start-Service spooler
Start-Sleep -Seconds 1
$s = Get-Service spooler
"spooler=" + $s.Status
'''
    rc, out, err = _ps(script, timeout=180)
    ok = "Running" in (out or "")
    return ok, ("Cola de impresión reiniciada." if ok else
                "El servicio de impresión no arrancó: comprobar que no falten controladores."), _cola(out + err)


def _store_reregistrar(aviso):
    aviso("Re-registrando las aplicaciones de la Tienda (2-5 minutos)...")
    script = r'''
$n = 0; $e = 0
Get-AppXPackage -AllUsers -ErrorAction SilentlyContinue | ForEach-Object {
    $m = Join-Path $_.InstallLocation 'AppXManifest.xml'
    if (Test-Path $m) {
        try { Add-AppxPackage -DisableDevelopmentMode -Register $m -ErrorAction Stop; $n++ } catch { $e++ }
    }
}
"registradas=$n errores=$e"
'''
    rc, out, err = _ps(script, timeout=1800)
    return "registradas=" in (out or ""), "Aplicaciones de la Tienda re-registradas: %s" % (out or ""), _cola(out + err)


def _wu_reset(aviso):
    aviso("Restableciendo los componentes de Windows Update (tarda unos minutos)...")
    script = r'''
$ErrorActionPreference = 'SilentlyContinue'
Stop-Service wuauserv -Force; Stop-Service cryptSvc -Force; Stop-Service bits -Force; Stop-Service msiserver -Force
Start-Sleep -Seconds 3
Rename-Item "$env:SystemRoot\SoftwareDistribution" "SoftwareDistribution.old" -ErrorAction SilentlyContinue
Rename-Item "$env:SystemRoot\System32\catroot2" "catroot2.old" -ErrorAction SilentlyContinue
$dlls = @('atl.dll','urlmon.dll','mshtml.dll','shdocvw.dll','browseui.dll','jscript.dll','vbscript.dll',
          'scrrun.dll','msxml.dll','msxml3.dll','msxml6.dll','actxprxy.dll','softpub.dll','wintrust.dll',
          'dssenh.dll','rsaenh.dll','gpkcsp.dll','sccbase.dll','slbcsp.dll','cryptdlg.dll','oleaut32.dll',
          'ole32.dll','shell32.dll','initpki.dll','wuapi.dll','wuaueng.dll','wuaueng1.dll','wucltui.dll',
          'wups.dll','wups2.dll','wuweb.dll','qmgr.dll','qmgrprxy.dll','wucltux.dll','muweb.dll','wuwebv.dll')
foreach ($d in $dlls) { $p = Join-Path "$env:SystemRoot\System32" $d; if (Test-Path $p) { regsvr32.exe /s $p } }
Start-Service cryptSvc; Start-Service bits; Start-Service wuauserv
"restablecido"
'''
    rc, out, err = _ps(script, timeout=1200)
    ok = "restablecido" in (out or "")
    return ok, ("Componentes de Windows Update restablecidos. Reiniciar y volver a buscar actualizaciones."
                if ok else "El restablecimiento no terminó bien."), _cola(out + err)


# ====================================================================== seguridad
def _activar_defender(aviso):
    aviso("Reactivando el antivirus de Windows...")
    script = r'''
Set-MpPreference -DisableRealtimeMonitoring $false -ErrorAction SilentlyContinue
Set-MpPreference -DisableBehaviorMonitoring $false -ErrorAction SilentlyContinue
Set-MpPreference -DisableIOAVProtection $false -ErrorAction SilentlyContinue
Set-Service WinDefend -StartupType Automatic -ErrorAction SilentlyContinue
Start-Service WinDefend -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$s = Get-MpComputerStatus
"activo=" + $s.AntivirusEnabled + " tiempo_real=" + $s.RealTimeProtectionEnabled
'''
    rc, out, err = _ps(script, timeout=300)
    ok = "tiempo_real=True" in (out or "")
    return ok, ("Antivirus y protección en tiempo real activados." if ok else
                "No se pudo confirmar: puede haber una política o otro antivirus que lo bloquee."), _cola(out + err)


def _defender_firmas(aviso):
    aviso("Actualizando las firmas del antivirus...")
    script = r'''
$mp = Join-Path $env:ProgramFiles 'Windows Defender\MpCmdRun.exe'
if (Test-Path $mp) { & $mp -SignatureUpdate | Out-String } else { 'MpCmdRun no encontrado' }
$s = Get-MpComputerStatus
"firmas=" + $s.AntivirusSignatureVersion + " dias=" + $s.AntivirusSignatureAge
'''
    rc, out, err = _ps(script, timeout=900)
    ok = "dias=0" in (out or "") or "dias=1" in (out or "")
    return ok, ("Firmas al día." if ok else "Se intentó actualizar; comprobar la fecha de las firmas."), _cola(out + err)


def _defender_escaneo(aviso):
    aviso("Ejecutando análisis rápido del antivirus (5-20 minutos)...")
    script = r'''
Start-MpScan -ScanType QuickScan
$s = Get-MpComputerStatus
"ultimo_analisis_dias=" + $s.QuickScanAge
'''
    rc, out, err = _ps(script, timeout=3600)
    return "ultimo_analisis_dias=0" in (out or ""), "Análisis rápido terminado.", _cola(out + err)


def _activar_firewall(aviso):
    aviso("Activando el cortafuegos en todos los perfiles...")
    script = r'''
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled True -ErrorAction SilentlyContinue
(Get-NetFirewallProfile | ForEach-Object { "$($_.Name)=$($_.Enabled)" }) -join ' '
'''
    rc, out, err = _ps(script, timeout=180)
    ok = out and "=False" not in (out or "")
    return bool(ok), ("Cortafuegos activo en todos los perfiles." if ok
                      else "No se pudo activar en todos los perfiles: revisar políticas."), _cola(out + err)


# ====================================================================== mantenimiento
def _sincronizar_hora(aviso):
    aviso("Sincronizando la hora con internet...")
    script = r'''
Restart-Service w32time -Force -ErrorAction SilentlyContinue
w32tm /resync /force | Out-String
w32tm /query /status | Select-Object -First 4 | Out-String
'''
    rc, out, err = _ps(script, timeout=180)
    ok = "correct" in (out or "").lower() or "completado" in (out or "").lower()
    return ok, ("Hora sincronizada." if ok else "No se pudo sincronizar (puede requerir salida UDP 123)."), _cola(out + err)


def _rescan_dispositivos(aviso):
    aviso("Buscando hardware y controladores...")
    rc, out, err = util.ejecutar(["pnputil.exe", "/scan-devices"], timeout=180)
    time.sleep(2)
    rc2, salida, _ = _ps(r'''
$e = @(Get-PnpDevice | Where-Object { $_.Status -eq 'Error' })
"con_error=" + $e.Count
''', timeout=180)
    ok = "con_error=0" in (salida or "")
    return ok, ("Sin dispositivos con error tras el escaneo." if ok
                else "Siguen quedando dispositivos con error: falta el controlador del fabricante."), _cola((out or "") + " " + (salida or ""))


def _habilitar_winre(aviso):
    aviso("Habilitando el entorno de recuperación...")
    rc, out, err = util.ejecutar(["reagentc.exe", "/enable"], timeout=300)
    rc2, salida, _ = util.ejecutar(["reagentc.exe", "/info"], timeout=120)
    ok = "Habilitado" in (salida or "") or "Enabled" in (salida or "")
    return ok, ("Entorno de recuperación habilitado." if ok else "No se pudo habilitar (suele faltar la partición de recuperación)."), _cola((out or "") + " " + (salida or ""))


def _activar_restauracion(aviso):
    aviso("Activando la restauración del sistema...")
    script = r'''
Enable-ComputerRestore -Drive "$env:SystemDrive\" -ErrorAction SilentlyContinue
Set-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore' -Name DisableSR -Value 0 -ErrorAction SilentlyContinue
vssadmin resize shadowstorage /for=C: /on=C: /maxsize=10% 2>&1 | Out-String
$p = @(Get-ComputerRestorePoint)
"puntos=" + $p.Count
'''
    rc, out, err = _ps(script, timeout=300)
    ok = "puntos=" in (out or "")
    return ok, "Restauración del sistema activada (10% del disco para copias).", _cola(out + err)


def _punto_restauracion(aviso):
    aviso("Creando un punto de restauración...")
    script = r'''
$ErrorActionPreference = 'SilentlyContinue'
Enable-ComputerRestore -Drive "$env:SystemDrive\" -ErrorAction SilentlyContinue
Checkpoint-Computer -Description 'HERMES-RESCATE' -RestorePointType MODIFY_SETTINGS -ErrorAction SilentlyContinue
$p = @(Get-ComputerRestorePoint | Where-Object { $_.Description -like '*HERMES*' })
"creados=" + $p.Count
'''
    rc, out, err = _ps(script, timeout=900)
    ok = "creados=" in (out or "") and "creados=0" not in (out or "")
    return ok, ("Punto de restauración creado." if ok else
                "No se creó: Windows limita a un punto por día (o la restauración está apagada)."), _cola(out + err)


def _desactivar_inicio_rapido(aviso):
    aviso("Desactivando el inicio rápido...")
    script = r'''
Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -Name HiberbootEnabled -Value 0
$v = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -Name HiberbootEnabled).HiberbootEnabled
"inicio_rapido=" + $v
'''
    rc, out, err = _ps(script, timeout=120)
    ok = "inicio_rapido=0" in (out or "")
    return ok, "Inicio rápido desactivado: el apagado será completo.", _cola(out + err)


def _restaurar_energia(aviso):
    aviso("Restaurando los planes de energía por defecto...")
    rc, out, err = util.ejecutar(["powercfg.exe", "-restoredefaultschemes"], timeout=120)
    ok = rc == 0
    return ok, ("Planes de energía restaurados." if ok else "No se pudieron restaurar."), _cola(out + err)


def _limpiar_hosts(aviso):
    aviso("Guardando copia del fichero hosts y restaurando el original...")
    ruta = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "drivers", "etc", "hosts")
    copia = ruta + ".hermes-rescate-" + time.strftime("%Y%m%d-%H%M%S")
    script = r'''
$h = "$env:SystemRoot\System32\drivers\etc\hosts"
if (Test-Path $h) {
    Copy-Item $h -Destination ("$h.hermes-rescate-" + (Get-Date -Format 'yyyyMMdd-HHmmss')) -Force
    $lineas = @(
        '# Copyright (c) 1993-2009 Microsoft Corp.',
        '# Fichero hosts restaurado por HERMES-RESCATE',
        '127.0.0.1 localhost',
        '::1 localhost',
        ''
    )
    Set-Content -Path $h -Value $lineas -Encoding ASCII
    "hosts restaurado"
} else { "no existe el fichero hosts" }
'''
    rc, out, err = _ps(script, timeout=120)
    ok = "hosts restaurado" in (out or "")
    return ok, ("Fichero hosts restaurado (la copia se guardó junto al original)." if ok
                else "No se pudo restaurar el fichero hosts."), _cola((out or "") + " " + (err or "") + " " + copia)


# ====================================================================== manuales (nivel 3)
def _manual(texto):
    def accion(aviso):
        return False, "Esta reparación se hace a mano; aquí tienes los pasos.", texto
    return accion


INSTRUCCIONES_DISCO = (
    "1. Copiar los datos importantes a otro disco o al USB antes de tocar nada.\n"
    "2. Descargar la utilidad del fabricante (Samsung Magician, Crucial Storage Executive, "
    "SeaTools) y leer el estado SMART.\n"
    "3. Sustituir el disco por un SSD nuevo y reinstalar Windows.\n"
    "4. Un disco con fallo SMART o desgaste >90% no se repara: se cambia."
)
INSTRUCCIONES_ARRANQUE = (
    "Arrancar desde el USB de Windows (o WinRE) y, en Símbolo del sistema:\n"
    "  bootrec /fixmbr\n  bootrec /fixboot\n  bootrec /scanos\n  bootrec /rebuildbcd\n"
    "Si rebuildbcd no encuentra Windows, comprobar con diskpart que la partición EFI esté activa.\n"
    "Esto se hace SIEMPRE desde el entorno de recuperación, nunca con Windows arrancado."
)
INSTRUCCIONES_PASSWORD = (
    "Para restablecer la contraseña de una cuenta local (no de dominio):\n"
    "1. Desde WinRE: copiar utilman.exe a utilman.bak y cmd.exe a utilman.exe.\n"
    "2. Reiniciar, pulsar el botón de accesibilidad: abre una consola como SYSTEM.\n"
    "3. net user <usuario> <nueva_clave>\n"
    "4. Restaurar los ficheros originales al terminar.\n"
    "Solo en equipos del cliente y con su autorización por escrito."
)


# ====================================================================== acciones compuestas
def _conectar_wifi(aviso):
    from . import wifi
    datos = wifi.cargar()
    redes = sorted(datos.get("redes") or [], key=lambda r: r.get("prioridad", 9))
    if not redes:
        return False, "No hay ninguna red configurada en config/wifi.json.", ""
    errores = []
    for red in redes:
        ok, mensaje = wifi.conectar(red.get("ssid", ""), wifi.desofuscar(red.get("clave", "")), aviso=aviso)
        if ok:
            return True, mensaje, "red: %s" % red.get("ssid")
        errores.append("%s: %s" % (red.get("nombre") or red.get("ssid"), mensaje))
    return False, "No se pudo conectar a ninguna red configurada.", "\n".join(errores)


def _instalar_actualizaciones(aviso):
    from . import instalador
    resultado = instalador.actualizar_windows(aviso=aviso, maximo_s=7200)
    hechas = resultado.get("hechas") or []
    fallidas = resultado.get("fallidas") or []
    detalle = json.dumps(resultado, ensure_ascii=False, indent=1)[:3000]
    if resultado.get("error"):
        return False, "No se pudo completar: %s" % resultado["error"], detalle
    if resultado.get("total") == 0:
        return True, "No había actualizaciones pendientes.", detalle
    mensaje = "%d actualizaciones instaladas, %d con problemas." % (len(hechas), len(fallidas))
    if resultado.get("reinicio_necesario"):
        mensaje += " Hace falta reiniciar para terminar."
    return len(fallidas) == 0, mensaje, detalle


def _instalar_drivers(aviso):
    from . import instalador
    resultado = instalador.actualizar_windows(solo_drivers=True, aviso=aviso, maximo_s=3600)
    hechas = resultado.get("hechas") or []
    detalle = json.dumps(resultado, ensure_ascii=False, indent=1)[:3000]
    if resultado.get("error"):
        return False, "No se pudo completar: %s" % resultado["error"], detalle
    if resultado.get("total") == 0:
        return True, "Windows Update no ofrece controladores nuevos.", detalle
    return True, "%d controladores actualizados." % len(hechas), detalle


def _abrir_windows_update(aviso):
    os.startfile("ms-settings:windowsupdate")
    return True, "Se abrió la pantalla de Windows Update.", ""


def _abrir_administrador_dispositivos(aviso):
    os.startfile("devmgmt.msc")
    return True, "Se abrió el Administrador de dispositivos.", ""


# ====================================================================== registro
def _r():
    _reg("conectar_wifi", "Conectar al WiFi del técnico", 1,
         "Conecta este equipo al hotspot configurado para poder descargar actualizaciones y controladores.",
         "Sin red no hay Windows Update, ni drivers, ni chat de IA. Es el primer paso en la mayoría de reparaciones.",
         _conectar_wifi, admin=False, red=True, categoria="Red")

    _reg("limpiar_temp", "Borrar archivos temporales", 1,
         "Elimina temporales del usuario y de Windows. No toca documentos.",
         "Cuando falta espacio o el sistema va lento.",
         _limpiar_temp, categoria="Limpieza")
    _reg("vaciar_papelera", "Vaciar la papelera", 1,
         "Vacía la papelera de reciclaje de todas las unidades.",
         "Suele ser lo que más espacio libera de golpe.",
         _vaciar_papelera, categoria="Limpieza")
    _reg("limpiar_wu", "Vaciar caché de Windows Update", 1,
         "Borra los archivos ya descargados de actualizaciones (se vuelven a bajar si hacen falta).",
         "Cuando Windows Update se queda atascado o el disco está lleno.",
         _limpiar_wu, admin=True, categoria="Limpieza")
    _reg("limpiar_prefetch", "Limpiar Prefetch", 1,
         "Borra los datos de precarga; Windows los regenera solo.",
         "Equipos que arrancan lento tras mucho tiempo de uso.",
         _limpiar_prefetch, admin=True, categoria="Limpieza")
    _reg("limpiar_volcados", "Borrar volcados de fallo", 1,
         "Elimina los ficheros de volcado de pantallazos azules (pueden ocupar GB).",
         "Después de diagnosticar un cuelgue, o para recuperar espacio.",
         _limpiar_volcados, admin=True, categoria="Limpieza")
    _reg("optimizar_winsxs", "Compactar almacén de componentes", 2,
         "Limpia versiones antiguas de componentes de Windows (DISM).",
         "Disco lleno y no hay más que borrar. Tarda 10-20 minutos y no se puede deshacer.",
         _optimizar_winsxs, admin=True, categoria="Limpieza", lento=True)

    _reg("dism_check", "Comprobar imagen del sistema (DISM)", 1,
         "Comprueba si los componentes de Windows están dañados.",
         "Antivirus, pantallazos azules o funciones que fallan.",
         _dism_check, admin=True, categoria="Integridad", lento=True)
    _reg("dism_restore", "Reparar imagen del sistema (DISM)", 2,
         "Repara los componentes dañados de Windows descargándolos de Microsoft.",
         "Solo si DISM CheckHealth dice que hay daños o SFC no puede reparar.",
         _dism_restore, admin=True, red=True, categoria="Integridad", lento=True)
    _reg("sfc_scan", "Comprobar archivos de sistema (SFC)", 1,
         "Verifica y repara archivos protegidos de Windows.",
         "Fallos raros, aplicaciones que no arrancan, errores tras una actualización.",
         _sfc, admin=True, categoria="Integridad", lento=True)
    _reg("chkdsk_scan", "Analizar el disco (solo lectura)", 1,
         "Analiza errores del sistema de archivos sin modificar nada.",
         "Antes de cualquier reparación agresiva, o si hay cuelgues.",
         _chkdsk_scan, admin=True, categoria="Integridad", lento=True)

    _reg("flush_dns", "Vaciar caché de DNS", 1,
         "Borra las direcciones guardadas y vuelve a preguntar al servidor DNS.",
         "Páginas que no cargan, errores de nombre, internet «a medias».",
         _flush_dns, categoria="Red")
    _reg("renovar_ip", "Renovar la dirección IP", 2,
         "Suelta y vuelve a pedir la IP al router. La conexión se corta unos segundos.",
         "Sin internet con cable/WiFi conectado, o IP en conflicto.",
         _renovar_ip, categoria="Red")
    _reg("reset_proxy", "Quitar el proxy del sistema", 1,
         "Desactiva el proxy de WinHTTP y de Internet Explorer/Edge.",
         "Malware que deja el navegador sin internet.",
         _reset_proxy, categoria="Red")
    _reg("reset_winsock", "Restablecer Winsock", 2,
         "Devuelve la configuración de red a la de fábrica. Requiere reiniciar.",
         "Sin internet después de quitar malware o VPN.",
         _reset_winsock, admin=True, categoria="Red")
    _reg("reset_tcpip", "Restablecer la pila TCP/IP", 2,
         "Reinstala la pila de red de Windows. Requiere reiniciar.",
         "Errores de red persistentes que no se van con Winsock.",
         _reset_tcpip, admin=True, categoria="Red")
    _reg("conectar_wifi_hotspot", "Conectar al hotspot (avanzado)", 1,
         "Igual que «Conectar al WiFi del técnico», listando todas las redes configuradas.",
         "Cuando hay varias redes guardadas.", _conectar_wifi, categoria="Red")

    _reg("reiniciar_explorer", "Reiniciar el Explorador", 1,
         "Cierra y vuelve a abrir el Explorador de Windows.",
         "Barra de tareas congelada o escritorio en blanco.",
         _reiniciar_explorer, categoria="Interfaz")
    _reg("cache_iconos", "Reconstruir caché de iconos", 1,
         "Borra y regenera la caché de iconos y miniaturas.",
         "Iconos en blanco o miniaturas que no cargan.",
         _cache_iconos, categoria="Interfaz")
    _reg("spooler", "Reiniciar cola de impresión", 1,
         "Reinicia el servicio de impresión y limpia trabajos atascados.",
         "No se puede imprimir o la cola se queda bloqueada.",
         _spooler, admin=True, categoria="Interfaz")
    _reg("store_reregistrar", "Re-registrar apps de la Tienda", 1,
         "Vuelve a registrar las aplicaciones de Microsoft Store.",
         "Calculadora, Fotos, Tienda o Configuración que no abren.",
         _store_reregistrar, admin=True, categoria="Interfaz", lento=True)
    _reg("wu_reset", "Restablecer Windows Update", 2,
         "Reinicia los componentes de Windows Update desde cero (renombra SoftwareDistribution y catroot2).",
         "Windows Update con error 0x800… que no se va con nada.",
         _wu_reset, admin=True, red=True, categoria="Actualizaciones", lento=True)

    _reg("activar_defender", "Reactivar el antivirus", 2,
         "Vuelve a activar Defender y su protección en tiempo real.",
         "Equipo que se quedó sin antivirus (malware o un «optimizador»).",
         _activar_defender, admin=True, categoria="Seguridad")
    _reg("defender_firmas", "Actualizar firmas del antivirus", 1,
         "Fuerza la descarga de las definiciones más recientes.",
         "Firmas con más de una semana, o tras mucho tiempo apagado.",
         _defender_firmas, admin=True, red=True, categoria="Seguridad")
    _reg("defender_escaneo", "Análisis rápido del antivirus", 1,
         "Busca malware en las ubicaciones críticas.",
         "Equipo con síntomas de infección. Tarda 5-20 minutos.",
         _defender_escaneo, admin=True, categoria="Seguridad", lento=True)
    _reg("activar_firewall", "Activar el cortafuegos", 2,
         "Activa el cortafuegos de Windows en los tres perfiles.",
         "Cortafuegos desactivado por malware o por error.",
         _activar_firewall, admin=True, categoria="Seguridad")

    _reg("sincronizar_hora", "Sincronizar la hora", 1,
         "Fuerza la sincronización con el servidor de hora de internet.",
         "Certificados que fallan, errores de SSL o registros con horas raras.",
         _sincronizar_hora, categoria="Sistema")
    _reg("rescan_dispositivos", "Buscar hardware y controladores", 1,
         "Pide a Windows que vuelva a detectar los dispositivos.",
         "Dispositivos con signo de exclamación en el Administrador de dispositivos.",
         _rescan_dispositivos, admin=True, categoria="Sistema")
    _reg("habilitar_winre", "Habilitar entorno de recuperación", 2,
         "Activa WinRE, el Windows de emergencia que permite reparar el arranque.",
         "Equipo sin WinRE: si no arranca, no hay forma de repararlo sin USB.",
         _habilitar_winre, admin=True, categoria="Sistema")
    _reg("activar_restauracion", "Activar restauración del sistema", 2,
         "Activa los puntos de restauración (usa hasta un 10% del disco).",
         "Antes de instalar software grande o drivers.",
         _activar_restauracion, admin=True, categoria="Sistema")
    _reg("punto_restauracion", "Crear punto de restauración", 1,
         "Guarda el estado actual para poder volver atrás.",
         "Siempre antes de otras reparaciones. Es la red de seguridad.",
         _punto_restauracion, admin=True, categoria="Sistema")
    _reg("desactivar_inicio_rapido", "Desactivar inicio rápido", 2,
         "Hace que apagar el equipo sea un apagado real, no una hibernación.",
         "Fallos que desaparecen al reiniciar pero no al apagar y encender.",
         _desactivar_inicio_rapido, admin=True, categoria="Sistema")
    _reg("restaurar_energia", "Restaurar planes de energía", 1,
         "Devuelve los planes de energía a los valores por defecto.",
         "Equipo que se apaga la pantalla solo o no suspende.",
         _restaurar_energia, categoria="Sistema")
    _reg("limpiar_hosts", "Restaurar fichero hosts", 2,
         "Guarda copia y deja el hosts limpio (127.0.0.1 localhost).",
         "Páginas que no cargan, publicidad rara o redirecciones.",
         _limpiar_hosts, admin=True, categoria="Seguridad")

    _reg("instalar_actualizaciones", "Instalar actualizaciones de Windows", 2,
         "Descarga e instala todas las actualizaciones pendientes, una a una, mostrando el progreso.",
         "Equipo sin actualizar: es la causa número uno de fallos y agujeros de seguridad. Puede tardar horas.",
         _instalar_actualizaciones, admin=True, red=True, categoria="Actualizaciones", lento=True)
    _reg("instalar_drivers", "Instalar controladores desde Windows Update", 2,
         "Instala solo las actualizaciones de tipo controlador que ofrece Microsoft.",
         "WiFi, audio, vídeo o impresora que no funcionan.",
         _instalar_drivers, admin=True, red=True, categoria="Actualizaciones", lento=True)
    _reg("abrir_windows_update", "Abrir Windows Update", 1,
         "Abre la pantalla de actualizaciones de Configuración.",
         "Para revisar a mano lo que queda pendiente.",
         _abrir_windows_update, categoria="Actualizaciones")
    _reg("abrir_administrador_dispositivos", "Abrir Administrador de dispositivos", 1,
         "Abre el administrador de dispositivos.",
         "Para ver qué hardware falla y con qué controlador.",
         _abrir_administrador_dispositivos, categoria="Sistema")

    _reg("instrucciones_disco", "Sustituir el disco (manual)", 3,
         "Pasos para reemplazar un disco que falla.",
         "Disco con aviso SMART o desgaste extremo.",
         _manual(INSTRUCCIONES_DISCO), categoria="Manual")
    _reg("instrucciones_arranque", "Reparar el arranque (manual)", 3,
         "Comandos de bootrec desde el entorno de recuperación.",
         "El equipo no arranca Windows.",
         _manual(INSTRUCCIONES_ARRANQUE), categoria="Manual")
    _reg("instrucciones_password", "Restablecer contraseña local (manual)", 3,
         "Procedimiento con utilman desde WinRE.",
         "Cuenta local bloqueada con autorización del cliente.",
         _manual(INSTRUCCIONES_PASSWORD), categoria="Manual")


_r()


def obtener(rid):
    return CATALOGO.get(rid)


def por_categoria():
    grupos = {}
    for r in CATALOGO.values():
        grupos.setdefault(r["categoria"], []).append(r)
    for lista in grupos.values():
        lista.sort(key=lambda x: (x["nivel"], x["nombre"]))
    return grupos


def ejecutar(rid, aviso=None):
    """Ejecuta una reparacion y devuelve el registro de lo ocurrido."""
    aviso = aviso or (lambda *_: None)
    r = CATALOGO.get(rid)
    if not r:
        return {"id": rid, "ok": False, "mensaje": "Reparación desconocida: %s" % rid, "detalle": ""}
    if r["nivel"] == 3:
        return {"id": rid, "ok": False, "mensaje": r["que"], "detalle": "", "manual": True}
    if r["admin"] and not util.es_admin():
        return {"id": rid, "ok": False, "detalle": "",
                "mensaje": "Necesita permisos de administrador: cierra y abre el programa como administrador."}
    util.log("REPARACION inicio: %s" % rid)
    t0 = time.time()
    try:
        ok, mensaje, detalle = r["accion"](aviso)
    except Exception as exc:  # una reparacion no debe tumbar el programa
        ok, mensaje, detalle = False, "Error al ejecutar: %s" % exc, ""
    segundos = round(time.time() - t0, 1)
    registro = {"id": rid, "nombre": r["nombre"], "nivel": r["nivel"], "ok": bool(ok),
                "mensaje": mensaje, "detalle": detalle, "segundos": segundos,
                "fecha": time.strftime("%Y-%m-%d %H:%M:%S")}
    util.log("REPARACION fin: %s ok=%s (%.1f s) %s" % (rid, ok, segundos, mensaje))
    return registro
