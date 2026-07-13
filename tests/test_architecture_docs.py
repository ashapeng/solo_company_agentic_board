from scripts.check_architecture import check


def test_architecture_catalog_matches_repository_structure():
    assert check() == []
