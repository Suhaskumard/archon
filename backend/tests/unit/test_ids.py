import time

from archon.core.ids import new_id, new_ulid


def test_new_id_has_prefix_and_length():
    ident = new_id("run")
    assert ident.startswith("run_")
    assert len(ident.split("_", 1)[1]) == 26


def test_ids_are_unique_and_k_sortable():
    first = new_ulid()
    time.sleep(0.005)
    second = new_ulid()
    assert first != second
    assert first < second  # timestamp prefix keeps them ordered


def test_invalid_prefix_rejected():
    import pytest

    with pytest.raises(ValueError):
        new_id("bad prefix")
