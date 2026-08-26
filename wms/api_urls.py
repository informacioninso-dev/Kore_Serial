from django.urls import path

from .api import InventoryBalanceListAPIView, InventoryOperationAPIView, MaterialListAPIView, ReceiptReceiveAPIView


urlpatterns = [
    path("materials/", MaterialListAPIView.as_view(), name="material_list"),
    path("balances/", InventoryBalanceListAPIView.as_view(), name="balance_list"),
    path("receipts/receive/", ReceiptReceiveAPIView.as_view(), name="receipt_receive"),
    path("movements/", InventoryOperationAPIView.as_view(), name="movement_create"),
]
