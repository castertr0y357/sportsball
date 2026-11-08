"""
Core views package consolidating public church & announcement views,
system administration & telemetry views, and testing sandbox views.
All views are implemented as Class-Based Views with backward-compatible callables.
"""

from .mixins import SuperuserRequiredMixin
from .public_views import (
    HomeView,
    MyChurchView,
    ChurchListView,
    ChurchDetailView,
    CreateChurchView,
    AssignChurchCommissionerView,
    ToggleChurchDuesView,
    AnnouncementListView,
    CreateAnnouncementView,
    JoinChurchByInviteView,
    AnnouncementDetailView,
    ToggleAnnouncementBannerView,
    home,
    my_church,
    church_list,
    church_detail,
    create_church,
    assign_church_commissioner,
    toggle_church_dues,
    announcement_list,
    create_announcement,
    join_church_by_invite,
    announcement_detail,
    toggle_announcement_banner,
    HealthCheckView,
    health_check,
)
from .admin_views import (
    SystemAdminDashboardView,
    SystemAdminBackupsView,
    BackupManualTriggerView,
    BackupTestConnectionApiView,
    DownloadBackupView,
    RestoreBackupView,
    DeleteBackupView,
    SystemAdminUsersView,
    AdminResetUserPasswordView,
    AdminToggleUserActiveView,
    AdminToggleMaintenanceModeView,
    AdminUpdateEmergencyBannerView,
)
from .testing_views import (
    TestUsersPortalView,
    QuickSwitchTestUserView,
    CreateInAppTestUserView,
    ResetAllDemoDataInAppView,
)

# Backward-compatible callables for URLs
system_admin_dashboard = SystemAdminDashboardView.as_view()
system_admin_backups = SystemAdminBackupsView.as_view()
backup_manual_trigger = BackupManualTriggerView.as_view()
backup_test_connection_api = BackupTestConnectionApiView.as_view()
download_backup = DownloadBackupView.as_view()
restore_backup_view = RestoreBackupView.as_view()
delete_backup = DeleteBackupView.as_view()
system_admin_users = SystemAdminUsersView.as_view()
admin_reset_user_password = AdminResetUserPasswordView.as_view()
admin_toggle_user_active = AdminToggleUserActiveView.as_view()
admin_toggle_maintenance_mode = AdminToggleMaintenanceModeView.as_view()
admin_update_emergency_banner = AdminUpdateEmergencyBannerView.as_view()

test_users_portal = TestUsersPortalView.as_view()
quick_switch_test_user = QuickSwitchTestUserView.as_view()
create_in_app_test_user = CreateInAppTestUserView.as_view()
reset_all_demo_data_in_app = ResetAllDemoDataInAppView.as_view()

__all__ = [
    'SuperuserRequiredMixin',
    # Public CBVs
    'HomeView', 'MyChurchView', 'ChurchListView', 'ChurchDetailView',
    'CreateChurchView', 'AssignChurchCommissionerView', 'ToggleChurchDuesView',
    'AnnouncementListView', 'CreateAnnouncementView', 'JoinChurchByInviteView',
    'AnnouncementDetailView', 'ToggleAnnouncementBannerView',
    # Admin CBVs
    'SystemAdminDashboardView', 'SystemAdminBackupsView', 'BackupManualTriggerView',
    'BackupTestConnectionApiView', 'DownloadBackupView', 'RestoreBackupView',
    'DeleteBackupView', 'SystemAdminUsersView', 'AdminResetUserPasswordView',
    'AdminToggleUserActiveView', 'AdminToggleMaintenanceModeView', 'AdminUpdateEmergencyBannerView',
    # Testing CBVs
    'TestUsersPortalView', 'QuickSwitchTestUserView', 'CreateInAppTestUserView',
    'ResetAllDemoDataInAppView',
]
