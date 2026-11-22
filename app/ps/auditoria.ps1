# Auditoria RAPIDA del equipo. Escribe JSON UTF-8 en -Salida.
# Pensado para Windows PowerShell 5.1+ (Windows 7 SP1 en adelante). Objetivo: < 20 s.
param(
    [string]$Salida = "auditoria.json",
    [int]$DiasEventos = 7
)

$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference   = 'SilentlyContinue'
$WarningPreference    = 'SilentlyContinue'

$tm = [ordered]@{}
$script:ultimo = Get-Date
$script:inicio = Get-Date
function Marca($n) {
    $tm[$n] = [int]((Get-Date) - $script:ultimo).TotalMilliseconds
    $script:ultimo = Get-Date
    try { Add-Content -LiteralPath "$Salida.progreso.txt" -Value ("{0} {1}" -f (Get-Date).ToString('HH:mm:ss'), $n) -Encoding UTF8 } catch { }
}
function ISO($f) { try { return ([datetime]$f).ToString('s') } catch { return $null } }
function Recorta($t, $n) {
    if ($null -eq $t) { return $null }
    $t = [string]$t
    $t = ($t -split "`r?`n")[0]
    if ($t.Length -gt $n) { $t = $t.Substring(0, $n) + '...' }
    return $t
}
function Test-Puerto($host_, $puerto, $ms = 1500) {
    try {
        $c = New-Object Net.Sockets.TcpClient
        $r = $c.BeginConnect($host_, $puerto, $null, $null)
        if ($r.AsyncWaitHandle.WaitOne($ms)) { $c.EndConnect($r); $c.Close(); return $true }
        $c.Close(); return $false
    } catch { return $false }
}
# Get-WinEvent -FilterHashtable con arrays de Id/Level y StartTime falla en
# silencio con culturas como es-ES (convierte la fecha a "vi./23/10/2026" y no
# filtra). XPath con fecha ISO en UTC es independiente del idioma.
function Eventos($log, $condicion, $desde, $max) {
    $iso = $desde.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
    $xp = "*[System[($condicion) and TimeCreated[@SystemTime>='$iso']]]"
    return @(Get-WinEvent -LogName $log -FilterXPath $xp -MaxEvents $max -ErrorAction SilentlyContinue)
}

