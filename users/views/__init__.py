"""
Users views package consolidating authentication, profile management,
digital waivers, free agents, and the Walk-Up & Team Intro Audio Studio.
All views are implemented as Class-Based Views with backward-compatible callables.
"""

from .auth_views import (
    UserRegisterView,
    SignWaiverView,
    SignParentalWaiverView,
)
from .profile_views import (
    UserProfileView,
    PlayerDetailView,
    EditProfileView,
    FreeAgentListView,
    ToggleSubAvailabilityView,
)
from .audio_studio_views import (
    AudioStudioView,
    AudioUploadTrimView,
    AudioSetActiveView,
    AudioAdoptJukeboxView,
    AudioVetoView,
    AudioDeleteView,
)

# Backward-compatible callables
register = UserRegisterView.as_view()
profile = UserProfileView.as_view()
player_detail = PlayerDetailView.as_view()
edit_profile = EditProfileView.as_view()
sign_waiver = SignWaiverView.as_view()
sign_parental_waiver_view = SignParentalWaiverView.as_view()
free_agent_list = FreeAgentListView.as_view()
toggle_sub_availability = ToggleSubAvailabilityView.as_view()

audio_studio = AudioStudioView.as_view()
audio_upload_trim = AudioUploadTrimView.as_view()
audio_set_active = AudioSetActiveView.as_view()
audio_adopt_jukebox = AudioAdoptJukeboxView.as_view()
audio_veto = AudioVetoView.as_view()
audio_delete = AudioDeleteView.as_view()
