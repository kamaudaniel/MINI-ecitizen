from django.urls import path

from .views import (
    CustomLoginView,
    CustomLogoutView,
    admin_dashboard,
    admin_feedback_dashboard,
    admin_feedback_detail,
    admin_improvement_create,
    admin_improvement_detail,
    admin_improvement_list,
    create_request,
    landing,
    register,
    request_detail,
    request_list,
)

urlpatterns = [
    path('', landing, name='landing'),
    path('requests/', request_list, name='request_list'),
    path('register/', register, name='register'),
    path('accounts/login/', CustomLoginView.as_view(), name='login'),
    path('logout/', CustomLogoutView.as_view(), name='logout'),
    path('requests/new/', create_request, name='create_request'),
    path('requests/<int:pk>/', request_detail, name='request_detail'),
    path('dashboard/', admin_dashboard, name='admin_dashboard'),
    path('dashboard/feedback/', admin_feedback_dashboard, name='admin_feedback_dashboard'),
    path('dashboard/feedback/<int:pk>/', admin_feedback_detail, name='admin_feedback_detail'),
    path('dashboard/improvements/', admin_improvement_list, name='admin_improvement_list'),
    path('dashboard/improvements/new/', admin_improvement_create, name='admin_improvement_create'),
    path('dashboard/improvements/<int:pk>/', admin_improvement_detail, name='admin_improvement_detail'),
]
