import os
from django.core.management.base import BaseCommand
from users.models import CustomUser


class Command(BaseCommand):
    help = "Creates or updates an initial superuser/admin from environment variables (useful for Kubernetes / CI / Docker)"

    def handle(self, *args, **options):
        username = os.environ.get('DJANGO_SUPERUSER_USERNAME')
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
        email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')

        if not username or not password:
            self.stdout.write(self.style.NOTICE(
                "DJANGO_SUPERUSER_USERNAME and DJANGO_SUPERUSER_PASSWORD not set. Skipping bootstrap admin."
            ))
            return

        user, created = CustomUser.objects.get_or_create(
            username=username,
            defaults={
                'email': email or f"{username}@sportsball.local",
                'role': 'admin',
                'is_staff': True,
                'is_superuser': True,
                'waiver_signed': True,
            }
        )

        user.set_password(password)
        user.is_staff = True
        user.is_superuser = True
        user.role = 'admin'
        if email:
            user.email = email
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f"Successfully bootstrapped superuser '{username}'."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' credentials updated from ENV."))
