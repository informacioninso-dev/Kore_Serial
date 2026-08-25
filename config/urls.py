from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from config.views import DashboardView
from tenants import tenant_views


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", DashboardView.as_view(), name="dashboard"),
    path("produccion/", include(("assembly.urls", "assembly"), namespace="assembly")),
    path("ensamblaje/", include(("assembly.urls", "assembly"), namespace="assembly_legacy")),
    path("configuracion/", include(("core.urls", "core"), namespace="core")),
    path("usuarios/", tenant_views.TenantUserListView.as_view(), name="tenant_users"),
    path("usuarios/nuevo/", tenant_views.TenantUserCreateView.as_view(), name="tenant_user_create"),
    path("usuarios/<int:pk>/toggle/", tenant_views.TenantUserToggleView.as_view(), name="tenant_user_toggle"),
    path("usuarios/<int:pk>/eliminar/", tenant_views.TenantUserDeleteView.as_view(), name="tenant_user_delete"),
    path("usuarios/<int:pk>/password/", tenant_views.TenantUserPasswordResetView.as_view(), name="tenant_user_password_reset"),
    path("usuarios/<int:pk>/rol/", tenant_views.TenantUserRoleUpdateView.as_view(), name="tenant_user_role_update"),
    path("usuarios/roles/nuevo/", tenant_views.TenantRoleCreateView.as_view(), name="tenant_role_create"),
    path("usuarios/roles/<int:pk>/editar/", tenant_views.TenantRoleUpdateView.as_view(), name="tenant_role_update"),
    path("usuarios/roles/<int:pk>/eliminar/", tenant_views.TenantRoleDeleteView.as_view(), name="tenant_role_delete"),
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/assembly/v1/", include(("assembly.api_urls", "assembly_api_v1"), namespace="assembly_api_v1")),
    path("api/assembly/", include(("assembly.api_urls", "assembly_api"), namespace="assembly_api")),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="auth/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password/change/", auth_views.PasswordChangeView.as_view(template_name="auth/password_change.html"), name="password_change"),
    path("accounts/password/change/done/", auth_views.PasswordChangeDoneView.as_view(template_name="auth/password_change_done.html"), name="password_change_done"),
    path("accounts/password/reset/", auth_views.PasswordResetView.as_view(template_name="auth/password_reset.html", email_template_name="auth/password_reset_email.txt", html_email_template_name="auth/password_reset_email.html", subject_template_name="auth/password_reset_subject.txt", success_url="/accounts/password/reset/done/"), name="password_reset"),
    path("accounts/password/reset/done/", auth_views.PasswordResetDoneView.as_view(template_name="auth/password_reset_done.html"), name="password_reset_done"),
    path("accounts/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(template_name="auth/password_reset_confirm.html", success_url="/accounts/reset/done/"), name="password_reset_confirm"),
    path("accounts/reset/done/", auth_views.PasswordResetCompleteView.as_view(template_name="auth/password_reset_complete.html"), name="password_reset_complete"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
