from django.urls import path

from . import views


urlpatterns = [
    path("", views.EdgeDashboardView.as_view(), name="dashboard"),
    path("gateways/", views.GatewayListView.as_view(), name="gateway_list"),
    path("gateways/nuevo/", views.GatewayCreateView.as_view(), name="gateway_create"),
    path("gateways/<int:pk>/", views.GatewayDetailView.as_view(), name="gateway_detail"),
    path("gateways/<int:pk>/editar/", views.GatewayUpdateView.as_view(), name="gateway_update"),
    path("gateways/<int:pk>/token/", views.GatewayRotateTokenView.as_view(), name="gateway_rotate_token"),
    path("gateways/<int:pk>/ping/", views.GatewayPingView.as_view(), name="gateway_ping"),
    path("dispositivos/", views.DeviceListView.as_view(), name="device_list"),
    path("dispositivos/nuevo/", views.DeviceCreateView.as_view(), name="device_create"),
    path("dispositivos/<int:pk>/editar/", views.DeviceUpdateView.as_view(), name="device_update"),
    path("reglas/", views.SignalRuleListView.as_view(), name="rule_list"),
    path("reglas/nueva/", views.SignalRuleCreateView.as_view(), name="rule_create"),
    path("reglas/<int:pk>/editar/", views.SignalRuleUpdateView.as_view(), name="rule_update"),
    path("senales/", views.SignalListView.as_view(), name="signal_list"),
    path("senales/<int:pk>/", views.SignalDetailView.as_view(), name="signal_detail"),
    path("senales/<int:pk>/reintentar/", views.SignalRetryView.as_view(), name="signal_retry"),
    path("salud/", views.HealthCheckListView.as_view(), name="health_list"),
    path("comandos/", views.CommandListView.as_view(), name="command_list"),
    path("comandos/nuevo/", views.CommandCreateView.as_view(), name="command_create"),
]
