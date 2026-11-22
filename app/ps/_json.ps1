# Serializador JSON comun (dot-source). ConvertTo-Json de Windows PowerShell 5.1
# revienta con OutOfMemoryException y puede tardar minutos con objetos grandes:
# estas funciones son rapidas y tienen limite de profundidad.
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
function Guardar-Json($objeto, $ruta) {
    try {
        [IO.File]::WriteAllText($ruta, (J $objeto 0), (New-Object System.Text.UTF8Encoding($false)))
        return $true
    } catch { return $false }
}
