from django.urls import path

from .views import ChangeControlDetailView, ChangeControlListView

app_name = "changecontrol"

urlpatterns = [
    path("", ChangeControlListView.as_view(), name="list"),
    path("<str:code>/", ChangeControlDetailView.as_view(), name="detail"),
]
