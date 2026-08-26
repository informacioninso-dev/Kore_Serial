from django.urls import path

from .api import InventoryBalanceListAPIView, InventoryOperationAPIView, LineInstallationAPIView, MaterialListAPIView, PickMissionListAPIView, PickTaskCompleteAPIView, ReceiptReceiveAPIView


urlpatterns = [
    path("materials/", MaterialListAPIView.as_view(), name="material_list"),
    path("balances/", InventoryBalanceListAPIView.as_view(), name="balance_list"),
    path("receipts/receive/", ReceiptReceiveAPIView.as_view(), name="receipt_receive"),
    path("movements/", InventoryOperationAPIView.as_view(), name="movement_create"),
    path("picking/missions/", PickMissionListAPIView.as_view(), name="pick_mission_list"),
    path("picking/tasks/complete/", PickTaskCompleteAPIView.as_view(), name="pick_task_complete"),
    path("line-installations/", LineInstallationAPIView.as_view(), name="line_installation"),
]
