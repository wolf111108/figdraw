from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def example():
    def load(name="bar"):
        return yaml.safe_load((ROOT / "examples" / f"{name}.yaml").read_text())

    return load
