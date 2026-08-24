# Kore Serial

Kore Serial es un producto independiente para controlar la produccion de unidades ensambladas e identificables individualmente. Comparte la base tecnica de Kore ERP, pero no es una extension, un modulo ni un tenant de Kore.

Su primer caso de uso es el ensamblaje CKD de vehiculos. El modelo de dominio no depende del sector automotriz: debe servir tambien para carrocerias, motocicletas, linea blanca y otras industrias de ensamblaje discreto.

## Concepto central

Una unidad no es un lote. Cada unidad fisica tiene un numero de serie y una historia propia.

- **Producto ensamblado:** familia o modelo fabricable.
- **Version:** configuracion concreta de un producto.
- **Unidad serializada:** ejemplar fisico individual de una version, identificado por un numero de serie. En vehiculos ese identificador puede ser un VIN, pero el producto no lo presupone.

## Alcance actual

El primer hito entrega la base operativa del producto:

- Django 5.2, Python 3.13 y PostgreSQL con `django-tenants`: un esquema por empresa.
- Login, membresias por empresa y permisos Django por modulo.
- Modelos de producto ensamblado, version y unidad serializada, todos con auditoria de creacion y actualizacion.
- Bitacora operacional al registrar una unidad.
- Listado de unidades con filtros, estados y paginacion de 20, 50 o 100 registros que conserva los filtros activos.
- API preparada con DRF y SimpleJWT para terminales y recolectores externos.
- Redis para cache y Huey como cola ligera.
- `psycopg` 3, WeasyPrint como unico motor PDF y configuracion base de HTMX.

## Diseno para los siguientes hitos

Kore Serial se prepara para incorporar, sin cambiar la naturaleza individual de la unidad:

- Secuenciacion de modelos mixtos en una misma linea.
- Estaciones, takt time, andon y pantallas de piso con HTMX.
- Trazabilidad de torque por unidad y estacion.
- As-built de numeros de parte y series instaladas.
- Retrabajo con salida y reingreso de una unidad a la linea.
- Kits CKD, contenedores y planificacion contra arribos.
- Calculo de contenido nacional para regimenes arancelarios.

Las herramientas de torque, PLC y demas equipos de piso se comunicaran mediante un recolector independiente que publica a la API. Django no abre conexiones directas a esos equipos. Las terminales de estacion se disenan para tolerar cortes breves de red mediante estado local y cola de eventos pendientes.

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
.venv\Scripts\python.exe manage.py test assembly
```
