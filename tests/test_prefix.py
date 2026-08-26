import pytest

from hammunition_hill.prefix import PrefixTable, base_call

CTY_SAMPLE = """United States:            05:  08:  NA:   37.53:    91.67:     5.0:  K:
    AA,AB,AC,AK,K,N,W,=W1AW/4;
Germany:                  14:  28:  EU:   51.00:   -10.00:    -1.0:  DL:
    DA,DB,DL,DK,DJ;
Japan:                    25:  45:  AS:   36.00:  -138.00:    -9.0:  JA:
    JA,JE,JF,JH,7K;
"""


@pytest.fixture
def cty(tmp_path):
    path = tmp_path / "cty.dat"
    path.write_text(CTY_SAMPLE)
    return PrefixTable(path)


# --- callsign normalization --------------------------------------------
@pytest.mark.parametrize("call,expected", [
    ("W1AW", "W1AW"),
    ("W1AW/P", "W1AW"),      # portable says nothing about location
    ("W1AW/QRP", "W1AW"),
    ("W1AW/4", "W1AW"),      # a district within the same entity
    ("DL/W1AW", "DL"),       # prefix qualifier: the operator is in Germany
    ("W1AW/DL", "DL"),       # suffix qualifier, same meaning
    ("VP2E/W1AW/P", "VP2E"),
])
def test_base_call(call, expected):
    assert base_call(call) == expected


def test_base_call_is_case_insensitive():
    assert base_call("dl/w1aw") == "DL"


# --- cty.dat ------------------------------------------------------------
def test_cty_is_used_when_available(cty):
    assert not cty.approximate


def test_cty_lookup(cty):
    entity = cty.lookup("W1AW")
    assert entity.name == "United States"
    assert entity.continent == "NA"
    assert entity.cq_zone == 5


def test_cty_longitude_sign_is_flipped(cty):
    """cty.dat records west longitude as positive; everyone else does not."""
    assert cty.lookup("W1AW").lon == pytest.approx(-91.67)
    assert cty.lookup("DL1ABC").lon == pytest.approx(10.00)


def test_cty_exact_call_override_wins(cty):
    assert cty.lookup("W1AW/4").name == "United States"


def test_cty_aliases_resolve(cty):
    assert cty.lookup("DK5XY").name == "Germany"
    assert cty.lookup("7K1ABC").name == "Japan"


def test_unreadable_cty_falls_back(tmp_path):
    bad = tmp_path / "missing.dat"
    table = PrefixTable(bad)
    assert table.approximate
    assert table.lookup("W1AW") is not None


# --- built-in fallback --------------------------------------------------
@pytest.fixture
def builtin():
    return PrefixTable(None)


def test_builtin_is_marked_approximate(builtin):
    assert builtin.approximate
    assert builtin.lookup("W1AW").approximate is True


@pytest.mark.parametrize("call,name,continent", [
    ("W1AW", "United States", "NA"),
    ("KH6ABC", "Hawaii", "OC"),
    ("KL7ABC", "Alaska", "NA"),
    ("VE3XYZ", "Canada", "NA"),
    ("G0ABC", "England", "EU"),
    ("DL1ABC", "Germany", "EU"),
    ("JA1ABC", "Japan", "AS"),
    ("VK2ABC", "Australia", "OC"),
    ("ZS6ABC", "South Africa", "AF"),
    ("PY2ABC", "Brazil", "SA"),
    ("EA8ABC", "Canary Islands", "AF"),
])
def test_builtin_common_entities(builtin, call, name, continent):
    entity = builtin.lookup(call)
    assert entity.name == name
    assert entity.continent == continent


def test_longest_prefix_wins(builtin):
    """KH6 must beat K, and EA8 must beat EA."""
    assert builtin.lookup("KH6ABC").name == "Hawaii"
    assert builtin.lookup("K1ABC").name == "United States"
    assert builtin.lookup("EA8ABC").name == "Canary Islands"
    assert builtin.lookup("EA1ABC").name == "Spain"


def test_portable_prefix_relocates_the_operator(builtin):
    assert builtin.lookup("DL/W1AW").name == "Germany"
    assert builtin.lookup("W1AW/P").name == "United States"


@pytest.mark.parametrize("junk", ["", "   ", "!!!", "<script>"])
def test_junk_callsigns_return_none(builtin, junk):
    assert builtin.lookup(junk) is None
