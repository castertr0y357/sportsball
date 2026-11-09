from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q

# Bi-directional aliases supporting legacy tests and intuitive team logins
LEGACY_EMAIL_ALIASES = {
    # Coaches
    "coach.grace@sportsball.local": "coach.sluggers@sportsball.local",
    "coach_grace": "coach.sluggers@sportsball.local",
    "coach.sluggers@sportsball.local": "coach.grace@sportsball.local",
    "coach_sluggers": "coach.grace@sportsball.local",

    "coach.calvary@sportsball.local": "coach.crusaders@sportsball.local",
    "coach_calvary": "coach.crusaders@sportsball.local",
    "coach.crusaders@sportsball.local": "coach.calvary@sportsball.local",
    "coach_crusaders": "coach.calvary@sportsball.local",

    "coach.redeemer@sportsball.local": "coach.royals@sportsball.local",
    "coach_redeemer": "coach.royals@sportsball.local",
    "coach.royals@sportsball.local": "coach.redeemer@sportsball.local",
    "coach_royals": "coach.redeemer@sportsball.local",

    "coach.hope@sportsball.local": "coach.warriors@sportsball.local",
    "coach_hope": "coach.warriors@sportsball.local",
    "coach.warriors@sportsball.local": "coach.hope@sportsball.local",
    "coach_warriors": "coach.hope@sportsball.local",

    # Featured Players
    "player.josh@sportsball.local": "player.sluggers@sportsball.local",
    "player_josh": "player.sluggers@sportsball.local",
    "player.sluggers@sportsball.local": "player.josh@sportsball.local",
    "player_sluggers": "player.josh@sportsball.local",

    "player.micah@sportsball.local": "player.crusaders@sportsball.local",
    "player_micah": "player.crusaders@sportsball.local",
    "player.crusaders@sportsball.local": "player.micah@sportsball.local",
    "player_crusaders": "player.micah@sportsball.local",

    "player.ethan@sportsball.local": "player.royals@sportsball.local",
    "player_ethan": "player.royals@sportsball.local",
    "player.royals@sportsball.local": "player.ethan@sportsball.local",
    "player_royals": "player.ethan@sportsball.local",

    "player.sarah@sportsball.local": "player.warriors@sportsball.local",
    "player_sarah": "player.warriors@sportsball.local",
    "player.warriors@sportsball.local": "player.sarah@sportsball.local",
    "player_warriors": "player.sarah@sportsball.local",

    # Commissioners
    "commissioner": "commissioner@sportsball.local",
    "commish.softball@sportsball.local": "commish_softball",
    "commish_softball": "commish.softball@sportsball.local",
    "commish.basketball@sportsball.local": "commish_basketball",
    "commish_basketball": "commish.basketball@sportsball.local",
    "commish.football@sportsball.local": "commish_football",
    "commish_football": "commish.football@sportsball.local",
}


class EmailOrUsernameModelBackend(ModelBackend):
    """
    Authenticate against settings.AUTH_USER_MODEL using either email or username.
    Enables zero-friction email-only logins for players while maintaining backwards
    compatibility for admin and test console usernames and legacy aliases.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD) or kwargs.get('email')
        if not username or not password:
            return None

        username_clean = str(username).strip()
        prefix = username_clean.split('@')[0] if '@' in username_clean else username_clean

        query = (
            Q(email__iexact=username_clean) |
            Q(username__iexact=username_clean) |
            Q(username__iexact=prefix)
        )

        alias_target = LEGACY_EMAIL_ALIASES.get(username_clean.lower())
        if alias_target:
            alias_prefix = alias_target.split('@')[0] if '@' in alias_target else alias_target
            query |= (
                Q(email__iexact=alias_target) |
                Q(username__iexact=alias_target) |
                Q(username__iexact=alias_prefix)
            )

        user = UserModel.objects.filter(query).first()

        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
