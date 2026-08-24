# Estandar de Interfaz Kore ERP (fuente unica de verdad)

> **Lee este archivo ANTES de crear o modificar cualquier pantalla.**
> Todo modulo debe verse como una sola aplicacion. Si una pantalla no se parece
> a la referencia, esta mal — se ajusta la pantalla, no el estandar.
>
> **Implementacion de referencia:** `templates/procurement/purchase_order_list.html`
> y `templates/procurement/purchase_order_detail.html`. Ante cualquier duda,
> copiar el patron de `procurement` y adaptar solo los datos de la entidad.
>
> Este documento manda sobre el resto de guias de UI. Las demas
> (`listas_y_formularios_reutilizable.md`, `componentes_ui_listas.md`,
> `dropdown_actions.md`) son detalle de apoyo; si contradicen a este archivo,
> gana este.

---

## 1. Paleta (NO inventar colores de marca)

Fuente de verdad del CSS: `static/css/kore-theme.css` (remapea los tokens de Tailwind v4).
Si un valor aqui no coincide con el CSS, **gana el CSS**.

| Rol | HEX | Token Tailwind | Uso |
|-----|-----|----------------|-----|
| Primario | `#134d5f` | — | Estructura: navbar, sidebar, titulos H1/H2 |
| Accion / CTA | `#145da1` | `blue-600` | Boton principal, links, iconos de accion |
| Accion hover | `#1050a0` | `blue-700` | Hover del CTA |
| Accion suave | `#e8f0f9` | `blue-50` | Fondos hover, chips de accion |
| Superficie | `#d9e2e8` | `gray-200` | Fondos de secciones, cards, bordes |
| Base | `#ffffff` | — | Area de trabajo |

**El acento de marca es el AZUL `#145da1`, NO un teal/verde.**
Prohibido reintroducir `#2563eb`, `#2a9d8f`, `#83c5be` u otros colores por defecto.

El encabezado de los archivos generados (Excel `PatternFill` y `<th>` de las plantillas PDF)
usa el primario de marca `#134D5F` con texto blanco — nunca `#2563eb`.

Como las clases de Tailwind estan remapeadas, en templates se usan utilidades normales
(`bg-blue-600`, `text-blue-700`, `bg-gray-50`, etc.) y salen con la paleta de marca.

---

## 1.1. Principio de experiencia: una sola app

Kore debe sentirse como **una sola aplicacion**, no como modulos independientes pegados
entre si. Una persona que ya entendio Compras debe poder entrar a Calidad, Produccion,
Socios, Inventario o Ventas y reconocer inmediatamente:

- donde buscar;
- donde filtrar;
- donde crear un registro;
- donde ver el estado;
- donde entrar al detalle;
- donde descargar PDF/Excel;
- donde ejecutar la siguiente accion del flujo.

Por eso todos los modulos deben repetir la misma gramatica visual:

| Tipo de pantalla | Patron obligatorio |
|---|---|
| Inicio | resumen compacto -> tarjetas por proceso -> atencion/acciones -> actividad trazable reciente |
| Lista | nav de submodulo -> filtros/exportaciones/alta -> tabla desktop + cards mobile -> paginacion |
| Detalle | cabecera con titulo, codigo y estado -> botonera -> card unica de informacion general -> detalle/lineas/historial |
| Formulario | cabecera compacta -> card de datos generales -> card dominante de lineas/items -> acciones finales |
| Configuracion | tabs por modulo -> cards homogeneas por configuracion -> accion unica por card |
| PDF/Excel | mismos nombres, filtros y codigos visibles que la UI |

Regla de tenant/empresa:

- Nunca hardcodear nombres de empresa, RUC, direcciones, logos, correos, telefonos,
  dominios de cliente o marcas de cliente en pantallas, PDFs, Excel, XML, correos o seeds
  que puedan llegar a produccion.
- En documentos emitidos por la empresa se usa siempre `CompanyConfig`
  (`legal_name`, `trade_name`, `ruc`, `address`, `logo`) del tenant actual.
- En datos del cliente/proveedor se usa siempre el snapshot o la relacion del registro
  (`Partner`, factura, pedido, despacho, etc.), nunca texto fijo.
- Nombres como ONHNIMED, Ciauto, demo o cualquier cliente real solo pueden aparecer
  en datos de base de datos del tenant, documentacion operativa o fixtures/seeds claramente demo.

Regla de codigos de requisitos:

- La GUI nunca muestra codigos de requisitos, decisiones o brechas del mapa regulatorio
  (`PRE-02`, `COM-03`, `COM-D02`, `CRO-02`, `EXC-02`, etc.).
