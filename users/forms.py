from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import CustomUser


class CustomUserCreationForm(UserCreationForm):
    first_name = forms.CharField(
        max_length=150,
        required=True,
        label="First Name",
        widget=forms.TextInput(attrs={'placeholder': 'First Name', 'autocomplete': 'given-name'})
    )
    last_name = forms.CharField(
        max_length=150,
        required=True,
        label="Last Name",
        widget=forms.TextInput(attrs={'placeholder': 'Last Name', 'autocomplete': 'family-name'})
    )
    email = forms.EmailField(
        required=True,
        label="Email Address",
        help_text="Used to sign in and receive game day notifications.",
        widget=forms.EmailInput(attrs={'placeholder': 'you@example.com', 'autocomplete': 'email'})
    )

    agree_waiver = forms.BooleanField(
        required=False,
        initial=True,
        label="I certify the liability waiver and Christian sportsmanship covenant",
        widget=forms.CheckboxInput(attrs={'checked': 'checked'})
    )

    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = ('first_name', 'last_name', 'email')

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if not email:
            raise forms.ValidationError("Email address is required.")
        if CustomUser.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email address already exists. Please log in.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        email = self.cleaned_data['email'].strip().lower()
        user.email = email
        user.username = email[:150]
        if commit:
            user.save()
        return user


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Email Address",
        widget=forms.TextInput(attrs={
            'placeholder': 'you@example.com',
            'autocomplete': 'username email',
            'autofocus': True
        })
    )


class ProfileForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = (
            'first_name', 'last_name', 'email', 'church',
            'phone', 'emergency_contact_name', 'emergency_contact_phone',
            'birthdate', 'parent_guardian_name', 'parent_guardian_phone',
            'jersey_number', 'bio', 'is_free_agent',
            'walkup_song_title', 'walkup_song_file',
            'walkup_start_seconds', 'walkup_duration_seconds',
        )
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 3}),
            'birthdate': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean_walkup_song_file(self):
        file = self.cleaned_data.get('walkup_song_file')
        if file and hasattr(file, 'size'):
            max_size = 5 * 1024 * 1024  # 5MB max for fast offline ballpark loading
            if file.size > max_size:
                raise forms.ValidationError('Audio file too large. Please upload an audio clip under 5 MB (10–15 second snippet recommended).')
        return file


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
