from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def verne_marcxml() -> str:
    return (FIXTURES / "verne.xml").read_text()


@pytest.fixture
def verne_marc() -> bytes:
    return (FIXTURES / "verne.mrc").read_bytes()


@pytest.fixture
def russian_marcxml() -> str:
    return (FIXTURES / "russian-no-script.xml").read_text()
