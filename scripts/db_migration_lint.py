from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

DESTRUCTIVE_TAG = "# destructive: approved"
EMPTY_TAG = "# empty: allow"
TYPE_CHANGE_TAG = "# type-change: approved"
BACKFILL_TAG = "# backfill: ok"


@dataclass(frozen=True)
class UpgradeOps:
  """Capture upgrade operations so lint can enforce safety policies."""

  op_calls: list[str]
  drop_ops: list[str]
  nullable_false_ops: list[str]
  type_change_ops: list[str]
  has_backfill: bool


class _UpgradeOpsVisitor(ast.NodeVisitor):
  """Walk upgrade() AST nodes to detect schema operations and backfills."""

  def __init__(self) -> None:
    """Initialize tracking containers for upgrade() inspection."""
    # Track operations to detect empty migrations and unsafe patterns.
    self.op_calls: list[str] = []
    self.drop_ops: list[str] = []
    self.nullable_false_ops: list[str] = []
    self.type_change_ops: list[str] = []
    self.has_backfill = False
    # Initialize the base visitor to enable recursive traversal.
    super().__init__()

  def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
    """Inspect Alembic op.* calls so lint can enforce migration rules."""
    # Only capture calls that are Alembic op.* operations.
    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "op":
      op_name = node.func.attr
      self.op_calls.append(op_name)

      # Flag destructive operations in upgrade paths.
      if op_name in {"drop_table", "drop_column"}:
        self.drop_ops.append(op_name)

      # Track nullable=False changes and type changes that need explicit approval.
      if op_name == "alter_column":
        # Inspect keyword arguments for nullable/type change hints.
        for keyword in node.keywords:
          if keyword.arg == "nullable" and isinstance(keyword.value, ast.Constant) and keyword.value.value is False:
            self.nullable_false_ops.append(op_name)

          if keyword.arg == "type_":
            self.type_change_ops.append(op_name)

      # Treat bulk inserts as backfills for nullable enforcement checks.
      if op_name == "bulk_insert":
        self.has_backfill = True

      # Treat UPDATE/INSERT SQL as backfills for nullable enforcement checks.
      if op_name == "execute":
        # Scan SQL text for backfill-like statements.
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
          sql_text = node.args[0].value.upper()
          if "UPDATE" in sql_text or "INSERT" in sql_text:
            self.has_backfill = True

    # Continue walking nested nodes to capture all op calls.
    self.generic_visit(node)


def _find_upgrade_ops(tree: ast.AST) -> UpgradeOps:
  """Extract upgrade() operations so lint rules can be applied."""
  # Find the upgrade() function definition first.
  upgrade_nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "upgrade"]

  # Short-circuit when no upgrade() definition exists.
  if not upgrade_nodes:
    return UpgradeOps(op_calls=[], drop_ops=[], nullable_false_ops=[], type_change_ops=[], has_backfill=False)

  # Visit the upgrade() body to collect operations.
  visitor = _UpgradeOpsVisitor()
  visitor.visit(upgrade_nodes[0])
  return UpgradeOps(op_calls=visitor.op_calls, drop_ops=visitor.drop_ops, nullable_false_ops=visitor.nullable_false_ops, type_change_ops=visitor.type_change_ops, has_backfill=visitor.has_backfill)


def _lint_file(path: Path) -> list[str]:
  """Analyze a migration file and return any policy violations."""
  # Parse the migration file to inspect upgrade operations.
  text = path.read_text(encoding="utf-8")
  tree = ast.parse(text, filename=str(path))
  ops = _find_upgrade_ops(tree)

  # Detect lint suppression tags for destructive or empty migrations.
  destructive_approved = DESTRUCTIVE_TAG in text
  empty_allowed = EMPTY_TAG in text
  type_change_approved = TYPE_CHANGE_TAG in text
  backfill_tagged = BACKFILL_TAG in text

  # Collect lint violations for this migration file.
  errors: list[str] = []

  # Enforce non-empty migrations unless explicitly approved.
  if not ops.op_calls and not empty_allowed:
    errors.append("Migration upgrade() is empty. Add operations or tag with '# empty: allow'.")

  # Block destructive operations unless explicitly approved.
  if ops.drop_ops and not destructive_approved:
    errors.append("Destructive ops detected in upgrade(). Add '# destructive: approved' with reviewer sign-off.")

  # Require backfill notes when nullable is set to False in upgrade().
  if ops.nullable_false_ops and not (ops.has_backfill or backfill_tagged):
    errors.append("nullable=False detected without backfill. Add backfill step or tag with '# backfill: ok'.")

  # Require explicit approval for type changes to prevent narrowing without a plan.
  if ops.type_change_ops and not type_change_approved:
    errors.append("Type change detected. Add '# type-change: approved' with the expand/contract plan.")

  return errors


def _migration_paths() -> list[Path]:
  """Locate migration files so lint runs against a deterministic set."""
  # Resolve repository paths relative to this script.
  repo_root = Path(__file__).resolve().parents[1]
  versions_dir = repo_root / "dgs-backend" / "alembic" / "versions"
  return sorted(versions_dir.glob("*.py"))


def main() -> None:
  """Exit non-zero when migration lint detects policy violations."""
  # Aggregate lint errors across all migration files.
  errors: list[str] = []

  # Scan every migration file and collect errors in one pass.
  for path in _migration_paths():
    file_errors = _lint_file(path)
    if file_errors:
      # Expand file-specific errors into the aggregate list.
      for message in file_errors:
        errors.append(f"{path}: {message}")

  # Report all errors so developers can fix them in one pass.
  if errors:
    print("Migration lint failed:")
    for message in errors:
      print(f"- {message}")

    sys.exit(1)

  print("Migration lint passed.")


if __name__ == "__main__":
  main()
