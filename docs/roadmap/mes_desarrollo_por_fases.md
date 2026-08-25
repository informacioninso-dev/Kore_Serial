# Roadmap MES Kore Serial

Kore Serial tiene como objetivo convertirse en un MES serializado para
ensamblaje en planta. El sistema no se orienta a lotes de produccion; la unidad
fisica serializada es el eje de control, trazabilidad y liberacion.

## Fase 0 - Base ordenada para MES

Estado: base implementada.

Objetivo: separar con claridad lo operativo de lo configurable y dejar una base
demo repetible para arrancar el desarrollo del MES.

Entregables:

- Configuracion concentra maestros: empresa, unidades, bodegas, ubicaciones,
  productos, versiones, lineas, estaciones, rutas, pasos, equipos y sistema.
- Produccion concentra operacion diaria: unidades, eventos, componentes,
  calidad, retrabajos y liberacion.
- Admin del tenant puede entrar a Configuracion y a los maestros necesarios.
- Usuarios operativos solo ven configuracion de maestros si tienen permisos
  explicitos.
- Populate idempotente con datos demo de planta.
- Documentacion actualizada con el objetivo MES y separacion de interfaz.
- Pruebas de regresion para navegacion y permisos base.

Criterios de salida:

- `manage.py check` sin errores.
- `manage.py makemigrations --check --dry-run` sin cambios.
- `manage.py test` pasando.
- `/produccion/` no muestra maestros como productos, versiones, lineas, rutas o
  equipos.
- `/configuracion/` muestra maestros de produccion.
- `populate_kore_serial` puede correrse varias veces sin duplicar datos.

## Fase 1 - Pantalla de estacion

Estado: implementacion inicial.

Objetivo: permitir que un operario ejecute una unidad desde una estacion de
trabajo.

Entregables:

- Selector o acceso directo a estacion.
- Escaneo/busqueda de unidad por serial.
- Vista del paso actual segun ruta.
- Acciones: iniciar, completar, fallar, pausar, reanudar y enviar a retrabajo.
- Validacion de operario autorizado y equipo habilitado.
- Registro auditable de cada accion.

Criterios de salida:

- `/produccion/estacion/` permite seleccionar estacion y buscar unidad.
- La accion valida crea `UnitStationEvent` con unidad, estacion, paso,
  operario, fecha y origen manual.
- La estacion bloquea operacion cuando el operario o equipo no estan
  habilitados.
- Completar un paso con control de calidad requerido crea un `QualityGate`
  pendiente y deja la unidad en retencion de calidad.
- Enviar a retrabajo abre un `ReworkOrder` y marca la unidad en retrabajo.

## Fase 2 - Trazabilidad as-built

Estado: implementacion inicial.

Objetivo: registrar como quedo construida cada unidad.

Entregables:

- Componentes requeridos por paso.
- Registro de serial, lote o ambos.
- Validacion de partes criticas.
- Asociacion unidad-estacion-operario-fecha.
- Expediente de unidad con eventos y componentes instalados.

Criterios de salida:

- Configuracion permite definir componentes requeridos por paso.
- El componente instalado puede vincularse al requerimiento esperado.
- La trazabilidad requerida valida serial, lote o ambos.
- El expediente de unidad muestra requerimientos, componentes instalados,
  eventos, calidad, retrabajo y liberacion.
- La liberacion aprobada se bloquea si faltan componentes requeridos.

## Fase 3 - Calidad y liberacion

Estado: implementacion inicial.

Objetivo: bloquear avance o liberacion cuando falta control de calidad.

Entregables:

- Quality gates por estacion o paso.
- Evidencia de inspeccion.
- Estados pendiente, aprobado, fallido y excepcion aprobada.
- Bloqueo de liberacion por calidad pendiente o retrabajo abierto.
- Liberacion final formal con responsable, fecha y evidencia.

Criterios de salida:

- Produccion permite revisar controles de calidad con evidencia obligatoria.
- Calidad puede aprobar, fallar o aprobar excepcion con notas cuando aplica.
- Un fallo mantiene la unidad en retencion de calidad.
- Un control aprobado o exceptuado libera la retencion si no quedan bloqueos.
- La liberacion aprobada marca la unidad como liberada.
- La liberacion rechazada mantiene la unidad en retencion de calidad.

## Fase 4 - Retrabajo controlado

Estado: implementacion inicial.

Objetivo: corregir defectos sin perder trazabilidad.

Entregables:

- Apertura de retrabajo desde estacion o calidad.
- Salida y reingreso controlado a linea.
- Reinspeccion posterior.
- Cierre con evidencia y responsable.
- Historial de defecto por unidad.

