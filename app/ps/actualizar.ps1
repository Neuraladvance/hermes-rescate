# Instala actualizaciones de Windows (o solo controladores) una a una, guardando
# el progreso en JSON tras cada una. Es largo (puede tardar horas): el proceso se
# lanza aparte y se vigila leyendo el fichero.
param(
    [string]$Salida = "actualizar.json",
    [switch]$SoloDrivers,
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

$admin = $false
try {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $admin = (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} catch { }

$r = [ordered]@{
    completo    = $false
    inicio      = (Get-Date).ToString('s')
    modo        = if ($SoloDrivers) { 'controladores' } else { 'todo' }
    solo_descarga = [bool]$SoloDescargar
    admin       = $admin
    total       = 0
    hechas      = @()
    fallidas    = @()
    pendientes  = @()
    reinicio_necesario = $false
    fase        = 'iniciando'
}
Guardar-Json $r $Salida | Out-Null

if (-not $admin) {
    $r.completo = $true
    $r.error = 'Se necesitan privilegios de administrador para instalar actualizaciones.'
    Guardar-Json $r $Salida | Out-Null
    Write-Output 'ERROR: sin administrador'
    exit 1
}

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
    foreach ($u in $resultado.Updates) {
        $updates += $u
        $r.pendientes += [ordered]@{
            titulo = Recorta $u.Title 120
            kb     = ($u.KBArticleIDs -join ',')
            mb     = [math]::Round($u.MaxDownloadSize / 1MB, 1)
            tipo   = if ($u.Type -eq 2) { 'controlador' } else { 'actualizacion' }
        }
    }
    $r.total = $updates.Count
} catch {
    $r.completo = $true
    $r.error = 'Fallo al buscar actualizaciones: ' + (Recorta $_ 200)
    Guardar-Json $r $Salida | Out-Null
    Write-Output 'ERROR en la busqueda'
    exit 1
}

if ($r.total -eq 0) {
    $r.completo = $true
    $r.fase = 'nada que instalar'
    Guardar-Json $r $Salida | Out-Null
    Write-Output 'OK: no hay actualizaciones pendientes'
    exit 0
}

# ---------------------------------------------------------------- descarga e instalacion
$indice = 0
foreach ($u in $updates) {
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
