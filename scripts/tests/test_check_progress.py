"""Regression cases for omissions and incorrect references in accumulating records."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_progress  # noqa: E402
from check_progress import (  # noqa: E402
    anchors,
    check_evidence_labels,
    check_index,
    check_links,
    check_records,
    check_references,
)


class ProgressChecks(unittest.TestCase):
    def setUp(self):
        workspace = Path(__file__).resolve().parents[2]
        scratch = workspace / ".cache/progress-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name).resolve()
        # Cleanup is restricted to the directory explicitly created for these fixtures.
        self.assertTrue(self.root.is_relative_to(scratch.resolve()))
        self.addCleanup(self.temp.cleanup)

    def write(self, name, body):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def test_missing_file_and_fragment_fail_but_private_artifact_is_optional(self):
        source = self.write(
            "progress/README.md",
            "[file](missing.md)\n[heading](templates/target.md#틀린-절)\n"
            "[private](../data/private/missing.md)\n"
            "[artifact](../artifacts/not-shared.png)\n"
            "[public evidence](../data/operations/missing.json)\n"
            "[empty anchor](templates/target.md#)\n"
            "[real heading](templates/target.md#검증-결과)\n"
            "```md\n[example](nonexistent.md)\n```\n",
        )
        self.write("progress/templates/target.md", "# 검증 결과\n")
        errors, optional = check_links(self.root, [source])
        self.assertEqual(optional, 2)
        self.assertEqual(len(errors), 4)
        self.assertTrue(any("missing heading" in error for error in errors))
        self.assertTrue(any("data/operations" in error for error in errors))
        self.assertTrue(any("empty heading" in error for error in errors))

    def test_references_must_use_canonical_records_instead_of_legacy_redirects(self):
        source = self.write(
            "docs/README.md",
            "[old](../progress/02-m08-source-review.md)\n"
            "[old task](../progress/01-mvp-tasks.md)\n"
            "[canonical](../progress/records/02-m08-source-review.md)\n",
        )
        self.write("progress/02-m08-source-review.md", "# Moved\n")
        self.write("progress/01-mvp-tasks.md", "# Moved tasks\n")
        self.write("progress/records/02-m08-source-review.md", "# Evidence\n")
        errors, _ = check_links(self.root, [source])
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("unsupported progress path" in error for error in errors))
        archived = self.write("progress/records/old.md", "[old task](../01-mvp-tasks.md)\n")
        self.assertIn("unsupported progress path", check_links(self.root, [archived])[0][0])

    def test_unreferenced_legacy_file_cannot_restore_old_structure(self):
        self.board()
        self.write("progress/10-local-redeploy-image-cleanup.md", "# Old redirect\n")
        errors = check_references(self.root, {})
        self.assertTrue(any("unsupported root document" in error for error in errors))

    def test_korean_punctuation_code_and_duplicate_heading_anchors(self):
        self.assertEqual(
            anchors("# M13. 챗봇·세션 초기화\n## `검증` 결과\n## 검증 결과\n## 검증 결과-1\n"),
            {"m13-챗봇세션-초기화", "검증-결과", "검증-결과-1", "검증-결과-1-1"},
        )

    def record(self, record_id="R001", filename="one.md", observed="2026-10-18"):
        return self.write(
            "progress/records/" + filename,
            f"# {record_id} evidence\n\n"
            f"> 기록 ID: {record_id} · 기준일: {observed} · 환경: local\n"
            "> 관계: scoped update\n\n## Result\nOriginal evidence.\n",
        )

    def board(self, extra=""):
        return self.write("progress/current-status.md", "# Current\n갱신: 2026-10-18\n" + extra)

    def test_new_record_is_discovered_without_manual_registration(self):
        first = self.record()
        before = first.read_bytes()
        errors, entries = check_records(self.root)
        self.assertEqual(errors, [])
        self.assertEqual(set(entries), {"R001"})
        self.assertIn("stale generated index", check_index(self.root, entries)[0])
        self.assertFalse((self.root / "progress/records/README.md").exists())
        self.assertEqual(check_index(self.root, entries, write=True), [])
        self.assertEqual(check_index(self.root, entries), [])
        self.record("R002", "two.md")
        _, entries = check_records(self.root)
        self.assertTrue(check_index(self.root, entries))
        check_index(self.root, entries, write=True)
        self.assertIn(
            "R002", (self.root / "progress/records/README.md").read_text(encoding="utf-8")
        )
        self.assertEqual(first.read_bytes(), before)

    def test_write_command_does_not_overwrite_index_when_sources_are_invalid(self):
        self.board()
        self.record()
        bad = self.record("R001", "duplicate.md")
        index = self.write("progress/records/README.md", "keep previous output\n")
        with (
            patch.object(check_progress, "ROOT", self.root),
            patch.object(sys, "argv", ["check_progress.py", "--write"]),
            patch.object(check_progress.subprocess, "run") as git,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            git.return_value.stdout = bad.relative_to(self.root).as_posix().encode() + b"\0"
            self.assertEqual(check_progress.main(), 1)
        self.assertIn("duplicate evidence ID", output.getvalue())
        self.assertEqual(index.read_text(encoding="utf-8"), "keep previous output\n")

    def test_index_is_deterministic_detects_manual_drift_and_supports_renames(self):
        self.board()
        self.write("progress/README.md", "# Progress guide\n")
        first = self.record()
        self.record("R002", "two.md")
        _, entries = check_records(self.root)
        check_index(self.root, entries, write=True)
        index = self.root / "progress/records/README.md"
        original = index.read_bytes()
        check_index(self.root, dict(reversed(list(entries.items()))), write=True)
        self.assertEqual(index.read_bytes(), original)
        index.write_text("manual edit", encoding="utf-8")
        self.assertTrue(check_index(self.root, entries))
        self.assertEqual(index.read_text(encoding="utf-8"), "manual edit")  # CI checks never write.
        first.rename(first.with_name("renamed.md"))
        _, entries = check_records(self.root)
        check_index(self.root, entries, write=True)
        self.assertIn("(renamed.md)", index.read_text(encoding="utf-8"))
        self.assertEqual(check_links(self.root, [index])[0], [])

    def test_duplicate_id_missing_metadata_and_invalid_date_are_rejected(self):
        self.record()
        self.record("R001", "duplicate.md")
        self.record("R002", "bad-date.md", "2026-02-30")
        self.write("progress/records/forgotten.md", "# No metadata\n")
        errors, _ = check_records(self.root)
        self.assertTrue(any("duplicate evidence ID" in error for error in errors))
        self.assertTrue(any("invalid observed date" in error for error in errors))
        self.assertTrue(any("forgotten.md" in error for error in errors))

    def test_wrong_evidence_label_is_rejected_even_when_the_file_exists(self):
        self.record()
        self.record("R002", "two.md")
        source = self.board("[R002](records/one.md)\n[R001](records/one.md#result)\n")
        _, entries = check_records(self.root)
        errors = check_evidence_labels(self.root, [source], entries)
        self.assertEqual(len(errors), 1)
        self.assertIn("R002 label points to wrong record", errors[0])

    def test_completed_task_without_proof_and_unknown_references_fail(self):
        self.board(
            "| T-M12-01 | 완료 | tested | QA | I-OPS-99 |\n"
            "| T-M12-02 | 대기 | next | QA | T-M12-99 |\n"
            "| M13 | 완료 R099 | no proof |\n"
        )
        errors = check_references(self.root, {})
        for expected in [
            "completion requires date and evidence",
            "unknown evidence ID R099",
            "unknown task ID T-M12-99",
            "unknown input ID I-OPS-99",
            "needs canonical evidence",
        ]:
            self.assertTrue(any(expected in error for error in errors), errors)

    def test_dependency_cycle_and_premature_completion_fail(self):
        self.record()
        self.board(
            "| T-M12-01 | 완료 | 2026-10-18 [R001](records/one.md) | QA | T-M12-02 |\n"
            "| T-M12-02 | 대기 | next | QA | T-M12-01 |\n"
        )
        _, entries = check_records(self.root)
        errors = check_references(self.root, entries)
        self.assertTrue(any("dependency cycle" in error for error in errors))
        self.assertTrue(any("completed before dependency" in error for error in errors))

    def test_completed_task_requires_real_date_not_before_evidence(self):
        self.record()
        _, entries = check_records(self.root)
        for completed, message in [
            ("2026-02-30", "completion requires date"),
            ("2026-10-17", "completion predates"),
        ]:
            with self.subTest(completed=completed):
                self.board(
                    "| I-OPS-01 | supplied | detail |\n"
                    f"| T-M12-01 | 완료 | {completed} [R001](records/one.md) | QA | I-OPS-01 |\n"
                )
                self.assertTrue(
                    any(message in error for error in check_references(self.root, entries))
                )

    def test_duplicate_tasks_inputs_and_second_task_source_fail(self):
        self.board(
            "| I-OPS-01 | supplied | detail |\n| I-OPS-01 | supplied | detail |\n"
            "| T-M12-01 | 대기 | work | QA | I-OPS-01 |\n"
            "| T-M12-01 | 대기 | work | QA | I-OPS-01 |\n"
        )
        self.write("progress/01-mvp-tasks.md", "| T-M12-01 | 대기 | work | QA | I-OPS-01 |\n")
        errors = check_references(self.root, {})
        for expected in ["duplicate task ID", "duplicate input ID", "task rows belong only"]:
            self.assertTrue(any(expected in error for error in errors), errors)

    def test_single_board_accepts_valid_completion_and_no_remaining_tasks(self):
        self.record()
        self.board(
            "| I-OPS-01 | supplied | detail |\n"
            "| T-M12-01 | 완료 | 2026-10-18 [R001](records/one.md) | QA | I-OPS-01 |\n"
        )
        _, entries = check_records(self.root)
        self.assertEqual(check_references(self.root, entries), [])
        self.board("남은 작업 없음.\n")
        self.assertEqual(check_references(self.root, entries), [])


if __name__ == "__main__":
    unittest.main()
