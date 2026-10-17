"""Every model must be imported here, so that ``Base.metadata`` (used by Alembic) knows all the tables."""
from backend.models import kudos, permissions  # noqa: F401
