"""Tests for turning the heart-detection manifest into the dashboard's per-photo counts."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from import_hearts import collect_photos, shot_date  # noqa: E402


def test_shot_date_reads_the_day_from_the_file_name():
    assert shot_date('PXL_20230730_084939539.jpg') == '2023-07-30'
    assert shot_date('PXL_20230821_142046377 - Copy.jpg') == '2023-08-21'
    assert shot_date('holiday.jpg') == ''


def test_collect_photos_follows_the_wall_and_drops_the_rest():
    manifest = {
        'per_photo': [
            {'photo': 'PXL_20230730_000001000.jpg', 'hearts_detected': 200, 'hearts_with_writing': 80},
            {'photo': 'PXL_20230813_000002000 - Copy.jpg', 'hearts_detected': 150, 'hearts_with_writing': 90},   # not on the wall
            {'photo': 'PXL_20230820_000003000.jpg', 'hearts_detected': 300, 'hearts_with_writing': 60},
        ]
    }
    wall = {
        'photos': [
            {'x': 5000, 'number': 2, 'file': 'PXL_20230820_000003000.jpg'},
            {'x': 0, 'number': 1, 'file': 'PXL_20230730_000001000.jpg'},
        ]
    }

    assert collect_photos(manifest, wall) == [
        {'number': 1, 'date': '2023-07-30', 'hearts': 200, 'writing': 80},
        {'number': 2, 'date': '2023-08-20', 'hearts': 300, 'writing': 60},
    ]


def test_a_wall_photo_the_manifest_never_saw_has_no_hearts():
    wall = {'photos': [{'x': 0, 'number': 1, 'file': 'PXL_20230730_000001000.jpg'}]}
    assert collect_photos({}, wall) == [{'number': 1, 'date': '2023-07-30', 'hearts': 0, 'writing': 0}]
