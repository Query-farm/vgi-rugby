"""Registry mapping friendly league keys to ESPN's rugby league identifiers.

ESPN's site API addresses a league by its numeric *site* id (Six Nations is
``180659``) while its core API uses a different *core* id (Six Nations is
``8323``). The registry below was taken from
``sports.core.api.espn.com/v2/sports/rugby/leagues`` (25 leagues, verified
2026-11-10) so SQL users can write ``league := 'six_nations'`` instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class League:
    """One ESPN rugby competition."""

    key: str
    name: str
    site_id: int
    core_id: int
    gender: str
    level: str
    region: str
    season_span: str
    headline: bool = False
    active: bool = True

    def current_season(self, today: date) -> int:
        """Return the season label most likely to be in progress or next up.

        ESPN labels a season by the year in which it ends: the 2026-27
        Premiership is season 2027. Split seasons roll over on 1 July.
        """
        if self.season_span == "split":
            return today.year + 1 if today.month >= 7 else today.year
        return today.year


LEAGUES: dict[str, League] = {
    league.key: league
    for league in (
        League(
            "six_nations", "Six Nations", 180659, 8323, "men", "international", "Europe", "calendar", True
        ),
        League(
            "rugby_championship",
            "The Rugby Championship",
            244293,
            8328,
            "men",
            "international",
            "Southern Hemisphere",
            "calendar",
            True,
        ),
        League(
            "nations_championship",
            "Nations Championship",
            17567,
            24400,
            "men",
            "international",
            "Global",
            "calendar",
            True,
        ),
        League(
            "rugby_world_cup", "Rugby World Cup", 164205, 8337, "men", "international", "Global", "calendar"
        ),
        League(
            "womens_rugby_world_cup",
            "Women's Rugby World Cup",
            289237,
            17953,
            "women",
            "international",
            "Global",
            "calendar",
        ),
        League(
            "lions_tour",
            "British and Irish Lions Tour",
            268565,
            8016,
            "men",
            "international",
            "Global",
            "calendar",
        ),
        League(
            "test_matches",
            "International Test Match",
            289234,
            10659,
            "men",
            "international",
            "Global",
            "calendar",
        ),
        League("premiership", "Gallagher Prem", 267979, 8007, "men", "club", "England", "split", True),
        League(
            "urc",
            "United Rugby Championship",
            270557,
            8331,
            "men",
            "club",
            "Europe/South Africa",
            "split",
            True,
        ),
        League("top14", "French Top 14", 270559, 8005, "men", "club", "France", "split", True),
        League(
            "champions_cup",
            "European Rugby Champions Cup",
            271937,
            8329,
            "men",
            "club",
            "Europe",
            "split",
            True,
        ),
        League(
            "challenge_cup",
            "European Rugby Challenge Cup",
            272073,
            8010,
            "men",
            "club",
            "Europe",
            "split",
            True,
        ),
        League(
            "super_rugby", "Super Rugby Pacific", 242041, 8326, "men", "club", "Pacific", "calendar", True
        ),
        League(
            "currie_cup", "Currie Cup", 270555, 8002, "men", "club", "South Africa", "calendar", active=False
        ),
        League(
            "npc", "National Provincial Championship", 270563, 8004, "men", "club", "New Zealand", "calendar"
        ),
        League("mlr", "Major League Rugby", 289262, 19114, "men", "club", "North America", "calendar"),
        League("urba_primera_a", "URBA Primera A", 2009, 4001, "men", "club", "Argentina", "calendar"),
        League("urba_top14", "URBA Top 14", 289279, 20113, "men", "club", "Argentina", "calendar"),
        League("olympic_sevens_men", "Olympic Men's 7s", 282, 10743, "men", "sevens", "Global", "calendar"),
        League(
            "olympic_sevens_women",
            "Olympic Women's Rugby Sevens",
            283,
            10729,
            "women",
            "sevens",
            "Global",
            "calendar",
        ),
        League(
            "super_rugby_aotearoa",
            "Super Rugby Aotearoa",
            289271,
            19867,
            "men",
            "club",
            "New Zealand",
            "calendar",
            active=False,
        ),
        League(
            "super_rugby_au",
            "Super Rugby AU",
            289272,
            19869,
            "men",
            "club",
            "Australia",
            "calendar",
            active=False,
        ),
        League(
            "super_rugby_trans_tasman",
            "Super Rugby Trans-Tasman",
            289277,
            20008,
            "men",
            "club",
            "Pacific",
            "calendar",
            active=False,
        ),
        League(
            "tri_nations_2020",
            "2020 Tri Nations",
            289274,
            19940,
            "men",
            "international",
            "Southern Hemisphere",
            "calendar",
            active=False,
        ),
        League(
            "anglo_welsh_cup",
            "Anglo-Welsh Cup",
            236461,
            8009,
            "men",
            "club",
            "England/Wales",
            "split",
            active=False,
        ),
    )
}

LEAGUE_KEYS: tuple[str, ...] = tuple(LEAGUES)
HEADLINE_LEAGUES: tuple[str, ...] = tuple(key for key, league in LEAGUES.items() if league.headline)


def league(key: str) -> League:
    """Return a registered league, failing with the accepted keys."""
    try:
        return LEAGUES[key]
    except KeyError:
        raise ValueError(f"unknown league {key!r}; expected one of: {', '.join(LEAGUE_KEYS)}") from None
