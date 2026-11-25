"""A small, whitelisted subset of OData v4 query options, turned into SQLAlchemy clauses.

Supported: ``$filter`` with ``eq ne gt ge lt le``, ``and or not``, parentheses and ``startswith``,
``endswith``, ``contains``; ``$orderby``; ``$select``; ``$top``; ``$skip``; ``$count``. Property names
are only ever looked up in the ``fields`` mapping the caller passes, and values are always bound
parameters, so a request cannot reach anything else. Anything unsupported raises :class:`ODataError`.
"""
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import ColumnElement, and_, not_, or_

MAX_FILTER_LENGTH = 2000
MAX_DEPTH = 20

_TOKEN = re.compile(r"""\s*(?:
    (?P<string>'(?:[^']|'')*')
  | (?P<datetime>\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?)
  | (?P<number>-?\d+)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<punct>[(),])
)""", re.VERBOSE)
_COMPARISONS = {'eq', 'ne', 'gt', 'ge', 'lt', 'le'}
_FUNCTIONS = {'startswith', 'endswith', 'contains'}


class ODataError(ValueError):
    """The query option is invalid or unsupported (HTTP 400)."""


def _tokenize(text: str) -> list[tuple[str, str]]:
    if len(text) > MAX_FILTER_LENGTH:
        raise ODataError(f'The $filter is longer than {MAX_FILTER_LENGTH} characters')
    tokens, position = [], 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if not match or match.end() == position:
            if text[position:].strip():
                raise ODataError(f'Unexpected character at position {position + 1} of the $filter')
            break
        kind = match.lastgroup
        tokens.append((kind, match.group(kind)))
        position = match.end()
    return tokens


def _parse_datetime(text: str) -> datetime:
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        raise ODataError(f"Invalid date/time '{text}'")


