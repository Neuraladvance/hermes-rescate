# Actualizaciones y controladores de Windows, uno a uno, con el progreso en JSON.
#
# Modos:
#   -SoloBuscar            busca y guarda la lista SIN instalar (no hace falta admin)
#   -SoloDrivers           solo lo que Windows clasifica como controlador
#   -SoloActualizaciones   solo actualizaciones (sin controladores)
#   -ExcluirFirmware       descarta BIOS/UEFI/firmware del fabricante (lo delicado)
#   -SoloDescargar         descarga sin instalar
#
# Cada elemento se clasifica en tres grupos: actualizacion, controlador y firmware.
# El firmware (BIOS/UEFI) es lo único que puede dejar el equipo sin arrancar si se
# corta la corriente a mitad de la instalación: va aparte para pedir confirmación.
param(
    [string]$Salida = "actualizar.json",
    [switch]$SoloBuscar,
    [switch]$SoloDrivers,
    [switch]$SoloActualizaciones,
    [switch]$ExcluirFirmware,
    [switch]$SoloDescargar
)

$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference   = 'SilentlyContinue'
$WarningPreference    = 'SilentlyContinue'

. (Join-Path $PSScriptRoot '_json.ps1')

function Recorta($t, $n) {
    if ($null -eq $t) { return $null }
    $t = ([string]$t -split "`r?`n")[0]
    if ($t.Length -gt $n) { $t = $t.Substring(0, $n) + '...' }
    return $t
}
function Codigo($c) {
    switch ([int]$c) {
        2 { return 'correcto' }
        3 { return 'correcto con avisos' }
        4 { return 'fallido' }
        5 { return 'cancelado' }
        1 { return 'en curso' }
        default { return "codigo $c" }
    }
}
# Firmware = lo que puede dejar el equipo sin arrancar si se corta la corriente.
function Clasificar($u) {
    $titulo = [string]$u.Title
    if ($titulo -match '(?i)(bios|uefi|system firmware|firmware)') { return 'firmware' }
    if ($u.Type -eq 2) { return 'controlador' }
    return 'actualizacion'
}
function Nombre-Grupo($tipo) {
    switch ($tipo) {
        'firmware'    { return 'firmware' }
        'controlador' { return 'controladores' }
        default       { return 'actualizaciones' }
    }
}

