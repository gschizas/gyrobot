"""Tests of the OData subset parser. Run from the repository root: uv run python -m unittest discover tests"""
import pathlib
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

from sqlalchemy import column
from sqlalchemy.dialects import postgresql

from webapp import odata

FIELDS = {'Team': column('team'), 'Login': column('login'), 'GithubId': column('github_id'),
          'LastChanged': column('last_changed'), 'IsLatest': column('is_latest')}
TYPES = {'Team': 'string', 'Login': 'string', 'GithubId': 'int', 'LastChanged': 'datetime',
         'IsLatest': 'bool'}


def compiled(clause):
    result = clause.compile(dialect=postgresql.dialect())
    return str(result), result.params


def parse(text):
    return compiled(odata.parse_filter(text, FIELDS, TYPES))


class FilterTests(unittest.TestCase):
    def test_comparison_binds_the_value(self):
        sql, params = parse("Team eq 'a-b'")
        self.assertEqual(sql, 'team = %(team_1)s::VARCHAR')
        self.assertEqual(params, {'team_1': 'a-b'})

    def test_quotes_are_unescaped_and_never_reach_the_sql(self):
        sql, params = parse("Login eq 'o''brien'")
        self.assertNotIn('brien', sql)
        self.assertEqual(list(params.values()), ["o'brien"])

    def test_startswith_escapes_wildcards(self):
        _, params = parse("startswith(Team,'a%_')")
        self.assertEqual(list(params.values()), ['a/%/_'])

    def test_and_or_not_and_parentheses(self):
        sql, _ = parse("(Team eq 'a' or Team eq 'b') and not Login eq 'x'")
        self.assertIn(' OR ', sql)
        self.assertIn(' AND ', sql)
        self.assertIn('!=', sql)

    def test_and_binds_tighter_than_or(self):
        sql, _ = parse("Team eq 'a' or Team eq 'b' and Login eq 'c'")
        self.assertRegex(sql, r'^team = .* OR team = .* AND login = .*$')

    def test_numbers_and_dates(self):
        _, params = parse('GithubId gt 5 and LastChanged ge 2026-01-02T03:04:05Z')
        self.assertEqual(list(params.values()), [5, datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)])

    def test_booleans(self):
        self.assertEqual(parse('IsLatest eq true')[0], 'is_latest = true')
        self.assertRaises(odata.ODataError, parse, 'IsLatest eq 1')

    def test_null(self):
        self.assertEqual(parse('Team eq null')[0], 'team IS NULL')
        self.assertEqual(parse('Team ne null')[0], 'team IS NOT NULL')

    def test_rejections(self):
        for text in ["Unknown eq 'x'", "Team eq", "Team eq 5", "GithubId eq 'x'", "Team like 'x'", "Team eq 'x' extra",
                     "startswith(GithubId,'x')", "Team gt null", "Team eq 'x'; DROP TABLE accounts", "",
                     "(" * 30 + "Team eq 'x'" + ")" * 30, "Team eq '" + 'x' * 3000 + "'"]:
            with self.subTest(text=text[:40]):
                with self.assertRaises(odata.ODataError):
                    parse(text)


class OtherOptionTests(unittest.TestCase):
    def test_orderby(self):
        sql = [str(c.compile(dialect=postgresql.dialect())) for c in odata.parse_orderby('Team desc, Login', FIELDS)]
        self.assertEqual(sql, ['team DESC', 'login ASC'])

    def test_orderby_rejections(self):
        for text in ['Nope', 'Team sideways', 'Team desc extra', '']:
            with self.subTest(text=text):
                with self.assertRaises(odata.ODataError):
                    odata.parse_orderby(text, FIELDS)

    def test_select(self):
        self.assertEqual(odata.parse_select('Team, Login', list(FIELDS)), ['Team', 'Login'])
        with self.assertRaises(odata.ODataError):
            odata.parse_select('Team,Nope', list(FIELDS))

    def test_integers_and_booleans(self):
        self.assertEqual(odata.parse_int('$top', '1000', 0, 1000), 1000)
        for text in ['1001', '-1', 'x', '']:
            with self.subTest(text=text):
                with self.assertRaises(odata.ODataError):
                    odata.parse_int('$top', text, 0, 1000)
        self.assertTrue(odata.parse_bool('$count', 'true'))
        with self.assertRaises(odata.ODataError):
            odata.parse_bool('$count', 'yes')


if __name__ == '__main__':
    unittest.main()
