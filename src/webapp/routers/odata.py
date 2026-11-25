"""Read-only OData (light) listing of GitHub users: ``/api/odata/GithubUsers``.

Authentication: an OAuth2 bearer token or HTTP Basic (``client_id:client_secret``, for Excel / Power BI, which cannot
do the client-credentials flow). Both need the ``directory:read`` scope. Authorization is the permission rule
:data:`RULE_FUNCTION` (channel ``$api``, user = client id); its ``extra.team_prefixes`` limits the readable teams.
Denies by default when the rule is missing.
"""
import base64
import binascii
import logging
import os
from typing import Optional
from xml.sax.saxutils import quoteattr

import jwt
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import and_, or_

from backend import github_directory, github_history, permissions
from backend.configuration import user_allowed
from webapp import config, odata
from webapp.auth_oauth2 import decode_access_token, validate_client_credentials

logger = logging.getLogger('webapp.routers.odata')

RULE_FUNCTION = 'webapp.routers.odata:list_github_users'
HISTORY_RULE_FUNCTION = 'webapp.routers.odata:list_github_user_history'
SCOPE = 'directory:read'
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000
CONTENT_TYPE = 'application/json;odata.metadata=minimal'
NAMESPACE = 'GyroBot'

router = APIRouter(prefix='/api/odata', tags=['odata'])


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail,
                         headers={'WWW-Authenticate': 'Basic realm="odata", Bearer'})


def _basic_allowed(request: Request) -> bool:
    forwarded = request.headers.get('x-forwarded-proto', '').split(',')[0].strip()
    return (forwarded or request.url.scheme) == 'https' or os.environ.get('WEBAPP_ALLOW_BASIC_HTTP', '').lower() in (
        '1', 'true', 'yes')


def _client_from_basic(request: Request, encoded: str) -> str:
    if not _basic_allowed(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail='Basic authentication requires HTTPS')
    try:
        client_id, _, secret = base64.b64decode(encoded, validate=True).decode().partition(':')
    except (binascii.Error, UnicodeDecodeError):
        raise _unauthorized('Invalid Basic credentials')
    if not client_id or not validate_client_credentials(client_id, secret):
        raise _unauthorized('Invalid client credentials')
    if SCOPE not in config.client_scopes(client_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f'Missing scope: {SCOPE}')
    return client_id


def _client_from_bearer(token: str) -> str:
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise _unauthorized('Invalid or expired token')
    granted = set(str(payload.get('scope', '')).split()) & set(config.client_scopes(payload['sub']))
    if SCOPE not in granted:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f'Missing scope: {SCOPE}')
    return payload['sub']


def authenticate(request: Request) -> str:
    scheme, _, value = request.headers.get('authorization', '').partition(' ')
    if scheme.lower() == 'basic':
        return _client_from_basic(request, value.strip())
    if scheme.lower() == 'bearer':
        return _client_from_bearer(value.strip())
    raise _unauthorized('Not authenticated')


def _team_prefixes(client_id: str, rule_function: str = RULE_FUNCTION) -> Optional[list[str]]:
    """The team prefixes the client may read (None = all). Raises 403 when the rule is missing or denies."""
    rule = permissions.get_rule(rule_function)
    channels = rule['channels'] if rule else []
    if (rule is None or ('*' not in channels and config.api_channel_name() not in channels)
            or not user_allowed(config.api_team_name(), client_id, rule['users'])):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail='Not permitted to list GitHub users')
    prefixes = (rule.get('extra') or {}).get('team_prefixes')
    return [str(prefix) for prefix in prefixes] if prefixes else None


def _error(code: int, message: str) -> JSONResponse:
    return JSONResponse({'error': {'code': str(code), 'message': message}}, status_code=code)


def _json(body: dict) -> JSONResponse:
    return JSONResponse(body, media_type=CONTENT_TYPE, headers={'OData-Version': '4.0'})


def _base_url(request: Request) -> str:
    return str(request.url_for('odata_service')).rstrip('/')


@router.get('', name='odata_service')
def service_document(request: Request):
    authenticate(request)
    base = _base_url(request)
    return _json({'@odata.context': f'{base}/$metadata',
                  'value': [{'name': 'GithubUsers', 'kind': 'EntitySet', 'url': 'GithubUsers'},
                            {'name': 'GithubUserHistory', 'kind': 'EntitySet', 'url': 'GithubUserHistory'}]})


