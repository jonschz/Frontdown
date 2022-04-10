from pathlib import Path
import pytest

from Frontdown.file_methods import is_excluded, compare_pathnames


def test_is_excluded():
    # TODO more test cases
    testpaths = [Path("./abc/def"), Path(".\\abc\\def")]
    testrules = [["abc/def"], ["abc\\def"]]
    for path in testpaths:
        for rule in testrules:
            assert is_excluded(path, rule)


comparisons = [
    ("abc", "abd", -1),
    ("abc", "abc/a", -1),
    ("abc/def/ghi", "abc/def/ghi", 0),
    ("zyx/wvu/trs", "zyx/wvu/trs", 0),
    ("abc/def/ghi", "abc/eef/ghi", -1),
    ("abc/def", "abc/def/ghi", -1),
    ("abc/def/gh", "abc/def/ghi", -1),
    ("abc/abc", "abc\\abc", 0),
    # this test fails for locale.strcoll()
    ("abc/abc", "abc abc", -1)
]
# turn all list entries into paths
comparisons = list(map(lambda x: (Path(x[0]), Path(x[1]), x[2]), comparisons))


@pytest.mark.parametrize("p0,p1,expected", comparisons)
def test_one_comparison(p0: Path, p1: Path, expected: int):
    assert compare_pathnames(p0, p1) == expected
    assert compare_pathnames(p1, p0) == -expected


if __name__ == '__main__':
    test_is_excluded()
    # TODO: Integration test: take some folder structure, run relativeWalk, verify it is sorted w.r.t. compare_pathnames
    print("Test successful")
