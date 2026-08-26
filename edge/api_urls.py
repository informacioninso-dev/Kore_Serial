from django.urls import path

from .api import (
    CommandAckAPIView,
    CommandPullAPIView,
    DeviceConfigAPIView,
    HeartbeatAPIView,
    SignalIngestAPIView,
    SignalStatusAPIView,
)


urlpatterns = [
    path("signals/", SignalIngestAPIView.as_view(), name="signal_ingest"),
    path("signals/status/", SignalStatusAPIView.as_view(), name="signal_status"),
    path("heartbeat/", HeartbeatAPIView.as_view(), name="heartbeat"),
    path("devices/", DeviceConfigAPIView.as_view(), name="device_config"),
    path("commands/", CommandPullAPIView.as_view(), name="command_pull"),
    path("commands/ack/", CommandAckAPIView.as_view(), name="command_ack"),
]
