def test_pyproject_pinned_to_1_0_3():
    """Sanity check: pyproject pins cognee==1.0.3."""
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads(Path(__file__).parent.parent.joinpath("pyproject.toml").read_text())
    deps = pyproject["project"]["dependencies"]
    assert any("cognee==1.0.3" in d for d in deps), f"cognee not pinned to 1.0.3 in {deps}"
