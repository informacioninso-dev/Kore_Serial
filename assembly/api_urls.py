from django.urls import path

from .api import EquipmentEventIngestView


urlpatterns = [
    path("equipment-events/", EquipmentEventIngestView.as_view(), name="equipment_event_ingest"),
]
