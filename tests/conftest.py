from copy import deepcopy

import asdf
import pytest

from gladius_roman.demo import create_demo
from gladius_roman.io import read_exposure


@pytest.fixture
def demo(tmp_path):
    config = create_demo(tmp_path / "demo")
    return config


@pytest.fixture
def exposure(demo):
    return read_exposure(demo.parent / "images/demo0_cal.asdf")


@pytest.fixture
def modify_parent(demo):
    def change(update, filename="demo0_cal.asdf"):
        path = demo.parent / "images" / filename
        with asdf.open(path, lazy_load=False, memmap=False) as af:
            tree = deepcopy(dict(af.tree))
        update(tree)
        path.unlink()
        asdf.AsdfFile(tree).write_to(path)
        return path

    return change
