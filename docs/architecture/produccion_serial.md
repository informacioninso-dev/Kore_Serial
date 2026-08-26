# Produccion Serial

Kore Line usa **Produccion** como nombre visible del modulo, pero la app
Django principal sigue siendo `assembly`. La razon es tecnica y funcional:
Kore ERP ya usa produccion con una logica por lotes, mientras que Kore Line
controla unidades fisicas individuales.

## Principio central

Una unidad no es un lote. El lote puede existir para partes, kits, consumibles o
contenedores CKD, pero la unidad ensamblada mantiene identidad propia por numero
de serie o VIN.

## Dominio base

- `AssembledProduct`: familia o modelo fabricable.
- `ProductVersion`: configuracion concreta del producto.
- `Plant`: planta fisica donde se ejecuta produccion.
- `PlantArea`: area operacional dentro de una planta.
- `ProductionOrder`: orden de produccion que agrupa demanda, producto,
  version, planta, planes y unidades.
- `ProductionPlan`: demanda ejecutable por version, linea, fecha y turno.
- `SerializedUnit`: ejemplar fisico individual.
- `ProductionQueueItem`: posicion operativa de una unidad en la cola de linea.
- `LineBalanceStudy`: estudio calculado de carga por estacion contra takt,
  capacidad de turno y datos reales.
- `ModelMixPlan` y `ModelMixPlanItem`: planificacion de versiones distintas en
  una misma linea.
- `AndonSignal`: senal formal de alerta o escalamiento operacional.
- `ProductionDowntime`: paro de linea o estacion con causa, duracion y cierre.
- `StationOfflineEvent`: captura local pendiente de sincronizacion posterior.
- `ExternalMaterialKit`: kit CKD o material externo ligado a version, plan o
  linea.
- `AssemblyLine`: linea de ensamblaje.
- `AssemblyStation`: estacion de trabajo dentro de una linea.
- `AssemblyRoute`: ruta productiva aplicable a una version.
- `AssemblyRouteStep`: paso de ruta ejecutado en una estacion.
- `RouteStepParameter`: parametro esperado por paso, con rango, origen y
  criticidad.
- `RouteStepComponentRequirement`: componente esperado por paso de ruta, con
  cantidad, criticidad y trazabilidad requerida.
- `UnitStationEvent`: evento operacional de una unidad en una estacion.
- `ProductionMeasurement`: medicion capturada por unidad, estacion y
  parametro.
- `InstalledComponent`: componente instalado en una unidad, trazable por serial,
  lote o ambos.
- `QualityGate`: punto de control de calidad que puede bloquear liberacion.
- `ReworkOrder`: retrabajo abierto contra una unidad.
- `ReleaseApproval`: decision formal de liberacion o rechazo.

## Separacion de interfaz

Produccion debe enfocarse en ejecucion diaria: planes, secuencia, unidades, eventos,
componentes instalados, controles de calidad, retrabajos y liberacion.

Configuracion debe concentrar maestros y parametros: productos, versiones,
lineas, estaciones, rutas, pasos, equipos, unidades de medida, bodegas y
ubicaciones. Aunque varios modelos vivan tecnicamente en `assembly`, su
pantalla pertenece a Configuracion cuando define estructura o reglas antes de
operar una unidad.

## Planificacion de produccion

`/produccion/ordenes/` es el nivel formal de demanda productiva. Una
`ProductionOrder` define que producto o version se fabricara, en que planta,
con que cantidad objetivo, fecha requerida, prioridad, referencia externa y
estado.

`/produccion/planes/` convierte la OP o la necesidad de planta en planes
ejecutables. Cada `ProductionPlan` define version fabricable, linea, fecha,
turno, cantidad objetivo, prioridad, ventana planificada y estado. Si el plan
esta ligado a una OP, las unidades generadas o vinculadas heredan esa OP para
mantener avance y trazabilidad desde demanda hasta liberacion.

Estados iniciales:

