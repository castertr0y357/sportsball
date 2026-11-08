from django.urls import path
from django.contrib.auth import views as auth_views
from users import views
from users.forms import EmailAuthenticationForm

urlpatterns = [
    path('register/', views.UserRegisterView.as_view(), name='register'),
    path('login/', auth_views.LoginView.as_view(
        template_name='users/login.html',
        authentication_form=EmailAuthenticationForm
    ), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    # Password Reset Flow (Gmail SMTP / Console)
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='users/password_reset.html',
        email_template_name='users/password_reset_email.html',
        subject_template_name='users/password_reset_subject.txt'
    ), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='users/password_reset_done.html'
    ), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='users/password_reset_confirm.html'
    ), name='password_reset_confirm'),
    path('password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='users/password_reset_complete.html'
    ), name='password_reset_complete'),

    # Player Profile & Waivers
    path('profile/', views.UserProfileView.as_view(), name='profile'),
    path('profile/edit/', views.EditProfileView.as_view(), name='edit_profile'),
    path('profile/waiver/', views.SignWaiverView.as_view(), name='sign_waiver'),
    path('minors/<int:minor_id>/waiver/', views.SignParentalWaiverView.as_view(), name='sign_parental_waiver'),
    path('players/<int:user_id>/', views.PlayerDetailView.as_view(), name='player_detail'),
    path('free-agents/', views.FreeAgentListView.as_view(), name='free_agent_list'),
    path('profile/toggle-sub/', views.ToggleSubAvailabilityView.as_view(), name='toggle_sub_availability'),

    # Precision Walk-Up & Team Intro Audio Studio
    path('profile/audio-studio/', views.AudioStudioView.as_view(), name='audio_studio'),
    path('profile/audio-studio/upload/', views.AudioUploadTrimView.as_view(), name='audio_upload_trim'),
    path('profile/audio-studio/<int:track_id>/set-active/', views.AudioSetActiveView.as_view(), name='audio_set_active'),
    path('profile/audio-studio/<int:track_id>/adopt/', views.AudioAdoptJukeboxView.as_view(), name='audio_adopt_jukebox'),
    path('profile/audio-studio/<int:track_id>/veto/', views.AudioVetoView.as_view(), name='audio_veto'),
    path('profile/audio-studio/<int:track_id>/delete/', views.AudioDeleteView.as_view(), name='audio_delete'),
]
