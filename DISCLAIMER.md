# Aviso legal y limitación de responsabilidad

## 0. Responsabilidad única y exclusiva del usuario

**EL USO DE ESTE PROGRAMA ES BAJO LA RESPONSABILIDAD ÚNICA Y EXCLUSIVA DE QUIEN LO
EJECUTA.** Antes de usarlo por primera vez, el programa muestra este aviso y exige una
respuesta explícita: **ACEPTO** o **REHUSO**. Si se rehúsa, el programa se cierra y no
ejecuta ninguna acción. La decisión queda registrada en `logs/aceptaciones.jsonl`
(fecha, equipo, usuario y versión), de modo que siempre puede saberse quién aceptó y
cuándo en cada máquina.

Nadie más —ni el autor, ni los colaboradores, ni el proveedor del modelo de IA— responde
de las consecuencias del uso: ni de los daños en el equipo, ni de la pérdida de datos,
ni del uso indebido en equipos ajenos, ni del incumplimiento de normas internas o
legales en que se incurra al ejecutarlo.

**HERMES-RESCATE** es un proyecto de [Neuraladvance.net](https://neuraladvance.net)
publicado con licencia MIT. Léelo antes de usarlo en un equipo que no sea tuyo.

## 1. Se entrega «tal cual», sin garantía

El software se proporciona **sin garantía de ningún tipo**, expresa o implícita,
incluidas —sin limitarse a ellas— las garantías de comerciabilidad, idoneidad para
un fin concreto y ausencia de infracción. No se garantiza que funcione sin errores,
que interrumpa su actividad ante fallos ni que sea compatible con todos los equipos,
versiones de Windows, configuraciones o *firmware*.

## 2. Uso bajo tu responsabilidad

HERMES-RESCATE **modifica la configuración del sistema operativo** cuando se le pide:
limpia archivos temporales, reinicia servicios, reinicia componentes de Windows Update,
restablece la red, instala actualizaciones y controladores, y activa o desactiva
funciones de seguridad. Aunque cada acción indica su nivel de riesgo y las que cambian
configuración piden confirmación, **el resultado puede no ser el esperado** por
diferencias de hardware, controladores de terceros, software de seguridad o políticas
de la organización.

**Antes de ejecutar cualquier reparación, haz una copia de seguridad de los datos del
equipo.** El programa no hace copias de seguridad de tus archivos y no sustituye a una.

## 3. Necesitas autorización sobre el equipo

Usa esta herramienta **solo en equipos propios o en equipos sobre los que tengas
autorización expresa y por escrito del responsable**. Acceder, auditar o modificar un
sistema sin permiso puede ser ilegal según la legislación aplicable, con independencia
de que el equipo esté físicamente a tu alcance.

## 4. Datos personales y confidencialidad

Los informes (`informes/`) y los registros (`logs/`) contienen **datos del equipo
auditado**: nombre del equipo, usuario, número de serie, direcciones MAC e IP,
programas instalados, eventos del sistema y configuración de red. En muchos casos
estos datos son datos personales según el RGPD y la LOPDGDD.

Quien ejecuta el programa es el **responsable del tratamiento** de esos datos: debe
guardarlos de forma segura, no publicarlos, entregarlos solo a quien corresponda y
borrarlos cuando ya no sean necesarios. El autor del software no recibe, almacena ni
trata esos datos: todo se queda en el USB donde se ejecuta.

Si activas el modo de IA, un resumen del equipo se envía al proveedor del modelo que
hayas configurado. El programa avisa antes de enviar y sustituye los identificadores
(nombre de equipo, usuario, dominio, serie, MAC e IP) por marcadores, pero **la
decisión y la responsabilidad de ese envío son tuyas**, así como las condiciones del
proveedor que elijas.

## 5. Componentes de terceros

- **Python** (embebido, descargado de python.org) se distribuye bajo la licencia PSF.
- **Windows Update**, **winget** y los paquetes que instala se rigen por las
  licencias y condiciones de Microsoft y de cada fabricante.
- **Los modelos de IA** que configures se rigen por los términos de su proveedor.
- Este repositorio **no incluye** imágenes ISO, controladores ni software de terceros.
  Las instrucciones de `Docs/MODO-FRIO.txt` remiten a las fuentes oficiales.

## 6. La IA puede equivocarse

El diagnóstico del programa es determinista (reglas sobre datos reales), pero el modo
conversacional se apoya en un modelo de lenguaje que **puede producir explicaciones
incorrectas**. Por eso el agente **solo puede ejecutar acciones del catálogo** y
siempre con confirmación humana, y por eso nada se ejecuta por su cuenta. Verifica
siempre lo que te diga un modelo antes de actuar.

## 7. No es una herramienta forense ni certificada

HERMES-RESCATE es una utilidad de mantenimiento. No está pensada para análisis
forense, no preserva la cadena de custodia, no emite certificaciones y no sustituye
el diagnóstico de un servicio técnico ni de un peritaje.

## 8. Límite de responsabilidad

En la máxima medida permitida por la ley aplicable, **Neuraladvance.net y los
colaboradores del proyecto no serán responsables** de daños directos, indirectos,
incidentales, especiales o consecuentes —incluida la pérdida de datos, de
beneficios, de negocio o la interrupción de la actividad— derivados del uso o de la
imposibilidad de uso de este software, aunque se hubiera advertido de la posibilidad
de tales daños.

Esta limitación no excluye ni limita la responsabilidad en los supuestos en que la ley
no permita excluirla (por ejemplo, dolo o negligencia grave, o daños a la vida o a la
salud), ni los derechos que la normativa de consumo reconozca al usuario final.

## 9. Licencia

El código se publica bajo licencia **MIT** (ver `LICENSE`): puedes usarlo, modificarlo
y redistribuirlo, conservando el aviso de copyright y de licencia. La licencia MIT
incluye su propia cláusula de exención de garantía, que se aplica junto con este aviso.

---

*Última actualización: noviembre de 2026. Proyecto: https://neuraladvance.net*
