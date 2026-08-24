# Tema de marca Kore Serial

Este documento fija la separacion visual de Kore Serial frente a la vertical Kore ERP heredada.

## Principio

Kore Serial es la vertical de ensamblaje del ecosistema Kore. Mantiene la estructura de producto y experiencia heredada, pero su acento visual es industrial y operativo.

No tocar `static/img/logo.png` en esta etapa. El check interior del logo se recoloreara despues, cuando se trabaje el activo de marca.

## Logo y wordmark

- La base hexagonal del logo permanece constante.
- El check interior debe pasar a Naranja Industrial `#FF8C00` cuando se edite el logo.
- El texto principal se expresa como `KORE Serial`.
- `KORE` mantiene peso fuerte para continuidad de ecosistema.
- `Serial` se muestra a la derecha, con peso mas ligero y acento naranja.

## Paleta oficial

La paleta completa de swatches estrategicos define los tonos clave para guiar toda la comunicacion y la interfaz de usuario: Naranja Industrial para alertas y acciones, Ambar Precision para estados medios, Gris Carbon para la base unificada, y neutros como Gris Claro y Blanco Tecnico para legibilidad en planta.

| Rol | HEX | Uso |
|---|---|---|
| Naranja Industrial | `#FF8C00` | Alertas operativas, acciones principales, flujo, control operativo, acento de vertical |
| Ambar Precision | `#FFC107` | Avisos, estado medio, atencion operativa |
| Gris Carbon Profundo | `#333333` | Estructura, texto principal, robustez ERP |
| Gris Medio Operativo | `#999999` | Bordes, separadores, subtitulos |
| Gris Claro | `#F0F0F0` | Fondo tecnico de interfaz de planta |
| Blanco Tecnico | `#FFFFFF` | Contenido y legibilidad |

## Implementacion

La fuente unica de marca es `static/css/kore-theme.css`.

Las plantillas base cargan los assets comunes mediante `templates/partials/_head_assets.html`. Si se crea una nueva plantilla base, debe incluir ese partial en vez de declarar CSS propio.

Por compatibilidad con el software heredado, las plantillas pueden seguir usando clases Tailwind existentes como `bg-blue-600`, `text-blue-700`, `border-blue-300` y `focus:ring-blue-500`. En Kore Serial, esas clases estan remapeadas visualmente a la paleta naranja desde `kore-theme.css`.

No reintroducir estos colores como marca en nuevas pantallas:

- Azul petroleo `#134D5F`
- Azul electrico `#145DA1`
- Azul hover `#1050A0`
- Azul por defecto Tailwind `#2563EB`
- Teal/verde de marca generico `#2A9D8F` o `#83C5BE`

## Regla practica

- CTA principal: naranja solido mediante `bg-blue-600 text-white hover:bg-blue-700`.
- Accion de proceso: outline naranja mediante `border-blue-300 bg-blue-50 text-blue-700`.
- Avisos: ambar.
- PDF: rojo.
- Excel: verde.
- Estados positivos: verde/emerald.
- Texto principal y estructura: carbon.
