# Kore Line

Kore Line es una plataforma industrial para ensamblaje serializado. Su primer
producto visible es un **MES** para controlar piso de planta, pero la vision
completa es mas amplia: MES, WMS, Edge, Connect, trazabilidad, eventos,
indicadores e integracion con sistemas externos.

Comparte base tecnica con Kore ERP, pero no es una extension, un modulo ni un
tenant de Kore. Kore Line debe poder operar como producto propio para plantas
de ensamblaje discreto.

Su primer caso de uso es el ensamblaje CKD de vehiculos. El modelo de dominio
no queda amarrado al sector automotriz: debe servir tambien para carrocerias,
motocicletas, linea blanca, maquinaria, electronica y otras industrias donde
cada unidad fisica necesita historia propia.

## Idea central

Una unidad no es un lote. Cada unidad fisica tiene identidad, ruta, eventos,
componentes, mediciones, defectos, retrabajos y liberacion propia.

- **Producto ensamblado:** familia o modelo fabricable.
- **Version:** configuracion concreta de un producto o modelo.
- **Unidad serializada:** ejemplar fisico individual de una version,
  identificado por numero de serie. En vehiculos ese identificador puede ser
  un VIN, pero el sistema no debe depender solo de VIN.
- **Ruta:** operaciones y estaciones por donde debe pasar la unidad.
- **As-built:** lo que realmente quedo instalado, medido, inspeccionado y
  aprobado en esa unidad.

## Vision de plataforma

Kore Line debe cubrir cuatro piezas principales.

### 1. Kore Line MES

El MES es el cerebro de ejecucion de produccion. Orquesta la planta desde la
orden hasta la liberacion final.

Debe controlar:

- Modelo de planta: empresa, planta, area, linea, estacion y equipo.
- Productos, versiones, BOM, BOP, rutas y operaciones.
- Ordenes de produccion, planes, turnos, prioridades y secuencia.
- Unidades serializadas o VIN por orden.
- Ejecucion por estacion: entrada, inicio, pausa, reanudacion, falla,
  completado y salida.
- Takt time, cycle time, lead time, wait time y downtime.
- Calidad, defectos, bloqueos, retrabajos, reinspecciones y liberacion.
- Trazabilidad y genealogia de componentes por serial, lote o ambos.
- Instrucciones digitales por modelo, estacion y operacion.
- Parametros productivos manuales o capturados desde equipos.
- KPIs de planta: plan vs real, productividad, WIP, takt, cycle time,
  defectos, retrabajos, FPY y base para OEE.

### 2. Kore WMS

Kore WMS es el cerebro logistico de la plataforma. No reemplaza el inventario
financiero de un ERP; controla el movimiento fisico operativo de materiales
para que la linea reciba lo correcto, en el lugar correcto y en el momento
correcto.

Debe cubrir:

- Maestro de materiales, SKU, familias, unidades, proveedores, lotes y series.
- Estructura fisica: planta, bodega, zona, pasillo, rack, nivel y posicion.
- Recepcion CKD, ASN, pallets, QR, contenido, inspeccion y ubicacion.
- Inventario por ubicacion: bodega, supermercado, line side, bloqueado y
  disponible.
- Movimientos trazados por origen, destino, material, cantidad, usuario,
  fecha y motivo.
- Picking, kitting, reposicion, line feeding, Kanban digital y stock min/max.
- Preparacion de materiales por serial/VIN cuando aplique.

### 3. Kore Edge

Kore Edge es el puente entre software y planta. La logica industrial de bajo
nivel no debe vivir dentro del MES Django.

Debe encargarse de:

- Comunicacion con PLC, sensores, scanners, torquimetros, bancos de prueba e
  impresoras.
- OPC UA, MQTT, Modbus TCP, APIs industriales y otros protocolos OT.
- Adquisicion, buffering, normalizacion y sincronizacion de datos.
- Health checks de equipos.
- Operacion ante perdida temporal de conexion.
- Transformar senales tecnicas de maquina en eventos de negocio, por ejemplo
  `TorqueMeasured`, `OperationCompleted` o `MachineAlarmRaised`.

Regla de arquitectura:

```text
Kore decide QUE debe hacerse.
PLC/maquina decide COMO ejecutarlo fisicamente.
```

Kore no controla directamente motores, robots ni sistemas de seguridad.

### 4. Kore Connect

Kore Connect integra Kore Line con el mundo IT.

Debe poder conectar:

