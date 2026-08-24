from django.urls import path

from .views import (
    CompanyConfigView,
    LocationCreateView,
    LocationListView,
    LocationUpdateView,
    SettingsDashboardView,
    SystemInfoView,
    UnitCreateView,
    UnitListView,
    UnitUpdateView,
    WarehouseCreateView,
    WarehouseListView,
    WarehouseUpdateView,
)


app_name = "core"

urlpatterns = [
    path("", SettingsDashboardView.as_view(), name="settings"),
    path("sistema/", SystemInfoView.as_view(), name="system_info"),
    path("empresa/", CompanyConfigView.as_view(), name="company"),
    path("unidades/", UnitListView.as_view(), name="unit_list"),
    path("unidades/nueva/", UnitCreateView.as_view(), name="unit_create"),
    path("unidades/<int:pk>/editar/", UnitUpdateView.as_view(), name="unit_update"),
    path("bodegas/", WarehouseListView.as_view(), name="warehouse_list"),
    path("bodegas/nueva/", WarehouseCreateView.as_view(), name="warehouse_create"),
    path("bodegas/<int:pk>/editar/", WarehouseUpdateView.as_view(), name="warehouse_update"),
    path("ubicaciones/", LocationListView.as_view(), name="location_list"),
    path("ubicaciones/nueva/", LocationCreateView.as_view(), name="location_create"),
    path("ubicaciones/<int:pk>/editar/", LocationUpdateView.as_view(), name="location_update"),
]
