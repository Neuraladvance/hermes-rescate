# Instantánea del sistema para detectar restos de una desinstalación.
# Uso: powershell -File restos.ps1 -Salida <ruta.json> [-Marca antes|despues]
param(
    [Parameter(Mandatory = $true)][string]$Salida,
    [string]$Marca = "antes"
)

$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
$WarningPreference = 'SilentlyContinue'

function J-Esc([string]$t) {
    if ($null -eq $t) { return "" }
    $t = $t -replace '\\', '\\\\' -replace '"', '\"' -replace "`r", '\r' -replace "`n", '\n' -replace "`t", '\t'
    return $t
}

# ------------------------------------------------------------------ programas
$programas = @()
$fuentes = @(
    @{ Ruta = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'; Rama = 'HKLM' },
    @{ Ruta = 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'; Rama = 'HKLM32' },
    @{ Ruta = 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'; Rama = 'HKCU' }
)
foreach ($fuente in $fuentes) {
    foreach ($clave in (Get-ItemProperty $fuente.Ruta | Where-Object { $_.DisplayName })) {
        $programas += ('{"nombre":"' + (J-Esc $clave.DisplayName) + '","version":"' + (J-Esc $clave.DisplayVersion) +
            '","editor":"' + (J-Esc $clave.Publisher) + '","ubicacion":"' + (J-Esc $clave.InstallLocation) +
            '","desinstalar":"' + (J-Esc $clave.UninstallString) + '","clave":"' + (J-Esc $clave.PSChildName) +
            '","rama":"' + $fuente.Rama + '"}')
    }
}

# ------------------------------------------------------------------ carpetas
$carpetas = @()
$bases = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramData, $env:LOCALAPPDATA, $env:APPDATA)
foreach ($base in $bases) {
    if (-not $base -or -not (Test-Path $base)) { continue }
    foreach ($carpeta in (Get-ChildItem -Directory -LiteralPath $base)) {
        $carpetas += ('{"ruta":"' + (J-Esc $carpeta.FullName) + '","carpeta":"' + (J-Esc $carpeta.Name) +
            '","base":"' + (J-Esc $base) + '"}')
    }
}

# ------------------------------------------------------------------ servicios y tareas
$servicios = @()
foreach ($s in (Get-Service)) {
    $servicios += ('{"nombre":"' + (J-Esc $s.Name) + '","visible":"' + (J-Esc $s.DisplayName) + '"}')
}
$tareas = @()
foreach ($t in (Get-ScheduledTask)) {
    $tareas += ('{"ruta":"' + (J-Esc ($t.TaskPath + $t.TaskName)) + '"}')
}

# ------------------------------------------------------------------ claves de software
$software = @()
foreach ($base in @('HKLM:\SOFTWARE', 'HKLM:\SOFTWARE\WOW6432Node', 'HKCU:\SOFTWARE')) {
    foreach ($clave in (Get-ChildItem $base)) {
        $software += ('{"clave":"' + (J-Esc $clave.PSPath) + '","nombre":"' + (J-Esc $clave.PSChildName) + '"}')
    }
}

$json = '{"marca":"' + $Marca + '","programas":[' + ($programas -join ',') + '],"carpetas":[' +
    ($carpetas -join ',') + '],"servicios":[' + ($servicios -join ',') + '],"tareas":[' +
    ($tareas -join ',') + '],"software":[' + ($software -join ',') + ']}'

$carpeta = Split-Path -Parent $Salida
if (-not (Test-Path $carpeta)) { New-Item -ItemType Directory -Path $carpeta -Force | Out-Null }
[System.IO.File]::WriteAllText($Salida, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Output ("instantanea " + $Marca + " programa=" + $programas.Count + " carpetas=" + $carpetas.Count)