$d = [ordered]@{}
$d.version_script = 2
$d.generado = (Get-Date).ToString('s')
$d.equipo = $env:COMPUTERNAME
$d.usuario = $env:USERNAME
$d.dominio = $env:USERDOMAIN
$d.errores = @()
$d.admin = $false
try {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $d.admin = (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} catch { }
Marca 'inicio'

# ---------------------------------------------------------------- sistema
try {
    $os = Get-CimInstance Win32_OperatingSystem
    $cs = Get-CimInstance Win32_ComputerSystem
    $bb = Get-CimInstance Win32_BaseBoard
    $bios = Get-CimInstance Win32_BIOS
    $d.so = [ordered]@{
        nombre       = $os.Caption
        version      = $os.Version
        build        = $os.BuildNumber
        arquitectura = $os.OSArchitecture
        instalado    = ISO $os.InstallDate
        arranque     = ISO $os.LastBootUpTime
        uptime_horas = [math]::Round(((Get-Date) - $os.LastBootUpTime).TotalHours, 1)
        fabricante   = $cs.Manufacturer
        modelo       = $cs.Model
        serie        = "$($bios.SerialNumber)".Trim()
        placa        = "$($bb.Manufacturer) $($bb.Product)"
        bios         = "$($bios.Manufacturer) $($bios.SMBIOSBIOSVersion)"
        bios_fecha   = ISO $bios.ReleaseDate
        locale       = (Get-Culture).Name
        zona         = (Get-TimeZone).Id
        ram_total_gb = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
        ram_libre_gb = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
        ram_uso_pct  = [math]::Round(100 * (1 - ($os.FreePhysicalMemory / $os.TotalVisibleMemorySize)), 1)
    }
} catch { $d.errores += "so: $_" }
Marca 'sistema'

# ---------------------------------------------------------------- activacion
try {
    $lic = Get-CimInstance SoftwareLicensingProduct -Filter "PartialProductKey IS NOT NULL AND ApplicationID='55c92734-d682-4d71-983e-d6ec3f16059f'" | Select-Object -First 1
    if ($lic) {
        $mapa = @{ 0 = 'Sin licencia'; 1 = 'Activado'; 2 = 'Periodo de gracia'; 3 = 'Gracia adicional'; 4 = 'No genuino'; 5 = 'Notificacion'; 6 = 'Gracia extendida' }
        $d.activacion = [ordered]@{
            estado      = [int]$lic.LicenseStatus
            descripcion = $mapa[[int]$lic.LicenseStatus]
            edicion     = $lic.Name
            canal       = $lic.ProductKeyChannel
        }
    }
} catch { $d.errores += "activacion: $_" }
Marca 'activacion'

# ---------------------------------------------------------------- cpu / ram
try {
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    $d.cpu = [ordered]@{
        nombre    = "$($cpu.Name)".Trim()
        nucleos   = $cpu.NumberOfCores
        hilos     = $cpu.NumberOfLogicalProcessors
        mhz       = $cpu.MaxClockSpeed
        socket    = $cpu.SocketDesignation
        carga_pct = $cpu.LoadPercentage
    }
} catch { $d.errores += "cpu: $_" }

try {
    $mods = @(Get-CimInstance Win32_PhysicalMemory | ForEach-Object {
        [ordered]@{ ranura = $_.DeviceLocator; gb = [math]::Round($_.Capacity / 1GB, 1); mhz = $_.Speed; fabricante = "$($_.Manufacturer)" }
    })
    $arr = Get-CimInstance Win32_PhysicalMemoryArray | Select-Object -First 1
    $d.ram = [ordered]@{ modulos = $mods; ranuras_totales = $arr.MemoryDevices; ranuras_usadas = $mods.Count }
} catch { $d.errores += "ram: $_" }
Marca 'cpu_ram'

# ---------------------------------------------------------------- discos
try {
    $smart = $null
    try {
        $pp = Get-CimInstance -Namespace root\wmi -ClassName MSStorageDriver_FailurePredictStatus | Select-Object -First 1
        if ($pp) { $smart = [bool]$pp.PredictFailure }
    } catch { }
    $d.discos = @(Get-CimInstance Win32_DiskDrive | ForEach-Object {
        [ordered]@{
            modelo    = "$($_.Model)".Trim()
            tipo      = "$($_.MediaType)"
            interfaz  = "$($_.InterfaceType)"
            gb        = [math]::Round($_.Size / 1GB, 1)
            particiones = $_.Partitions
            estado    = "$($_.Status)"
            serie     = "$($_.SerialNumber)".Trim()
            fallo_previsto = $smart
        }
    })
} catch { $d.errores += "discos: $_" }

try {
    $d.discos_fisicos = @(Get-PhysicalDisk | ForEach-Object {
        [ordered]@{ modelo = $_.FriendlyName; medio = "$($_.MediaType)"; bus = "$($_.BusType)"; gb = [math]::Round($_.Size / 1GB, 1); salud = "$($_.HealthStatus)"; operativo = ($_.OperationalStatus -join ',') }
    })
} catch { }

try {
    $d.volumenes = @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
        $tot = [double]$_.Size; $lib = [double]$_.FreeSpace
        [ordered]@{
            letra     = $_.DeviceID
            etiqueta  = "$($_.VolumeName)"
            fs        = $_.FileSystem
            gb        = [math]::Round($tot / 1GB, 1)
            libre_gb  = [math]::Round($lib / 1GB, 1)
            libre_pct = if ($tot -gt 0) { [math]::Round(100 * $lib / $tot, 1) } else { 0 }
        }
    })
} catch { $d.errores += "volumenes: $_" }
Marca 'discos'

# ---------------------------------------------------------------- bateria
try {
    $bat = Get-CimInstance Win32_Battery | Select-Object -First 1
    if ($bat) {
        $dis = $null; $cap = $null; $ciclos = $null
        try { $dis = (Get-CimInstance -Namespace root\wmi -ClassName BatteryStaticData | Select-Object -First 1).DesignedCapacity } catch { }
        try { $cap = (Get-CimInstance -Namespace root\wmi -ClassName BatteryFullChargedCapacity | Select-Object -First 1).FullChargedCapacity } catch { }
        try { $ciclos = (Get-CimInstance -Namespace root\wmi -ClassName BatteryCycleCount | Select-Object -First 1).CycleCount } catch { }
        $salud = $null
        if ($dis -and $cap -and $dis -gt 0) { $salud = [math]::Round(100 * $cap / $dis, 1) }
        $d.bateria = [ordered]@{
            presente      = $true
            carga_pct     = $bat.EstimatedChargeRemaining
            diseno_mwh    = $dis
            capacidad_mwh = $cap
            salud_pct     = $salud
            ciclos        = $ciclos
        }
    } else { $d.bateria = [ordered]@{ presente = $false } }
} catch { $d.errores += "bateria: $_" }
Marca 'bateria'

