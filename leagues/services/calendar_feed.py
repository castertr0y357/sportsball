import datetime
from django.utils import timezone


def format_ics_datetime(dt: datetime.datetime) -> str:
    """Format datetime into standard iCal UTC format: YYYYMMDDTHHMMSSZ."""
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    dt_utc = dt.astimezone(datetime.timezone.utc)
    return dt_utc.strftime('%Y%m%dT%H%M%SZ')


def escape_ics_text(text: str) -> str:
    """Escape special iCal characters according to RFC 5545."""
    if not text:
        return ""
    text = text.replace('\\', '\\\\')
    text = text.replace(';', '\\;')
    text = text.replace(',', '\\,')
    text = text.replace('\n', '\\n')
    return text


def generate_ics_feed(games, calendar_name="SportsBall Schedule", request=None) -> str:
    """
    Generate an RFC 5545 compliant iCalendar (.ics) string from a queryset of Games.
    Compatible with Apple Calendar (iOS/macOS), Google Calendar, Outlook, and Android.
    """
    now_str = format_ics_datetime(timezone.now())

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SportsBall//Church Sports Leagues//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_ics_text(calendar_name)}",
        "X-WR-TIMEZONE:UTC",
    ]

    for game in games:
        dtstart = format_ics_datetime(game.date)
        # Default game duration = 75 minutes
        dtend = format_ics_datetime(game.date + datetime.timedelta(minutes=75))

        sport_label = game.season.league.get_sport_display() if (game.season and game.season.league) else "Game"
        summary = f"{game.team1.name} vs {game.team2.name} ({sport_label})"

        game_url = ""
        if request:
            game_url = request.build_absolute_uri(game.get_absolute_url() if hasattr(game, 'get_absolute_url') else f"/leagues/games/{game.id}/")

        desc_parts = [
            f"Matchup: {game.team1.name} vs {game.team2.name}",
            f"League: {game.season.league.name if game.season and game.season.league else 'SportsBall'}",
            f"Season: {game.season.name if game.season else ''}",
            f"Status: {game.get_status_display()}",
        ]
        if game.notes:
            desc_parts.append(f"Notes: {game.notes}")
        if game_url:
            desc_parts.append(f"Live Score & GameCast: {game_url}")

        description = "\\n".join([escape_ics_text(p) for p in desc_parts])

        status_str = "CONFIRMED"
        if game.status in ('cancelled', 'postponed'):
            status_str = "CANCELLED"

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:game-{game.id}@sportsball.local",
            f"DTSTAMP:{now_str}",
            f"DTSTART:{dtstart}",
            f"DTEND:{dtend}",
            f"SUMMARY:{escape_ics_text(summary)}",
            f"LOCATION:{escape_ics_text(game.location)}",
            f"DESCRIPTION:{description}",
            f"STATUS:{status_str}",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
