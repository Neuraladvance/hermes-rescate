# Comprobaciones LENTAS (Defender, BitLocker, desgaste de disco, Windows Update).
# Escribe el JSON despues de cada bloque: si se cuelga y lo matan, lo hecho se conserva.
param(
    [string]$Salida = "lento.json"
)

$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference   = 'SilentlyContinue'
$WarningPreference    = 'SilentlyContinue'

. (Join-Path $PSScriptRoot '_json.ps1')

function Recorta($t, $n) {
    if ($null -eq $t) { return $null }
    $t = [string]$t
    $t = ($t -split "`r?`n")[0]
    if ($t.Length -gt $n) { $t = $t.Substring(0, $n) + '...' }
    return $t
}

$r = [ordered]@{ completo = $false; generado = (Get-Date).ToString('s') }
$admin = $false
try {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $admin = (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} catch { }
$r.admin = $admin
Guardar-Json $r $Salida | Out-Null

# ---------------------------------------------------------------- Defender
try {
    $mp = Get-MpComputerStatus
    if ($mp) {
        $r.defender = [ordered]@{
            servicio        = [bool]$mp.AMServiceEnabled
            activo          = [bool]$mp.AntivirusEnabled
            tiempo_real     = [bool]$mp.RealTimeProtectionEnabled
            firmas_dias     = $mp.AntivirusSignatureAge
            firmas_version  = "$($mp.AntivirusSignatureVersion)"
            escaneo_rapido_dias = $mp.QuickScanAge
            escaneo_completo_dias = $mp.FullScanAge
            manipulacion    = [bool]$mp.IsTamperProtected
        }
    }
} catch { $r.defender = [ordered]@{ error = (Recorta $_ 160) } }
Guardar-Json $r $Salida | Out-Null

# ---------------------------------------------------------------- BitLocker
if ($admin) {
    try {
        $r.bitlocker = @(Get-BitLockerVolume | ForEach-Object {
            [ordered]@{ volumen = "$($_.MountPoint)"; estado = "$($_.VolumeStatus)"; proteccion = "$($_.ProtectionStatus)"; cifrado_pct = $_.EncryptionPercentage; tipo = "$($_.EncryptionMethod)" }
        })
    } catch { $r.bitlocker = @() }
} else {
    $r.bitlocker = $null
    $r.bitlocker_nota = 'requiere administrador'
}
Guardar-Json $r $Salida | Out-Null

# ---------------------------------------------------------------- desgaste del disco
if ($admin) {
    try {
        $r.desgaste = @(Get-PhysicalDisk | ForEach-Object {
            $c = $null
            try { $c = $_ | Get-StorageReliabilityCounter } catch { }
            [ordered]@{
                modelo      = "$($_.FriendlyName)"
                salud       = "$($_.HealthStatus)"
                desgaste_pct = if ($c) { $c.Wear } else { $null }
                temperatura = if ($c) { $c.Temperature } else { $null }
                horas_encendido = if ($c) { $c.PowerOnHours } else { $null }
                errores_lectura = if ($c) { $c.ReadErrorsTotal } else { $null }
                errores_escritura = if ($c) { $c.WriteErrorsTotal } else { $null }
            }
        })
    } catch { }
}
Guardar-Json $r $Salida | Out-Null

# ---------------------------------------------------------------- Windows Update (lo mas lento, al final)
# Si esto se cuelga, el proceso se mata desde fuera: los bloques anteriores ya
# estan guardados y "completo" se queda en false.
try {
    $sesion = New-Object -ComObject Microsoft.Update.Session
    $buscador = $sesion.CreateUpdateSearcher()
    $res = $buscador.Search("IsInstalled=0 and IsHidden=0")
    $lista = @()
    foreach ($u in $res.Updates) {
        $lista += [ordered]@{
            titulo      = "$($u.Title)"
            kb          = ($u.KBArticleIDs -join ',')
            severidad   = "$($u.MsrcSeverity)"
            obligatoria = [bool]$u.IsMandatory
            descargada  = [bool]$u.IsDownloaded
            mb          = [math]::Round($u.MaxDownloadSize / 1MB, 1)
        }
    }
    $r.wu_pendientes = $lista
    $r.wu_total = $lista.Count
    $r.wu_criticas = @($lista | Where-Object { $_.severidad -match 'Critical|Important|Cr[ií]tica|Importante' }).Count
} catch {
    $r.wu_pendientes = $null
    $r.wu_nota = 'busqueda de actualizaciones sin respuesta: ' + (Recorta $_ 160)
}
$r.completo = $true
Guardar-Json $r $Salida | Out-Null
Write-Output ("OK " + $Salida)
