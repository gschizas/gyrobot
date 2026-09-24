"""Pydantic request/response models for the REST API."""
from typing import List, Optional

from pydantic import BaseModel, Field


class GithubOnboardRequest(BaseModel):
    username: str = Field(..., description="GitHub username to invite")
    email: str = Field(..., description="Colleague's email address")
    team: str = Field(..., description="Enterprise team slug to assign once accepted")


class CrowdOnboardRequest(BaseModel):
    username: str
    team: str


class JetbrainsOnboardRequest(BaseModel):
    email: str
    team_name: str


class SlackOnboardRequest(BaseModel):
    email: str
    member_ids: List[str] = Field(..., min_length=1)


class OffboardRequest(BaseModel):
    email: str


class CommandMessage(BaseModel):
    type: str
    text: Optional[str] = None
    title: Optional[str] = None
    is_error: Optional[bool] = None


class CommandResult(BaseModel):
    success: bool
    exit_code: int
    output: str
    messages: List[dict]
    error: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    expires_in: int
