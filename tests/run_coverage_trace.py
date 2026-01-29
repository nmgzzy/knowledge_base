import sys
from pathlib import Path
import tempfile
import unittest
from trace import Trace


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    ignoredirs = []
    repo_root_str = str(repo_root)
    for p in sys.path:
        if not p:
            continue
        try:
            rp = str(Path(p).resolve())
        except Exception:
            continue
        if rp.startswith(repo_root_str):
            continue
        if Path(rp).is_dir():
            ignoredirs.append(rp)

    loader = unittest.TestLoader()
    suite = loader.discover("tests")
    runner = unittest.TextTestRunner(verbosity=2)

    tracer = Trace(
        count=True,
        trace=False,
        ignoredirs=tuple(ignoredirs),
        ignoremods=(
            "unittest",
            "trace",
            "dataclasses",
            "importlib",
            "pkgutil",
            "pathlib",
            "json",
            "sqlite3",
            "urllib",
        ),
    )

    with tempfile.TemporaryDirectory() as coverdir:
        result = tracer.runfunc(runner.run, suite)
        results = tracer.results()
        results.write_results(show_missing=True, summary=True, coverdir=coverdir)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
