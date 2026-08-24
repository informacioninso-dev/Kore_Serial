from django.urls import path

from .views import SerializedUnitListView


app_name = "assembly"

urlpatterns = [
    path("unidades/", SerializedUnitListView.as_view(), name="unit_list"),
]
