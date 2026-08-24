# Produccion Serial

Kore Serial usa **Produccion** como nombre visible del modulo, pero la app
Django principal sigue siendo `assembly`. La razon es tecnica y funcional:
Kore ERP ya usa produccion con una logica por lotes, mientras que Kore Serial
controla unidades fisicas individuales.

## Principio central

Una unidad no es un lote. El lote puede existir para partes, kits, consumibles o
contenedores CKD, pero la unidad ensamblada mantiene identidad propia por numero
de serie o VIN.

## Dominio base

- `AssembledProduct`: familia o modelo fabricable.
- `ProductVersion`: configuracion concreta del producto.
- `ProductionPlan`: demanda ejecutable por version, linea, fecha y turno.
- `SerializedUnit`: ejemplar fisico individual.
- `ProductionQueueItem`: posicion operativa de una unidad en la cola de linea.
- `AssemblyLine`: linea de ensamblaje.
- `AssemblyStation`: estacion de trabajo dentro de una linea.
- `AssemblyRoute`: ruta productiva aplicable a una version.
- `AssemblyRouteStep`: paso de ruta ejecutado en una estacion.
- `RouteStepComponentRequirement`: componente esperado por paso de ruta, con
  cantidad, criticidad y trazabilidad requerida.
- `UnitStationEvent`: evento operacional de una unidad en una estacion.
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

`/produccion/planes/` convierte la demanda de planta en planes ejecutables.
Cada `ProductionPlan` define version fabricable, linea, fecha, turno, cantidad
objetivo, prioridad, ventana planificada y estado.

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
debe publicar eventos a la API de Kore Serial.

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