- ERP.
- PLM.
- WMS externo.
- QMS.
- CMMS.
- BI.
- SAP.
- SQL Server.
- B22 cuando aplique por necesidad fiscal o documental.
- APIs de terceros.

Kore Line no debe depender operativamente de Kore ERP. La integracion externa
prevista por ahora es B22 cuando exista necesidad del negocio.

## Integracion MES + WMS

Esta es una de las partes mas valiosas de la plataforma.

Kore Line conoce la secuencia productiva y sabe que una unidad llegara a una
estacion en un tiempo aproximado. Con la version, BOM y ruta puede calcular que
material necesita, para que unidad, para que estacion y para cuando.

Flujo esperado:

```text
Kore Line
secuencia productiva
        |
        v
Kore WMS
explosion de necesidades
        |
        +-- picking
        +-- kitting
        +-- reposicion
        +-- JIS
        |
        v
Line side
```

El objetivo es que produccion y logistica trabajen sobre la misma verdad
operativa.

## Poka-yoke logistico

El sistema debe evitar errores de instalacion mediante validacion operativa:

```text
Operador escanea unidad/VIN
        +
Operador escanea pieza
        |
        v
Kore valida si la pieza corresponde al modelo, version, ruta y estacion
```

Resultado esperado:

- Pieza correcta: permite instalacion y registra genealogia.
- Pieza incorrecta: bloquea o alerta, dejando evidencia del intento.

Cuando una pieza se instala correctamente, un solo evento debe poder:

- Registrar genealogia en Kore Line.
- Descontar inventario fisico en Kore WMS.
- Enviar consumo o movimiento al ERP/conector cuando aplique.
- Alimentar indicadores y trazabilidad.

## Modelo de eventos

Los modulos deben comunicarse mediante eventos para evitar una plataforma
acoplada y dificil de mantener.

Ejemplo de evento:

```text
MaterialInstalled
- serial/VIN
- material
- serial o lote de pieza
- estacion
- operacion
- timestamp
- operador
```

Ese evento puede ser escuchado por:

- MES para genealogia.
- WMS para consumo.
- ERP/Connect para movimiento externo.
- Analytics para KPIs.

Un evento, varios efectos.

## Flujo industrial objetivo

```text
ERP
 |
 | orden de produccion
 v
Kore Line MES
 | OP + serial/VIN + secuencia
 |
 +-----------------------+
 |                       |
 v                       v
Kore WMS                 Kore Edge
 | necesidades           | maquinas
 | picking/kitting       | PLC/sensores
 v                       v
Line side                Estacion
 |                       |
 +-----------+-----------+
             v
        Unidad serializada
             |
     pieza + proceso + medicion
             |
      todo correcto?
        |          |
       si          no
        |          |
        v          v
 siguiente      calidad /
 estacion       retrabajo
        |          |
        +-----+----+
              v
          fin de linea
              |
          pruebas / PDI
              |
        unidad liberada
```

## Modelo de informacion central

La plataforma debe girar alrededor de pocas entidades fuertes:

| Entidad | Proposito |
| --- | --- |
| `ProductionOrder` | Que producir. |
| `ProductModel` / `AssembledProduct` | Que modelo o familia se fabrica. |
| `ProductVersion` | Configuracion concreta del producto. |
| `SerialUnit` / `SerializedUnit` | Que unidad fisica se esta construyendo. |
| `Routing` / `AssemblyRoute` | Por donde pasa la unidad. |
| `Operation` / `AssemblyRouteStep` | Que debe realizarse. |
| `Station` / `AssemblyStation` | Donde ocurre. |
| `Material` | Que pieza se necesita. |
| `Lot` / `Serial` | Que pieza concreta se instala o consume. |
| `InventoryLocation` | Donde esta el material. |
| `Equipment` | Que maquina o equipo interviene. |
| `Measurement` | Que valor produjo una maquina o inspeccion. |
| `Defect` | Que salio mal. |
| `Downtime` | Por que se detuvo la operacion. |
| `User` / `Operator` | Quien hizo que. |
| `Event` | Que ocurrio y cuando. |

Esto es mas importante que las pantallas: si el modelo de informacion queda
bien, las pantallas pueden evolucionar sin romper la plataforma.

## Alcance actual del repo

El estado actual entrega la primera base operativa del MES serializado:

- Django 5.2, Python 3.13 y PostgreSQL con `django-tenants`: un esquema por
  empresa.