- `DRAFT`: plan en preparacion;
- `RELEASED`: plan aprobado para ejecucion;
- `IN_EXECUTION`: plan activo en planta;
- `CLOSED`: plan terminado;
- `CANCELLED`: plan cancelado.

Las unidades serializadas pueden generarse desde el plan o vincularse si ya
existen. La Fase 5 no decide secuencia fina por estacion; esa cola queda para
la Fase 6.

## Secuenciacion de linea

`/produccion/secuencia/` ordena la cola operativa de unidades por linea. Cada
`ProductionQueueItem` asigna una unidad a plan, linea, ruta, secuencia,
prioridad y estado.

La secuencia se puede generar desde un plan liberado o en ejecucion. El sistema
elige la ruta activa aprobada de la version cuando existe; si no hay ruta
aprobada, usa la primera ruta activa disponible.

La vista `/produccion/secuencia/estaciones/` agrupa los proximos trabajos por
estacion segun el siguiente paso de ruta pendiente para cada unidad. El
reordenamiento manual registra bitacora operativa con posicion anterior,
posicion nueva, actor y motivo.

## Balanceo de linea

`/produccion/balanceo/` calcula si una linea puede cumplir el takt objetivo
con la ruta y la demanda planificada. Un `LineBalanceStudy` guarda parametros y
resultado para que el supervisor pueda comparar escenarios sin alterar la
secuencia operativa.

El calculo usa los pasos activos de la ruta para sumar tiempo estandar por
estacion. Con esos tiempos estima carga por turno, capacidad de unidades,
cuello de botella y eficiencia de balance. Si el estudio tiene una ventana de
datos reales, tambien compara contra eventos completados para obtener takt real
y ciclos observados.

El snapshot calculado queda guardado en el estudio junto con recomendaciones.
La simulacion inicial no mueve pasos automaticamente: propone segundos de
contenido que podrian redistribuirse desde estaciones sobre takt hacia
estaciones con holgura o hacia capacidad adicional.

## Instrucciones digitales y parametros

Cada `AssemblyRouteStep` puede guardar instrucciones de operacion, notas de
seguridad, criterios de aceptacion y una referencia documental o visual. La
consola de estacion muestra esa informacion junto al paso actual para que el
operario no tenga que interpretar el flujo desde listados administrativos.

Los `RouteStepParameter` definen que debe medirse en cada paso: codigo, nombre,
tipo, unidad, valor objetivo, minimo, maximo, origen esperado, obligatoriedad y
criticidad. El origen puede ser manual, PLC, maquina, API, OPC UA, MQTT o
sensor.

Las `ProductionMeasurement` registran el valor real por unidad, estacion y
parametro. El sistema calcula resultado aprobado, fuera de rango, pendiente o
no aplica. Una liberacion aprobada se bloquea cuando un parametro obligatorio
no existe, esta pendiente o la ultima medicion esta fuera de rango.

## Genealogia inversa

La trazabilidad no solo debe responder que componentes tiene una unidad.
Tambien debe responder que unidades quedan impactadas por un serial, lote,
parte o nombre de componente.

`/produccion/genealogia/` permite esa busqueda inversa sobre
`InstalledComponent`. Esto es clave para contenciones de calidad, retiros,
analisis de causa raiz y decisiones de liberacion por lote afectado.

## MES avanzado

`/produccion/avanzado/` agrupa los controles industriales que hacen al MES mas
robusto: Andon formal, paros, modo offline, modelos mixtos y kits externos. No
sustituye el panel principal; actua como tablero de gestion para excepciones y
planificacion extendida.

`AndonSignal` registra alertas de linea o estacion con severidad, estado,
unidad, plan y responsables. La senal puede pasar por abierta, reconocida,
resuelta o cancelada, siempre con bitacora operativa.

`ProductionDowntime` registra un paro con causa, categoria, inicio, fin,
duracion, evidencia y posible relacion a una senal Andon. Esto deja la base
para OEE real, analisis de perdidas y tiempos de respuesta.

