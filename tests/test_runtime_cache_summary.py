"""Cache status traverses a directory once while preserving all metrics."""
import os
from pathlib import Path
from unittest.mock import patch
from lingshu_gate.runtime_cache_management import _cache_info


def test_cache_metrics_use_one_walk(tmp_path: Path) -> None:
    nested = tmp_path / 'nested'
    nested.mkdir()
    (tmp_path / 'first').write_bytes(b'abc')
    (nested / 'second').write_bytes(b'12345')
    for item in (tmp_path, nested, tmp_path / 'first', nested / 'second'):
        os.utime(item, (1000000000, 1000000000))
    original = Path.rglob
    with patch.object(Path, 'rglob', autospec=True, side_effect=original) as walk:
        result = _cache_info('npm', tmp_path)
    assert walk.call_count == 1
    assert result['file_count'] == 2
    assert result['size_bytes'] == 8
    assert result['last_modified_at'] == '2001-09-09T01:46:40+00:00'


def test_missing_empty_and_file_cache_paths(tmp_path: Path) -> None:
    assert _cache_info('npm', tmp_path / 'missing')['last_modified_at'] is None
    assert _cache_info('npm', tmp_path)['file_count'] == 0
    assert _cache_info('npm', tmp_path)['last_modified_at'] is not None
    item = tmp_path / 'file'
    item.write_bytes(b'abc')
    info = _cache_info('npm', item)
    assert info['file_count'] == info['size_bytes'] == 0
    assert info['last_modified_at'] is not None
