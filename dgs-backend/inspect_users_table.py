import asyncio
from sqlalchemy import create_engine, inspect

# Sync engine for inspection
DATABASE_URL = "postgresql://dgs:dgs_password@localhost:5432/dgs"


def inspect_table():
  try:
    engine = create_engine(DATABASE_URL)
    inspector = inspect(engine)
    if not inspector.has_table("users"):
      print("Table 'users' does not exist.")
      return

    columns = inspector.get_columns("users")
    print("Columns in 'users' table:")
    for col in columns:
      print(f"- {col['name']}: {col['type']} (nullable={col['nullable']}, default={col.get('default')})")
  except Exception as e:
    print(f"Error: {e}")


if __name__ == "__main__":
  inspect_table()
