from django.urls import path

from .api import ConnectorStatusAPIView, InboundReceiveAPIView


urlpatterns = [
    path("inbound/", InboundReceiveAPIView.as_view(), name="inbound_receive"),
    path("status/", ConnectorStatusAPIView.as_view(), name="connector_status"),
]