# ---------------------------------------------------------------- seguridad
try { $d.antivirus = @(Get-CimInstance -Namespace root\SecurityCenter2 -ClassName AntiVirusProduct | ForEach-Object { [ordered]@{ nombre = "$($_.displayName)"; estado = $_.productState } }) } catch { }

try {
    $d.firewall = @(Get-NetFirewallProfile | ForEach-Object {
        [ordered]@{ perfil = $_.Name; activo = [bool]$_.Enabled; entrante = "$($_.DefaultInboundAction)" }
    })
} catch { $d.errores += "firewall: $_" }

try { $d.secure_boot = [bool](Confirm-SecureBootUEFI) } catch { $d.secure_boot = $null }
try { $t = Get-Tpm; $d.tpm = [ordered]@{ presente = [bool]$t.TpmPresent; listo = [bool]$t.TpmReady; habilitado = [bool]$t.TpmEnabled } } catch { }
Marca 'seguridad'

# ---------------------------------------------------------------- actualizaciones (rapido)
try {
    $d.actualizaciones = [ordered]@{
        instaladas = @(Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 6 | ForEach-Object {
            [ordered]@{ kb = $_.HotFixID; fecha = ISO $_.InstalledOn }
        })
    }
} catch { $d.errores += "hotfix: $_" }

