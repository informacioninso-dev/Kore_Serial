from django.urls import path

from . import views


urlpatterns = [
    path("", views.EventBusDashboardView.as_view(), name="dashboard"),
    path("catalogo/", views.EventTypeListView.as_view(), name="type_list"),
    path("catalogo/nuevo/", views.EventTypeCreateView.as_view(), name="type_create"),
    path("catalogo/<int:pk>/editar/", views.EventTypeUpdateView.as_view(), name="type_update"),
    path("catalogo/sembrar/", views.SeedCatalogView.as_view(), name="type_seed"),
    path("eventos/", views.EventListView.as_view(), name="event_list"),
    path("eventos/<int:pk>/", views.EventDetailView.as_view(), name="event_detail"),
    path("suscripciones/", views.SubscriptionListView.as_view(), name="subscription_list"),
    path("suscripciones/nueva/", views.SubscriptionCreateView.as_view(), name="subscription_create"),
    path("suscripciones/<int:pk>/editar/", views.SubscriptionUpdateView.as_view(), name="subscription_update"),
    path("entregas/", views.DeliveryListView.as_view(), name="delivery_list"),
    path("entregas/procesar/", views.DispatchPendingView.as_view(), name="delivery_dispatch"),
    path("entregas/<int:pk>/reintentar/", views.RetryDeliveryView.as_view(), name="delivery_retry"),
    path("indicadores/", views.IndicatorListView.as_view(), name="indicator_list"),
    path("indicadores/recalcular/", views.RebuildIndicatorsView.as_view(), name="indicator_rebuild"),
]
