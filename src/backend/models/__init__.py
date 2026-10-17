"""Every model must be imported here, so that ``Base.metadata`` (used by Alembic) knows all the tables."""
from backend.models import accounts, approval, kudos, permissions  # noqa: F401
