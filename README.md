# Kore Serial

Kore Serial es un MES serializado para controlar la ejecucion de unidades ensambladas e identificables individualmente en planta. Comparte la base tecnica de Kore ERP, pero no es una extension, un modulo ni un tenant de Kore.

Su primer caso de uso es el ensamblaje CKD de vehiculos. El modelo de dominio no depende del sector automotriz: debe servir tambien para carrocerias, motocicletas, linea blanca y otras industrias de ensamblaje discreto.

## Concepto central

Una unidad no es un lote. Cada unidad fisica tiene un numero de serie y una historia propia.

- **Producto ensamblado:** familia o modelo fabricable.
- **Version:** configuracion concreta de un producto.
- **Unidad serializada:** ejemplar fisico individual de una version, identificado por un numero de serie. En vehiculos ese identificador puede ser un VIN, pero el producto no lo presupone.

## Objetivo MES

El objetivo de producto es un **Manufacturing Execution System (MES)** para
ensamblaje serializado. El sistema debe orquestar piso de planta: unidad,
estacion, ruta, componentes, controles de calidad, retrabajos, equipos,
evidencia y liberacion.

El plan de desarrollo por fases vive en
[`docs/roadmap/mes_desarrollo_por_fases.md`](docs/roadmap/mes_desarrollo_por_fases.md).

## Estado de fases MES

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

Fases no implementadas todavia:

- **Fase 10 - Indicadores MES:** pendiente.
- **Fase 11 - Balanceo de linea:** pendiente.
- **Fase 12 - MES avanzado:** pendiente.

Siguiente fase recomendada: **Fase 10 - Indicadores MES**.

## Modulo Produccion

El modulo visible del producto se llama **Produccion**. Internamente vive en la
app Django `assembly` para distinguirlo de la produccion por lotes heredada de
Kore ERP. En Kore Serial, produccion significa produccion serializada: la unidad
fisica es el eje operativo, no el lote.

El modulo Produccion cubre la ejecucion operativa:

- Planes de produccion por version, linea, fecha y turno.
- Secuencia de linea por unidad, prioridad, ruta y proxima estacion.
- Registro y seguimiento de unidades serializadas.
- Eventos de avance por unidad, estacion y operario.
- Componentes instalados con trazabilidad por serial, lote o ambos.
- Control de calidad, retrabajo y liberacion de unidad.

Los maestros que gobiernan esa ejecucion se administran desde Configuracion:
productos, versiones, lineas, estaciones, rutas, pasos y equipos de planta.

## Modulos Configuracion y Usuarios

La operacion de Produccion depende de dos modulos transversales:

- **Configuracion** (`/configuracion/`): guarda los datos base de la empresa,
  unidades de medida, bodegas, ubicaciones, productos, versiones, lineas,
  estaciones, rutas, pasos, equipos y la informacion tecnica de la version
  instalada. Es administrado por usuarios con rol de administrador del tenant.
- **Usuarios** (`/usuarios/`): administra usuarios del tenant, roles base,
  roles personalizados, permisos por modulo, activacion, eliminacion de
  membresias y reseteo de contrasenas.

Estos modulos son parte del nucleo operativo. No deben implementarse como
pantallas aisladas por modulo de negocio; deben conservarse como servicios
transversales para que Produccion, Calidad e integraciones usen la misma fuente
de usuarios, permisos y parametros.

## Alcance actual

El primer hito entrega la base operativa del producto:

- Django 5.2, Python 3.13 y PostgreSQL con `django-tenants`: un esquema por empresa.
- Login, membresias por empresa y permisos Django por modulo.
- Configuracion tenant: empresa, unidades, bodegas, ubicaciones e informacion de sistema.
- Usuarios tenant: altas, roles, permisos, activacion y reseteo de contrasenas.
- Modelos de producto ensamblado, version, plan, secuencia y unidad serializada, todos con auditoria de creacion y actualizacion.
- Bitacora operacional al registrar una unidad.
- Listado de unidades con filtros, estados y paginacion de 20, 50 o 100 registros que conserva los filtros activos.
- Base DRF y SimpleJWT preparada para terminales y recolectores externos.
- Redis para cache y Huey como cola ligera.
- `psycopg` 3, WeasyPrint como unico motor PDF y configuracion base de HTMX.

## Diseno para los siguientes hitos

Kore Serial se prepara para incorporar, sin cambiar la naturaleza individual de la unidad:

- Balanceo y optimizacion de modelos mixtos en una misma linea.
- Estaciones, takt time, andon y pantallas de piso con HTMX.
- Trazabilidad de torque por unidad y estacion.
- As-built de numeros de parte, lotes y series instaladas.
- Retrabajo con salida y reingreso de una unidad a la linea.
- Kits CKD, contenedores y planificacion contra arribos.
- Calculo de contenido nacional para regimenes arancelarios.

Las herramientas de torque, PLC y demas equipos de piso se comunicaran mediante un recolector independiente que publica a la API. Django no abre conexiones directas a esos equipos. Las terminales de estacion se disenan para tolerar cortes breves de red mediante estado local y cola de eventos pendientes.

Kore Serial no se integra con Kore ERP como dependencia operativa. Por ahora, la
integracion externa prevista es B22 cuando aplique por necesidad fiscal o
documental. Cualquier integracion de planta debe entrar por API propia del
producto.

## Desarrollo local

```powershell
poetry install
.venv\Scripts\python.exe manage.py migrate_schemas --shared --noinput
.venv\Scripts\python.exe manage.py runserver
```

La configuracion se toma de `.env`; usa `.env.example` como referencia. La base inicial no contiene empresas, usuarios ni datos demo.

## Verificacion

```powershell
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py test
```
