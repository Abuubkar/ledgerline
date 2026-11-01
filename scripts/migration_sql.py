"""Print the SQL of the migrations a branch adds, for review and linting (CI pipes it into squawk).

Migrations already on the base branch were reviewed when they landed (docs/migrations.md); linting them again on
every PR would only repeat old decisions. So this finds the migration files added since `base`, works out the
revision they start from, and renders `alembic upgrade <start>:head --sql`. Prints nothing when none were added.

  uv run python scripts/migration_sql.py origin/main > new_migrations.sql
"""

import re
import subprocess
import sys
from pathlib import Path

VERSIONS = "apps/api/migrations/versions"


def revision_ids(path: Path) -> tuple[str, str | None]:
    text = path.read_text()
    revision = re.search(r'^revision[^=]*=\s*"([^"]+)"', text, re.M)
    down = re.search(r'^down_revision[^=]*=\s*"([^"]+)"', text, re.M)
    if not revision:
        sys.exit(f"{path}: no revision id found")
    return revision.group(1), down.group(1) if down else None


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    added = subprocess.run(["git", "diff", "--name-only", "--diff-filter=A", f"{base}...HEAD", "--", VERSIONS],
                           capture_output=True, text=True, check=True).stdout.split()
    files = [Path(f) for f in added if f.endswith(".py")]
    if not files:
        print("-- no new migrations", file=sys.stderr)
        return
    ids = dict(revision_ids(f) for f in files)  # revision -> down_revision
    starts = {down for down in ids.values() if down not in ids}
    if len(starts) != 1:
        sys.exit(f"new migrations don't form one chain from the base branch (they start from {sorted(map(str, starts))})")
    start = starts.pop() or "base"
    print(f"-- migrations added since {base}: {', '.join(sorted(ids))} (upgrade {start}:head)", file=sys.stderr)
    subprocess.run(["alembic", "upgrade", f"{start}:head", "--sql"], check=True)


if __name__ == "__main__":
    main()
