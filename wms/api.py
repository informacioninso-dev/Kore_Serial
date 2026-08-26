from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import InboundReceiptLine, InventoryBalance, InventoryState, Material, MaterialLot, MaterialSerial
from .services import adjust_inventory, change_inventory_state, receive_receipt_line, transfer_inventory


class WMSAPIView(APIView):
    required_permission = ""

    def enforce_permission(self):
        if self.required_permission and not self.request.user.has_perm(self.required_permission):
            raise PermissionDenied("El token no tiene permiso para esta operacion WMS.")


class ReceiptReceiveSerializer(serializers.Serializer):
    receipt_line_id = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal("0.0001"))
    lot_number = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    serial_numbers = serializers.ListField(child=serializers.CharField(max_length=120), required=False, default=list)
    reason = serializers.CharField(max_length=240, required=False, allow_blank=True, default="")


class InventoryOperationSerializer(serializers.Serializer):
    operation = serializers.ChoiceField(choices=("TRANSFER", "STATE", "ADJUST_IN", "ADJUST_OUT"))
    material_code = serializers.CharField(max_length=80)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal("0.0001"))
    source_location_code = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    destination_location_code = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    source_state = serializers.ChoiceField(choices=InventoryState.choices, required=False, allow_blank=True, default="")
    destination_state = serializers.ChoiceField(choices=InventoryState.choices, required=False, allow_blank=True, default="")
    lot_number = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    serial_number = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    reason = serializers.CharField(max_length=240)


class MaterialListAPIView(WMSAPIView):
    required_permission = "wms.view_material"

    def get(self, request):
        self.enforce_permission()
        materials = Material.objects.filter(is_active=True).select_related("base_unit").order_by("code")
        return Response(
            [
                {
                    "code": material.code,
                    "name": material.name,
                    "base_unit": material.base_unit.code,
                    "traceability": material.traceability,
                }
                for material in materials
            ]
        )


class InventoryBalanceListAPIView(WMSAPIView):
    required_permission = "wms.view_inventorybalance"

    def get(self, request):
        self.enforce_permission()
        balances = InventoryBalance.objects.select_related("material__base_unit", "location", "lot", "serial").order_by(
            "material__code", "location__code", "state", "id"
        )
        material_code = request.query_params.get("material", "").strip()
        location_code = request.query_params.get("location", "").strip()
        if material_code:
            balances = balances.filter(material__code=material_code)
        if location_code:
            balances = balances.filter(location__code=location_code)
        return Response(
            [
                {
                    "material_code": balance.material.code,
                    "location_code": balance.location.code,
                    "state": balance.state,
                    "quantity": str(balance.quantity),
                    "unit": balance.material.base_unit.code,
                    "lot_number": balance.lot.number if balance.lot_id else "",
                    "serial_number": balance.serial.number if balance.serial_id else "",
                }
                for balance in balances
            ]
        )


class ReceiptReceiveAPIView(WMSAPIView):
    required_permission = "wms.add_inventorymovement"

    def post(self, request):
        self.enforce_permission()
        serializer = ReceiptReceiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        line = InboundReceiptLine.objects.select_related("receipt", "material").filter(pk=serializer.validated_data["receipt_line_id"]).first()
        if line is None:
            raise NotFound("Linea de recepcion no encontrada.")
        try:
            movements = receive_receipt_line(
                actor=request.user,
                receipt_line=line,
                quantity=serializer.validated_data["quantity"],
                lot_number=serializer.validated_data["lot_number"],
                serial_numbers=serializer.validated_data["serial_numbers"],
                reason=serializer.validated_data["reason"],
            )
        except DjangoValidationError as error:
            raise ValidationError({"detail": error.messages})
        return Response({"movement_ids": [movement.pk for movement in movements], "receipt_code": line.receipt.code}, status=status.HTTP_201_CREATED)


class InventoryOperationAPIView(WMSAPIView):
    required_permission = "wms.add_inventorymovement"

    def post(self, request):
        self.enforce_permission()
        serializer = InventoryOperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        material = Material.objects.filter(code=data["material_code"], is_active=True).first()
        if material is None:
            raise ValidationError({"material_code": "Material no encontrado o inactivo."})
        from core.models import Location

        source = Location.objects.filter(code=data["source_location_code"], is_active=True).first() if data["source_location_code"] else None
        destination = Location.objects.filter(code=data["destination_location_code"], is_active=True).first() if data["destination_location_code"] else None
        lot = MaterialLot.objects.filter(material=material, number=data["lot_number"]).first() if data["lot_number"] else None
        serial = MaterialSerial.objects.filter(material=material, number=data["serial_number"]).first() if data["serial_number"] else None
        if data["lot_number"] and lot is None:
            raise ValidationError({"lot_number": "Lote no encontrado para el material."})
        if data["serial_number"] and serial is None:
            raise ValidationError({"serial_number": "Serie no encontrada para el material."})
        try:
            if data["operation"] == "TRANSFER":
                movement = transfer_inventory(actor=request.user, material=material, quantity=data["quantity"], source_location=source, destination_location=destination, state=data["source_state"], lot=lot, serial=serial, reason=data["reason"])
            elif data["operation"] == "STATE":
                movement = change_inventory_state(actor=request.user, material=material, quantity=data["quantity"], location=source, source_state=data["source_state"], destination_state=data["destination_state"], lot=lot, serial=serial, reason=data["reason"])
            else:
                movement = adjust_inventory(actor=request.user, material=material, quantity=data["quantity"], location=destination if data["operation"] == "ADJUST_IN" else source, state=data["destination_state"] if data["operation"] == "ADJUST_IN" else data["source_state"], direction="IN" if data["operation"] == "ADJUST_IN" else "OUT", lot=lot, serial=serial, reason=data["reason"])
        except (DjangoValidationError, AttributeError) as error:
            raise ValidationError({"detail": getattr(error, "messages", [str(error)])})
        return Response({"id": movement.pk, "movement_type": movement.movement_type, "quantity": str(movement.quantity)}, status=status.HTTP_201_CREATED)