`StationOfflineEvent` permite capturar eventos de estacion cuando una terminal
no tiene red. La sincronizacion posterior reutiliza las mismas reglas de la API
MES y crea `UnitStationEvent` con origen `OFFLINE`, manteniendo idempotencia por
identificador externo.

`ModelMixPlan` y sus items permiten planificar versiones distintas en una misma
linea. La implementacion inicial genera planes de produccion por version; la
secuencia optimizada de modelos mixtos queda para una iteracion posterior.

`ExternalMaterialKit` representa kits CKD o referencias externas, inicialmente
B22, con cantidades esperadas/recibidas y estado. El modelo evita acoplar Kore
Serial a un ERP externo: la integracion entra por datos propios del MES.

## Pantalla de estacion

`/produccion/estacion/` es la pantalla operativa de piso. No administra el
maestro de estaciones; usa una estacion ya configurada para ejecutar una unidad
contra su paso de ruta.

La pantalla registra eventos manuales (`UnitStationEvent`) para iniciar,
pausar, reanudar, completar, fallar o enviar a retrabajo. Antes de registrar
valida que el usuario este habilitado para la estacion y que los equipos
asignados puedan usarse. Cuando el paso o la estacion requiere calidad, al
completar genera un `QualityGate` pendiente y deja la unidad en retencion de
calidad. Al enviar a retrabajo crea un `ReworkOrder`.

## Trazabilidad de componentes

La recomendacion para el producto es soportar serial y lote desde el modelo:

- Partes criticas: serial obligatorio.
- Consumibles, tornilleria, quimicos o kits: lote obligatorio.
- Partes con doble trazabilidad: serial y lote.

No se debe limitar el sistema a solo serial porque varias industrias discretas
mezclan piezas serializadas con materiales controlados por lote.

Los componentes esperados se configuran como requerimientos por paso de ruta.
El expediente de unidad compara esos requerimientos contra los componentes
instalados y muestra pendientes de cantidad o trazabilidad. Una liberacion
aprobada debe bloquearse si el as-built requerido no esta completo.

## Equipos e integraciones

Los equipos de planta se registran en `core.EquipmentIntegration` y se asignan a
estaciones. Esto cubre scanners, torquimetros, impresoras, PLC, bancos de prueba
y otros equipos disponibles para mediciones o captura de eventos.

Django no abre conexiones directas contra esos equipos. Un recolector externo
debe publicar eventos a la API de Kore Line.

## Calidad y liberacion

Una unidad no deberia pasar a estado final si mantiene:

- controles de calidad bloqueantes pendientes o fallidos;
- retrabajos abiertos;
- eventos obligatorios de ruta sin completar;
- componentes criticos sin trazabilidad.

La liberacion vive como evento explicito para conservar actor, fecha, evidencia
y resultado.

La revision operativa de calidad se ejecuta desde `/produccion/calidad/`.
Cada `QualityGate` puede cerrarse como aprobado, fallido o excepcion aprobada,
con evidencia y responsable. Un resultado fallido mantiene la unidad en
retencion de calidad. Un resultado aprobado o exceptuado puede devolver la
unidad a proceso o completarla si no quedan otros bloqueos.

`ReleaseApproval` es el cierre formal posterior. Una aprobacion valida cambia
la unidad a `RELEASED`; un rechazo la deja en `QUALITY_HOLD`.

## Retrabajo controlado

`ReworkOrder` conserva el defecto, estacion detectada, responsable de apertura,
estado, evidencia de cierre y control de reinspeccion. La gestion operativa se
realiza desde `/produccion/retrabajos/`.

El flujo recomendado es:

- abrir o iniciar retrabajo y mantener la unidad en `REWORK`;
- enviar a reinspeccion con evidencia, creando un `QualityGate` pendiente y un
  evento `REWORK_IN`;
- cerrar automaticamente el retrabajo cuando la reinspeccion queda aprobada o
  exceptuada;
- devolver el retrabajo a proceso si la reinspeccion falla;
- cancelar solo con notas justificadas.
