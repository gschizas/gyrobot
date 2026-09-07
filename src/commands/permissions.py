"""Admin commands for the DB-backed permission system (``backend.permissions``).

Permission rules live in the ``permission_rules`` table (populated via
``scripts/migrate_permissions.py --to-db``) and are cached in-process after
first use; edits made directly in the database are not picked up until the
cache is invalidated. ``permissions reload`` does that manually - there is no
automatic TTL/expiry by design (see ``backend/permissions.py``).
"""
import click

from backend import permissions
from backend.configuration import check_security
from commands import gyrobot, ClickAliasedGroup
from commands.extended_context import ExtendedContext

_SECURITY_TEXT = {
    'reload': 'reload the permission cache',
    'show': 'view a permission rule',
}


@gyrobot.group('permissions', cls=ClickAliasedGroup, aliases=['perms'])
@click.pass_context
def permissions_group(ctx: ExtendedContext):
    """Inspect and manage the DB-backed permission system"""
    ctx.ensure_object(dict)
    ctx.obj['security_text'] = _SECURITY_TEXT


@permissions_group.command('reload', aliases=['refresh'])
@click.pass_context
@check_security
def reload_permissions(ctx: ExtendedContext):
    """Invalidate the in-process permission cache so the next check reloads from the database"""
    permissions.invalidate_cache()
    ctx.chat.send_text(":arrows_counterclockwise: Permission cache invalidated; "
                       "rules will be reloaded from the database on next use.")


@permissions_group.command('show')
@click.argument('function_name')
@click.argument('environment', default=permissions.GLOBAL_ENVIRONMENT)
@click.argument('role', default=permissions.DEFAULT_ROLE)
@click.pass_context
@check_security
def show_permission(ctx: ExtendedContext, function_name: str, environment: str, role: str):
    """Show the resolved permission rule for FUNCTION_NAME (module:func) [ENVIRONMENT] [ROLE]"""
    rule = permissions.get_rule(function_name, environment, role)
    if rule is None:
        ctx.chat.send_text(
            f"No rule for `{function_name}` environment=`{environment}` role=`{role}`.",
            is_error=True)
        return
    lines = [
        f"*{function_name}* environment=`{environment}` role=`{role}`",
        f"Users: {', '.join(rule['users']) or '(none)'}",
        f"Channels: {', '.join(rule['channels']) or '(none)'}",
    ]
    if rule['extra']:
        lines.append(f"Extra: {rule['extra']}")
    ctx.chat.send_text('\n'.join(lines))
