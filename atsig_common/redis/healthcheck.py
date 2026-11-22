"""
Healthcheck of a worker container (`supervise` writes the heartbeat file):

    python -m atsig_common.redis.healthcheck --max-age 60

Exit code 0 when the heartbeat is fresh, 1 when it is missing or older than `--max-age`.
"""

import argparse
import os
import sys
import time

from .supervisor import HEARTBEAT_FILE


def is_healthy(path: str, max_age: float) -> bool:
    try:
        return time.time() - os.path.getmtime(path) <= max_age
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-age", type=float, default=60.0)
    parser.add_argument("--file", default=HEARTBEAT_FILE)
    args = parser.parse_args(argv)
    return 0 if is_healthy(args.file, args.max_age) else 1


if __name__ == "__main__":
    sys.exit(main())
