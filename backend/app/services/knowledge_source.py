"""Offline M08 verification and lossless article/annex preparation. No URL fetching."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

ARTICLES = ["제6조의2", *(f"제{i}조" for i in range(7, 46))]
RELATIONS = {"제10조제2항": "별표 2", "제42조제5항": "별표 3", "제43조제2항": "별표 4"}
CONTEXT = [*(f"제{i}조" for i in range(1, 6)), "부칙 전체"]
MAX_FILE_BYTES = 10 * 1024 * 1024


def digest(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_bounded(path: Path) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Source file too large")
    return data


@dataclass(frozen=True)
class SourceBundle:
    manifest: dict
    manifest_hash: str
    chunks: list[dict]


def text_blocks(markdown: str) -> dict[str, str]:
    result = {}
    for section in re.split(r"(?m)^## ", markdown)[1:]:
        heading, _, tail = section.partition("\n")
        blocks = re.findall(r"```text\n(.*?)\n```", tail, re.S)
        if blocks:
            key = heading.split("(")[0].strip()
            if key in result or len(blocks) != 1:
                raise ValueError("Duplicate/ambiguous source section")
            result[key] = blocks[0]
    return result


def prepare_source(directory: Path, expected_hash: str) -> SourceBundle:
    """Require an independently pinned manifest hash before creating any chunk."""
    root = directory.resolve(strict=True)
    raw = read_bounded(root / "manifest.json")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_hash) or digest(raw) != expected_hash:
        raise ValueError("Manifest fingerprint mismatch")
    manifest = json.loads(raw)
    if (
        manifest.get("schemaVersion") != 1
        or manifest.get("status") != "COMPLETE_VERIFIED"
        or manifest.get("missing") != []
        or manifest.get("articles") != ARTICLES
        or manifest.get("relations") != RELATIONS
        or not manifest.get("reviewer")
        or not manifest.get("reviewedAt")
        or manifest.get("documentKind") != "LAW_CRITERIA"
        or [a["number"] for a in manifest.get("annexes", [])] != [2, 3, 4]
    ):
        raise ValueError("Incomplete source review or scope")
    files = {}
    entries = manifest.get("files", [])
    if not entries or len(entries) > 100:
        raise ValueError("Invalid source inventory")
    total = 0
    for entry in entries:
        name = entry["path"]
        path = (root / name).resolve(strict=True)
        if path == root or not path.is_relative_to(root) or name in files:
            raise ValueError("Unsafe/duplicate source path")
        data = read_bounded(path)
        total += len(data)
        if total > 100 * 1024 * 1024:
            raise ValueError("Source bundle too large")
        if len(data) != entry["bytes"] or digest(data) != entry["sha256"]:
            raise ValueError("Source file fingerprint mismatch")
        files[name] = data

    def parsed(name):
        return json.loads(files[name])

    def decoded(name):
        return files[name].decode("utf-8").replace("\r\n", "\n")

    coverage = parsed("coverage.json")
    wanted = ARTICLES + ["별표 2", "별표 3", "별표 4"]
    if [c["id"] for c in coverage] != wanted or any(
        c.get("missing") != []
        or any(c.get(k) is not True for k in ("complete", "acquired", "organized"))
        for c in coverage
    ):
        raise ValueError("Incomplete coverage")
    verification = parsed("verification.json")
    if (
        verification.get("status") != "PASS"
        or verification.get("missing") != []
        or [c["id"] for c in verification["checks"]] != wanted
        or any(c.get("passed") is not True for c in verification["checks"])
    ):
        raise ValueError("Source verification did not pass")
    paragraphs = parsed("law-paragraphs.json")
    blocks = text_blocks(decoded("organized.md"))
    contexts = text_blocks(decoded("context.md"))
    if list(blocks) != ARTICLES or list(contexts) != CONTEXT:
        raise ValueError("Missing full article or applicability context")
    chunks = []
    external = {row["article"]: row["references"] for row in parsed("external-references.json")}
    for row in coverage[:40]:
        locator = row["id"]
        start, end = row["sourceParagraphRange"]
        if not 1 <= start <= end <= len(paragraphs):
            raise ValueError("Invalid paragraph range")
        body = "\n\n".join(p.strip() for p in paragraphs[start - 1 : end])
        if body != blocks[locator] or digest(body) != row["sha256"]:
            raise ValueError("Article text or boundary mismatch")
        expected_annex = {"제10조": [2], "제42조": [3], "제43조": [4]}.get(locator, [])
        if row["relatedAnnexes"] != expected_annex:
            raise ValueError("Annex relationship mismatch")
        chunks.append(
            {
                "locator": locator,
                "body": body,
                "contentHash": digest(body),
                "metadata": {
                    "role": "ARTICLE",
                    "sourceParagraphRange": [start, end],
                    "relatedLocators": [f"별표 {n}" for n in expected_annex],
                    "contextLocators": CONTEXT,
                    "externalReferences": external.get(locator, []),
                    "unresolved": locator in {"제43조", "제45조"},
                },
            }
        )
    annexes = parsed("annexes-organized.json")
    if [a["number"] for a in annexes] != [2, 3, 4]:
        raise ValueError("Incomplete annexes")
    for annex, row in zip(annexes, coverage[40:], strict=True):
        if len(annex["rows"]) != row["dataRows"] or len(annex["footnotes"]) != row["footnotes"]:
            raise ValueError("Annex row/footnote mismatch")
        # JSON retains merged-cell expansion, line breaks, units and all footnotes.
        body = canonical(annex)
        chunks.append(
            {
                "locator": row["id"],
                "body": body,
                "contentHash": digest(body),
                "metadata": {
                    "role": "ANNEX",
                    "relatedLocators": [{2: "제10조", 3: "제42조", 4: "제43조"}[annex["number"]]],
                    "contextLocators": CONTEXT,
                    "sourceFile": row["sourceFile"],
                    "unresolved": annex["number"] == 4,
                },
            }
        )
    for locator, body in contexts.items():
        if not body.strip():
            raise ValueError("Empty context")
        chunks.append(
            {
                "locator": locator,
                "body": body,
                "contentHash": digest(body),
                "metadata": {
                    "role": "CONTEXT",
                    "relatedLocators": [],
                    "contextLocators": [],
                    "unresolved": False,
                },
            }
        )
    return SourceBundle(manifest, expected_hash, chunks)
