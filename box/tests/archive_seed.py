"""Archive seeding for Librarian/Joker tests. Never a singleton child at any level."""

from __future__ import annotations

from box.schema.models import Cabinet, Drawer, File, Joke


def _joke(
    *,
    file_id: str,
    category: str,
    score: int,
    text: str,
    position: int,
) -> Joke:
    return Joke(
        file_id=file_id,
        prompt_responses=[{"role": "assistant", "content": text}],
        joke_text=text,
        user_reaction="ha",
        score=score,
        category=category,
        joke_metadata={
            "topic": "travel",
            "style": "one-liner",
            "length": "short",
            "sensitivity_flags": [],
        },
        user_context={"occupation_field": "tech"},
        attribution={"joker": "joker-v1", "account": "acct_test"},
        provenance={
            "source": "generated",
            "model": "gpt-4o-mini",
            "prompt": "tell a joke",
            "selection_rationale": "seed",
        },
        set_id={"set": "seed_set", "position": position},
    )


async def seed_two_genres(session) -> None:
    """Two cabinets, two drawers each, two files each, two jokes each.

    High scorers live under AirportSecurity; ThinOffice has exactly two jokes
    (thin coverage is < 3, but still more than one child).
    """
    cab_a = Cabinet(label="Travel")
    cab_b = Cabinet(label="Work")
    session.add_all([cab_a, cab_b])
    await session.flush()

    dr_a1 = Drawer(label="Airports", cabinet_id=cab_a.id)
    dr_a2 = Drawer(label="Hotels", cabinet_id=cab_a.id)
    dr_b1 = Drawer(label="Office", cabinet_id=cab_b.id)
    dr_b2 = Drawer(label="Meetings", cabinet_id=cab_b.id)
    session.add_all([dr_a1, dr_a2, dr_b1, dr_b2])
    await session.flush()

    f_sec = File(label="AirportSecurity", drawer_id=dr_a1.id)
    f_bag = File(label="BaggageClaim", drawer_id=dr_a1.id)
    f_hot1 = File(label="CheckIn", drawer_id=dr_a2.id)
    f_hot2 = File(label="RoomService", drawer_id=dr_a2.id)
    f_off1 = File(label="ThinOffice", drawer_id=dr_b1.id)
    f_off2 = File(label="Printers", drawer_id=dr_b1.id)
    f_mt1 = File(label="Standups", drawer_id=dr_b2.id)
    f_mt2 = File(label="Slack", drawer_id=dr_b2.id)
    session.add_all([f_sec, f_bag, f_hot1, f_hot2, f_off1, f_off2, f_mt1, f_mt2])
    await session.flush()

    jokes = [
        _joke(file_id=f_sec.id, category="AirportSecurity", score=9, text="TSA packed bags bit", position=1),
        _joke(file_id=f_sec.id, category="AirportSecurity", score=8, text="Shoes off again bit", position=2),
        _joke(file_id=f_bag.id, category="BaggageClaim", score=7, text="Carousel conspiracy", position=1),
        _joke(file_id=f_bag.id, category="BaggageClaim", score=6, text="Black suitcase identical", position=2),
        _joke(file_id=f_hot1.id, category="CheckIn", score=5, text="Loyalty points joke", position=1),
        _joke(file_id=f_hot1.id, category="CheckIn", score=4, text="ID still required", position=2),
        _joke(file_id=f_hot2.id, category="RoomService", score=5, text="Club sandwich midnight", position=1),
        _joke(file_id=f_hot2.id, category="RoomService", score=4, text="Ice machine pilgrimage", position=2),
        _joke(file_id=f_off1.id, category="ThinOffice", score=4, text="Hot desk lottery", position=1),
        _joke(file_id=f_off1.id, category="ThinOffice", score=3, text="Standing desk guilt", position=2),
        _joke(file_id=f_off2.id, category="Printers", score=5, text="PC load letter", position=1),
        _joke(file_id=f_off2.id, category="Printers", score=5, text="Paper jam theatre", position=2),
        _joke(file_id=f_mt1.id, category="Standups", score=6, text="Yesterday I blocked myself", position=1),
        _joke(file_id=f_mt1.id, category="Standups", score=5, text="No blockers except this meeting", position=2),
        _joke(file_id=f_mt2.id, category="Slack", score=6, text="Thread that should have been a huddle", position=1),
        _joke(file_id=f_mt2.id, category="Slack", score=5, text="Emoji as performance review", position=2),
    ]
    session.add_all(jokes)
    await session.flush()
