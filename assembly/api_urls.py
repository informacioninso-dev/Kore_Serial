from django.urls import path

from .api import (
    EquipmentEventDetailView,
    EquipmentEventIngestView,
    InstalledComponentCreateAPIView,
    IntegrationProfileView,
    ProductionMeasurementCreateAPIView,
    QualityGateDecisionView,
    StationOfflineEventSyncView,
    StationEventCreateView,
    UnitCurrentStepView,
    UnitDetailView,
)


urlpatterns = [
    path("integration/profile/", IntegrationProfileView.as_view(), name="integration_profile"),
    path("units/<str:serial_number>/", UnitDetailView.as_view(), name="unit_detail"),
    path("units/<str:serial_number>/current-step/", UnitCurrentStepView.as_view(), name="unit_current_step"),
    path("station-events/", StationEventCreateView.as_view(), name="station_event_create"),
    path("offline-events/", StationOfflineEventSyncView.as_view(), name="offline_event_sync"),
    path("components/", InstalledComponentCreateAPIView.as_view(), name="component_create"),
    path("measurements/", ProductionMeasurementCreateAPIView.as_view(), name="measurement_create"),
    path("quality-gates/<int:pk>/decision/", QualityGateDecisionView.as_view(), name="quality_gate_decision"),
    path("equipment-events/", EquipmentEventIngestView.as_view(), name="equipment_event_ingest"),
    path("equipment-events/<str:external_id>/", EquipmentEventDetailView.as_view(), name="equipment_event_detail"),
]
