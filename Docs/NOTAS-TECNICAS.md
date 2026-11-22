# Notas técnicas: lo que costó descubrir

Apuntes de las trampas reales encontradas al construir esto, con PowerShell 5.1 de
serie en Windows 10/11. Si vas a tocar el código, esto te ahorra horas.

## 1. `ConvertTo-Json` de PowerShell 5.1 revienta con `OutOfMemoryException`

Con el objeto de la auditoría (unas 40 claves anidadas, ~30 KB) `ConvertTo-Json`
lanza `System.OutOfMemoryException` y tarda **minutos** en morir. El síntoma es
traidor: el script imprime «OK» y el JSON queda de 0 bytes, porque el error es no
terminante y `$json` se queda vacío.

Serializar por bloques tampoco sirve: se cuelga igual. La solución es un
serializador propio (`app/ps/_json.ps1`: `J`, `J-Esc`, `Guardar-Json`), 40 líneas,
con límite de profundidad para que una referencia circular no cuelgue.

## 2. `Get-WinEvent -FilterHashtable` falla en silencio con culturas como es-ES

```powershell
# MAL: no filtra nada y no avisa
Get-WinEvent -FilterHashtable @{LogName='System'; Id=41,1001,6008; StartTime=$ini}
```

Cuando el hash contiene **arrays** (`Id=1,2` o `Level=1,2`) además de `StartTime`,
PowerShell reconstruye la consulta como texto y formatea la fecha con la cultura
actual (`vi./23/10/2026`). `Get-WinEvent` la rechaza con «El formato DateTime del
siguiente valor no es válido» y devuelve eventos **sin filtrar**: en un equipo real
contaba 400 «errores de los últimos 7 días» cuando había 57, y 17 apagones en 30
días cuando había 2.

```powershell
# BIEN: XPath con fecha ISO en UTC, independiente del idioma
$iso = $desde.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
$xp  = "*[System[(EventID=41 or EventID=1001) and TimeCreated[@SystemTime>='$iso']]]"
Get-WinEvent -LogName System -FilterXPath $xp -MaxEvents 30
```

## 3. Los trabajos de PowerShell bloquean más de lo que parece

`Start-Job` + `Wait-Job -Timeout` + `Remove-Job -Force` espera a que el trabajo
muera de verdad: con una búsqueda COM de Windows Update dentro, el script se quedó
**4 minutos** en lugar de los 45 s previstos. Nada de jobs: proceso aparte que el
proceso padre puede matar (`subprocess.Popen` + `kill`), y el script guardando su
JSON **después de cada bloque** para que un cuelgue no se lleve lo hecho.

## 4. Consultas WMI: el filtro es la diferencia

```powershell
Get-CimInstance SoftwareLicensingProduct | ...        # 19 s
Get-CimInstance SoftwareLicensingProduct -Filter "PartialProductKey IS NOT NULL AND ApplicationID='55c92734-d682-4d71-983e-d6ec3f16059f'"
                                                      # 727 ms
```

Lo mismo con `Win32_Service -Filter "StartMode='Auto'"` en vez de filtrar en
PowerShell.

## 5. Sin administrador, «no puedo» no es «está mal»

- `reagentc /info` devuelve «Este comando solo puede ejecutarse desde un símbolo del
  sistema con privilegios elevados», no un estado. Hay que detectar ese texto y
  dejar el valor en `null` (requiere administrador), no en `False` (parecería que
  WinRE está deshabilitado).
- `Get-BitLockerVolume` tarda ~5 s y sin admin da acceso denegado; el equivalente
  CIM (`root\cimv2\security\MicrosoftVolumeEncryption`) también. Va en la fase lenta
  y solo con admin.
- La salud de la batería no está en WMI sin admin (`BatteryStaticData.DesignCapacity`
  llega vacío). Vía fiable: `powercfg /batteryreport /xml` y leer `DesignCapacity` y
  `FullChargeCapacity` (primer valor no vacío; el XML repite el bloque).

## 6. Falsos positivos que hay que evitar

- **Servicios «automáticos» detenidos**: hay que excluir los de inicio diferido
  (`DelayedAutoStart`) y los de **inicio por desencadenador**. Se detectan mirando
  `HKLM\SYSTEM\CurrentControlSet\Services\<nombre>\TriggerInfo`. Sin esto, cualquier
  portátil con lector de huellas aparece con «servicios caídos» (`WbioSrvc`).
- **Eventos 41/6008** no son «pantallazos azules»: son apagados sin cerrar Windows
  (botón mantenido, batería agotada). Los pantallazos son el evento 1001. Mezclarlos
  convierte un equipo sano en una alarma roja.
- **Ruido conocido** del registro: `DistributedCOM 10010`, `TPM-WMI 1796`,
  `BitLocker-Driver 24641`. Se muestran como información, no como avería.

## 7. Detalles de Windows que muerden

- **Acentos en consola**: `chcp 65001` en el `.bat`, `SetConsoleOutputCP(65001)` y
  `sys.stdout.reconfigure(encoding='utf-8')`. Si no, el menú sale con símbolos raros
  en equipos con configuración regional española.
- **PowerShell desde Python**: para comandos sueltos, `-EncodedCommand` (base64
  UTF-16LE), así no hay infierno de comillas ni acentos. Para los `.ps1`, `-File` con
  ruta absoluta.
- **`switch` no es una expresión**: dentro de una concatenación de cadenas en PS 5.1
  da error de sintaxis. Usa un `if/elseif` o una tabla `@{}`.
- **FAT32** no admite ficheros de más de 4 GB: si el USB va a llevar ISOs de Windows,
  exFAT o NTFS, y 16 GB o más de capacidad.
- **AutoRun** está desactivado para memorias USB desde Windows 7. Cualquier programa
  que se ejecute solo al conectar un USB es un agujero de seguridad: aquí se abre a
  mano y el `autorun.inf` solo pone etiqueta e icono.

## 8. Empaquetar Python en un USB

`python-3.11.9-embed-amd64.zip` (~11 MB, ~21 MB descomprimido) trae el intérprete,
la biblioteca estándar y `vcruntime140.dll`: no necesita nada instalado en el equipo.
Solo hace falta que el código añada su propia carpeta a `sys.path` al arrancar, porque
el `._pth` del embeddido no incluye el directorio del script:

```python
RAIZ_APP = os.path.dirname(os.path.abspath(__file__))
if RAIZ_APP not in sys.path:
    sys.path.insert(0, RAIZ_APP)
```

Todo el código usa solo la biblioteca estándar (sin `requests`, sin `psutil`, sin
`pywin32`): menos dependencias, nada que instalar, nada que actualizar.

## 9. Generar un icono sin dependencias

El `.ico` se construye sin Pillow: se renderiza el diseño con Chrome en modo
*headless* a 16, 32, 48 y 256 px y se empaquetan los PNG en un contenedor ICO
(`Docs/hacer_icono.py`). Cada tamaño queda dibujado a su resolución real, no
reescalado por Windows.
