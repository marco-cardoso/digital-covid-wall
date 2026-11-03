"""Tests for collecting the OCR'd names from the heart JSON files."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from import_victims import collect_names  # noqa: E402


def test_collect_names_dedupes_in_first_seen_order(tmp_path):
    (tmp_path / 'a.json').write_text(json.dumps({'names': [' Ann Lee ', '', 'Bob']}), encoding='utf-8')
    (tmp_path / 'b.json').write_text(json.dumps({'names': ['Bob', 'ann lee', None]}), encoding='utf-8')
    assert collect_names(tmp_path) == ['Ann Lee', 'Bob', 'ann lee']


def test_collect_names_skips_broken_files(tmp_path):
    (tmp_path / 'a.json').write_text('{not json', encoding='utf-8')
    (tmp_path / 'b.json').write_text(json.dumps({'names': ['Bob']}), encoding='utf-8')
    assert collect_names(tmp_path) == ['Bob']
