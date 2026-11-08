"""
URL configuration for the core application.
Routes directly to Class-Based Views for fellowship, system administration, and testing.
"""

from django.urls import path
from core import views

urlpatterns = [
    # Public & Fellowship Pages
    path('', views.HomeView.as_view(), name='home'),
    path('my-church/', views.MyChurchView.as_view(), name='my_church'),
    path('churches/', views.ChurchListView.as_view(), name='church_list'),
    path('churches/create/', views.CreateChurchView.as_view(), name='create_church'),
    path('churches/invite/<str:invite_code>/', views.JoinChurchByInviteView.as_view(), name='join_church_invite'),
    path('churches/<int:church_id>/', views.ChurchDetailView.as_view(), name='church_detail'),
    path('churches/<int:church_id>/assign-commissioner/', views.AssignChurchCommissionerView.as_view(), name='assign_church_commissioner'),
    path('churches/<int:church_id>/toggle-dues/', views.ToggleChurchDuesView.as_view(), name='toggle_church_dues'),
    path('announcements/', views.AnnouncementListView.as_view(), name='announcement_list'),
    path('announcements/create/', views.CreateAnnouncementView.as_view(), name='create_announcement'),
    path('announcements/<int:pk>/', views.AnnouncementDetailView.as_view(), name='announcement_detail'),
    path('announcements/<int:pk>/toggle-banner/', views.ToggleAnnouncementBannerView.as_view(), name='toggle_announcement_banner'),

    # In-App Sandbox & Test User Portal (Kubernetes & Browser Testing)
    path('testing-sandbox/', views.TestUsersPortalView.as_view(), name='test_users_portal'),
    path('testing-sandbox/switch/<str:username>/', views.QuickSwitchTestUserView.as_view(), name='quick_switch_test_user'),
    path('testing-sandbox/create/', views.CreateInAppTestUserView.as_view(), name='create_in_app_test_user'),
    path('testing-sandbox/reseed/', views.ResetAllDemoDataInAppView.as_view(), name='reset_all_demo_data'),

    # Platform System Administration & GFS Backups (Superuser Only)
    path('system-admin/', views.SystemAdminDashboardView.as_view(), name='system_admin_dashboard'),
    path('system-admin/backups/', views.SystemAdminBackupsView.as_view(), name='system_admin_backups'),
    path('system-admin/backups/create/', views.BackupManualTriggerView.as_view(), name='backup_manual_trigger'),
    path('system-admin/backups/test-connection/', views.BackupTestConnectionApiView.as_view(), name='backup_test_connection_api'),
    path('system-admin/backups/<uuid:backup_uuid>/download/', views.DownloadBackupView.as_view(), name='download_backup'),
    path('system-admin/backups/<uuid:backup_uuid>/restore/', views.RestoreBackupView.as_view(), name='restore_backup_view'),
    path('system-admin/backups/<uuid:backup_uuid>/delete/', views.DeleteBackupView.as_view(), name='delete_backup'),
    path('system-admin/users/', views.SystemAdminUsersView.as_view(), name='system_admin_users'),
    path('system-admin/users/<int:user_id>/reset-password/', views.AdminResetUserPasswordView.as_view(), name='admin_reset_user_password'),
    path('system-admin/users/<int:user_id>/toggle-active/', views.AdminToggleUserActiveView.as_view(), name='admin_toggle_user_active'),
    path('system-admin/maintenance/toggle/', views.AdminToggleMaintenanceModeView.as_view(), name='admin_toggle_maintenance_mode'),
    path('system-admin/banner/update/', views.AdminUpdateEmergencyBannerView.as_view(), name='admin_update_emergency_banner'),
]
