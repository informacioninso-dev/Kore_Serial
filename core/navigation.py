"""Navegacion de modulo, definida una sola vez para todos.

Cada modulo tenia su propia barra escrita a mano, y bastaron unas semanas para
que divergieran: Planta agrupada por etapas, los demas con una tira de enlaces.
Quien aprendia a moverse en uno tenia que volver a aprender en el siguiente.

Aqui la estructura vive en datos y la dibuja una sola plantilla. Un modulo
nuevo declara sus grupos y hereda el comportamiento completo: agrupacion,
resaltado del activo y filtrado por permisos.
"""

from django.urls import NoReverseMatch, reverse


# Estructura: namespace -> {panel, grupos, extra}
#   grupo  = (etiqueta, [(url_name, etiqueta, permiso), ...])
#   permiso vacio = visible para cualquiera que entre al modulo
MODULE_NAVS = {
    "assembly": {
        "panel": ("assembly:index", "Panel"),
        "groups": [
            ("Ejecucion", [
                ("assembly:order_list", "Ordenes de produccion", "assembly.view_productionorder"),
                ("assembly:plan_list", "Planes", "assembly.view_productionplan"),
                ("assembly:queue_list", "Secuencia de linea", "assembly.view_productionqueueitem"),
                ("assembly:station_console", "Consola de estacion", "assembly.add_unitstationevent"),
            ]),
            ("Trazabilidad", [
                ("assembly:unit_list", "Unidades", "assembly.view_serializedunit"),
                ("assembly:component_list", "Componentes instalados", "assembly.view_installedcomponent"),
                ("assembly:genealogy", "Genealogia", "assembly.view_installedcomponent"),
                ("assembly:measurement_list", "Mediciones", "assembly.view_productionmeasurement"),
                ("assembly:event_list", "Eventos de estacion", "assembly.view_unitstationevent"),
            ]),
            ("Calidad", [
                ("assembly:quality_list", "Controles de calidad", "assembly.view_qualitygate"),
                ("assembly:rework_list", "Retrabajos", "assembly.view_reworkorder"),
                ("assembly:release_list", "Liberacion", "assembly.view_releaseapproval"),
            ]),
            ("Analisis", [
                ("assembly:metrics", "Indicadores MES", ""),
                ("assembly:advanced", "Andon, paros y offline", "assembly.view_andonsignal"),
                ("assembly:balance_list", "Balanceo de linea", "assembly.view_linebalancestudy"),
            ]),
        ],
    },
    "wms": {
        "panel": ("wms:dashboard", "Panel"),
        "groups": [
            ("Inventario", [
                ("wms:balance_list", "Existencias", "wms.view_inventorybalance"),
                ("wms:receipt_list", "Recepciones CKD", "wms.view_inboundreceipt"),
                ("wms:movement_list", "Movimientos", "wms.view_inventorymovement"),
            ]),
            ("Abastecimiento", [
                ("wms:kit_list", "Kits de linea", "wms.view_assemblykit"),
                ("wms:pick_mission_list", "Picking", "wms.view_pickmission"),
                ("wms:kanban_signal_list", "Kanban", "wms.view_kanbansignal"),
                ("wms:consumption_list", "Consumos de ensamble", "wms.view_assemblymaterialconsumption"),
            ]),
        ],
    },
    "edge": {
        "panel": ("edge:dashboard", "Panel"),
        "groups": [
            ("Senales", [
                ("edge:signal_list", "Senales recibidas", "edge.view_edgesignal"),
            ]),
            ("Operacion", [
                ("edge:health_list", "Salud de gateways", "edge.view_edgehealthcheck"),
                ("edge:command_list", "Comandos", "edge.view_edgecommand"),
            ]),
        ],
    },
    "eventbus": {
        "panel": ("eventbus:dashboard", "Panel"),
        "groups": [
            ("Bus", [
                ("eventbus:event_list", "Eventos publicados", "eventbus.view_domainevent"),
                ("eventbus:delivery_list", "Entregas", "eventbus.view_eventdelivery"),
            ]),
            ("Analisis", [
                ("eventbus:indicator_list", "Indicadores diarios", "eventbus.view_indicatorsnapshot"),
            ]),
        ],
    },
    "connect": {
        "panel": ("connect:dashboard", "Panel"),
        "groups": [
            ("Mensajes", [
                ("connect:outbound_list", "Salida", "connect.view_outboundmessage"),
                ("connect:inbound_list", "Entrada", "connect.view_inboundmessage"),
            ]),
            ("Control", [
                ("connect:reconciliation_list", "Reconciliaciones", "connect.view_reconciliationrun"),
            ]),
        ],
    },
}


