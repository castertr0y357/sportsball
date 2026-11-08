"""
Management command to auto-finalize pending match scores past the review window.
Scheduled via cron / task runners or executed directly by administrators.
"""
from django.core.management.base import BaseCommand
from leagues.models import Game


class Command(BaseCommand):
    help = "Auto-confirms pending match scores that have exceeded the opponent review window (default: 48 hours)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours',
            type=int,
            default=48,
            help="Review window threshold in hours (default: 48)."
        )

    def handle(self, *args, **options):
        hours = options['hours']
        self.stdout.write(f"Checking for pending games submitted more than {hours} hours ago...")
        count = Game.auto_finalize_stale_pending_games(hours=hours)
        if count:
            self.stdout.write(self.style.SUCCESS(f"Successfully auto-finalized {count} stale pending game(s)."))
        else:
            self.stdout.write(self.style.NOTICE("No stale pending games found."))