- Esos codigos pueden existir en documentacion tecnica, pruebas o enlaces internos de
  trazabilidad, pero no en labels, titulos, botones, badges, mensajes flash, ayudas,
  PDFs de usuario, Excel ni documentos externos.
- La pantalla debe usar lenguaje operativo: `Disponibilidad y capacidad`,
  `Resolucion de imposibilidad`, `Alcance autorizado`, `Recursos habilitados`,
  `Cambios y cancelaciones posteriores`.
- Los codigos internos de registro controlado (`ERP-...`) tampoco se muestran en la
  interfaz salvo en herramientas tecnicas/admin de auditoria explicitamente internas.

No se crean layouts especiales por modulo salvo que exista una razon operativa clara.
La diferencia entre modulos debe estar en los datos y reglas de negocio, no en la forma
de navegar la pantalla.

---

## 1.2. Inicio / panel general

Inicio es un tablero operativo, no una landing. Debe responder en segundos:
que procesos estan activos, que pendientes requieren atencion y a donde debe
entrar el usuario para resolverlos.

Patron obligatorio:

- cabecera compacta con fecha/hora de actualizacion;
- resumen superior con 3-4 KPIs transversales;
- tarjetas homogeneas por proceso con pendiente principal, dos metricas y accion;
- columna lateral de atencion con pendientes enlazados a la lista operativa;
- acciones rapidas filtradas por permisos;
- actividad trazable reciente y movimientos recientes en tablas compactas.

Reglas:

- No usar heroes, graficos decorativos ni tarjetas infladas.
- No duplicar el detalle de cada modulo; Inicio solo resume y enlaza.
- Los codigos regulatorios internos no se muestran en Inicio.
- Si una base local no tiene una tabla nueva de auditoria, Inicio no debe romper;
  puede mostrar la seccion vacia hasta que se ejecuten migraciones.

---

## 2. Semantica de color (lo que hace que un modulo "se vea igual")

El color **no es decorativo**: cada accion tiene un color fijo. Esta es la causa #1 de que
los modulos parezcan apps distintas cuando no se respeta.

| Elemento | Color | Clases (outline) | Clases (solido) |
|----------|-------|------------------|-----------------|
| **CTA principal** (`+ Nuevo`, `Guardar`, `Crear`) | Azul solido | — | `bg-blue-600 text-white hover:bg-blue-700` |
| **Accion de proceso** (`Confirmar`, `Autorizar`) | Azul outline | `border-blue-300 bg-blue-50 text-blue-700 hover:bg-blue-100` | — |
| **Workflow positivo** (`Enviar`, `Aprobar`, `Recepcionar`, `Completar`) | Emerald outline | `border-emerald-300 bg-emerald-50 text-emerald-700 hover:bg-emerald-100` | `bg-emerald-600 text-white hover:bg-emerald-700` |
| **Boton PDF** | Rojo | `border-red-200 bg-red-50 text-red-700 hover:bg-red-100` | en dropdown: `text-red-600 hover:bg-red-50` |
| **Boton Excel** | Verde | `border-green-200 bg-green-50 text-green-700 hover:bg-green-100` | en dropdown: `text-green-700 hover:bg-green-50` |
| **Accion destructiva** (`Anular`, `Cancelar`, `Rechazar`) | Rojo | `border-red-300 bg-red-50 text-red-700 hover:bg-red-100` | — |
| **Volver / secundaria neutra** | Neutro | `border text-gray-700 hover:bg-gray-50` | — |

Regla rapida: **Excel = verde, PDF = rojo, CTA = azul.**
Emerald se reserva para acciones de workflow positivo y estados — nunca para Excel ni para el CTA.

---

## 3. Badges de estado (mapeo fijo)

```html
<span class="inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium
  {% if obj.status == 'DONE' or obj.status == 'RECEIVED' or obj.status == 'COMPLETED' or obj.status == 'APPROVED' %}
    border-emerald-200 bg-emerald-50 text-emerald-700
  {% elif obj.status == 'CANCELLED' or obj.status == 'CANCELED' or obj.status == 'REJECTED' %}
    border-red-200 bg-red-50 text-red-700
  {% elif obj.status == 'CONFIRMED' or obj.status == 'RELEASED' or obj.status == 'ACTIVE' %}
    border-green-200 bg-green-50 text-green-700
  {% elif obj.status == 'SENT' or obj.status == 'IN_PROGRESS' or obj.status == 'UNDER_QA' %}
    border-amber-200 bg-amber-50 text-amber-700
  {% else %}border-gray-200 bg-gray-50 text-gray-700{% endif %}">
  {{ obj.get_status_display }}
</span>
```