$admin = $false
try {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $admin = (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} catch { }

$r = [ordered]@{
    completo    = $false
    inicio      = (Get-Date).ToString('s')
    modo        = if ($SoloBuscar) { 'solo busqueda' } elseif ($SoloDrivers) { 'controladores' } elseif ($SoloActualizaciones) { 'solo actualizaciones' } else { 'todo' }
    excluir_firmware = [bool]$ExcluirFirmware
    solo_descarga = [bool]$SoloDescargar
    admin       = $admin
    total       = 0
    grupos      = [ordered]@{ actualizaciones = 0; controladores = 0; firmware = 0 }
    mb          = [ordered]@{ actualizaciones = 0; controladores = 0; firmware = 0 }
    hechas      = @()
    fallidas    = @()
    pendientes  = @()
    reinicio_necesario = $false
    fase        = 'iniciando'
}
Guardar-Json $r $Salida | Out-Null

# ---------------------------------------------------------------- busqueda
$r.fase = 'buscando actualizaciones'
Guardar-Json $r $Salida | Out-Null

try {
    $sesion = New-Object -ComObject Microsoft.Update.Session
    $buscador = $sesion.CreateUpdateSearcher()
    $criterio = "IsInstalled=0 and IsHidden=0"
    if ($SoloDrivers) { $criterio = "IsInstalled=0 and IsHidden=0 and Type='Driver'" }
    $resultado = $buscador.Search($criterio)

    $updates = @()
    $tipos   = @()
    foreach ($u in $resultado.Updates) {
        $tipo = Clasificar $u
        $mb   = [math]::Round($u.MaxDownloadSize / 1MB, 1)
        $updates += $u
        $tipos   += $tipo
        $r.pendientes += [ordered]@{
            titulo = Recorta $u.Title 120
            kb     = ($u.KBArticleIDs -join ',')
            mb     = $mb
            tipo   = $tipo
        }
        $grupo = Nombre-Grupo $tipo
        $r.grupos[$grupo] = [int]$r.grupos[$grupo] + 1
        $r.mb[$grupo]     = [math]::Round([double]$r.mb[$grupo] + $mb, 1)
    }
    $r.total = $updates.Count
} catch {
    $r.completo = $true
    $r.error = 'Fallo al buscar actualizaciones: ' + (Recorta $_ 200)
    Guardar-Json $r $Salida | Out-Null
    Write-Output 'ERROR en la busqueda'
    exit 1
}

# La búsqueda no necesita administrador: se puede consultar sin tocar el equipo.
if ($SoloBuscar) {
    $r.completo = $true
    $r.fase = 'solo busqueda'
    $r.fin = (Get-Date).ToString('s')
    Guardar-Json $r $Salida | Out-Null
    Write-Output ("OK busqueda: total=" + $r.total + " actualizaciones=" + $r.grupos.actualizaciones + " controladores=" + $r.grupos.controladores + " firmware=" + $r.grupos.firmware)
    exit 0
}

if (-not $admin) {
    $r.completo = $true
    $r.error = 'Se necesitan privilegios de administrador para instalar actualizaciones.'
    Guardar-Json $r $Salida | Out-Null
    Write-Output 'ERROR: sin administrador'
    exit 1
}

# ---------------------------------------------------------------- seleccion
$elegidas = @()
for ($i = 0; $i -lt $updates.Count; $i++) {
    $tipo = $tipos[$i]
    if ($SoloActualizaciones -and $tipo -ne 'actualizacion') { continue }
    if ($SoloDrivers -and $tipo -eq 'actualizacion') { continue }
    if ($ExcluirFirmware -and $tipo -eq 'firmware') { continue }
    $elegidas += $updates[$i]
}
$r.total = $elegidas.Count

if ($r.total -eq 0) {
    $r.completo = $true
    $r.fase = 'nada que instalar con estos filtros'
    Guardar-Json $r $Salida | Out-Null
    Write-Output 'OK: no hay nada que instalar con los filtros aplicados'
    exit 0
}

# ---------------------------------------------------------------- descarga e instalacion
$indice = 0
foreach ($u in $elegidas) {
    $indice++
    $titulo = Recorta $u.Title 120
    $r.fase = "($indice/$($r.total)) $titulo"
    Guardar-Json $r $Salida | Out-Null

    try {
        if (-not $u.EulaAccepted) { try { $u.EulaAccepted = $true } catch { } }
        $coleccion = New-Object -ComObject Microsoft.Update.UpdateColl
        $coleccion.Add($u) | Out-Null

        $descargador = $sesion.CreateUpdateDownloader()
        $descargador.Updates = $coleccion
        $rd = $descargador.Download()

        if ([int]$rd.ResultCode -notin @(2, 3)) {
            $r.fallidas += [ordered]@{ titulo = $titulo; motivo = 'descarga: ' + (Codigo $rd.ResultCode) }
            continue
        }

        if ($SoloDescargar) {
            $r.hechas += [ordered]@{ titulo = $titulo; resultado = 'descargada' }
            continue
        }

        $instalador = $sesion.CreateUpdateInstaller()
        $instalador.Updates = $coleccion
        $ri = $instalador.Install()

        if ($instalador.RebootRequiredAfter) { $r.reinicio_necesario = $true }
        $entrada = [ordered]@{ titulo = $titulo; resultado = (Codigo $ri.ResultCode) }
        if ([int]$ri.ResultCode -in @(2, 3)) {
            $r.hechas += $entrada
        } else {
            $entrada.motivo = 'instalacion: ' + (Codigo $ri.ResultCode)
            $r.fallidas += $entrada
        }
    } catch {
        $r.fallidas += [ordered]@{ titulo = $titulo; motivo = Recorta $_ 160 }
    }
    Guardar-Json $r $Salida | Out-Null
}

$r.fase = 'terminado'
$r.completo = $true
$r.fin = (Get-Date).ToString('s')
Guardar-Json $r $Salida | Out-Null
Write-Output ("OK instaladas=" + $r.hechas.Count + " fallidas=" + $r.fallidas.Count)
