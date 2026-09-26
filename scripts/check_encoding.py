"""Check all project source and documentation for valid UTF-8 bytes."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
paths = [ROOT / name for name in ("README.md", "pyproject.toml", ".gitignore", ".env.example")]
for directory, pattern in (("src", "*.py"), ("tests", "*.py"),
                           ("scripts", "*.py"), ("docs", "*.md")):
    paths.extend((ROOT / directory).rglob(pattern))

failures = []
suspect_sequences = ("\ufffd", "\u00c3\u00a7", "\u00c3\u00a3", "\u00c3\u00a9")
for path in paths:
    payload = path.read_bytes()
    try:
        content = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        failures.append((str(path), exc.start + 1, payload[exc.start:exc.end].hex()))
        continue
    for number, line in enumerate(content.splitlines(), start=1):
        if any(sequence in line for sequence in suspect_sequences):
            failures.append((str(path), number, line.encode("utf-8").hex()))

if failures:
    for path, position, problem_bytes in failures:
        print(f"{path}:{position}: bytes={problem_bytes}")
    raise SystemExit(1)
print(f"valid UTF-8: {len(paths)} files")
