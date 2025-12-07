from django.urls import path
from . import views
from .password_views import CustomPasswordChangeView
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', views.marketplace, name='marketplace'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('admin_dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('users/create/', views.create_user, name='create_user'),
    path('users/<int:user_id>/edit/', views.edit_user, name='edit_user'),
    path('users/<int:user_id>/delete/', views.delete_user, name='delete_user'),
    path('space/<uuid:space_id>/', views.space_view, name='space_view'),
    path('space/<uuid:space_id>/manage/', views.manage_users, name='manage_users'),
    path('space/<uuid:space_id>/edit/', views.edit_space, name='edit_space'),
    path('space/<uuid:space_id>/delete/', views.delete_space, name='delete_space'),
    path('space/create/', views.create_space, name='create_space'),
    path('space/<uuid:space_id>/upload/', views.upload_document, name='upload_document'),
    path('space/<uuid:space_id>/ingest_url/', views.ingest_url_view, name='ingest_url'),
    path('space/<uuid:space_id>/document/<uuid:doc_id>/delete/', views.delete_document, name='delete_document'),
    path('space/<uuid:space_id>/chat/', views.chat_api, name='chat_api'),
    
    # Auth
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='marketplace', template_name='registration/logout_confirm.html'), name='logout'),
    path('password_change/', CustomPasswordChangeView.as_view(), name='password_change'),
    path('password_change/done/', auth_views.PasswordChangeDoneView.as_view(template_name='registration/password_change_done.html'), name='password_change_done'),
    
    # Protected Media
    path('media/documents/<path:path>', views.serve_protected_media, name='serve_protected_media'),
]
