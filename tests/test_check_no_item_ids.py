"""The pre-commit guard that keeps raw eBay item IDs out of the public repo.

Codex review, finding 4: if the step that strips item_ids failed, the workflow
carried on and committed them. The strip step now fails closed, and
scripts/check_no_item_ids.py checks the staged files again right before the
commit. These tests pin that check.

Run: pytest tests/test_check_no_item_ids.py
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_no_item_ids as guard  # noqa: E402


def test_finds_key_at_any_depth():
    obj = {"c1": {"active_listings": 3, "item_ids": ["a"]}, "c2": [{"x": {"item_ids": []}}]}
    assert guard.find_key_paths(obj) == ["$.c1.item_ids", "$.c2[0].x.item_ids"]


def test_clean_snapshot_passes():
    snap = {"c1": {"active_listings": 3, "avg_price": 10.0, "est_sold": 1}}
    assert guard.check_blob("data/snapshots/ebay-2026-09-26.json", json.dumps(snap).encode()) == []


def test_snapshot_with_ids_fails():
    snap = {"c1": {"active_listings": 3, "item_ids": ["v1|123|0"]}}
    problems = guard.check_blob("data/snapshots/ebay-2026-09-26.json", json.dumps(snap).encode())
    assert len(problems) == 1 and "item_ids" in problems[0]


def test_empty_id_list_still_fails():
    """The key itself is the leak signal, even when the list is empty."""
    snap = {"c1": {"active_listings": 0, "item_ids": []}}
    assert guard.check_blob("data/snapshots/ebay-2026-09-26.json", json.dumps(snap).encode())


def test_unparseable_json_with_key_fails():
    assert guard.check_blob("docs/data/x.json", b'{"c1": {"item_ids": ["a"]')


def test_unparseable_json_without_key_passes():
    assert guard.check_blob("docs/data/x.json", b'{"c1": ') == []


def test_non_json_files_are_ignored():
    assert guard.check_blob("collectors/ebay.py", b'row["item_ids"] = ids') == []


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_main_reads_the_staged_copy(tmp_path, monkeypatch, capsys):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    snap = tmp_path / "ebay-2026-09-26.json"
    monkeypatch.chdir(tmp_path)

    # Clean file staged -> exit 0.
    snap.write_text(json.dumps({"c1": {"active_listings": 3}}))
    _git(tmp_path, "add", snap.name)
    assert guard.main() == 0

    # IDs staged -> exit 1, even after the working-tree copy is cleaned, because
    # the staged copy is what would be committed.
    snap.write_text(json.dumps({"c1": {"active_listings": 3, "item_ids": ["a", "b"]}}))
    _git(tmp_path, "add", snap.name)
    snap.write_text(json.dumps({"c1": {"active_listings": 3}}))
    assert guard.main() == 1
    assert "Refusing to commit" in capsys.readouterr().err

    # Re-stage the clean copy -> exit 0 again.
    _git(tmp_path, "add", snap.name)
    assert guard.main() == 0
