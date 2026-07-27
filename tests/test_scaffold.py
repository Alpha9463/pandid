def test_package_imports():
    import pandid

    assert isinstance(pandid.__version__, str)
