from django.urls import path
from . import views
from . import exports

app_name = "audit"

urlpatterns = [
    path("", views.AuditDashboardView.as_view(), name="dashboard"),
    path("planes/", views.AuditPlanListView.as_view(), name="plan_list"),
    path("planes/nuevo/", views.AuditPlanCreateView.as_view(), name="plan_create"),
    path("planes/<int:pk>/", views.AuditPlanDetailView.as_view(), name="plan_detail"),
    path("planes/<int:pk>/aprobar/", views.AuditPlanApproveView.as_view(), name="plan_approve"),
    path("planes/<int:plan_pk>/nueva-auditoria/", views.AuditScheduleCreateView.as_view(), name="schedule_create"),
    path("auditorias/<int:pk>/", views.AuditScheduleDetailView.as_view(), name="schedule_detail"),
    path("auditorias/<int:pk>/cancelar/", views.AuditScheduleCancelView.as_view(), name="schedule_cancel"),
    path("auditorias/<int:pk>/iniciar/", views.AuditExecutionCreateView.as_view(), name="execution_create"),
    path("ejecucion/<int:pk>/", views.AuditExecutionDetailView.as_view(), name="execution_detail"),
    path("ejecucion/<int:pk>/hallazgo/", views.AuditFindingCreateView.as_view(), name="finding_create"),
    path("ejecucion/<int:pk>/cerrar/", views.AuditClosureView.as_view(), name="closure"),
    path("planes/<int:pk>/export/pdf/", exports.AuditPlanPDFView.as_view(), name="plan_pdf"),
    path("planes/<int:pk>/export/excel/", exports.AuditPlanExcelView.as_view(), name="plan_excel"),
    path("ejecucion/<int:pk>/export/pdf/", exports.AuditExecutionPDFView.as_view(), name="execution_pdf"),
    path("ejecucion/<int:pk>/export/excel/", exports.AuditExecutionExcelView.as_view(), name="execution_excel"),
]
