"""Account model for tracking onboarding/offboarding across resources."""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID, uuid4


@dataclass
class Account:
    """Flexible account model to track user across multiple provisioning resources.
    
    Attributes:
        id: Unique account identifier (UUID)
        name: Account holder's name (optional)
        primary_email: Primary email address (used as key for lookups)
        created_at: Account creation timestamp
        updated_at: Last update timestamp
        metadata: Additional flexible data (dict)
    """
    name: Optional[str] = None
    primary_email: Optional[str] = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert account to dictionary for storage."""
        return {
            'id': str(self.id),
            'name': self.name,
            'primary_email': self.primary_email,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'metadata': self.metadata,
        }

    @staticmethod
    def from_dict(data: dict) -> 'Account':
        """Reconstruct account from dictionary."""
        return Account(
            id=UUID(data['id']) if isinstance(data['id'], str) else data['id'],
            name=data.get('name'),
            primary_email=data.get('primary_email'),
            created_at=datetime.fromisoformat(data['created_at']) if isinstance(data['created_at'], str) else data['created_at'],
            updated_at=datetime.fromisoformat(data['updated_at']) if isinstance(data['updated_at'], str) else data['updated_at'],
            metadata=data.get('metadata', {}),
        )


@dataclass
class Provision:
    """Tracks provisioning state for a single resource on an account.
    
    Attributes:
        id: Unique provision identifier (UUID)
        account_id: Associated account UUID
        resource: Resource type ('github', 'jetbrains', 'crowd', 'slack')
        status: Provisioning status ('pending', 'invited', 'accepted', 'assigned', 'active', 'failed')
        data: Resource-specific data (e.g., {username, node_id, license_id, member_ids})
        created_at: Provision creation timestamp
        updated_at: Last update timestamp
    """
    account_id: UUID
    resource: str
    status: str = 'pending'
    data: Dict[str, Any] = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        """Convert provision to dictionary for storage."""
        return {
            'id': str(self.id),
            'account_id': str(self.account_id),
            'resource': self.resource,
            'status': self.status,
            'data': self.data,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }

    @staticmethod
    def from_dict(data: dict) -> 'Provision':
        """Reconstruct provision from dictionary."""
        return Provision(
            id=UUID(data['id']) if isinstance(data['id'], str) else data['id'],
            account_id=UUID(data['account_id']) if isinstance(data['account_id'], str) else data['account_id'],
            resource=data['resource'],
            status=data.get('status', 'pending'),
            data=data.get('data', {}),
            created_at=datetime.fromisoformat(data['created_at']) if isinstance(data['created_at'], str) else data['created_at'],
            updated_at=datetime.fromisoformat(data['updated_at']) if isinstance(data['updated_at'], str) else data['updated_at'],
        )
