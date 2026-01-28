import os


def sync_env_example(env_path=".env", example_path=".env.example"):
  keys = set()

  # 1. Collect keys from both files to ensure full coverage
  for file_path in [env_path, example_path]:
    if os.path.exists(file_path):
      with open(file_path) as f:
        for line in f:
          line = line.strip()
          # Ignore comments and empty lines
          if line and not line.startswith("#"):
            if "=" in line:
              key = line.split("=")[0].strip()
              keys.add(key)

  if not keys:
    print("No configuration keys found.")
    return

  # 2. Sort keys alphabetically for a clean file structure
  sorted_keys = sorted(list(keys))

  # 3. Write the fresh .env.example
  try:
    with open(example_path, "w") as f:
      f.write("# Auto-generated .env.example\n")
      f.write("# Define your local values in a .env file\n\n")
      for key in sorted_keys:
        f.write(f"{key}=\n")

    print(f"Successfully updated {example_path} with {len(sorted_keys)} keys.")
  except OSError as e:
    print(f"Error writing to file: {e}")


if __name__ == "__main__":
  sync_env_example()