- Chip "andon" redondeado, sin punto decorativo.
- Mismo mapeo en todos los modulos: verde/emerald = ok, ambar = en proceso, rojo = anulado/rechazado, gris = borrador.

---

## 4. Estructura de pagina de LISTA

Referencia: `templates/procurement/purchase_order_list.html`.

1. `{% include "<app>/_nav.html" %}` — nav del submodulo (pills azules: activo `bg-blue-600 text-white`, inactivo `bg-gray-100 text-gray-700`).
2. Barra de filtros en tarjeta blanca (`rounded-2xl border bg-white p-3`), una sola fila en desktop:
   `Buscar (q)`, `status`, `date_from`, `date_to`, boton `Filtrar`, link `Limpiar`,
   y a la derecha (`ml-auto`): `PDF` | `Excel` | `+ Nuevo`.
3. Mobile: cards apilados (`block md:hidden`). Desktop: tabla (`hidden md:block`).
4. Tabla compacta (`text-sm`, celdas `px-4 py-2/py-3`), columna de acciones de ancho fijo.
5. Acciones por fila DENTRO de la fila: CTA de workflow visible + dropdown de 3 puntos para el resto.
6. Paginacion con selector `per_page` 20/50/100 que preserva los filtros.

### Contrato de una lista reutilizable

La vista (`ListView`) debe exponer siempre que aplique:

- `q`: busqueda textual por codigo, nombre, documento o entidad relacionada.
- `status`: estado del registro.
- `date_from` / `date_to`: rango de fecha principal de la entidad.
- `per_page`: solo `20`, `50` o `100`.
- `status_choices`: choices del estado mostrados en espanol.

La plantilla debe preservar el querystring en:

- paginacion;
- selector `per_page`;
- PDF;
- Excel;
- links secundarios que vuelven a la lista filtrada, cuando aplique.

Los exportadores PDF/Excel de listado deben reutilizar la misma funcion/filtro que la
lista. Si la UI muestra registros filtrados, el PDF/Excel debe representar ese mismo
universo, no el listado completo sin filtros.

### Caso especial: Calidad / QA

Calidad tiene dos subareas y no deben mezclarse en la misma pantalla:

- **Control QA** usa `templates/quality/_nav.html`: pendientes, inspecciones, planes QA, recepciones y trazabilidad.
- **Gestion QA** usa `templates/quality/_nav_gestion.html`: NC/CAPA, quejas, auditorias, retiros y tecnovigilancia.
- Una pantalla debe incluir solo uno de esos navs. Si aparece `quality/_nav.html` y `quality/_nav_gestion.html` juntos, la pantalla esta mal.
- Ambos navs usan pills azules para el activo; no existe tema rojo por modulo.

---

## 5. Estructura de pagina de DETALLE

Referencia: `templates/procurement/purchase_order_detail.html`.

- Cabecera con titulo + numero de documento + badge de estado.
- Botonera superior derecha en este orden: workflow positivo (azul/emerald) → `PDF` (rojo) → `Excel` (verde) → `Volver` (neutro).
- Card unica de **Informacion general** arriba: no separar cada campo en una card distinta.
- La card de Informacion general usa grid interno (`sm:grid-cols-2`, `lg:grid-cols-3`) y badge de estado arriba a la derecha.
- Debajo va el contenido dominante: lineas, materiales, historial, resultados, movimientos o evidencias.
- 4 decimales en todos los valores numericos (UI/PDF/Excel).

---

## 6. Estructura de FORMULARIO

- Card de datos generales compacto + card de detalle (lineas/items) dominante.
- Botones para agregar/quitar lineas.
- CTA principal azul solido (`Guardar`/`Crear`) + secundaria neutra (`Cancelar`).
- Errores por campo visibles.

### Contrato de un formulario reutilizable

- La cabecera no debe explicar el modulo si el titulo ya es claro.
- Los campos generales van agrupados en una card compacta.
- Las lineas/items/evidencias ocupan la card principal.
- Agregar/quitar lineas usa botones neutros, salvo que sea una accion final de workflow.
- Guardar/Crear es el unico CTA azul solido.
- Si el formulario es largo, las acciones finales pueden ir en barra sticky inferior.

---

## 6.1. Estructura de CONFIGURACION

Referencia: `templates/core/settings.html`.

La configuracion no debe mandar al usuario a pantallas que visualmente parezcan otro
modulo sin contexto. Si una configuracion vive bajo `Configuracion`, su lista/formulario
debe conservar el contexto de configuracion o volver claramente a configuracion.

Patron:

