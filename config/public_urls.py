from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from config.views import PublicDashboardView


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", PublicDashboardView.as_view(), name="dashboard"),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="auth/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password/change/", auth_views.PasswordChangeView.as_view(template_name="auth/password_change.html"), name="password_change"),
    path("accounts/password/change/done/", auth_views.PasswordChangeDoneView.as_view(template_name="auth/password_change_done.html"), name="password_change_done"),
    path("accounts/password/reset/", auth_views.PasswordResetView.as_view(template_name="auth/password_reset.html", email_template_name="auth/password_reset_email.txt", html_email_template_name="auth/password_reset_email.html", subject_template_name="auth/password_reset_subject.txt", success_url="/accounts/password/reset/done/"), name="password_reset"),
    path("accounts/password/reset/done/", auth_views.PasswordResetDoneView.as_view(template_name="auth/password_reset_done.html"), name="password_reset_done"),
    path("accounts/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(template_name="auth/password_reset_confirm.html", success_url="/accounts/reset/done/"), name="password_reset_confirm"),
    path("accounts/reset/done/", auth_views.PasswordResetCompleteView.as_view(template_name="auth/password_reset_complete.html"), name="password_reset_complete"),
]
