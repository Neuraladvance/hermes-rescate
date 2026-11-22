# -*- coding: utf-8 -*-
"""Simulación completa de HERMES-RESCATE: busca bugs sin tocar el equipo.

Recorre todas las opciones del menú y todas las órdenes de la línea de comandos con
dobles de prueba en lugar de las acciones que modifican el sistema: no se ejecuta
ninguna reparación, ni instalación, ni actualización real. Lo único real es la
auditoría (lectura) y la consulta a Windows Update (lectura).

Uso:  runtime\\python\\python.exe tests\\simulacion.py [-v]
"""
import ast
import builtins
import io
import json
import os
import py_compile
import sys
import traceback

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "app")
sys.path.insert(0, APP)

VERBOSE = "-v" in sys.argv
resultados = []


def check(nombre, funcion):
    """Ejecuta una comprobación y apunta el resultado."""
    try:
        detalle = funcion()
        resultados.append((True, nombre, detalle or ""))
        print("  ✓ %-58s %s" % (nombre, detalle or ""))
    except Exception as exc:
        resultados.append((False, nombre, "%s: %s" % (type(exc).__name__, exc)))
        print("  ✗ %-58s %s" % (nombre, "%s: %s" % (type(exc).__name__, exc)))
        if VERBOSE:
            traceback.print_exc()


def seccion(texto):
    print()
    print("-" * 78)
    print(" " + texto)
    print("-" * 78)


# ====================================================================== A. codigo
def marcadores(texto):
    total, i = 0, 0
    while i < len(texto):
        if texto[i] == "%":
            if i + 1 < len(texto) and texto[i + 1] == "%":
                i += 2
                continue
            j = i + 1
            while j < len(texto) and texto[j] in "0123456789.-+ #":
                j += 1
            if j < len(texto) and texto[j] in "sdrifgxXoeEc":
                total += 1
                i = j + 1
                continue
        i += 1
    return total


def compilar_todo():
    """Compila el fuente en memoria (py_compile no puede escribir en NUL en Windows)."""
    fallos = []
    total = 0
    for carpeta, _, ficheros in os.walk(APP):
        for nombre in ficheros:
            if not nombre.endswith(".py"):
                continue
            ruta = os.path.join(carpeta, nombre)
            total += 1
            try:
                compile(io.open(ruta, encoding="utf-8").read(), ruta, "exec")
            except SyntaxError as exc:
                fallos.append("%s:%s %s" % (nombre, exc.lineno, exc.msg))
    if fallos:
        raise AssertionError("; ".join(fallos))
    return "%d ficheros .py" % total


def formatos_rotos():
    problemas = []
    for carpeta, _, ficheros in os.walk(APP):
        for nombre in ficheros:
            if not nombre.endswith(".py"):
                continue
            ruta = os.path.join(carpeta, nombre)
            arbol = ast.parse(io.open(ruta, encoding="utf-8").read())
            for nodo in ast.walk(arbol):
                if not (isinstance(nodo, ast.BinOp) and isinstance(nodo.op, ast.Mod)):
                    continue
                if not (isinstance(nodo.left, ast.Constant)
                        and isinstance(nodo.left.value, str)):
                    continue
                esperados = marcadores(nodo.left.value)
                dados = (len(nodo.right.elts) if isinstance(nodo.right, ast.Tuple) else 1)
                if esperados != dados:
                    problemas.append("%s:%d (%d vs %d)" % (nombre, nodo.lineno, esperados, dados))
    if problemas:
        raise AssertionError("; ".join(problemas))
    return "0 mensajes con el formato roto"