try {
    $reboot = $false
    if (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending') { $reboot = $true }
    if (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired') { $reboot = $true }
    if ((Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name PendingFileRenameOperations).PendingFileRenameOperations) { $reboot = $true }
    $d.reinicio_pendiente = $reboot
} catch { }
Marca 'actualizaciones'

# ---------------------------------------------------------------- estabilidad
try {
    $ini = (Get-Date).AddDays(-$DiasEventos)
    $evs = Eventos 'System' '(Level=1 or Level=2)' $ini 400
    $d.eventos_sistema_total = $evs.Count
    $d.eventos_sistema = @($evs | Group-Object ProviderName, Id | Sort-Object Count -Descending | Select-Object -First 12 | ForEach-Object {
        [ordered]@{
            origen  = "$($_.Group[0].ProviderName)"
            id      = $_.Group[0].Id
            veces   = $_.Count
            ultimo  = ISO $_.Group[0].TimeCreated
            muestra = Recorta $_.Group[0].Message 240
        }
    })
} catch { $d.errores += "eventos_sistema: $_" }

try {
    $evs = Eventos 'Application' '(Level=1 or Level=2)' (Get-Date).AddDays(-$DiasEventos) 400
    $d.eventos_aplicacion = @($evs | Group-Object ProviderName, Id | Sort-Object Count -Descending | Select-Object -First 8 | ForEach-Object {
        [ordered]@{ origen = "$($_.Group[0].ProviderName)"; id = $_.Group[0].Id; veces = $_.Count; ultimo = ISO $_.Group[0].TimeCreated; muestra = Recorta $_.Group[0].Message 180 }
    })
} catch { $d.errores += "eventos_aplicacion: $_" }

try {
    $inc = @(Eventos 'System' '(EventID=41 or EventID=1001 or EventID=6008)' (Get-Date).AddDays(-30) 30 | ForEach-Object { [ordered]@{ id = $_.Id; fecha = ISO $_.TimeCreated; texto = Recorta $_.Message 180 } })
    $d.incidentes = $inc
    $d.incidentes_total = $inc.Count
} catch { }

try {
    $d.reinicios = @(Eventos 'System' 'EventID=1074' (Get-Date).AddDays(-30) 15 |
        ForEach-Object { [ordered]@{ fecha = ISO $_.TimeCreated; texto = Recorta $_.Message 160 } })
} catch { }

try {
    $d.dispositivos_error = @(Get-PnpDevice | Where-Object { $_.Status -eq 'Error' -or $_.Status -eq 'Degraded' } | Select-Object -First 25 | ForEach-Object {
        [ordered]@{ nombre = "$($_.FriendlyName)"; clase = "$($_.Class)"; estado = "$($_.Status)"; problema = $_.Problem }
    })
} catch { $d.errores += "pnp: $_" }

try {
    $d.servicios_parados = @(Get-CimInstance Win32_Service -Filter "StartMode='Auto'" | Where-Object { $_.State -ne 'Running' -and -not $_.DelayedAutoStart } | ForEach-Object {
        $trigger = $false
        try { $trigger = Test-Path "HKLM:\SYSTEM\CurrentControlSet\Services\$($_.Name)\TriggerInfo" } catch { }
        [ordered]@{ nombre = $_.Name; visible = "$($_.DisplayName)"; estado = "$($_.State)"; ruta = "$($_.PathName)"; trigger = $trigger }
    })
} catch { $d.errores += "servicios: $_" }
Marca 'estabilidad'

# ---------------------------------------------------------------- arranque / software
try {
    $d.arranque = @(Get-CimInstance Win32_StartupCommand | ForEach-Object {
        [ordered]@{ nombre = "$($_.Name)"; comando = Recorta $_.Command 180; ubicacion = "$($_.Location)"; usuario = "$($_.User)" }
    })
} catch { $d.errores += "arranque: $_" }

try {
    $claves = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    $progs = @(Get-ItemProperty $claves | Where-Object { $_.DisplayName -and -not $_.SystemComponent -and -not $_.ReleaseType -and -not $_.ParentKeyName } | ForEach-Object {
        [ordered]@{
            nombre  = "$($_.DisplayName)"
            version = "$($_.DisplayVersion)"
            editor  = "$($_.Publisher)"
            fecha   = "$($_.InstallDate)"
            mb      = if ($_.EstimatedSize) { [math]::Round($_.EstimatedSize / 1024, 1) } else { 0 }
        }
    })
    $limite = [int](Get-Date).AddDays(-60).ToString('yyyyMMdd')
    $d.programas = [ordered]@{
        total     = $progs.Count
        grandes   = @($progs | Sort-Object mb -Descending | Select-Object -First 12)
        recientes = @($progs | Where-Object { $_.fecha.Length -eq 8 -and [int]$_.fecha -ge $limite } | Select-Object -First 12)
    }
} catch { $d.errores += "programas: $_" }
Marca 'software'

# ---------------------------------------------------------------- red
try {
    $ad = @(Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled=True" | ForEach-Object {
        [ordered]@{
            descripcion = "$($_.Description)"
            ip          = ($_.IPAddress -join ', ')
            puerta      = ($_.DefaultIPGateway -join ', ')
            dns         = ($_.DNSServerSearchOrder -join ', ')
            dhcp        = [bool]$_.DHCPEnabled
            mac         = "$($_.MACAddress)"
        }
    })
    $d.red = [ordered]@{
        adaptadores = $ad
        conectividad = [ordered]@{
            internet_443  = Test-Puerto '1.1.1.1' 443
            dns_53        = Test-Puerto '8.8.8.8' 53
            microsoft_443 = Test-Puerto 'www.microsoft.com' 443
        }
    }
    try {
        $p = (($ad | Select-Object -First 1).puerta -split ',')[0].Trim()
        if ($p) { $d.red.ping_puerta = [bool](Test-Connection -ComputerName $p -Count 1 -Quiet) }
    } catch { }
} catch { $d.errores += "red: $_" }

try {
    $ie = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
    $d.proxy = [ordered]@{ activo = [bool]$ie.ProxyEnable; servidor = "$($ie.ProxyServer)" }
} catch { }

try {
    $h = "$env:SystemRoot\System32\drivers\etc\hosts"
    if (Test-Path $h) {
        $lineas = @(Get-Content $h | Where-Object { $_.Trim() -ne '' -and -not $_.Trim().StartsWith('#') })
        $d.hosts = [ordered]@{ entradas = $lineas.Count; muestra = @($lineas | Select-Object -First 15) }
    }
} catch { }
Marca 'red'

# ---------------------------------------------------------------- energia / mantenimiento
try {
    $d.energia = [ordered]@{
        plan               = Recorta ((powercfg /getactivescheme) -join ' ') 120
        hibernacion_activa = (Test-Path "$env:SystemDrive\hiberfil.sys")
        inicio_rapido      = [bool](Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -Name HiberbootEnabled).HiberbootEnabled
    }
} catch { $d.errores += "energia: $_" }

try {
    $d.restauracion = [ordered]@{
        deshabilitada = [bool](Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore' -Name DisableSR -ErrorAction SilentlyContinue).DisableSR
        puntos = @(Get-ComputerRestorePoint | Select-Object -Last 5 | ForEach-Object { [ordered]@{ descripcion = "$($_.Description)"; fecha = ISO $_.CreationTime } })
    }
} catch { }

try {
    $out = (cmd /c "reagentc /info 2>nul") -join ' '
    if ($out -match 'privilegios elevados|elevated') {
        $d.winre = [ordered]@{ habilitado = $null; texto = 'requiere administrador' }
    } else {
        $d.winre = [ordered]@{ habilitado = [bool]($out -match 'Habilitado|Enabled'); texto = (Recorta $out 160) }
    }
} catch { }

try {
    $g = @(Get-LocalGroupMember -Group 'Administradores' -ErrorAction SilentlyContinue | ForEach-Object { "$($_.Name)" })
    if ($g.Count -eq 0) { $g = @(Get-LocalGroupMember -Group 'Administrators' -ErrorAction SilentlyContinue | ForEach-Object { "$($_.Name)" }) }
    $d.cuentas = [ordered]@{ admins = $g; admins_total = $g.Count }
} catch { }

try {
    $d.hora = [ordered]@{
        ahora = (Get-Date).ToString('s')
        utc   = (Get-Date).ToUniversalTime().ToString('s')
        sincronizacion = Recorta (((w32tm /query /status 2>$null) -join ' ')) 140
    }
} catch { }
Marca 'mantenimiento'

# ---------------------------------------------------------------- escritura
$d.tiempos_ms = $tm
$d.total_ms = [int]((Get-Date) - $script:inicio).TotalMilliseconds

# Serializador JSON propio: ConvertTo-Json de Windows PowerShell 5.1 revienta
# (OutOfMemoryException) y puede tardar minutos con este objeto. Este es rapido,
# sin sorpresas y con limite de profundidad (una referencia circular no cuelga).
function J-Esc([string]$s) {
    $sb = New-Object System.Text.StringBuilder
    foreach ($ch in $s.ToCharArray()) {
        $c = [int][char]$ch
        if ($c -eq 34) { [void]$sb.Append('\"') }
        elseif ($c -eq 92) { [void]$sb.Append('\\') }
        elseif ($c -eq 10) { [void]$sb.Append('\n') }
        elseif ($c -eq 13) { [void]$sb.Append('\r') }
        elseif ($c -eq 9) { [void]$sb.Append('\t') }
        elseif ($c -lt 32) { [void]$sb.Append('\u' + $c.ToString('x4')) }
        else { [void]$sb.Append($ch) }
    }
    return $sb.ToString()
}
function J($v, $prof) {
    if ($prof -gt 12) { return '"..."' }
    if ($null -eq $v) { return 'null' }
    if ($v -is [bool]) { if ($v) { return 'true' } else { return 'false' } }
    if ($v -is [datetime]) { return '"' + $v.ToString('s') + '"' }
    if ($v -is [string]) { return '"' + (J-Esc $v) + '"' }
    $t = $v.GetType()
    if ($t.IsPrimitive -or $v -is [decimal]) {
        $dv = 0.0
        if ([double]::TryParse([string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0}', $v), [ref]$dv)) {
            if ([double]::IsNaN($dv) -or [double]::IsInfinity($dv)) { return 'null' }
        }
        return [string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0}', $v)
    }
    if ($v -is [System.Collections.IDictionary]) {
        $p = New-Object System.Collections.ArrayList
        foreach ($k in $v.Keys) { [void]$p.Add('"' + (J-Esc ([string]$k)) + '":' + (J $v[$k] ($prof + 1))) }
        return '{' + ($p -join ',') + '}'
    }
    if ($v -is [System.Collections.IEnumerable]) {
        $p = New-Object System.Collections.ArrayList
        foreach ($i in $v) { [void]$p.Add((J $i ($prof + 1))) }
        return '[' + ($p -join ',') + ']'
    }
    return '"' + (J-Esc ([string]$v)) + '"'
}

$json = J $d 0
try {
    [IO.File]::WriteAllText($Salida, $json, (New-Object System.Text.UTF8Encoding($false)))
    Remove-Item -LiteralPath "$Salida.progreso.txt" -Force -ErrorAction SilentlyContinue
    Write-Output ("OK " + $Salida + " (" + $d.total_ms + " ms, " + $json.Length + " bytes)")
} catch {
    Write-Output ("ERROR escribiendo ${Salida}: $_")
}
