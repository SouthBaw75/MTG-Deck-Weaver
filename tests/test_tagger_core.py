"""Core framework tests: CardView normalization, taxonomy, override plumbing."""

import textwrap

from weaver.knowledge.cardview import CardView, cheaper_is_better
from weaver.knowledge.taxonomy import TAGS, category_of, is_valid_tag


def _cv(**kw):
    base = dict(name="Test Card", type_line="Creature — Human Wizard", oracle_text="")
    base.update(kw)
    return CardView.from_dict(base)


def test_reminder_text_stripped():
    cv = _cv(oracle_text="Deathtouch (Any amount of damage this deals to a creature is enough to destroy it.)")
    assert "(" not in cv.text
    assert "deathtouch" in cv.text_lower


def test_self_reference_normalized():
    cv = _cv(
        name="Yuriko, the Tiger's Shadow",
        oracle_text="Whenever Yuriko, the Tiger's Shadow deals combat damage, draw. Return Yuriko to the command zone.",
    )
    assert "Yuriko" not in cv.text
    assert cv.text.count("~") == 2


def test_type_line_parsing():
    cv = _cv(type_line="Legendary Snow Creature — Elf Druid")
    assert cv.supertypes == {"legendary", "snow"}
    assert cv.types == {"creature"}
    assert cv.subtypes == {"elf", "druid"}
    assert cv.is_creature and cv.is_permanent and not cv.is_land


def test_multiface_type_line():
    cv = _cv(type_line="Instant // Sorcery")
    assert cv.types == {"instant", "sorcery"}
    assert not cv.is_permanent


def test_lines_split():
    cv = _cv(oracle_text=textwrap.dedent("""\
        Flying
        {T}: Add {G}.
        //
        Draw a card."""))
    assert len(cv.lines) == 3


def test_instant_speed_via_flash():
    assert _cv(keywords=["Flash"]).is_instant_speed
    assert _cv(type_line="Instant").is_instant_speed
    assert not _cv(type_line="Sorcery").is_instant_speed


def test_taxonomy_shape():
    assert len(TAGS) > 40
    assert is_valid_tag("ramp.rock") and not is_valid_tag("nonsense.tag")
    assert category_of("ramp.rock") == "mana"


def test_cheaper_is_better_bounds():
    assert cheaper_is_better(0) == 1.0
    assert cheaper_is_better(1) == 1.0
    assert cheaper_is_better(9) == 0.3
    assert 0.3 < cheaper_is_better(4) < 1.0


def test_override_application(tmp_path):
    from weaver.knowledge.tagger import _apply_overrides, load_overrides
    from weaver.knowledge.cardview import TagHit

    (tmp_path / "tag_overrides.yaml").write_text(
        textwrap.dedent("""\
        - card: Ashnod's Altar
          add:
            - tag: sac-outlet
              quality: 0.95
          remove:
            - ramp.rock
          quality:
            token-producer: 0.4
        """)
    )
    overrides = load_overrides(tmp_path)
    hits = {
        "ramp.rock": TagHit("ramp.rock", 0.8, "adds {C}{C}"),
        "token-producer": TagHit("token-producer", 0.9, "x"),
    }
    assert _apply_overrides("Ashnod's Altar", hits, overrides)
    assert "ramp.rock" not in hits
    assert hits["sac-outlet"].quality == 0.95
    assert hits["token-producer"].quality == 0.4
    assert not _apply_overrides("Sol Ring", hits, overrides)
