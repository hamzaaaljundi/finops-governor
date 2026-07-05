"""UsdStageLoader tests (M5, Task 5.1)."""

import pytest

from finops_governor.validity.usd_stage import UsdStageError, UsdStageLoader

_VALID_USDA = """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Cube "box"
    {
        double size = 1.0
    }
}
"""


@pytest.fixture
def stage_file(tmp_path):
    p = tmp_path / "scene.usda"
    p.write_text(_VALID_USDA)
    return str(p)


def test_loader_is_lazy():
    # constructing the loader opens nothing
    assert UsdStageLoader()._cache == {}


def test_loads_a_valid_stage(stage_file):
    assert UsdStageLoader().load(stage_file) is not None


def test_memoizes_by_path(stage_file):
    loader = UsdStageLoader()
    # same path -> same object, opened at most once
    assert loader.load(stage_file) is loader.load(stage_file)
    assert len(loader._cache) == 1


def test_missing_path_raises_clean_error(tmp_path):
    with pytest.raises(UsdStageError):
        UsdStageLoader().load(str(tmp_path / "does_not_exist.usda"))
