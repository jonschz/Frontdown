from typing import Union
import pytest

from Frontdown.statistics_module import sizeof_fmt


strOutputs = [
    (0, '  0 B'),
    (-1, ' -1 B'),
    (10, ' 10 B'),
    (-10, '-10 B'),
    (500, '500 B'),
    (-500, '-500 B'),
    (100.4, '100 B'),
    (1024, '1.0 KiB'),
    (1024**2, '1.0 MiB'),
    (1024*1023.95, '1.0 MiB'),
    (1024*1023.94, '1023.9 KiB'),
]


@pytest.mark.parametrize("numBytes,expected", strOutputs)
def test_one_sizeof_fmt(numBytes: Union[int, float], expected: str):
    assert sizeof_fmt(numBytes) == expected


def test_sizeof_fmt_params():
    assert sizeof_fmt(1024**3, suffix='Byte') == '1.0 GiByte'
    assert sizeof_fmt(float(1024**3), suffix='Byte') == '1.0 GiByte'
