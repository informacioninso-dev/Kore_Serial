from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone

from .models import EquipmentInboundEventStatus, StationEventType
from .services import process_equipment_event


class EquipmentEventSerializer(serializers.Serializer):
    external_id = serializers.CharField(max_length=120)
    equipment_code = serializers.CharField(max_length=50)
    station_code = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    unit_serial_number = serializers.CharField(max_length=120)
    operator_username = serializers.CharField(max_length=150)
    event_type = serializers.ChoiceField(choices=StationEventType.choices)
    event_at = serializers.DateTimeField(required=False, default=timezone.now)
    payload = serializers.JSONField(required=False, default=dict)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class EquipmentEventIngestView(APIView):
    """Entrada HTTP para recolectores que operan fuera de los workers Django."""

    def post(self, request):
        if not request.user.has_perm("assembly.add_equipmentinboundevent"):
            raise PermissionDenied("No tiene permiso para registrar eventos de equipos.")

        serializer = EquipmentEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        inbound_event, created = process_equipment_event(actor=request.user, **data)
        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        if created and inbound_event.status == EquipmentInboundEventStatus.REJECTED:
            response_status = status.HTTP_422_UNPROCESSABLE_ENTITY
        return Response(
            {
                "external_id": inbound_event.external_id,
                "status": inbound_event.status,
                "detail": inbound_event.result_detail,
                "station_event_id": inbound_event.station_event_id,
            },
            status=response_status,
        )
