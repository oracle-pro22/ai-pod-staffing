"""Check required package versions without importing or starting the application."""
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def main():
    if sys.version_info < (3, 11):
        print("Python 3.11+ is required.", file=sys.stderr)
        return 1
    for line in Path(__file__).with_name("requirements.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, separator, expected = line.strip().partition("==")
        if not separator or not expected:
            print("Invalid pinned dependency in backend/requirements.txt.", file=sys.stderr)
            return 1
        try:
            if version(name) != expected:
                return 1
        except PackageNotFoundError:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