# ====================================================================== B. catalogo
def catalogo_completo():
    from nucleo import reparaciones
    obligatorios = ("id", "nombre", "nivel", "que", "cuando", "accion", "categoria")
    problemas = []
    for rid, r in reparaciones.CATALOGO.items():
        for campo in obligatorios:
            if not r.get(campo):
                problemas.append("%s sin %s" % (rid, campo))
        if r.get("nivel") not in (1, 2, 3):
            problemas.append("%s nivel=%r" % (rid, r.get("nivel")))
        if not callable(r.get("accion")):
            problemas.append("%s accion no invocable" % rid)
        if reparaciones.obtener(rid) is not r:
            problemas.append("%s no se recupera con obtener()" % rid)
    if problemas:
        raise AssertionError("; ".join(problemas))
    por_nivel = {}
    for r in reparaciones.CATALOGO.values():
        por_nivel[r["nivel"]] = por_nivel.get(r["nivel"], 0) + 1
    return "%d acciones · niveles %s" % (len(reparaciones.CATALOGO), por_nivel)


def catalogo_ejecutar_inexistente():
    from nucleo import reparaciones
    registro = reparaciones.ejecutar("no_existe_esta_accion")
    assert registro["ok"] is False, "una acción inexistente no debe darse por buena"
    return "rechaza ids inexistentes"


# ====================================================================== C. diagnostico
def diagnostico_fuzz():
    """Quita claves y mete basura: ninguna regla debe romper."""
    from nucleo import diagnostico
    real = DATOS
    problemas = []
    claves = [k for k in real.keys() if not k.startswith("_")]
    casos = [("datos vacíos", {}), ("None", None),
             ("solo so", {"so": {}}),
             ("valores raros", {"so": {"nombre": None, "build": "x"},
                                "discos": [{}], "bateria": {"salud_pct": "raro"},
                                "hosts": {"entradas": None}, "eventos": None})]
    for clave in claves:
        copia = {k: v for k, v in real.items() if k != clave}
        casos.append(("sin %s" % clave, copia))
    for nombre, datos in casos:
        try:
            hallazgos, resumen = diagnostico.evaluar(datos)
            assert isinstance(hallazgos, list) and isinstance(resumen, dict)
            for h in hallazgos:
                assert h.get("severidad") in ("critico", "aviso", "info"), h
        except Exception as exc:
            problemas.append("%s → %s: %s" % (nombre, type(exc).__name__, exc))
    if problemas:
        raise AssertionError(" | ".join(problemas[:4]))
    return "%d escenarios sin excepción" % len(casos)


def recomendadas_solo_validas():
    from nucleo import diagnostico, reparaciones
    ids = diagnostico.recomendadas(HALLAZGOS)
    invalidas = [i for i in ids if reparaciones.obtener(i) is None]
    assert not invalidas, "recomienda acciones inexistentes: %s" % invalidas
    return "%d recomendadas, todas del catálogo" % len(ids)


def consultas_lista_blanca():
    """El canal de consultas no debe permitir nada que modifique el equipo."""
    from nucleo import consulta
    permitidas = ["Get-Process Dropbox", "Get-Process Dropbox | Select-Object Name,Responding",
                  "sc query Spooler", "ipconfig /all", "tasklist", "netstat -ano",
                  "Get-CimInstance Win32_DiskDrive | Format-Table -AutoSize", "winget list",
                  "Get-EventLog -LogName System -Newest 10", r"dir C:\Windows"]
    bloqueadas = [r"Remove-Item C:\Windows -Recurse", "Set-Service Spooler -Status Stopped",
                  "taskkill /F /IM chrome.exe", "format C:", "shutdown /r",
                  "Stop-Process -Name explorer", "Get-Process x | Remove-Item",
                  r"reg add HKLM\x /v y /d z", r"dir C:\ ; del C:\x",
                  r"Get-ChildItem | Out-File C:\x.txt", "powershell -Command Get-Process"]
    fallos = []
    for cmd in permitidas:
        ok, motivo = consulta.permitida(cmd)
        if not ok:
            fallos.append("bloquea de más: %s (%s)" % (cmd, motivo))
    for cmd in bloqueadas:
        ok, motivo = consulta.permitida(cmd)
        if ok:
            fallos.append("PERMITE: %s" % cmd)
    if fallos:
        raise AssertionError(" | ".join(fallos))
    return "%d de lectura + %d bloqueadas" % (len(permitidas), len(bloqueadas))


