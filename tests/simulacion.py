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
