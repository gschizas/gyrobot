"""Slack account deactivation (STUB).

Real integration target: Slack SCIM API
    DELETE /scim/v2/Users/{id}    (deactivate a member)
Requires an org/workspace admin token with the ``admin`` SCIM scope.
"""
def deactivate(ctx, emails: list[str], member_ids: list[str]) -> str:
    """Deactivate every Slack account of one person.

    A person may have several Slack accounts (signed up with different emails), so this takes all the
    known member ids plus every email the person is known by, and deactivates each distinct account found.
    """
    # TODO: resolve each email with users.lookupByEmail, union with member_ids, then deactivate each via SCIM.
    ctx.logger.info(f"[stub] Deactivate Slack users: member ids {member_ids}, emails {emails}")
    return (f"Slack accounts would be deactivated (stub): {len(member_ids)} known member id(s), "
            f"looking up {len(emails)} email(s): {', '.join(emails)}")