def _entity_type(name: str, field_types: dict[str, str]) -> str:
    edm = {'string': 'Edm.String', 'int': 'Edm.Int64', 'datetime': 'Edm.DateTimeOffset'}
    properties = ['<Property Name="Id" Type="Edm.String" Nullable="false"/>',
                  '<Property Name="NodeId" Type="Edm.String"/>']
    properties += [f'<Property Name={quoteattr(prop)} Type="{edm[kind]}"/>' for prop, kind in field_types.items()]
    return f'<EntityType Name="{name}"><Key><PropertyRef Name="Id"/></Key>' + ''.join(properties) + '</EntityType>'


@router.get('/$metadata')
def metadata(request: Request):
    authenticate(request)
    xml = ('<?xml version="1.0" encoding="utf-8"?>'
           '<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">'
           '<edmx:DataServices>'
           f'<Schema Namespace="{NAMESPACE}" xmlns="http://docs.oasis-open.org/odata/ns/edm">'
           + _entity_type('GithubUser', github_directory.FIELD_TYPES)
           + _entity_type('GithubUserHistory', github_history.FIELD_TYPES) +
           '<EntityContainer Name="Container">'
           f'<EntitySet Name="GithubUsers" EntityType="{NAMESPACE}.GithubUser"/>'
           f'<EntitySet Name="GithubUserHistory" EntityType="{NAMESPACE}.GithubUserHistory"/>'
           '</EntityContainer></Schema></edmx:DataServices></edmx:Edmx>')
    return Response(xml, media_type='application/xml', headers={'OData-Version': '4.0'})

def _prefix_condition(prefixes: list[str], team):
    return or_(*[team.startswith(prefix, autoescape=True) for prefix in prefixes])


def _serve(request: Request, entity_set: str, route: str, rule_function: str, fields: dict, types: dict,
           list_rows, count_rows, row_id):
    client_id = authenticate(request)
    allowed_prefixes = _team_prefixes(client_id, rule_function)
    params = request.query_params
    try:
        conditions = []
        if params.get('$filter'):
            conditions.append(odata.parse_filter(params['$filter'], fields, types))
        if params.get('team_prefix'):
            conditions.append(_prefix_condition([params['team_prefix']], fields['Team']))
        if allowed_prefixes is not None:
            conditions.append(_prefix_condition(allowed_prefixes, fields['Team']))
        where = and_(*conditions) if conditions else None
        order_by = odata.parse_orderby(params['$orderby'], fields) if params.get('$orderby') else None
        names = list(types) + ['NodeId']
        selected = odata.parse_select(params['$select'], ['Id'] + names) if params.get('$select') else None
        top = odata.parse_int('$top', params['$top'], 0, MAX_PAGE_SIZE) if '$top' in params else DEFAULT_PAGE_SIZE
        skip = odata.parse_int('$skip', params['$skip'], 0) if '$skip' in params else 0
        count = odata.parse_bool('$count', params['$count']) if '$count' in params else False
    except odata.ODataError as ex:
        return _error(400, str(ex))

    rows = list_rows(where, order_by, top + 1, skip)
    has_more = len(rows) > top
    rows = rows[:top]
    for row in rows:
        row['Id'] = row_id(row)
        row['LastChanged'] = row['LastChanged'].isoformat() if row['LastChanged'] else None
        if selected:
            for name in [name for name in row if name not in selected]:
                del row[name]
    logger.info(f"{client_id} listed {entity_set}: filter={params.get('$filter')!r} "
                f"team_prefix={params.get('team_prefix')!r} skip={skip} rows={len(rows)}")

    body = {'@odata.context': f'{_base_url(request)}/$metadata#{entity_set}'}
    if count:
        body['@odata.count'] = count_rows(where)
    body['value'] = rows
    if has_more:
        next_params = {**request.query_params, '$skip': str(skip + top)}
        body['@odata.nextLink'] = str(request.url_for(route).replace_query_params(**next_params))
    return _json(body)


@router.get('/GithubUsers', name='github_users')
def github_users(request: Request):
    return _serve(request, 'GithubUsers', 'github_users', RULE_FUNCTION,
                  github_directory.FIELDS, github_directory.FIELD_TYPES,
                  github_directory.list_github_users, github_directory.count_github_users,
                  lambda row: f"{row['Login']}|{row['Team']}")


@router.get('/GithubUserHistory', name='github_user_history')
def github_user_history(request: Request):
    return _serve(request, 'GithubUserHistory', 'github_user_history', HISTORY_RULE_FUNCTION,
                  github_history.FIELDS, github_history.FIELD_TYPES,
                  github_history.list_history, github_history.count_history,
                  lambda row: row['Id'])