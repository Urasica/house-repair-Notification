"""Check progress sources/links; --write refreshes the derived index (stdlib only)."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s]+?)(?:\s+\"[^\"]*\")?\s*\)")
REFERENCE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]+>|\S+)", re.M)
RECORD_ID = re.compile(r"\bR\d{3,}\b")
TASK_ID = re.compile(r"\bT-M\d+A?-\d{2}\b")
INPUT_ID = re.compile(r"\bI-[A-Z]+-\d{2}\b")
OPTIONAL = (Path("data/private"), Path("artifacts"))
ROOT_DOCUMENTS = {"README.md", "current-status.md"}


def prose(text: str) -> str:
    """Hide fenced code, preserving line numbers for actionable errors."""
    output = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence is None and marker:
            fence = marker.group(1)
            output.append("")
        elif fence and re.fullmatch(rf"\s{{0,3}}{re.escape(fence[0])}{{{len(fence)},}}\s*", line):
            fence = None
            output.append("")
        else:
            output.append(line if fence is None else "")
    return "\n".join(output)


def anchors(text: str) -> set[str]:
    text = prose(text)
    result = set(re.findall(r"<(?:a|span)\s+(?:id|name)=[\"']([^\"']+)", text))
    used: set[str] = set()
    for heading in re.finditer(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", text, re.M):
        title = re.sub(r"<[^>]+>", "", heading.group(1)).lower()
        title = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", title)
        slug = re.sub(r"[^\w\s-]", "", title).replace(" ", "-")
        candidate = slug
        suffix = 0
        while candidate in used:
            suffix += 1
            candidate = f"{slug}-{suffix}"
        used.add(candidate)
        result.add(candidate)
    return result


def links(text: str):
    text = re.sub(r"`+[^`\n]*`+", "", prose(text))
    for pattern in (LINK, REFERENCE):
        for match in pattern.finditer(text):
            yield text.count("\n", 0, match.start()) + 1, match.group(1).strip("<>")


def check_links(root: Path, files: list[Path]) -> tuple[list[str], int]:
    errors = []
    optional = 0
    cache = {}
    for source in files:
        for line, url in links(source.read_text(encoding="utf-8-sig")):
            parsed = urlsplit(url)
            if parsed.scheme or parsed.netloc:
                continue
            target = (source.parent / unquote(parsed.path)).resolve() if parsed.path else source
            label = f"{source.relative_to(root).as_posix()}:{line}: {url}"
            if not target.is_relative_to(root):
                errors.append(f"{label}: target leaves repository")
                continue
            relative = target.relative_to(root)
            if any(relative.is_relative_to(prefix) for prefix in OPTIONAL):
                optional += 1
                continue
            if "#" in url and not parsed.fragment:
                errors.append(f"{label}: empty heading/anchor; link file directly for its top")
            if not target.exists():
                errors.append(f"{label}: missing file")
            elif (
                target.parent == root / "progress"
                and target.suffix.lower() == ".md"
                and target.name not in ROOT_DOCUMENTS
            ):
                errors.append(f"{label}: unsupported progress path; use current-status or records/")
            elif target.suffix.lower() == ".md" and parsed.fragment:
                if target not in cache:
                    cache[target] = anchors(target.read_text(encoding="utf-8-sig"))
                if unquote(parsed.fragment) not in cache[target]:
                    errors.append(f"{label}: missing heading/anchor")
    return errors, optional


@dataclass(frozen=True)
class Record:
    path: Path
    title: str
    observed: str
    environment: str
    relation: str


def check_records(root: Path) -> tuple[list[str], dict[str, Record]]:
    """Records own their metadata; the index is only a generated view."""
    directory = root / "progress/records"
    errors = []
    entries: dict[str, Record] = {}
    for path in sorted(directory.rglob("*.md")):
        if path == directory / "README.md":
            continue
        body = path.read_text(encoding="utf-8-sig")
        header = re.findall(
            r"^> 기록 ID: (R\d{3,}) · 기준일: (\d{4}-\d{2}-\d{2}) · 환경: (.+)$",
            body,
            re.M,
        )
        title = re.findall(r"^# (.+)$", body, re.M)
        relation = re.findall(r"^> 관계: (.+)$", body, re.M)
        label = path.relative_to(root).as_posix()
        if path.parent != directory:
            errors.append(f"{label}: record must be directly inside progress/records")
        if len(header) != 1 or len(title) != 1 or len(relation) != 1:
            errors.append(f"{label}: require one title, ID/date/environment header and relation")
            continue
        record_id, observed, environment = header[0]
        try:
            date.fromisoformat(observed)
        except ValueError:
            errors.append(f"{record_id}: invalid observed date")
        if record_id in entries:
            errors.append(f"{record_id}: duplicate evidence ID")
        entries[record_id] = Record(path, title[0], observed, environment, relation[0])
    if not entries:
        errors.append("progress/records: no evidence records")
    return errors, entries


def table_cell(text: str) -> str:
    return text.replace("|", "&#124;")


def render_index(entries: dict[str, Record]) -> str:
    lines = [
        "# 증거 기록 색인",
        "",
        "<!-- Generated by scripts/check_progress.py --write. Do not edit. -->",
        "",
        "각 기록의 제목·ID·기준일·환경·관계에서 자동 생성한다. 수정은 해당 기록에서 한다. "
        "기록 번호나 날짜만으로 현재 상태를 추정하지 않는다.",
        "",
        "[현재 상태와 남은 작업](../current-status.md) · [작성 방법](../README.md)",
        "",
        "| ID | 기준일 | 기록 | 환경·범위 | 관계·해석 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record_id, item in sorted(entries.items(), key=lambda pair: int(pair[0][1:])):
        title = table_cell(item.title).replace("[", "&#91;").replace("]", "&#93;")
        lines.append(
            f"| {record_id} | {item.observed} | [{title}]({item.path.name}) | "
            f"{table_cell(item.environment)} | {table_cell(item.relation)} |"
        )
    return "\n".join(lines) + "\n"


def check_index(root: Path, entries: dict[str, Record], *, write: bool = False) -> list[str]:
    index = root / "progress/records/README.md"
    expected = render_index(entries)
    if index.is_file() and index.read_text(encoding="utf-8-sig") == expected:
        return []
    if write:
        index.write_text(expected, encoding="utf-8")
        return []
    return [
        "progress/records/README.md: stale generated index; "
        "run python scripts/check_progress.py --write"
    ]


def check_references(root: Path, entries: dict[str, Record]) -> list[str]:
    errors = []
    current = root / "progress/current-status.md"
    if not current.is_file():
        return ["progress/current-status.md: required progress document missing"]
    current_text = current.read_text(encoding="utf-8-sig")
    for other in (root / "progress").glob("*.md"):
        if other.name not in ROOT_DOCUMENTS:
            errors.append(f"{other.name}: unsupported root document; put evidence in records/")
        if other != current and re.search(
            r"^\|\s*T-M", prose(other.read_text(encoding="utf-8-sig")), re.M
        ):
            errors.append(f"{other.name}: task rows belong only in current-status.md")
    tasks: dict[str, tuple[str, str]] = {}
    inputs = []
    allowed_status = {"대기", "입력 대기", "진행", "검증", "완료", "취소", "대체"}
    for row in current_text.splitlines():
        if re.match(r"^\|\s*I-[A-Z]", row):
            inputs.append(row.split("|")[1].strip())
        if re.match(r"^\| M\d", row) and not re.search(r"\]\(records/[^)]+\)", row):
            errors.append(f"current-status: milestone needs canonical evidence: {row}")
        if not re.match(r"^\|\s*T-M", row):
            continue
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if len(cells) != 5 or not TASK_ID.fullmatch(cells[0]):
            errors.append(f"current-status: malformed task row: {row}")
            continue
        task, status, evidence, owner, dependency = cells
        if task in tasks:
            errors.append(f"{task}: duplicate task ID")
        tasks[task] = (status, dependency)
        if status not in allowed_status or not owner or not dependency:
            errors.append(f"{task}: require valid status, owner role and dependency")
        proofs = {
            (current.parent / unquote(urlsplit(url).path)).resolve()
            for _, url in links(evidence)
            if not urlsplit(url).scheme and not urlsplit(url).netloc
        }
        proven = [item for item in entries.values() if item.path in proofs]
        if status == "완료":
            dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", evidence)
            try:
                completed = date.fromisoformat(dates[0]) if len(dates) == 1 else None
            except ValueError:
                completed = None
            if completed is None or not proven:
                errors.append(f"{task}: completion requires date and evidence link")
            elif any(item.observed > completed.isoformat() for item in proven):
                errors.append(f"{task}: completion predates its evidence")
        if status in {"취소", "대체"} and not evidence:
            errors.append(f"{task}: cancellation/replacement needs explanation")
    if len(inputs) != len(set(inputs)):
        errors.append("current-status: duplicate input ID")
    for input_id in inputs:
        if not INPUT_ID.fullmatch(input_id):
            errors.append(f"current-status: invalid input ID {input_id}")
    # A fully finished project may legitimately have no remaining tasks.
    for path in [current, *(item.path for item in entries.values())]:
        body = prose(path.read_text(encoding="utf-8-sig"))
        for record_id in set(RECORD_ID.findall(body)) - entries.keys():
            errors.append(f"{path.relative_to(root)}: unknown evidence ID {record_id}")
        if path == current:
            for task in set(TASK_ID.findall(body)) - tasks.keys():
                errors.append(f"current-status: unknown task ID {task}")
            for input_id in set(INPUT_ID.findall(body)) - set(inputs):
                errors.append(f"current-status: unknown input ID {input_id}")
    updated = re.search(r"갱신: (\d{4}-\d{2}-\d{2})", current_text)
    try:
        if not updated:
            raise ValueError
        date.fromisoformat(updated.group(1))
    except ValueError:
        errors.append("current-status: missing/invalid as-of date")
    # Check the dependency graph, not just whether the referenced IDs exist.
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task: str) -> None:
        if task in visiting:
            errors.append(f"{task}: dependency cycle")
            return
        if task in visited:
            return
        visiting.add(task)
        for dependency in TASK_ID.findall(tasks[task][1]):
            if dependency in tasks:
                if tasks[task][0] == "완료" and tasks[dependency][0] != "완료":
                    errors.append(f"{task}: completed before dependency {dependency}")
                visit(dependency)
        visiting.remove(task)
        visited.add(task)

    for task in tasks:
        visit(task)
    return errors


def check_evidence_labels(root: Path, files: list[Path], entries: dict[str, Record]) -> list[str]:
    """A valid link can still cite the wrong R ID; validate both together."""
    errors = []
    for path in files:
        for match in LINK.finditer(prose(path.read_text(encoding="utf-8-sig"))):
            # LINK captures destinations; its full text includes the visible label.
            label = match.group(0).split("](", 1)[0]
            for record_id in RECORD_ID.findall(label):
                item = entries.get(record_id)
                parsed = urlsplit(match.group(1).strip("<>"))
                target = (path.parent / unquote(parsed.path)).resolve()
                if item is None or parsed.scheme or parsed.netloc or target != item.path:
                    errors.append(
                        f"{path.relative_to(root)}: {record_id} label points to wrong record"
                    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate the evidence index")
    args = parser.parse_args()
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={ROOT.as_posix()}",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "*.md",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    files = {ROOT / name for name in result.stdout.decode("utf-8").split("\0") if name}
    files.update((ROOT / "progress").rglob("*.md"))
    # Git may still list deleted tracked files during a rename/refactor.
    files = sorted(path for path in files if path.is_file())
    errors, entries = check_records(ROOT)
    errors.extend(check_references(ROOT, entries))
    index = ROOT / "progress/records/README.md"
    sources = [path for path in files if path != index]
    link_errors, optional = check_links(ROOT, sources)
    errors.extend(link_errors)
    errors.extend(check_evidence_labels(ROOT, sources, entries))
    # A stale index may link to renamed files. Validate sources before regenerating it.
    if not errors:
        errors.extend(check_index(ROOT, entries, write=args.write))
    if not errors:
        index_errors, _ = check_links(ROOT, [index])
        errors.extend(index_errors)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(
        f"PASS: {len(files)} Markdown files, {len(entries)} discovered records; "
        f"generated index current; {optional} optional local artifact links excluded."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