def acciones_con_nombre():
    """Las acciones que necesitan nombre lo validan y lo exigen."""
    from nucleo import reparaciones
    r = reparaciones.obtener("reiniciar_proceso")
    assert r and r.get("parametro"), "reiniciar_proceso debe pedir nombre"
    assert reparaciones.obtener("reiniciar_servicio").get("parametro")
    sin = reparaciones.ejecutar("reiniciar_proceso")
    malo = reparaciones.ejecutar("reiniciar_proceso", parametro="a;b|c")
    assert not sin["ok"] and not malo["ok"], "acepta nombre vacío o con caracteres raros"
    return "2 acciones con nombre · validación de nombre"


def procesos_en_la_auditoria():
    """La auditoría debe traer procesos (para responder «¿corre X?»)."""
    total = DATOS.get("procesos_total")
    if not total:
        raise AssertionError("la auditoría no trae procesos_total")
    apps = DATOS.get("procesos_apps") or []
    gordos = DATOS.get("procesos_gordos") or []
    return "%d procesos · %d con ventana · %d grandes · %d colgados" % (
        total, len(apps), len(gordos), len(DATOS.get("procesos_colgados") or []))


def modelo_solo_razonamiento():
    """Si un modelo gratuito contesta solo en «reasoning», no se pierde la respuesta."""
    import urllib.request
    from nucleo import ia

    class Falsa(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    original = urllib.request.urlopen
    cfg = {"endpoint": "https://x/v1", "modelo": "m1", "clave": "k", "temperatura": 0.2,
           "max_tokens": 50, "alternativas": ["m2"], "max_modelos": 3}
    solo_razon = {"choices": [{"message": {"content": "", "reasoning":
                                           "Pienso...\nConclusion: usa limpiar_temp."}}]}
    bueno = {"choices": [{"message": {"content": "Respuesta buena."}}]}
    casos = [([solo_razon, bueno], "m2", "Respuesta buena"),
             ([solo_razon, solo_razon], "m1", "Conclusion")]
    try:
        for respuestas, modelo_esperado, trozo in casos:
            cola = list(respuestas)

            def falso(peticion, timeout=None, _cola=cola):
                return Falsa(json.dumps(_cola.pop(0)).encode())

            urllib.request.urlopen = falso
            texto, modelo, errores = ia._peticion(cfg, [{"role": "user", "content": "hola"}])
            assert modelo == modelo_esperado, (modelo, modelo_esperado)
            assert trozo in texto, texto[:60]
    finally:
        urllib.request.urlopen = original
    return "razonamiento usado solo si no hay nada mejor"


def progreso_winget():
    """winget debe ir contando los pasos, no quedarse callado hasta el final."""
    import subprocess
    from nucleo import instalador

    salida = ("Found VLC media player [VideoLAN.VLC] Version 3.0.21\r"
              "Downloading https://x/vlc.exe\r"
              "  ####    5%\r  ######## 17%\r  ############## 40%\r  ######## 100%\r"
              "Successfully verified installer hash\r"
              "Starting package install...\r"
              "Successfully installed\r")

    class ProcesoFalso:
        def __init__(self):
            self.datos = salida.encode("utf-8")
            self.pos = 0
            self.returncode = 0
            padre = self

            class _Out:
                def read(self, n=1):
                    trozo = padre.datos[padre.pos:padre.pos + n]
                    padre.pos += n
                    return trozo

            self.stdout = _Out()

        def wait(self):
            return 0

        def kill(self):
            pass

    class PopenFalso:
        def __init__(self, argumentos, **kwargs):
            self._p = ProcesoFalso()

        def __getattr__(self, nombre):
            return getattr(self._p, nombre)

    original = subprocess.Popen
    pasos = []
    try:
        subprocess.Popen = PopenFalso
        ok, texto = instalador.instalar("VideoLAN.VLC", aviso=pasos.append)
    finally:
        subprocess.Popen = original
    if not ok:
        raise AssertionError("debería darse por bueno")
    faltan = [lo for lo in ("Paquete encontrado", "Descargando", "verificada", "Instalando",
                            "Instalado") if not any(lo in p for p in pasos)]
    if faltan:
        raise AssertionError("no avisa de: %s" % ", ".join(faltan))
    porcentajes = sum(1 for p in pasos if "%" in p)
    if porcentajes < 3:
        raise AssertionError("no muestra el porcentaje de descarga")
    return "%d avisos · %d con porcentaje" % (len(pasos), porcentajes)


def restos_desinstalacion():
    """Detecta restos de una desinstalación y no toca lo compartido."""
    from nucleo import desinstalador as d

    programa = {"nombre": "FooSoft Editor 3", "editor": "FooSoft",
                "ubicacion": r"C:\Program Files\FooSoft"}
    antes = {
        "programas": [{"nombre": "FooSoft Editor 3", "ubicacion": r"C:\Program Files\FooSoft"},
                      {"nombre": "BarCad 2026", "ubicacion": r"C:\Program Files\FooSoft\shared"}],
        "carpetas": [{"ruta": r"C:\Program Files\FooSoft\shared", "carpeta": "shared"},
                     {"ruta": r"C:\ProgramData\FooSoft", "carpeta": "FooSoft"},
                     {"ruta": r"C:\Program Files\Common Files", "carpeta": "Common Files"}],
        "software": [{"clave": "HKLM:\\SOFTWARE\\FooSoft", "nombre": "FooSoft"},
                     {"clave": "HKLM:\\SOFTWARE\\Microsoft", "nombre": "Microsoft"}],
        "servicios": [{"nombre": "FooSoftSvc", "visible": "FooSoft Updater"},
                      {"nombre": "Spooler", "visible": "Cola de impresión"}],
        "tareas": [{"ruta": "\\FooSoft\\Actualizar"}, {"ruta": "\\Microsoft\\Windows\\Defrag"}],
    }
    despues = {
        "programas": [{"nombre": "BarCad 2026", "ubicacion": r"C:\Program Files\FooSoft\shared"}],
        "carpetas": antes["carpetas"],
        "software": antes["software"],
        "servicios": antes["servicios"],
        "tareas": [{"ruta": "\\Microsoft\\Windows\\Defrag"}],
    }
    quedan = d.restos(programa, antes, despues)
    nombres = {(e["tipo"], e.get("nombre")) for e in quedan}
    esperados = {("carpeta", "FooSoft"), ("carpeta", "shared"), ("registro", "FooSoft"),
                 ("servicio", "FooSoft Updater"), ("tarea", "\\FooSoft\\Actualizar")}
    faltan = esperados - nombres
    if faltan:
        raise AssertionError("no detecta: %s" % faltan)
    sobra = [n for n in nombres if n[1] in ("Microsoft", "Common Files", "Spooler")
             or (n[1] and "Defrag" in n[1])]
    if sobra:
        raise AssertionError("marca como resto algo del sistema: %s" % sobra)
    compartidas = [e for e in quedan if e.get("nombre") == "shared"]
    if not compartidas or not compartidas[0]["compartida"]:
        raise AssertionError("no avisa de que la carpeta la usa otro programa")
    borrables = [e for e in quedan if not e["intocable"] and not e["compartida"]]
    if any(e.get("nombre") == "shared" for e in borrables):
        raise AssertionError("pretende borrar una carpeta compartida")
    return "%d restos · %d borrables · %d compartidos" % (
        len(quedan), len(borrables), len(quedan) - len(borrables))


# ====================================================================== D. informe
def informe_se_genera():
    import rescate
    antes = set(os.listdir(rescate.util.INFORMES))
    registro = rescate.informar(DATOS, HALLAZGOS, RESUMEN)
    llamadas = registro if isinstance(registro, (list, tuple)) else []
    nuevos = sorted(set(os.listdir(rescate.util.INFORMES)) - antes)
    if not nuevos:
        raise AssertionError("no se escribió ningún informe")
    rutas = [os.path.join(rescate.util.INFORMES, n) for n in nuevos]
    vacios = [r for r in rutas if os.path.getsize(r) < 500]
    assert not vacios, "informes casi vacíos: %s" % vacios
    html = [r for r in rutas if r.endswith(".html")]
    if html:
        texto = io.open(html[0], encoding="utf-8").read()
        for marca in ("Traceback", "None<", "%s"):
            assert marca not in texto, "el HTML contiene %r" % marca
    return "%d ficheros (%s)" % (len(rutas), ", ".join(sorted({os.path.splitext(r)[1] for r in rutas})))


def informe_datos_vacios():
    import rescate
    rescate.informar({}, [], {"veredicto": "?"})
    return "no rompe con datos vacíos"


# ====================================================================== E. menu
def menu_completo():
    """Pulsa las 9 opciones. Lo que modifica, con dobles de prueba."""
    import rescate
    from nucleo import ia, instalador, reparaciones, wifi

    # --- dobles: nada real
    registro = {"ejecutar": [], "instalar": [], "actualizar": [], "red": []}
    real_ejecutar = reparaciones.ejecutar

    def falso_ejecutar(rid, aviso=None):
        registro["ejecutar"].append(rid)
        return {"id": rid, "ok": True, "mensaje": "simulado", "segundos": 0.1,
                "nivel": (reparaciones.obtener(rid) or {}).get("nivel", 1)}

    reparaciones.ejecutar = falso_ejecutar
    instalador.instalar = lambda p: (registro["instalar"].append(p), (True, "simulado"))[1]
    instalador.actualizar_windows = lambda **k: (registro["actualizar"].append(k),
                                                {"hechas": [], "fallidas": []})[1]
    instalador.buscar_actualizaciones = lambda **k: {
        "completo": True, "pendientes": [
            {"titulo": "Acumulativa", "mb": 100.0, "tipo": "actualizacion"},
            {"titulo": "Intel - System", "mb": 5.0, "tipo": "controlador"},
            {"titulo": "HP - Firmware", "mb": 20.0, "tipo": "firmware"}],
        "grupos": {"actualizaciones": 1, "controladores": 1, "firmware": 1}}
    wifi.adaptador_wifi = lambda: {"interfaz": "Wi-Fi"}
    wifi.estado_conexion = lambda: "conectado (simulado)"
    wifi.cargar = lambda: {"redes": [{"nombre": "prueba", "ssid": "prueba", "clave": "obf:x"}]}
    wifi.conectar = lambda *a, **k: (registro["red"].append(a), (True, "simulado"))[1]
    wifi.escanear = lambda *a, **k: [{"ssid": "vecina", "senal": 80, "seguridad": "WPA2"}]
    ia.config = lambda: {"endpoint": "https://x/v1", "modelo": "m", "clave": "k",
                         "alternativas": [], "max_modelos": 3, "cifrada": False,
                         "temperatura": 0.2, "max_tokens": 100, "aviso_privacidad": True}
    ia.hay_clave_cifrada = lambda: False
    ia.desbloqueada = lambda: False
    ia.modelos = lambda cfg: ["modelo-1"]
    ia.probar = lambda cfg=None: (True, " 1. ✓ modelo-1 → OK")

    class AgenteFalso:
        ultimos_errores = []
        ultimo_modelo = "modelo-1"
        ultimas_consultas = []

        def __init__(self, *a, **k):
            pass

        def aviso_privacidad(self):
            return "  (aviso de privacidad simulado)"

        def preguntar(self, texto):
            if "falla" in texto:
                raise RuntimeError("Ningún modelo respondió (simulado)")
            return "respuesta simulada\nACCION: limpiar_temp", ["limpiar_temp"]

    ia.Agente = AgenteFalso

    # --- auditoría real ya hecha: se reutiliza
    rescate.ejecutar_auditoria = lambda: (DATOS, HALLAZGOS, RESUMEN)
    os.startfile_original = os.startfile
    os.startfile = lambda *a, **k: None

    fallos = []
    entradas = {
        "1": ["0"],                       # revisar + informe
        "2": ["n"] * 12 + ["0"],          # reparar lo recomendado (todo a no)
        "3": ["n", "n", "n", "0"],        # wifi
        "4": ["n", "n", "n", "0"],        # actualizaciones: no a los tres grupos
        "5": ["0", "0"],                  # instalar programas: volver
        "6": ["0", "0"],                  # catálogo: volver
        "7": ["n", "0", "salir", "0"],    # IA sin enviar
        "8": ["0"],                       # abrir informes
        "9": ["n", "0"],                  # aviso legal
        "z": ["0"],                       # opción inexistente
    }
    for opcion, respuestas in entradas.items():
        gen = iter(respuestas)
        builtins.input = lambda *a, **k: next(gen, "0")
        try:
            rescate.menu_principal() if opcion == "1" else _opcion_suelta(opcion)
        except Exception as exc:
            fallos.append("opción %s → %s: %s" % (opcion, type(exc).__name__, exc))

    reparaciones.ejecutar = real_ejecutar
    os.startfile = os.startfile_original
    if fallos:
        raise AssertionError(" | ".join(fallos))
    return ("9 opciones sin excepción · ejecutadas=%d instaladas=%d actualizaciones=%d red=%d"
            % (len(registro["ejecutar"]), len(registro["instalar"]),
               len(registro["actualizar"]), len(registro["red"])))


def _opcion_suelta(opcion):
    """Ejecuta una opción concreta del menú sin entrar en el bucle."""
    import rescate
    if opcion == "2":
        rescate.aplicar_recomendadas(DATOS, HALLAZGOS, RESUMEN)
    elif opcion == "3":
        rescate.menu_wifi()
    elif opcion == "4":
        rescate.menu_actualizar()
    elif opcion == "5":
        rescate.menu_instalar()
    elif opcion == "6":
        rescate.menu_catalogo(DATOS, HALLAZGOS, RESUMEN)
    elif opcion == "7":
        rescate.menu_chat(DATOS, HALLAZGOS, RESUMEN)
    elif opcion == "8":
        os.startfile(rescate.util.INFORMES)
    elif opcion == "9":
        rescate.menu_aviso()
    else:
        print("  Opción no válida.")


def menu_nada_sin_permiso():
    """Con todas las respuestas a 'no', no debe ejecutarse ninguna reparación."""
    import rescate
    from nucleo import reparaciones
    real = reparaciones.ejecutar
    llamadas = []
    reparaciones.ejecutar = lambda rid, aviso=None: (llamadas.append(rid),
                                                     {"id": rid, "ok": True, "mensaje": "",
                                                      "segundos": 0, "nivel": 1})[1]
    gen = iter(["n"] * 20)
    builtins.input = lambda *a, **k: next(gen, "n")
    rescate.aplicar_recomendadas(DATOS, HALLAZGOS, RESUMEN)
    reparaciones.ejecutar = real
    if llamadas:
        raise AssertionError("se ejecutó sin permiso: %s" % llamadas)
    return "0 reparaciones con todo a «no»"


# ====================================================================== F. CLI
def cli_completa():
    import rescate
    from nucleo import instalador, reparaciones, wifi

    real = (reparaciones.ejecutar, instalador.instalar, instalador.actualizar_windows)
    ejecutadas = []
    reparaciones.ejecutar = lambda rid, aviso=None: (ejecutadas.append(rid),
                                                     {"id": rid, "ok": True, "mensaje": "",
                                                      "segundos": 0, "nivel": 1})[1]
    instalador.instalar = lambda p: (True, "simulado")
    instalador.actualizar_windows = lambda **k: {"hechas": [], "fallidas": []}
    wifi.cargar = lambda: {"redes": []}

    ordenes = [
        ["--listar"], ["--estado"], ["--aviso"], ["--ia-probar"],
        ["--reparar", "limpiar_temp"], ["--reparar", "no_existe"],
        ["--instalar", "7zip.7zip"], ["--instalar"],
        ["--drivers"], ["--actualizar"],
    ]
    fallos = []
    for orden in ordenes:
        gen = iter(["S"])
        builtins.input = lambda *a, **k: next(gen, "S")
        sys.argv = ["rescate.py"] + orden
        try:
            codigo = rescate.main()
            if codigo not in (0, 1, 2):
                fallos.append("%s → código raro %r" % (" ".join(orden), codigo))
        except SystemExit as exc:
            if exc.code not in (0, 1, 2):
                fallos.append("%s → SystemExit %r" % (" ".join(orden), exc.code))
        except Exception as exc:
            fallos.append("%s → %s: %s" % (" ".join(orden), type(exc).__name__, exc))
    reparaciones.ejecutar, instalador.instalar, instalador.actualizar_windows = real
    if fallos:
        raise AssertionError(" | ".join(fallos))
    return "%d órdenes sin excepción" % len(ordenes)


def cli_sin_aceptar():
    """Con 'N' en el aviso legal, ninguna orden debe ejecutarse."""
    import rescate
    from nucleo import reparaciones
    real = reparaciones.ejecutar
    llamadas = []
    reparaciones.ejecutar = lambda rid, aviso=None: (llamadas.append(rid), {"ok": True})[1]
    gen = iter(["N"])
    builtins.input = lambda *a, **k: next(gen, "N")
    sys.argv = ["rescate.py", "--reparar", "limpiar_temp"]
    codigo = rescate.main()
    reparaciones.ejecutar = real
    assert codigo == 2, "debería salir con 2 al rehusar, salió %r" % codigo
    assert not llamadas, "ejecutó una reparación sin aceptar el aviso"
    return "rehusar → código 2, 0 reparaciones"


# ====================================================================== principal
if __name__ == "__main__":
    print("=" * 78)
    print(" SIMULACIÓN COMPLETA · HERMES-RESCATE")
    print(" Nada de lo que se prueba aquí modifica el equipo.")
    print("=" * 78)

    seccion("A. Código")
    check("Todos los módulos compilan", compilar_todo)
    check("Mensajes con formato correcto (%s vs argumentos)", formatos_rotos)

    seccion("C. Diagnóstico")
    from nucleo import auditoria, diagnostico
    print("  (auditoría real de lectura, puede tardar ~20 s...)")
    DATOS = auditoria.auditar(con_lento=False)
    HALLAZGOS, RESUMEN = diagnostico.evaluar(DATOS)
    print("  auditoría: %d bloques · %d hallazgos · veredicto %r"
          % (len(DATOS), len(HALLAZGOS), RESUMEN.get("veredicto")))
    check("Reglas robustas ante datos raros o ausentes", diagnostico_fuzz)
    check("Las recomendaciones existen en el catálogo", recomendadas_solo_validas)

    seccion("C2. Consultas de solo lectura y acciones con nombre")
    check("Lista blanca de consultas", consultas_lista_blanca)
    check("Acciones que piden nombre", acciones_con_nombre)
    check("Procesos en la auditoría", procesos_en_la_auditoria)
    check("Respuesta solo en «reasoning»", modelo_solo_razonamiento)
    check("Progreso de winget paso a paso", progreso_winget)
    check("Restos de una desinstalación (compartidos a salvo)", restos_desinstalacion)

    seccion("B. Catálogo de reparaciones")
    check("Catálogo íntegro", catalogo_completo)
    check("Ejecutar un id inexistente no rompe", catalogo_ejecutar_inexistente)

    seccion("D. Informes")
    check("Se generan HTML/MD/JSON", informe_se_genera)
    check("No rompe con datos vacíos", informe_datos_vacios)

    seccion("E. Menú (9 opciones)")
    check("Recorrido de todas las opciones", menu_completo)
    check("Sin permiso no se ejecuta nada", menu_nada_sin_permiso)

    seccion("F. Línea de comandos")
    check("Todas las órdenes", cli_completa)
    check("Rehusar el aviso bloquea la ejecución", cli_sin_aceptar)

    total = len(resultados)
    bien = sum(1 for ok, _, _ in resultados if ok)
    print()
    print("=" * 78)
    print(" RESULTADO: %d/%d comprobaciones correctas" % (bien, total))
    for ok, nombre, detalle in resultados:
        if not ok:
            print("   ✗ %s → %s" % (nombre, detalle))
    print("=" * 78)
    sys.exit(0 if bien == total else 1)