Criterios de salida:

- Produccion permite gestionar un retrabajo desde su propia pantalla.
- Un retrabajo puede pasar por abierto, en proceso, revision calidad, cerrado o
  cancelado.
- Enviar a reinspeccion genera un `QualityGate` pendiente y un evento
  `REWORK_IN` en la estacion detectada.
- El cierre exige evidencia y responsable.
- Una reinspeccion aprobada cierra el retrabajo asociado.
- Una reinspeccion fallida devuelve el retrabajo a proceso.

## Fase 5 - Planificacion de produccion

Estado: implementacion inicial.

Objetivo: convertir la demanda o necesidad de planta en planes ejecutables.

Entregables:

- Planes de produccion por producto, version, fecha y turno.
- Cantidad objetivo y unidades serializadas esperadas.
- Linea asignada, prioridad y ventana de ejecucion.
- Estados: borrador, liberado, en ejecucion, cerrado y cancelado.
- Generacion o vinculacion de unidades serializadas desde el plan.

Criterios de salida:

- Produccion permite listar, crear y editar planes de produccion.
- Un plan define version, linea, fecha, turno, cantidad objetivo, prioridad y
  ventana planificada.
- La pantalla de gestion permite liberar, iniciar, cerrar o cancelar el plan.
- El plan puede generar unidades serializadas sin superar la cantidad objetivo.
- Unidades existentes pueden vincularse al plan si corresponden a la misma
  version.
- El expediente de unidad muestra el plan asociado cuando existe.

## Fase 6 - Secuenciacion de linea

Estado: implementacion inicial.

Objetivo: ordenar la cola de ejecucion de planta.

Entregables:

- Cola de unidades por linea.
- Prioridades y secuencia sugerida.
- Asignacion unidad-linea-ruta.
- Vista de proximos trabajos por estacion.
- Reordenamiento manual con auditoria.

Criterios de salida:

- Produccion permite listar y filtrar la secuencia por linea, estado y proxima
  estacion.
- Un plan liberado o en ejecucion puede generar items de secuencia para sus
  unidades.
- Cada item asigna unidad, plan, linea, ruta, prioridad, estado y posicion.
- Existe vista de proximos trabajos agrupados por estacion.
- La pantalla de gestion permite mover posicion, marcar lista, retener o
  cancelar.
- El reordenamiento manual registra bitacora operativa con actor, posicion
  anterior, posicion nueva y motivo.

## Fase 7 - Integracion con equipos

Estado: implementacion inicial.

Objetivo: recibir datos reales desde planta mediante API y recolectores.

Entregables:

- API de eventos externos.
- Integracion por collector para scanners, torquimetros, PLC, bancos de prueba
  e impresoras.
- Validacion de calibracion, mantenimiento y habilitacion de operarios.
- Asociacion automatica equipo-estacion-unidad-evento.

## Fase 8 - Panel de planta

Estado: implementacion inicial.

Objetivo: dar visibilidad operacional a supervisores.

Entregables:

- Dashboard por linea.
- Estado por estacion.
- Unidades en proceso.
- Calidad pendiente.
- Retrabajos abiertos.
- Alertas y primeras senales tipo andon.

## Fase 9 - API MES formal

Estado: implementacion inicial.

Objetivo: estabilizar contratos para terminales, apps y recolectores.

Entregables:

- API para consultar unidad.
- API para paso actual.
- API para registrar evento.
- API para instalar componente.
- API para registrar calidad.
- API para equipos externos.
- Tokens y permisos por integracion.

## Fase 10 - Indicadores MES

Estado: implementacion inicial.

Objetivo: medir desempeno de planta.

Entregables:

- Tiempo por unidad y estacion.
- Takt real contra takt objetivo.
- Retrabajos por causa.
- Fallas por estacion.
- Productividad por linea.
- Base para OEE.

## Fase 11 - Balanceo de linea

Objetivo: ajustar la carga de trabajo contra capacidad real y takt objetivo.

Entregables:

- Tiempos estandar por paso y estacion.
- Carga por estacion contra capacidad por turno.
- Deteccion de cuellos de botella.
- Simulacion de redistribucion de pasos.
- Comparacion takt objetivo contra takt real.
- Recomendaciones de balanceo por linea, producto o version.

## Fase 12 - MES avanzado

Objetivo: robustez industrial.

Entregables:

- Andon formal.
- Paros y causas.
- Modo offline por estacion.
- Sincronizacion posterior.
- Modelos mixtos.
- Integracion avanzada con kits CKD, inventario y planificacion externa.
