from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("review/<int:agreement_id>/", views.create_review, name="leave_review"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.show_dashboard, name="dashboard"),
    path("company/edit/", views.edit_company, name="edit_company"),
    path("verify-email/", views.verify_email, name="verify_email"),
    path("verify-email/resend/", views.resend_verification, name="resend_verification"),
    path("analytics/", views.show_analytics, name="analytics"),
    path(
        "company/<int:company_id>/", views.show_company_profile, name="company_profile"
    ),
]
