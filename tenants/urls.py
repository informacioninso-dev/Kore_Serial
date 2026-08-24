from django.urls import path

from . import views

app_name = "tenants"

urlpatterns = [
    # Tenants
    path("", views.TenantListView.as_view(), name="list"),
    path("nuevo/", views.TenantCreateView.as_view(), name="create"),
    path("<int:pk>/", views.TenantDetailView.as_view(), name="detail"),
    path("<int:pk>/editar/", views.TenantEditView.as_view(), name="edit"),
    path("<int:pk>/switch/", views.TenantSwitchView.as_view(), name="switch"),
    path("<int:pk>/toggle/", views.TenantToggleActiveView.as_view(), name="toggle_active"),
    path("miembro/<int:pk>/toggle/", views.MembershipToggleView.as_view(), name="membership_toggle"),
    path("miembro/<int:pk>/eliminar/", views.MembershipDeleteView.as_view(), name="membership_delete"),
    path("<int:pk>/modulo/<str:module>/toggle/", views.TenantModuleToggleView.as_view(), name="module_toggle"),
    path("<int:pk>/edicion/<str:edition>/aplicar/", views.TenantApplyEditionView.as_view(), name="apply_edition"),
    path("<int:pk>/cajero/asignar/", views.TenantCashierAssignView.as_view(), name="cashier_assign"),
    path("<int:pk>/cajero/<int:assignment_pk>/toggle/", views.TenantCashierAssignToggleView.as_view(), name="cashier_toggle"),

    # Planes
    path("planes/", views.PlanListView.as_view(), name="plan_list"),
    path("planes/nuevo/", views.PlanCreateView.as_view(), name="plan_create"),
    path("planes/<int:pk>/editar/", views.PlanEditView.as_view(), name="plan_edit"),
    path("planes/<int:pk>/toggle/", views.PlanToggleView.as_view(), name="plan_toggle"),
]
