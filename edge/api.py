"""API que habla con el collector, no con personas.

El agente de planta no tiene usuario: se autentica con el token de su gateway
en la cabecera `X-Edge-Token`. Por eso estos endpoints no usan JWT.
"""

from rest_framework import serializers, status
from rest_framework.exceptions import AuthenticationFailed, NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import EdgeCommand, EdgeCommandStatus, EdgeGatewayStatus, EdgeSignalStatus
from .services import ack_command, authenticate_gateway, claim_commands, ingest_signal, register_heartbeat


class EdgeGatewayAPIView(APIView):
    """Resuelve el gateway por token antes de cualquier operacion."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get_gateway(self, request):
        token = request.headers.get("X-Edge-Token", "").strip()
        gateway = authenticate_gateway(token)
        if gateway is None:
            raise AuthenticationFailed("Token de gateway invalido o gateway inactivo.")
        return gateway


class SignalSerializer(serializers.Serializer):
    external_id = serializers.CharField(max_length=120)
    device_code = serializers.CharField(max_length=40)
    signal_key = serializers.CharField(max_length=80)
    raw_value = serializers.CharField(max_length=240, required=False, allow_blank=True, default="")
    numeric_value = serializers.DecimalField(
        max_digits=14, decimal_places=4, required=False, allow_null=True, default=None
    )
    unit_of_measure = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    unit_serial_number = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    operator_username = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    captured_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    from_buffer = serializers.BooleanField(required=False, default=False)
    payload = serializers.JSONField(required=False, default=dict)


class SignalBatchSerializer(serializers.Serializer):
    signals = SignalSerializer(many=True, allow_empty=False)


class HeartbeatSerializer(serializers.Serializer):
    agent_version = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    queue_depth = serializers.IntegerField(min_value=0, required=False, default=0)
    buffered_count = serializers.IntegerField(min_value=0, required=False, default=0)
    cpu_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True, default=None
    )
    memory_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True, default=None
    )
    latency_ms = serializers.IntegerField(min_value=0, required=False, allow_null=True, default=None)
    status = serializers.ChoiceField(
        choices=EdgeGatewayStatus.choices, required=False, default=EdgeGatewayStatus.ONLINE
    )
    detail = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class CommandAckSerializer(serializers.Serializer):
    command_id = serializers.IntegerField(min_value=1)
    succeeded = serializers.BooleanField()
    response = serializers.JSONField(required=False, default=dict)
    detail = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class SignalIngestAPIView(EdgeGatewayAPIView):
    """Recibe senales crudas, incluido el vaciado del buffer offline."""

    def post(self, request):
        gateway = self.get_gateway(request)
        payload = request.data if isinstance(request.data, dict) else {}
        if "signals" not in payload:
            payload = {"signals": [request.data]}
        serializer = SignalBatchSerializer(data=payload)
        serializer.is_valid(raise_exception=True)

        accepted, duplicated, failed = [], [], []
        for item in serializer.validated_data["signals"]:
            try:
                signal, created = ingest_signal(
                    gateway=gateway,
                    device_code=item["device_code"],
                    external_id=item["external_id"],
                    signal_key=item["signal_key"],
                    raw_value=item["raw_value"],
                    numeric_value=item["numeric_value"],
                    unit_of_measure=item["unit_of_measure"],
                    unit_serial_number=item["unit_serial_number"],
                    operator_username=item["operator_username"],
                    captured_at=item["captured_at"],
                    from_buffer=item["from_buffer"],
                    payload=item["payload"],
                )
            except ValueError as error:
                failed.append({"external_id": item["external_id"], "detail": str(error)})
                continue
            entry = {
                "external_id": signal.external_id,
                "id": signal.pk,
                "status": signal.status,
                "detail": signal.result_detail,
            }
            (accepted if created else duplicated).append(entry)

        return Response(
            {
                "gateway": gateway.code,
                "accepted": accepted,
                "duplicated": duplicated,
                "failed": failed,
            },
            status=status.HTTP_200_OK,
        )


class HeartbeatAPIView(EdgeGatewayAPIView):
    """Latido del collector. Devuelve cuantos comandos tiene esperando."""

    def post(self, request):
        gateway = self.get_gateway(request)
        serializer = HeartbeatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        check = register_heartbeat(
            gateway=gateway,
            agent_version=data["agent_version"],
            queue_depth=data["queue_depth"],
            buffered_count=data["buffered_count"],
            cpu_percent=data["cpu_percent"],
            memory_percent=data["memory_percent"],
            latency_ms=data["latency_ms"],
            status=data["status"],
            detail=data["detail"],
        )
        pending = EdgeCommand.objects.filter(
            gateway=gateway, status=EdgeCommandStatus.QUEUED
        ).count()
        return Response(
            {
                "gateway": gateway.code,
                "acknowledged_at": check.reported_at,
                "heartbeat_interval_seconds": gateway.heartbeat_interval_seconds,
                "pending_commands": pending,
            }
        )


class DeviceConfigAPIView(EdgeGatewayAPIView):
    """Configuracion que el collector necesita para arrancar."""

    def get(self, request):
        gateway = self.get_gateway(request)
        devices = gateway.devices.filter(is_active=True).select_related("equipment", "station")
        return Response(
            {
                "gateway": gateway.code,
                "heartbeat_interval_seconds": gateway.heartbeat_interval_seconds,
                "devices": [
                    {
                        "code": device.code,
                        "name": device.name,
                        "device_type": device.device_type,
                        "protocol": device.protocol,
                        "address": device.address,
                        "equipment_code": device.equipment_code,
                        "station_code": device.station.code if device.station_id else "",
                    }
                    for device in devices
                ],
            }
        )


class CommandPullAPIView(EdgeGatewayAPIView):
    """El gateway recoge sus comandos cuando puede. Nadie empuja a planta."""

    def get(self, request):
        gateway = self.get_gateway(request)
        commands = claim_commands(gateway)
        return Response(
            {
                "gateway": gateway.code,
                "commands": [
                    {
                        "id": command.pk,
                        "command_type": command.command_type,
                        "device_code": command.device.code if command.device_id else "",
                        "payload": command.payload,
                        "expires_at": command.expires_at,
                    }
                    for command in commands
                ],
            }
        )


class CommandAckAPIView(EdgeGatewayAPIView):
    """Cierra el handshake con el resultado real de la orden."""

    def post(self, request):
        gateway = self.get_gateway(request)
        serializer = CommandAckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        command = EdgeCommand.objects.filter(pk=data["command_id"], gateway=gateway).first()
        if command is None:
            raise NotFound("Comando no encontrado para este gateway.")
        try:
            ack_command(
                command=command,
                succeeded=data["succeeded"],
                response=data["response"],
                detail=data["detail"],
            )
        except ValueError as error:
            raise ValidationError({"command_id": str(error)})
        return Response({"id": command.pk, "status": command.status})


class SignalStatusAPIView(EdgeGatewayAPIView):
    """Permite al collector confirmar que sus senales se resolvieron."""

    def get(self, request):
        gateway = self.get_gateway(request)
        pending = gateway.signals.filter(
            status__in=[EdgeSignalStatus.PENDING, EdgeSignalStatus.REJECTED]
        ).count()
        return Response(
            {
                "gateway": gateway.code,
                "unresolved_signals": pending,
                "buffered_signal_count": gateway.buffered_signal_count,
            }
        )
