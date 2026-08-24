from django.contrib import admin
from .models import AuditPlan, AuditSchedule, AuditExecution, AuditFinding, AuditClosure

admin.site.register(AuditPlan)
admin.site.register(AuditSchedule)
admin.site.register(AuditExecution)
admin.site.register(AuditFinding)
admin.site.register(AuditClosure)
