"""Puerta de entrada para sistemas externos.

Igual que el collector de Conectividad, el sistema externo no tiene usuario:
se identifica con el token de entrada de su conector.
"""

from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ConnectorContract, ConnectorDirection
from .services import authenticate_connector, receive_inbound


class InboundSerializer(serializers.Serializer):
    external_id = serializers.CharField(max_length=180)
    contract_code = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    payload = serializers.JSONField(required=False, default=dict)


class ConnectorAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get_connector(self, request):
        token = request.headers.get("X-Connect-Token", "").strip()
        connector = authenticate_connector(token)
        if connector is None:
            raise AuthenticationFailed("Token de conector invalido o conector inactivo.")
        return connector


class InboundReceiveAPIView(ConnectorAPIView):
    """Recibe un mensaje externo. Idempotente por external_id."""

    def post(self, request):
        connector = self.get_connector(request)
        serializer = InboundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        contract = None
        if data["contract_code"]:
            contract = ConnectorContract.objects.filter(
                code=data["contract_code"],
                connector=connector,
                direction=ConnectorDirection.INBOUND,
                is_active=True,
            ).first()
            if contract is None:
                raise ValidationError({"contract_code": "Contrato de entrada no encontrado."})

        try:
            message, created = receive_inbound(
                connector=connector,
                external_id=data["external_id"],
                payload=data["payload"],
                contract=contract,
            )
        except ValueError as error:
            raise ValidationError({"connector": str(error)})

        return Response(
            {
                "id": message.pk,
                "external_id": message.external_id,
                "status": message.status,
                "duplicated": not created,
            }
        )


class ConnectorStatusAPIView(ConnectorAPIView):
    """Le permite al sistema externo saber como va su cola."""

    def get(self, request):
        connector = self.get_connector(request)
        return Response(
            {
                "connector": connector.code,
                "direction": connector.direction,
                "transport": connector.transport,
                "queued": connector.outbound.filter(status="QUEUED").count(),
                "failed": connector.outbound.filter(status="FAILED").count(),
                "inbound_received": connector.inbound.count(),
            }
        )