- Login, membresias por empresa y permisos Django por modulo.
- Configuracion tenant: empresa, unidades, bodegas, ubicaciones e informacion
  de sistema.
- Usuarios tenant: altas, roles, permisos, activacion y reseteo de
  contrasenas.
- Maestros de produccion en Configuracion: plantas, areas, productos,
  versiones, lineas, estaciones, rutas, pasos, parametros productivos, equipos
  y componentes requeridos.
- Produccion operativa: ordenes de produccion, planes, secuencia, unidades,
  eventos, mediciones, componentes, calidad, retrabajos y liberacion.
- Pantalla de estacion para operar una unidad contra su ruta.
- Instrucciones digitales por paso con seguridad, criterio de aceptacion y
  referencia documental.
- Mediciones productivas por parametro, rango y origen esperado.
- Trazabilidad as-built por serial, lote o ambos.
- Busqueda inversa de genealogia para ubicar unidades afectadas por serial,
  lote, parte o nombre de componente.
- Calidad bloqueante, retrabajo controlado y liberacion final.
- Balanceo de linea contra takt objetivo, capacidad por turno y tiempos reales.
- MES avanzado inicial: Andon, paros, modo offline, mix de modelos y kits
  externos.
- Panel global de inicio con KPIs, tendencias, dispersion de planta y accesos
  por rol.
- Base DRF y SimpleJWT preparada para terminales y recolectores externos.
- Redis para cache y Huey como cola ligera.
- `psycopg` 3, WeasyPrint como motor PDF y configuracion base de HTMX.

## Estado de fases MES

El roadmap MES inicial vive en
[`docs/roadmap/mes_desarrollo_por_fases.md`](docs/roadmap/mes_desarrollo_por_fases.md).

Fases implementadas:

- **Fase 0 - Base ordenada para MES:** implementada.
- **Fase 1 - Pantalla de estacion:** implementacion inicial.
- **Fase 2 - Trazabilidad as-built:** implementacion inicial.
- **Fase 3 - Calidad y liberacion:** implementacion inicial.
- **Fase 4 - Retrabajo controlado:** implementacion inicial.
- **Fase 5 - Planificacion de produccion:** implementacion inicial.
- **Fase 6 - Secuenciacion de linea:** implementacion inicial.
- **Fase 7 - Integracion con equipos:** implementacion inicial.
- **Fase 8 - Panel de planta:** implementacion inicial.
- **Fase 9 - API MES formal:** implementacion inicial.
- **Fase 10 - Indicadores MES:** implementacion inicial.
- **Fase 11 - Balanceo de linea:** implementacion inicial.
- **Fase 12 - MES avanzado:** implementacion inicial.
- **Fase 13 - Cierre funcional MES:** implementacion inicial.

Fases no implementadas dentro del roadmap MES inicial:

- Ninguna. Lo pendiente ya pertenece al roadmap de plataforma.

## Roadmap macro despues del cierre MES

El documento de arquitectura base para esta vision es
[`docs/architecture/Draft.docx`](docs/architecture/Draft.docx). Ese draft debe
convertirse en el documento maestro **Kore Line v1.0**.

Siguientes fases recomendadas:

### Fase 14 - WMS base

Objetivo: controlar materiales y ubicaciones operativas.

- Maestro de materiales.
- Estructura fisica de almacen.
- Recepcion CKD.
- Inventario por ubicacion y estado.
- Movimientos trazados.
- Stock disponible, bloqueado, supermercado y line side.

### Fase 15 - Picking, kitting y line feeding

Objetivo: conectar la secuencia productiva con abastecimiento a linea.

- Misiones de picking.
- Kits por unidad, serial/VIN o plan.
- Supermercado de linea.
- Reposicion min/max.
- Kanban digital.
- Entrega a estacion.

### Fase 16 - Poka-yoke y consumo automatico

Objetivo: evitar errores de ensamble y cerrar la genealogia material.

- Escaneo de unidad y pieza.
- Validacion pieza-modelo-version-ruta-estacion.
- Bloqueo de pieza incorrecta.
- Registro de genealogia.
- Descuento de inventario operativo.
- Evento unico para MES, WMS, Connect y Analytics.

### Fase 17 - Kore Edge

Objetivo: crear el puente OT para equipos de planta.

- Collector independiente.
- Integracion inicial con scanners, torquimetros o un PLC simulado.
- Normalizacion de senales tecnicas a eventos de negocio.
- Buffer offline.
- Health checks de equipo.
- Handshake robusto para integraciones bidireccionales selectivas.

