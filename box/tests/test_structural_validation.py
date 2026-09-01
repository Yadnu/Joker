"""test_structural_validation.py

A fully compliant tree reports zero violations.
A tree with a single-drawer cabinet, a single-file drawer, and a single-joke
file reports all three violations, each with the correct level, path, and
child_count.
"""

import pytest
from box.tests.helpers import joke_payload


@pytest.mark.asyncio
async def test_compliant_tree_zero_violations(client):
    """A tree with 2+ children at every level is compliant."""
    # 1 cabinet, 2 drawers, 2 files each, 2 jokes each
    base = "CompliantCab"
    for drw in ["CplDrw1", "CplDrw2"]:
        for fil in ["CplFil1", "CplFil2"]:
            for pos in [1, 2]:
                p = joke_payload(
                    cabinet=base, drawer=drw, file=fil, position=pos,
                    joke_text=f"Compliant joke {drw}/{fil}/{pos}",
                )
                r = await client.put("/box/upsert", json=p)
                assert r.status_code == 201

    r = await client.get("/compliance")
    assert r.status_code == 200
    data = r.json()

    # Filter violations to only our test cabinet to avoid interference
    our_violations = [
        v for v in data["violations"]
        if base in v.get("path", "")
    ]
    assert our_violations == [], f"Unexpected violations: {our_violations}"


@pytest.mark.asyncio
async def test_non_compliant_tree_reports_all_three_levels(client):
    """A tree with exactly 1 child at each level reports 3 violations."""
    # 1 cabinet with 1 drawer, 1 drawer with 1 file, 1 file with 1 joke
    cab = "SingletonCab"
    drw = "SingletonDrw"
    fil = "SingletonFile"

    p = joke_payload(cabinet=cab, drawer=drw, file=fil, position=1,
                     joke_text="The lone joke.")
    r = await client.put("/box/upsert", json=p)
    assert r.status_code == 201

    r2 = await client.get("/compliance")
    assert r2.status_code == 200
    violations = r2.json()["violations"]

    # Filter to our cabinet
    ours = [v for v in violations if cab in v.get("path", "")]
    assert len(ours) >= 3, f"Expected 3 violations, got: {ours}"

    levels_found = {v["level"] for v in ours}
    assert "cabinet" in levels_found
    assert "drawer" in levels_found
    assert "file" in levels_found

    for v in ours:
        assert v["child_count"] == 1
        assert v["path"]  # path must be non-empty


@pytest.mark.asyncio
async def test_violation_body_names_correct_level(client):
    """Each violation names the failing level explicitly."""
    cab = "ViolCab"
    drw = "ViolDrw"
    fil = "ViolFile"

    p = joke_payload(cabinet=cab, drawer=drw, file=fil)
    await client.put("/box/upsert", json=p)

    r = await client.get("/compliance")
    violations = [v for v in r.json()["violations"] if cab in v.get("path", "")]

    for v in violations:
        assert v["level"] in ("cabinet", "drawer", "file")
        assert "reason" in v
        assert v["level"] in v["reason"].lower() or v["path"].split(" > ")[0] in v["reason"]
