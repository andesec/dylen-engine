"""Import all SQLAlchemy ORM models so Alembic sees a complete metadata graph."""

from __future__ import annotations

# Import ORM modules for side effects so models register with Base.metadata.
# Keeping this list centralized prevents migrations/drift checks from silently missing tables.
import app.schema.audit  # noqa: F401
import app.schema.coach  # noqa: F401
import app.schema.email_delivery_logs  # noqa: F401
import app.schema.feature_flags  # noqa: F401
import app.schema.fenster  # noqa: F401
import app.schema.jobs  # noqa: F401
import app.schema.lessons  # noqa: F401
import app.schema.notifications  # noqa: F401
import app.schema.quotas  # noqa: F401
import app.schema.runtime_config  # noqa: F401
import app.schema.sql  # noqa: F401
