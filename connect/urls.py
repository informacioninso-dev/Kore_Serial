from django.urls import path

from . import views


urlpatterns = [
    path("", views.ConnectDashboardView.as_view(), name="dashboard"),
    path("conectores/", views.ConnectorListView.as_view(), name="connector_list"),
    path("conectores/nuevo/", views.ConnectorCreateView.as_view(), name="connector_create"),
    path("conectores/<int:pk>/", views.ConnectorDetailView.as_view(), name="connector_detail"),
    path("conectores/<int:pk>/editar/", views.ConnectorUpdateView.as_view(), name="connector_update"),
    path("contratos/", views.ContractListView.as_view(), name="contract_list"),
    path("contratos/nuevo/", views.ContractCreateView.as_view(), name="contract_create"),
    path("contratos/<int:pk>/editar/", views.ContractUpdateView.as_view(), name="contract_update"),
    path("salida/", views.OutboundListView.as_view(), name="outbound_list"),
    path("salida/<int:pk>/", views.OutboundDetailView.as_view(), name="outbound_detail"),
    path("salida/<int:pk>/enviar/", views.SendMessageView.as_view(), name="outbound_send"),
    path("salida/procesar/", views.FlushOutboundView.as_view(), name="outbound_flush"),
    path("entrada/", views.InboundListView.as_view(), name="inbound_list"),
    path("reconciliacion/", views.ReconciliationListView.as_view(), name="reconciliation_list"),
    path("reconciliacion/nueva/", views.ReconciliationRunView.as_view(), name="reconciliation_run"),
    path("reconciliacion/<int:pk>/", views.ReconciliationDetailView.as_view(), name="reconciliation_detail"),
    path("reconciliacion/<int:pk>/reencolar/", views.RequeueMissingView.as_view(), name="reconciliation_requeue"),
]
