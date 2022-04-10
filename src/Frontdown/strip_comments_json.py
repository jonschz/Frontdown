"""Slightly modified, original description below:

A port of the `JSON-minify` utility to the Python language.

Based on JSON.minify.js: https://github.com/getify/JSON.minify

Contributers:
  - Gerald Storer
    - Contributed original version
  - Felipe Machado
    - Performance optimization
  - Pradyun S. Gedam
    - Conditions and variable names changed
    - Reformatted tests and moved to separate file
    - Made into a PyPI Package
"""

import re
import json
from typing import Any, TextIO


def json_minify(string: str, strip_space: bool = True) -> str:
    """
        Deletes line and block comments in a json string. If strip_space is set to True,
        line breaks and space is also removed.
    """
    # A literal * must be escaped in a regex, so we need a literal backslash in the regex,
    # represented by  \\. Raw strings cannot be used because we also need \n and \r
    tokenizer = re.compile('"|(/\\*)|(\\*/)|(//)|\n|\r')
    end_slashes_re = re.compile(r'(\\)*$')

    in_string = False
    in_multi = False
    in_single = False

    new_str = []
    index = 0

    for match in re.finditer(tokenizer, string):

        # remove whitespace outside of comments,
        if not (in_multi or in_single):
            tmp = string[index:match.start()]
            if not in_string and strip_space:
                # replace white space as defined in standard
                tmp = re.sub('[ \t\n\r]+', '', tmp)
            new_str.append(tmp)

        index = match.end()
        val = match.group()

        if val == '"' and not (in_multi or in_single):
            escaped = end_slashes_re.search(string, 0, match.start())

            # start of string or unescaped quote character to end string
            if not in_string or (escaped is None or len(escaped.group()) % 2 == 0):  # noqa
                in_string = not in_string
            index -= 1  # include " character in next catch
        elif not (in_string or in_multi or in_single):
            if val == '/*':
                in_multi = True
            elif val == '//':
                in_single = True
            # Added to preserve line breaks
            elif (val in '\r\n') and not strip_space:
                new_str.append(val)
        elif val == '*/' and in_multi and not (in_string or in_single):
            in_multi = False
        elif val in '\r\n' and not (in_multi or in_string) and in_single:
            in_single = False
            # Added to preserve line breaks
            if not strip_space:
                new_str.append(val)
        elif not ((in_multi or in_single) or (val in ' \r\n\t' and strip_space)):  # noqa
            new_str.append(val)

    new_str.append(string[index:])
    return ''.join(new_str)


# A JSON text may be any JSON value, see https://stackoverflow.com/a/3833312/ ,
# thus a return type of Union[dict[str, object], list[object]] is too restrictive.
# Type hinting kwargs still acts up quite a bit, so Any is the best way to go here
def loads(string: str, **kwargs: Any) -> object:
    return json.loads(json_minify(string, strip_space=True), **kwargs)


def load(file: TextIO, **kwargs: Any) -> object:
    return loads(file.read(), **kwargs)


def dumps(obj: object, **kwargs: Any) -> str:
    return json.dumps(obj, **kwargs)


def dump(obj: object, file: TextIO, **kwargs: Any) -> None:
    json.dump(obj, file, **kwargs)
