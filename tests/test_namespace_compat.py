from __future__ import annotations


def test_smallink_is_the_canonical_runtime_namespace() -> None:
    import smallink
    from smallink.server import create_app as smallink_create_app

    assert smallink.__path__[0].endswith("/smallink")
    assert callable(smallink_create_app)


def test_legacy_link_namespace_forwards_without_own_implementation() -> None:
    import link
    import smallink
    from link.server import create_app as legacy_create_app

    assert link.__path__ == smallink.__path__
    assert callable(legacy_create_app)
