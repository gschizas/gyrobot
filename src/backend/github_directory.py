"""Read model of the GitHub users: one row per person and team membership.

A person without a ``team_memberships`` row is listed under their main team (``accounts.team``) with no role.
There is one GitHub provision per account, so a person who was removed and invited again appears once, with
the current login (the earlier ones are only in ``account_provision_history``).

``FIELDS`` maps the public (OData) property names to SQL expressions; the OData parser uses it as its
whitelist, so nothing else is ever reachable from a request.
"""
import base64
from typing import Any, Optional

from sqlalchemy import BigInteger, ColumnElement, cast, func, select
from sqlalchemy.orm import Session

from backend.database import get_engine
from backend.models.accounts import AccountRow, MembershipRow, ProvisionRow, RoleRow

_login = ProvisionRow.data['username'].astext
_github_id = cast(ProvisionRow.data['github_id'].astext, BigInteger)
_team = func.coalesce(MembershipRow.team, AccountRow.team)

FIELDS: dict[str, ColumnElement] = {
    'Login': _login,
    'GithubId': _github_id,
    'GlobalId': ProvisionRow.data['global_id'].astext,
    'Email': AccountRow.primary_email,
    'Team': _team,
    'Role': MembershipRow.role_key,
    'RoleName': RoleRow.display_name,
    'Status': ProvisionRow.status,
    'LastChanged': func.greatest(AccountRow.updated_at, ProvisionRow.updated_at,
                                 func.coalesce(MembershipRow.updated_at, AccountRow.updated_at)),
}


FIELD_TYPES = {'Login': 'string', 'GithubId': 'int', 'GlobalId': 'string', 'Email': 'string', 'Team': 'string',
               'Role': 'string', 'RoleName': 'string', 'Status': 'string', 'LastChanged': 'datetime'}


def node_id(github_id: Optional[int]) -> Optional[str]:
    """The legacy global node id of a user (``base64("04:User<id>")``); the newer ``U_kg...`` ids are not derivable."""
    if github_id is None:
        return None
    return base64.b64encode(f'04:User{github_id}'.encode()).decode()


def _base_query(*columns):
    return (select(*columns)
            .select_from(ProvisionRow)
            .join(AccountRow, AccountRow.id == ProvisionRow.account_id)
            .outerjoin(MembershipRow, MembershipRow.account_id == AccountRow.id)
            .outerjoin(RoleRow, RoleRow.key == MembershipRow.role_key)
            .where(ProvisionRow.resource == 'github'))


def _session() -> Session:
    return Session(get_engine())


def list_github_users(where: Optional[ColumnElement] = None, order_by: Optional[list] = None,
                      limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """Rows keyed by property name (all of ``FIELDS`` plus ``NodeId``). ``where`` and ``order_by`` are built from ``FIELDS``."""
    query = _base_query(*(expression.label(name) for name, expression in FIELDS.items()))
    if where is not None:
        query = query.where(where)
    # The login and team break ties so that paging is stable
    query = query.order_by(*(order_by or []), FIELDS['Team'], FIELDS['Login']).limit(limit).offset(offset)
    with _session() as session:
        rows = [dict(row._mapping) for row in session.execute(query)]
    for row in rows:
        row['NodeId'] = node_id(row['GithubId'])
    return rows


def count_github_users(where: Optional[ColumnElement] = None) -> int:
    query = _base_query(func.count())
    if where is not None:
        query = query.where(where)
    with _session() as session:
        return session.scalar(query)
