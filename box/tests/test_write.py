"""test_write.py

POST (PUT /box/upsert) a joke with all ten fields populated.
GET it back by id.
Assert every field round-trips unchanged including nested provenance
and prompt_responses.
"""

import pytest
from box.tests.helpers import joke_payload


@pytest.mark.asyncio
async def test_round_trip_all_fields(client):
    payload = joke_payload(
        cabinet="Technology",
        drawer="Software",
        file="Debugging",
        category="Observational",
        score=8,
        joke_text="Why do Java developers wear glasses? Because they don't C#.",
        user_reaction="Groaned and laughed.",
    )

    # Write
    r = await client.put("/box/upsert", json=payload)
    assert r.status_code == 201, r.text
    joke_id = r.json()["joke_id"]

    # Read back
    r2 = await client.get(f"/jokes/{joke_id}")
    assert r2.status_code == 200, r2.text
    got = r2.json()

    j = payload["joke"]

    # Scalar fields
    assert got["joke_text"] == j["joke_text"]
    assert got["user_reaction"] == j["user_reaction"]
    assert got["score"] == j["score"]
    assert got["category"] == j["category"]
    assert got["user_context"] == j["user_context"]

    # Nested: prompt_responses
    assert got["prompt_responses"] == j["prompt_responses"]

    # Nested: provenance
    assert got["provenance"]["source"] == j["provenance"]["source"]
    assert got["provenance"]["model"] == j["provenance"]["model"]
    assert got["provenance"]["prompt"] == j["provenance"]["prompt"]
    assert got["provenance"]["selection_rationale"] == j["provenance"]["selection_rationale"]

    # Nested: metadata
    assert got["metadata"]["topic"] == j["metadata"]["topic"]
    assert got["metadata"]["style"] == j["metadata"]["style"]
    assert got["metadata"]["length"] == j["metadata"]["length"]
    assert got["metadata"]["sensitivity_flags"] == j["metadata"]["sensitivity_flags"]

    # Nested: attribution
    assert got["attribution"]["joker"] == j["attribution"]["joker"]
    assert got["attribution"]["account"] == j["attribution"]["account"]

    # Nested: set_id
    assert got["set_id"]["set"] == j["set_id"]["set"]
    assert got["set_id"]["position"] == j["set_id"]["position"]
