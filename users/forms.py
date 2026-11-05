from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser


class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)

    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = (
            'username', 'email', 'first_name', 'last_name',
            'role', 'church', 'phone', 'jersey_number', 'is_free_agent',
        )


class ProfileForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = (
            'first_name', 'last_name', 'email', 'church',
            'phone', 'emergency_contact_name', 'emergency_contact_phone',
            'jersey_number', 'bio', 'is_free_agent',
            'walkup_song_title', 'walkup_song_file',
            'walkup_start_seconds', 'walkup_duration_seconds',
        )
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 3}),
        }


class WaiverSignatureForm(forms.Form):
    signature = forms.CharField(
        max_length=150,
        label="Type your full legal name as your electronic signature",
        help_text="By signing, you agree to the Church Sports League fellowship covenant and liability release."
    )
    agree = forms.BooleanField(
        required=True,
        label="I have read and agree to the Liability Waiver & Christian Sportsmanship Covenant"
    )
