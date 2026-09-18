"""Independent regressions: productivity requires content changes, not timestamps."""
import os
import subprocess

from switchbay import ce_host
from switchbay.agents import orchestration


def _fixture(tmp_path):
    wiki = tmp_path / 'wiki'
    wiki.mkdir()
    page = wiki / 'fixture.md'
    page.write_text('# Fixture\n\nSource fact A.\n')
    def git(*args):
        subprocess.run(['git', '-C', str(wiki), *args], check=True, capture_output=True)
    git('init')
    git('config', 'user.name', 'Fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    git('add', '.')
    git('commit', '-m', 'Fixture baseline')
    return page, git


def test_unchanged_page_rewrite_is_not_productive_work(tmp_path):
    page, _ = _fixture(tmp_path)
    before = ce_host.wiki_work_snapshot(tmp_path)
    original = page.read_text()
    stamp = page.stat().st_mtime_ns
    page.write_text(original)
    os.utime(page, ns=(stamp + 1_000_000_000, stamp + 1_000_000_000))
    receipt = ce_host.wiki_diff_receipt(tmp_path, before)
    assert receipt['wiki_pages_landed'] == 0, 'mtime alone must not count as work'
    assert not receipt['wiki_pages_changed']
    assert not orchestration._receipt_had_work(receipt)


def test_same_size_content_edit_survives_preserved_mtime(tmp_path):
    page, _ = _fixture(tmp_path)
    before = ce_host.wiki_work_snapshot(tmp_path)
    stamp = page.stat()
    page.write_text(page.read_text().replace('fact A', 'fact B'))
    os.utime(page, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    receipt = ce_host.wiki_diff_receipt(tmp_path, before)
    assert receipt['wiki_pages_landed'] == 1, 'Actual content changes must not be discarded'
    assert 'wiki/fixture.md' in receipt['wiki_pages_changed']
    assert orchestration._receipt_had_work(receipt)


def test_empty_commit_does_not_reset_no_work_detection(tmp_path):
    _, git = _fixture(tmp_path)
    before = ce_host.wiki_work_snapshot(tmp_path)
    git('commit', '--allow-empty', '-m', 'No content change')
    receipt = ce_host.wiki_diff_receipt(tmp_path, before)
    assert not receipt['wiki_pages_changed']
    assert not receipt['wiki_commit_diff']
    assert not orchestration._receipt_had_work(receipt), 'An empty commit is not useful curation'