### Fase 18 - Event Bus y analitica industrial

Objetivo: desacoplar los modulos y alimentar indicadores confiables.

- Catalogo formal de eventos.
- Publicacion y consumo interno.
- Idempotencia y auditoria.
- Indicadores derivados de eventos.
- Base para OEE, MTBF, MTTR, FPY y perdidas.

### Fase 19 - Kore Connect

Objetivo: integrar sistemas IT sin contaminar la logica MES.

- Conectores ERP/BI/API.
- Integracion B22 cuando aplique.
- Contratos de entrada y salida.
- Reintentos, errores, bitacora y reconciliacion.

### Fase 20 - Piloto automotriz CIAUTO

Objetivo: demostrar una historia completa de 8 a 10 minutos.

- Crear orden de produccion.
- Cargar modelo Wingle/POER.
- Generar seriales o VIN ficticios.
- Calcular secuencia.
- Calcular piezas requeridas.
- Generar picking y kitting.
- Abastecer line side.
- Ejecutar estacion.
- Simular dato de PLC.
- Simular defecto y retrabajo.
- Asociar pieza a unidad.
- Descontar stock.
- Cerrar unidad y actualizar dashboard.

## Modulos visibles del sistema

### Inicio

Vista ejecutiva del sistema completo. Debe mostrar KPIs, tendencias, dispersion
de planta, pendientes por rol y accesos directos a acciones relevantes.

### Produccion

Modulo operativo del MES. Internamente vive en la app Django `assembly` para
distinguirlo de la produccion por lotes heredada de Kore ERP.

Produccion cubre:

- Ordenes de produccion.
- Planes de produccion.
- Secuencia de linea.
- Consola de estacion.
- Unidades serializadas.
- Mediciones productivas.
- Componentes instalados.
- Genealogia inversa.
- Calidad.
- Retrabajos.
- Liberacion.
- Balanceo.
- Andon, paros, offline, mix y kits externos.
- Indicadores MES.

### Configuracion

Modulo transversal para datos base y reglas de operacion.

Configuracion guarda:

- Empresa, unidades, bodegas y ubicaciones.
- Plantas, areas, productos, versiones, lineas, estaciones, rutas y pasos.
- Parametros productivos y componentes requeridos por paso.
- Equipos de planta.
- Parametros del sistema.
- Informacion tecnica de la version instalada.

### Usuarios

Modulo transversal para seguridad operativa.

Usuarios administra:

- Usuarios del tenant.
- Roles base y personalizados.
- Permisos por modulo.
- Activacion, eliminacion de membresias y reseteo de contrasenas.

## Principios de arquitectura

- No quemar lineas, estaciones ni equipos en codigo.
- Lo configurable vive en Configuracion; lo operativo vive en Produccion.
- El MES no habla directo con PLC ni maquinas; eso le pertenece a Edge.
- Las integraciones IT externas pasan por Connect.
- Los modulos se comunican mediante eventos.
- La unidad serializada es el eje de trazabilidad.
- Lotes existen para piezas, kits, consumibles y contenedores, no como eje de
  la unidad ensamblada.
- La liberacion final debe bloquearse si faltan calidad, retrabajos,
  trazabilidad critica o ruta obligatoria.
- El sistema debe poder operar con perdida temporal de red en estaciones.

## Tema de marca

La guia de color de Kore Line vive en
[`docs/ui/tema_marca_kore_serial.md`](docs/ui/tema_marca_kore_serial.md).

Resumen:

- Naranja Industrial `#FF8C00`: acciones, alertas y control de flujo.
- Ambar Precision `#FFC107`: avisos y estados medios.
- Gris Carbon `#333333`: base visual, texto principal y robustez ERP.
- Gris Medio Operativo `#999999`: bordes, separadores y subtitulos.
- Gris Claro `#F0F0F0`: fondos de interfaz de planta.
- Blanco Tecnico `#FFFFFF`: contenido y legibilidad.

## Desarrollo local

```powershell
poetry install
.venv\Scripts\python.exe manage.py migrate_schemas --shared --noinput
.venv\Scripts\python.exe manage.py runserver
```

La configuracion se toma de `.env`; usa `.env.example` como referencia. La base
inicial no contiene empresas, usuarios ni datos demo.

## Verificacion

```powershell
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py test
```
