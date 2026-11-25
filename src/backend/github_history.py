"""Historical read model of the GitHub users: one row per recorded change.

The rows are the union of two event streams, each completed with the state of the other stream at that moment:

* ``account_provision_history`` (GitHub): login, ids and status of the event; the email and team are those of the
  latest ``account_history`` snapshot at or before it (falling back to the provision's own data, then to the account).
* ``account_history``: email and team of the event; the login, ids and status are those of the latest GitHub
  provision snapshot at or before it (empty if there was none yet).

Team memberships have no history, so ``Role``/``RoleName`` are the *current* role of the person in the row's team.
Nothing here writes; ``accounts`` and ``account_provisions`` are not needed.
"""
from typing import Any, Optional

from sqlalchemy import BigInteger, ColumnElement, DateTime, String, cast, func, literal, select, true
from sqlalchemy.orm import Session

from backend.database import get_engine
from backend.github_directory import node_id
from backend.models.accounts import AccountHistoryRow, AccountRow, MembershipRow, ProvisionHistoryRow, RoleRow

FIELD_TYPES = {'Event': 'string', 'Login': 'string', 'GithubId': 'int', 'GlobalId': 'string', 'Email': 'string',
               'Team': 'string', 'Role': 'string', 'RoleName': 'string', 'Status': 'string',
               'LastChanged': 'datetime'}


def _latest(model, *conditions):
    return select(model).where(*conditions).order_by(model.recorded_at.desc(), model.id.desc()).limit(1).lateral()


def _events():
    ph, ah = ProvisionHistoryRow, AccountHistoryRow

    snapshot = _latest(ah, ah.account_id == ph.account_id, ah.recorded_at <= ph.recorded_at)
    from_provisions = (
        select(
            func.concat('P', ph.id).label('Id'), literal('Provision').label('Event'), ph.account_id.label('AccountId'),
            ph.data['username'].astext.label('Login'),
            cast(ph.data['github_id'].astext, BigInteger).label('GithubId'),
            ph.data['global_id'].astext.label('GlobalId'),
            func.coalesce(snapshot.c.primary_email, ph.data['email'].astext, AccountRow.primary_email).label('Email'),
            func.coalesce(ph.data['team'].astext, snapshot.c.team, AccountRow.team).label('Team'),
            ph.status.label('Status'), ph.recorded_at.label('LastChanged'))
        .select_from(ph).join(AccountRow, AccountRow.id == ph.account_id).outerjoin(snapshot, true())
        .where(ph.resource == 'github'))

    provision = _latest(ph, ph.account_id == ah.account_id, ph.resource == 'github', ph.recorded_at <= ah.recorded_at)
    from_accounts = (
        select(
            func.concat('A', ah.id).label('Id'), literal('Account').label('Event'), ah.account_id.label('AccountId'),
            provision.c.data['username'].astext.label('Login'),
            cast(provision.c.data['github_id'].astext, BigInteger).label('GithubId'),
            provision.c.data['global_id'].astext.label('GlobalId'),
            func.coalesce(ah.primary_email, AccountRow.primary_email).label('Email'),
            func.coalesce(ah.team, AccountRow.team).label('Team'),
            cast(provision.c.status, String).label('Status'), cast(ah.recorded_at, DateTime(timezone=True)).label('LastChanged'))
        .select_from(ah).join(AccountRow, AccountRow.id == ah.account_id).outerjoin(provision, true()))

    return from_provisions.union_all(from_accounts).subquery('events')


_events_subquery = _events()
_c = _events_subquery.c

FIELDS: dict[str, ColumnElement] = {
    'Event': _c.Event, 'Login': _c.Login, 'GithubId': _c.GithubId, 'GlobalId': _c.GlobalId, 'Email': _c.Email,
    'Team': _c.Team, 'Role': MembershipRow.role_key, 'RoleName': RoleRow.display_name, 'Status': _c.Status,
    'LastChanged': _c.LastChanged,
}


def _base_query(*columns):
    return (select(*columns)
            .select_from(_events_subquery)
            .outerjoin(MembershipRow, (MembershipRow.account_id == _c.AccountId) & (MembershipRow.team == _c.Team))
            .outerjoin(RoleRow, RoleRow.key == MembershipRow.role_key))


def _session() -> Session:
    return Session(get_engine('APPROVAL_DATABASE_URL'))


def list_history(where: Optional[ColumnElement] = None, order_by: Optional[list] = None,
                 limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """Rows keyed by property name (``Id``, all of ``FIELDS`` and ``NodeId``). Oldest first unless ``order_by`` says otherwise."""
    query = _base_query(_c.Id.label('Id'), *(expression.label(name) for name, expression in FIELDS.items()))
    if where is not None:
        query = query.where(where)
    query = query.order_by(*(order_by or []), _c.LastChanged, _c.Id).limit(limit).offset(offset)
    with _session() as session:
        rows = [dict(row._mapping) for row in session.execute(query)]
    for row in rows:
        row['NodeId'] = node_id(row['GithubId'])
    return rows


def count_history(where: Optional[ColumnElement] = None) -> int:
    query = _base_query(func.count())
    if where is not None:
        query = query.where(where)
    with _session() as session:
        return session.scalar(query)
