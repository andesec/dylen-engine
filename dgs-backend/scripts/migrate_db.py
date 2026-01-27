import asyncio
import os
import sys

# Add the project root to the path so we can import 'app' if needed
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.smart_migrate import main


def run():
  if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
  asyncio.run(main())


if __name__ == "__main__":
  run()
