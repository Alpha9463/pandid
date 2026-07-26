def test_package_imports():
    import pfd

    assert isinstance(pfd.__version__, str)
