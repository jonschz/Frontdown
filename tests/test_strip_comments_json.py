import pytest
import json
from Frontdown.strip_comments_json import json_minify


# TODO fix implementation, expand test cases
@pytest.mark.skip("Needs implementation fixes")
def test_strip_comments_json():
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
