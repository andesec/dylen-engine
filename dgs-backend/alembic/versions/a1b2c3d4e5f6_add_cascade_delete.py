"""add_cascade_delete

Revision ID: a1b2c3d4e5f6
Revises: 9c5d1e8f2a3b
Create Date: 2026-01-27 12:00:00.000000

"""

from sqlalchemy.engine.reflection import Inspector

from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "9c5d1e8f2a3b"
branch_labels = None
depends_on = None


def upgrade():
  conn = op.get_bind()
  inspector = Inspector.from_engine(conn)

  target_tables = ["llm_audit_logs", "email_delivery_logs", "user_tier_overrides", "user_usage_metrics", "user_usage_logs"]

  for table in target_tables:
    # Check if table exists (safety check)
    if table not in inspector.get_table_names():
      continue

    fks = inspector.get_foreign_keys(table)
    for fk in fks:
      # Find FK pointing to users.id
      if fk["referred_table"] == "users" and fk["constrained_columns"] == ["user_id"]:
        # Drop existing constraint
        op.drop_constraint(fk["name"], table, type_="foreignkey")

        # Recreate with ON DELETE CASCADE
        # Note: We reuse the name if it was auto-generated or explicit.
        op.create_foreign_key(fk["name"], table, "users", ["user_id"], ["id"], ondelete="CASCADE")


def downgrade():
  conn = op.get_bind()
  inspector = Inspector.from_engine(conn)

  target_tables = ["llm_audit_logs", "email_delivery_logs", "user_tier_overrides", "user_usage_metrics", "user_usage_logs"]

  for table in target_tables:
    if table not in inspector.get_table_names():
      continue

    fks = inspector.get_foreign_keys(table)
    for fk in fks:
      if fk["referred_table"] == "users" and fk["constrained_columns"] == ["user_id"]:
        op.drop_constraint(fk["name"], table, type_="foreignkey")

        # Recreate WITHOUT ON DELETE CASCADE
        op.create_foreign_key(
          fk["name"],
          table,
          "users",
          ["user_id"],
          ["id"],
          # default is NO ACTION / RESTRICT
        )
