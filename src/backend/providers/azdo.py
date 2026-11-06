"""Azure DevOps provisioning (nothing to do).

Users reach Azure DevOps through Entra ID, which is synchronised with Active Directory, so there is nothing to
provision or remove here. The ``azdo`` provision is only a snapshot kept by ``backend.azdo_sync`` for reporting;
this module exists so that ``offboard`` knows the resource.
"""
from backend.accounts import Provision
from backend.providers.base import ProvisionRequest


def provision(ctx, account: ProvisionRequest) -> str:
    return "Azure DevOps access comes from Entra ID; nothing to provision"


def deprovision(ctx, provision: Provision) -> str:
    return "Azure DevOps access ends when the user is removed from Active Directory/Entra ID; nothing to do"
