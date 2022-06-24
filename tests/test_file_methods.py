from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
import pytest

from Frontdown.file_methods import is_excluded, compare_pathnames


def test_is_excluded():
    # TODO more test cases
    testpaths = [Path("./abc/def"), Path(".\\abc\\def")]
    testrules = [["abc/def"], ["abc\\def"]]
    for path in testpaths:
        for rule in testrules:
            assert is_excluded(path, rule)


sharedComparisonList = [
    ("abc", "abd", -1),
    ("abc", "abc/a", -1),
    ("abc/def/ghi", "abc/def/ghi", 0),
    ("zyx/wvu/trs", "zyx/wvu/trs", 0),
    ("abc/def/ghi", "abc/eef/ghi", -1),
    ("abc/def", "abc/def/ghi", -1),
    ("abc/def/gh", "abc/def/ghi", -1),
    # this test fails for locale.strcoll()
    ("abc/abc", "abc abc", -1)
]

windowsComparisonList = sharedComparisonList + [("abc/abc", "abc\\abc", 0)]
posixComparisonList = sharedComparisonList

# turn all list entries into PureWindowsPaths and PurePosixPaths
comparisons: list[tuple[PurePath, PurePath, int]] = list(
    map(lambda x: (PureWindowsPath(x[0]), PureWindowsPath(x[1]), x[2]), windowsComparisonList))
comparisons += list(
    map(lambda x: (PurePosixPath(x[0]), PurePosixPath(x[1]), x[2]), posixComparisonList))


@pytest.mark.parametrize("p0,p1,expected", comparisons)
def test_one_comparison(p0: Path, p1: Path, expected: int):
    assert compare_pathnames(p0, p1) == expected
    assert compare_pathnames(p1, p0) == -expected
