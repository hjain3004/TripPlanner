import pytest
from gateway.evidence.nodes import Claim

def test_contradicts_field_removed():
    assert "contradicts" not in Claim.model_fields