class _FilterParser:
    def __init__(self, text: str, fields: dict[str, ColumnElement], types: dict[str, str]):
        self.tokens = _tokenize(text)
        self.position = 0
        self.fields = fields
        self.types = types

    def parse(self) -> ColumnElement:
        if not self.tokens:
            raise ODataError('Empty $filter')
        clause = self._or(0)
        if self.position != len(self.tokens):
            raise ODataError(f"Unexpected '{self.tokens[self.position][1]}' in the $filter")
        return clause

    def _peek(self) -> Optional[tuple[str, str]]:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def _next(self) -> tuple[str, str]:
        token = self._peek()
        if token is None:
            raise ODataError('The $filter ends unexpectedly')
        self.position += 1
        return token

    def _accept(self, kind: str, value: Optional[str] = None) -> bool:
        token = self._peek()
        if token and token[0] == kind and (value is None or token[1] == value):
            self.position += 1
            return True
        return False

    def _expect(self, kind: str, value: str) -> None:
        if not self._accept(kind, value):
            raise ODataError(f"Expected '{value}' in the $filter")

    def _or(self, depth: int) -> ColumnElement:
        clauses = [self._and(depth)]
        while self._accept('name', 'or'):
            clauses.append(self._and(depth))
        return clauses[0] if len(clauses) == 1 else or_(*clauses)

    def _and(self, depth: int) -> ColumnElement:
        clauses = [self._not(depth)]
        while self._accept('name', 'and'):
            clauses.append(self._not(depth))
        return clauses[0] if len(clauses) == 1 else and_(*clauses)

    def _not(self, depth: int) -> ColumnElement:
        if depth > MAX_DEPTH:
            raise ODataError('The $filter is nested too deeply')
        if self._accept('name', 'not'):
            return not_(self._not(depth + 1))
        return self._primary(depth)

    def _primary(self, depth: int) -> ColumnElement:
        if self._accept('punct', '('):
            clause = self._or(depth + 1)
            self._expect('punct', ')')
            return clause
        kind, value = self._next()
        if kind != 'name':
            raise ODataError(f"Expected a property or function, found '{value}'")
        if value in _FUNCTIONS:
            return self._function(value)
        column = self._field(value)
        operator = self._next()
        if operator[0] != 'name' or operator[1] not in _COMPARISONS:
            raise ODataError(f"Expected a comparison operator after '{value}', found '{operator[1]}'")
        literal = self._literal(self.types[value])
        if literal is None:
            if operator[1] not in ('eq', 'ne'):
                raise ODataError("null can only be compared with 'eq' or 'ne'")
            return column.is_(None) if operator[1] == 'eq' else column.is_not(None)
        if self.types[value] == 'bool' and operator[1] not in ('eq', 'ne'):
            raise ODataError("Boolean properties can only be compared with 'eq' or 'ne'")
        if self.types[value] == 'bool':
            return column == literal if operator[1] == 'eq' else column != literal
        return {'eq': column == literal, 'ne': column != literal, 'gt': column > literal,
                'ge': column >= literal, 'lt': column < literal, 'le': column <= literal}[operator[1]]

    def _function(self, name: str) -> ColumnElement:
        self._expect('punct', '(')
        kind, field = self._next()
        if kind != 'name':
            raise ODataError(f'{name} needs a property as its first argument')
        column = self._field(field)
        if self.types[field] != 'string':
            raise ODataError(f"{name} only works on text properties, not '{field}'")
        self._expect('punct', ',')
        text = self._literal('string')
        self._expect('punct', ')')
        if text is None:
            raise ODataError(f'{name} needs a text argument')
        return getattr(column, name)(text, autoescape=True)

    def _field(self, name: str) -> ColumnElement:
        if name not in self.fields:
            raise ODataError(f"Unknown property '{name}'")
        return self.fields[name]

    def _literal(self, expected: str) -> Any:
        kind, value = self._next()
        if kind == 'name' and value == 'null':
            return None
        if kind == 'name' and value in ('true', 'false') and expected == 'bool':
            return value == 'true'
        if kind == 'string' and expected == 'string':
            return value[1:-1].replace("''", "'")
        if kind == 'number' and expected == 'int':
            return int(value)
        if kind == 'datetime' and expected == 'datetime':
            return _parse_datetime(value)
        raise ODataError(f"'{value}' is not a valid {expected} value")


def parse_filter(text: str, fields: dict[str, ColumnElement], types: dict[str, str]) -> ColumnElement:
    """``types`` maps each property to ``string``, ``int``, ``bool`` or ``datetime``."""
    return _FilterParser(text, fields, types).parse()


def parse_orderby(text: str, fields: dict[str, ColumnElement]) -> list[ColumnElement]:
    clauses = []
    for item in text.split(','):
        parts = item.split()
        if not parts or len(parts) > 2 or (len(parts) == 2 and parts[1] not in ('asc', 'desc')):
            raise ODataError(f"Invalid $orderby item '{item.strip()}'")
        if parts[0] not in fields:
            raise ODataError(f"Unknown property '{parts[0]}'")
        column = fields[parts[0]]
        clauses.append(column.desc() if len(parts) == 2 and parts[1] == 'desc' else column.asc())
    return clauses


def parse_select(text: str, names: list[str]) -> list[str]:
    selected = [name.strip() for name in text.split(',')]
    for name in selected:
        if name not in names:
            raise ODataError(f"Unknown property '{name}'")
    return selected


def parse_int(name: str, text: str, minimum: int, maximum: Optional[int] = None) -> int:
    if not re.fullmatch(r'\d+', text.strip()):
        raise ODataError(f'{name} must be a non-negative integer')
    value = int(text)
    if value < minimum or (maximum is not None and value > maximum):
        raise ODataError(f'{name} must be between {minimum} and {maximum}' if maximum is not None
                         else f'{name} must be at least {minimum}')
    return value


def parse_bool(name: str, text: str) -> bool:
    if text not in ('true', 'false'):
        raise ODataError(f"{name} must be 'true' or 'false'")
    return text == 'true'
