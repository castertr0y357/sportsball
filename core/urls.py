from . import views_admin
from django.urls import path
from . import views
from . import views_testing

urlpatterns = [
    path('', views.home, name='home'),
    path('my-church/', views.my_church, name='my_church'),
    path('churches/', views.church_list, name='church_list'),
    path('churches/create/', views.create_church, name='create_church'),
    path('churches/invite/<str:invite_code>/', views.join_church_by_invite, name='join_church_invite'),
    path('churches/<int:church_id>/', views.church_detail, name='church_detail'),
    path('churches/<int:church_id>/assign-commissioner/', views.assign_church_commissioner, name='assign_church_commissioner'),
    path('churches/<int:church_id>/toggle-dues/', views.toggle_church_dues, name='toggle_church_dues'),
    path('announcements/', views.announcement_list, name='announcement_list'),
    path('announcements/create/', views.create_announcement, name='create_announcement'),
    # In-App Sandbox & Test User Portal (Kubernetes & Browser Testing)
    path('testing-sandbox/', views_testing.test_users_portal, name='test_users_portal'),
    path('testing-sandbox/switch/<str:username>/', views_testing.quick_switch_test_user, name='quick_switch_test_user'),
    path('testing-sandbox/create/', views_testing.create_in_app_test_user, name='create_in_app_test_user'),
    path('testing-sandbox/reseed/', views_testing.reset_all_demo_data_in_app, name='reset_all_demo_data'),
    path('announcements/<int:pk>/', views.announcement_detail, name='announcement_detail'),
    path('announcements/<int:pk>/toggle-banner/', views.toggle_announcement_banner, name='toggle_announcement_banner'),
    # Platform System Administration & GFS Backups (Superuser Only)
    path('system-admin/', views_admin.system_admin_dashboard, name='system_admin_dashboard'),
    path('system-admin/backups/', views_admin.system_admin_backups, name='system_admin_backups'),
    path('system-admin/backups/create/', views_admin.backup_manual_trigger, name='backup_manual_trigger'),
    path('system-admin/backups/test-connection/', views_admin.backup_test_connection_api, name='backup_test_connection_api'),
    path('system-admin/backups/<uuid:backup_uuid>/download/', views_admin.download_backup, name='download_backup'),
    path('system-admin/backups/<uuid:backup_uuid>/restore/', views_admin.restore_backup_view, name='restore_backup_view'),
    path('system-admin/backups/<uuid:backup_uuid>/delete/', views_admin.delete_backup, name='delete_backup'),
    path('system-admin/users/', views_admin.system_admin_users, name='system_admin_users'),
    path('system-admin/users/<int:user_id>/reset-password/', views_admin.admin_reset_user_password, name='admin_reset_user_password'),
    path('system-admin/users/<int:user_id>/toggle-active/', views_admin.admin_toggle_user_active, name='admin_toggle_user_active'),
    path('system-admin/maintenance/toggle/', views_admin.admin_toggle_maintenance_mode, name='admin_toggle_maintenance_mode'),
    path('system-admin/banner/update/', views_admin.admin_update_emergency_banner, name='admin_update_emergency_banner'),
]
