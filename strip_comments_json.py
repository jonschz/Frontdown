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


def json_minify(string, strip_space=True):
    tokenizer = re.compile('"|(/\*)|(\*/)|(//)|\n|\r')
    end_slashes_re = re.compile(r'(\\)*$')

    in_string = False
    in_multi = False
    in_single = False

    new_str = []
    index = 0

    for match in re.finditer(tokenizer, string):

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
            elif val in '\r\n':		# This line added to preserve line breaks
                new_str.append(val)
        elif val == '*/' and in_multi and not (in_string or in_single):
            in_multi = False
        elif val in '\r\n' and not (in_multi or in_string) and in_single:
            in_single = False
            new_str.append(val)		# This line added to preserve line breaks
        elif not ((in_multi or in_single) or (val in ' \r\n\t' and strip_space)):  # noqa
            new_str.append(val)

    new_str.append(string[index:])
    return ''.join(new_str)

def loads(string, **kwargs):
    return json.loads(json_minify(string, False), **kwargs)

def load(file, **kwargs):
    return loads(file.read(), **kwargs)

def dumps(obj, **kwargs):
    return json.dumps(obj, **kwargs)

def dump(obj, file, **kwargs):
    return json.dump(obj, file, **kwargs)

# Testing routine
if __name__ == '__main__':
    with open("test-setup.json", encoding="utf-8") as exampleFile:
        with open("stripped.json", "w", encoding="utf-8") as outFile:
            outFile.write(json_minify(exampleFile.read(), False))