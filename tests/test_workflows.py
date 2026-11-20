from app.workflows import _extract_json


def test_extract_json_object_containing_arrays():
    result = _extract_json(
        'Result:\n{"decisions":["Stock bangles"],'
        '"actions":[{"task":"Post on Instagram","owner":"Bhavana"}],'
        '"open":[]}'
    )

    assert result == {
        "decisions": ["Stock bangles"],
        "actions": [{"task": "Post on Instagram", "owner": "Bhavana"}],
        "open": [],
    }


def test_extract_json_top_level_array():
    result = _extract_json('Plan:\n[{"activity":"Study"}]\nDone.')

    assert result == [{"activity": "Study"}]