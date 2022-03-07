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
import typing

def json_minify(string: str, strip_space=True) -> str:
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


# A JSON text may be any JSON value, see https://stackoverflow.com/a/3833312/
# Thus a return type of Union[dict[str, object], list[object]] is too restrictive
def loads(string: str, **kwargs) -> object:
    return json.loads(json_minify(string, strip_space=True), **kwargs)

def load(file: typing.TextIO, **kwargs) -> object:
    return loads(file.read(), **kwargs)

def dumps(obj, **kwargs) -> str:
    return json.dumps(obj, **kwargs)

def dump(obj, file, **kwargs) -> None:
    json.dump(obj, file, **kwargs)

# Testing routine
if __name__ == '__main__':
    # from https://stackoverflow.com/a/25851972/10666668
    # compare two dicts: orderNestedDicts(a) == orderNestedDicts(b)
    def orderNestedDicts(obj):
        if isinstance(obj, dict):
            return sorted((k, orderNestedDicts(v)) for k, v in obj.items())
        if isinstance(obj, list):
            return sorted(orderNestedDicts(x) for x in obj)
        else:
            return obj
        
    # First test: valid json, idempocy
    with open("default.config.json", encoding="utf-8") as exampleFile:
        originalJSONasStr = exampleFile.read()
        minifiedStrWithWhitespace = json_minify(originalJSONasStr, strip_space=False)
        minifiedStr = json_minify(originalJSONasStr, strip_space=True)
        with open("./integration_test_setup/stripped_whitespace.json", "w", encoding="utf-8") as outFile:
            outFile.write(minifiedStrWithWhitespace)
        with open("./integration_test_setup/stripped_compact.json", "w", encoding="utf-8") as outFile:
            outFile.write(minifiedStr)
        # check if both are valid json
        json.loads(minifiedStrWithWhitespace)
        json.loads(minifiedStr)
        # idempocy
        assert minifiedStrWithWhitespace == json_minify(minifiedStrWithWhitespace, strip_space=False)
        assert minifiedStr == json_minify(minifiedStr, strip_space=True)
        # verify semantic equivalence
        print("First test successful")
    
        # TODO Second test: open a json file without comments but with whitespace,
        # compare content of json.loads(...) with loads(...)
    