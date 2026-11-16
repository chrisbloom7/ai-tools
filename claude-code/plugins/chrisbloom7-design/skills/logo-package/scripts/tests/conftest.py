import pytest

from generic_brand import SIDES, make_brand
from logo_pipeline import build


@pytest.fixture(scope="session", params=SIDES, ids=[f"{s}px" for s in SIDES])
def generic_brand(request, tmp_path_factory):
    """(brand folder, BuildResult) of the synthetic ring-and-bar brand, built once per size."""
    brand = tmp_path_factory.mktemp(f"ring-bar-{request.param}")
    cfg = make_brand(brand, request.param)
    return brand, build.run(brand, config=cfg)