# Configuracion: todo lo que se define una vez y la operacion diaria no toca.
#
# Vive aparte de MODULE_NAVS porque sus pantallas estan repartidas en cinco apps
# (core, assembly, wms, edge, eventbus, connect) y aun asi tienen que verse como
# un solo lugar. Quien necesita configurar algo entra a Configuracion y lo
# encuentra, sin adivinar en que modulo lo escondieron.
CONFIG_NAV = {
    "panel": ("core:settings", "Panel"),
    "groups": [
        ("Empresa", [
            ("core:company", "Datos de la empresa", ""),
            ("core:system_info", "Informacion del sistema", ""),
        ]),
        ("Planta", [
            ("assembly:plant_list", "Plantas", "assembly.view_plant"),
            ("assembly:area_list", "Areas", "assembly.view_plantarea"),
            ("assembly:line_list", "Lineas", "assembly.view_assemblyline"),
            ("assembly:station_list", "Estaciones", "assembly.view_assemblystation"),
            ("assembly:equipment_list", "Equipos", "core.view_equipmentintegration"),
        ]),
        ("Producto", [
            ("assembly:product_list", "Productos", "assembly.view_assembledproduct"),
            ("assembly:version_list", "Versiones", "assembly.view_productversion"),
            ("assembly:route_list", "Rutas", "assembly.view_assemblyroute"),
            ("assembly:step_list", "Pasos", "assembly.view_assemblyroutestep"),
            ("assembly:parameter_list", "Parametros productivos", "assembly.view_routestepparameter"),
            ("assembly:requirement_list", "Componentes requeridos", "assembly.view_routestepcomponentrequirement"),
        ]),
        ("Materiales", [
            ("core:unit_list", "Unidades de medida", ""),
            ("wms:material_list", "Materiales", "wms.view_material"),
            ("wms:category_list", "Categorias de materiales", "wms.view_materialcategory"),
            ("core:warehouse_list", "Bodegas", ""),
            ("core:location_list", "Ubicaciones", ""),
            ("wms:location_profile_list", "Perfiles de ubicacion", "wms.view_wmslocationprofile"),
            ("wms:replenishment_rule_list", "Reglas de reposicion", "wms.view_replenishmentrule"),
        ]),
        ("Conectividad", [
            ("edge:gateway_list", "Gateways", "edge.view_edgegateway"),
            ("edge:device_list", "Dispositivos", "edge.view_edgedevice"),
            ("edge:rule_list", "Reglas de normalizacion", "edge.view_edgesignalrule"),
        ]),
        ("Integracion", [
            ("eventbus:type_list", "Catalogo de eventos", "eventbus.view_eventtype"),
            ("eventbus:subscription_list", "Suscripciones", "eventbus.view_eventsubscription"),
            ("connect:connector_list", "Conectores", "connect.view_connector"),
            ("connect:contract_list", "Contratos", "connect.view_connectorcontract"),
        ]),
    ],
}


def config_urls():
    """URLs que pertenecen a Configuracion, resueltas una sola vez."""
    urls = []
    for _, entries in CONFIG_NAV["groups"]:
        for url_name, _, _ in entries:
            try:
                urls.append(reverse(url_name))
            except NoReverseMatch:
                continue
    return urls


def is_configuration_path(request):
    """True si la pantalla actual es de configuracion, este en la app que este."""
    path = getattr(request, "path", "")
    settings_url = reverse("core:settings")
    if path.startswith(settings_url):
        return True
    return any(path.startswith(url) for url in config_urls())


def _can(user, permission):
    """Los superusuarios y el grupo admin ven todo, igual que en las vistas."""
    if not permission:
        return True
    if user.is_superuser:
        return True
    if user.has_perm(permission):
        return True
    return user.groups.filter(name="admin").exists()


def build_module_nav(request):
    """Arma la barra del modulo en el que esta el usuario, o None si no aplica.

    El activo se decide por la URL y no por una etiqueta que cada vista tenga
    que acordarse de pasar: una pantalla de detalle o de edicion resalta su
    grupo sin hacer nada.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None

    # Una pantalla de configuracion muestra la barra de Configuracion aunque
    # viva en la app de otro modulo: para el usuario es un solo lugar.
    if is_configuration_path(request):
        definition = CONFIG_NAV
    else:
        match = getattr(request, "resolver_match", None)
        namespace = getattr(match, "namespace", "") if match else ""
        definition = MODULE_NAVS.get(namespace)
        if definition is None:
            return None

    path = request.path
    panel_name, panel_label = definition["panel"]
    try:
        panel_url = reverse(panel_name)
    except NoReverseMatch:
        return None

    groups = []
    for label, entries in definition["groups"]:
        items = []
        for url_name, item_label, permission in entries:
            if not _can(user, permission):
                continue
            try:
                url = reverse(url_name)
            except NoReverseMatch:
                # Una ruta renombrada no puede tumbar la barra entera.
                continue
            items.append({"url": url, "label": item_label, "active": path.startswith(url)})
        if items:
            groups.append(
                {
                    "label": label,
                    "items": items,
                    "active": any(item["active"] for item in items),
                }
            )

    return {
        "panel": {"url": panel_url, "label": panel_label, "active": path == panel_url},
        "groups": groups,
    }
