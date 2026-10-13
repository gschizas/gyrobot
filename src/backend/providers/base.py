"""Account record passed to provider provision/deprovision stubs."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Role(Enum):
    FACILITATOR = 'facilitator'
    SCRUM_MASTER = 'scrum_master'
    FRONTEND_DEVELOPER = 'frontend_developer'
    BACKEND_DEVELOPER = 'backend_developer'
    FULL_STACK_DEVELOPER = 'full_stack_developer'
    IOS_DEVELOPER = 'ios_developer'
    ANDROID_DEVELOPER = 'android_developer'
    PRODUCT_OWNER = 'product_owner'


@dataclass
class ProvisionRequest:
    name: str
    email: str
    userid: str
    team: str
    role: Optional[Role] = None
    # Extra values a provider wants persisted with the provision (e.g. an invitation id)
    provision_data: dict = field(default_factory=dict)
