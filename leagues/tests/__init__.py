"""
Test package for the leagues application.
Aggregates all domain test suites:
- test_scoring_and_dugout
- test_scheduling_and_playoffs
- test_lineups_and_rosters
- test_officials_and_dues
- test_venues_and_weather
- test_discipline_and_conduct
- test_general_views
- test_production_hardening
- test_chaos_and_break_scenarios
"""

from leagues.tests.test_scoring_and_dugout import TestScoringAndDugoutCase
from leagues.tests.test_scheduling_and_playoffs import TestSchedulingAndPlayoffsCase
from leagues.tests.test_lineups_and_rosters import TestLineupsAndRostersCase
from leagues.tests.test_officials_and_dues import TestOfficialsAndDuesCase
from leagues.tests.test_venues_and_weather import TestVenuesAndWeatherCase
from leagues.tests.test_discipline_and_conduct import TestDisciplineAndConductCase
from leagues.tests.test_general_views import TestGeneralViewsCase
from leagues.tests.test_production_hardening import TestProductionHardening
from leagues.tests.test_chaos_and_break_scenarios import TestChaosAndBreakScenarios

__all__ = [
    'TestScoringAndDugoutCase',
    'TestSchedulingAndPlayoffsCase',
    'TestLineupsAndRostersCase',
    'TestOfficialsAndDuesCase',
    'TestVenuesAndWeatherCase',
    'TestDisciplineAndConductCase',
    'TestGeneralViewsCase',
    'TestProductionHardening',
    'TestChaosAndBreakScenarios',
]
