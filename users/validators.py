"""
Custom model and form validators for user accounts and media files.
"""
from django.core.exceptions import ValidationError


def validate_audio_file_size(file):
    """Enforces 8MB upload limit on audio clips."""
    max_mb = 8
    if hasattr(file, 'size') and file.size and file.size > max_mb * 1024 * 1024:
        raise ValidationError(f"Audio file size cannot exceed {max_mb} MB (uploaded {file.size / (1024 * 1024):.1f} MB).")
