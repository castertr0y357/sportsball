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
        help_text="Your typed signature must match your profile name (or username) to verify identity."
    )
    agree = forms.BooleanField(
        required=True,
        label="I have read and agree to the Liability Waiver & Christian Sportsmanship Covenant"
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_signature(self):
        sig = self.cleaned_data.get('signature', '').strip()
        if not self.user:
            return sig

        allowed_names = [self.user.username.strip().lower()]
        full_name = self.user.get_full_name().strip().lower()
        if full_name:
            allowed_names.append(full_name)

        sig_lower = sig.lower()
        # Ensure user didn't type gibberish or a mismatched name
        match_found = False
        for allowed in allowed_names:
            if sig_lower == allowed or sig_lower == f"{self.user.first_name.lower()} {self.user.last_name.lower()}".strip():
                match_found = True
                break

        if not match_found:
            expected = self.user.get_full_name() or self.user.username
            raise forms.ValidationError(
                f"Signature mismatch. Please type your registered full name: '{expected}'"
            )
        return sig