- tabs por modulo o dominio (`Empresa`, `Socios`, `Inventario`, `Produccion`, etc.);
- cards homogeneas, no tablas mezcladas con cards;
- cada card tiene: modulo/categoria, titulo, descripcion corta, estado/contador si aplica y una accion;
- display names en espanol, no nombres tecnicos (`Putaway`, `Picking`, `Warehouse Management`, etc.);
- evitar formularios largos desplegados por defecto cuando una accion `Configurar` o `Agregar` sea mas clara.

Regla de ubicacion:

- El modulo operativo solo muestra transacciones y ejecucion diaria.
- Catalogos, parametros, reglas y motivos viven en Configuracion.
- Si una pantalla se abre desde Configuracion, no debe mostrar el nav operativo del modulo de origen.
- En Ventas, `Listas de precios` y `Motivos de devolucion` pertenecen a Configuracion > Ventas.
- En Finanzas, `Plan de cuentas`, `Diarios contables`, `Periodos fiscales` y `Esquemas tributarios` pertenecen a Configuracion > Finanzas.
- En POS, `Puntos de venta` pertenece a Configuracion > POS.
- En Empresa, `Empresa / SRI`, `Documentos emitidos` y `Control de cambios` pertenecen a Configuracion > Empresa.
- En Socios, `Criterios de proveedores` y `Registro maestro de proveedores` pertenecen a Configuracion > Socios.
- En Compras, `Plantilla de etiquetas de recepcion` e `Historial de etiquetas` pertenecen a Configuracion > Compras.
- En Inventario, `Bodegas`, `Ubicaciones`, `Unidades de medida`, `Familias` y `Subfamilias` pertenecen a Configuracion > Inventario.
- En Produccion, `Listas de materiales`, `Rutas`, `Estaciones`, `Equipos y maquinaria` y `Habilitaciones de operarios` pertenecen a Configuracion > Produccion.
- La **FMA** es la excepcion deliberada: es un documento controlado con aprobaciones,
  no un catalogo, y vive en el modulo Produccion con su propio nav (CC-2026-021).
  Desde ella se abren estaciones, rutas, formulas y planes de calidad con retorno
  de contexto, de modo que configurar un producto no obliga a salirse (CC-2026-026).
- En Calidad, `Planes de calidad` pertenece a Configuracion > Calidad.

Las subpantallas de configuracion usan una cabecera comun:

- breadcrumb `Configuracion / <modulo>`;
- boton neutro `Volver a configuracion` que preserva el tab (`?tab=<modulo>`);
- pills internas solo de configuraciones hermanas;
- listas con filtros + paginacion 20/50/100;
- formularios con una card principal y acciones finales `Cancelar` + `Guardar`.

---

## 7. Dropdown de acciones (patron `data-dd-*`)

Estructura, CSS (`static/css/dropdown.css`) y JS inline en `{% block scripts %}`:
ver `templates/procurement/purchase_order_list.html` y `docs/ui/dropdown_actions.md`.
Dentro del dropdown: `Ver / Editar` (gris), `PDF` (rojo), `Excel` (verde), `Anular` (rojo).

Acciones operativas especiales, como `Etiqueta`, van tambien en el dropdown de la fila.
Si requieren parametros, abren un modal compacto sobre la misma lista. La configuracion
de campos, tamano, impresora e historial vive en `Configuracion`, no dentro de la lista
operativa.

---

## 8. Filosofia: ERP profesional, no app de consumo

Kore se usa 8 horas al dia. Prioridad: **densidad de informacion y velocidad de lectura**.

- Modelo a seguir: Airtable / Excel / Notion en modo tabla. **No**: landings ni dashboards con tarjetas infladas.
- Filas compactas (`py-2`), badges de color por categoria, hover suave (`hover:bg-gray-50`), sin animaciones llamativas.
- Sin subtitulos descriptivos de relleno bajo los titulos.

---

## 9. Checklist obligatorio antes de dar por hecha una pantalla

- [ ] Use `procurement` como referencia y copie su estructura.
- [ ] CTA principal en azul (`bg-blue-600`), no en emerald ni teal.
- [ ] Boton Excel en verde, boton PDF en rojo.
- [ ] Emerald solo en estados/workflow positivo; nunca en Excel ni CTA.
- [ ] Badges de estado con el mapeo de la seccion 3.
- [ ] Nav de submodulo con pills azules.
- [ ] Filtros `q/status/date_from/date_to` + paginacion 20/50/100 que preserva filtros.
- [ ] 4 decimales en UI/PDF/Excel.
- [ ] Permisos (`LoginRequiredMixin` + `ModulePermissionMixin`) y trazabilidad respetados.
- [ ] Sin colores hex de marca hardcodeados (`#2563eb`, `#2a9d8f`, etc.).
- [ ] Textos en español y UTF-8 sin errores de codificacion.
