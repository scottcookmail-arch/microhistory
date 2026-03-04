"""Tests for license filtering logic."""

import pytest

from microhistory.models import (
    COMMERCIAL_SAFE_LICENSES,
    AssetType,
    License,
    SourceAsset,
)
from microhistory.topic_research import _detect_license


# ---------------------------------------------------------------------------
# License detection
# ---------------------------------------------------------------------------

class TestDetectLicense:
    """Test the heuristic license detector."""

    def test_public_domain(self):
        assert _detect_license("This is public domain") == License.PUBLIC_DOMAIN

    def test_pd_us(self):
        assert _detect_license("PD-US-expired") == License.PUBLIC_DOMAIN

    def test_pd_old(self):
        assert _detect_license("PD-old-100") == License.PUBLIC_DOMAIN

    def test_cc0(self):
        assert _detect_license("CC0 1.0 Universal") == License.CC0

    def test_cc_zero(self):
        assert _detect_license("This is cc-zero licensed") == License.CC0

    def test_cc_by(self):
        assert _detect_license("Licensed under CC-BY 4.0") == License.CC_BY

    def test_cc_by_sa(self):
        assert _detect_license("CC-BY-SA 3.0") == License.CC_BY_SA

    def test_cc_by_nc(self):
        assert _detect_license("CC-BY-NC 4.0") == License.CC_BY_NC

    def test_us_gov(self):
        assert _detect_license("United States Government work") == License.US_GOV

    def test_usgov_short(self):
        assert _detect_license("USGov-NASA image") == License.US_GOV

    def test_unknown(self):
        assert _detect_license("All rights reserved 2024") == License.UNKNOWN

    def test_empty_string(self):
        assert _detect_license("") == License.UNKNOWN

    def test_case_insensitive(self):
        assert _detect_license("PUBLIC DOMAIN") == License.PUBLIC_DOMAIN


# ---------------------------------------------------------------------------
# Commercial safety check
# ---------------------------------------------------------------------------

class TestCommercialSafety:
    """Test the is_commercial_safe property on SourceAsset."""

    def _make_asset(self, license: License) -> SourceAsset:
        return SourceAsset(
            asset_id="test123",
            url="https://example.com/img.jpg",
            title="Test Asset",
            license=license,
        )

    def test_public_domain_is_safe(self):
        assert self._make_asset(License.PUBLIC_DOMAIN).is_commercial_safe

    def test_cc0_is_safe(self):
        assert self._make_asset(License.CC0).is_commercial_safe

    def test_cc_by_is_safe(self):
        assert self._make_asset(License.CC_BY).is_commercial_safe

    def test_cc_by_sa_is_safe(self):
        assert self._make_asset(License.CC_BY_SA).is_commercial_safe

    def test_us_gov_is_safe(self):
        assert self._make_asset(License.US_GOV).is_commercial_safe

    def test_cc_by_nc_is_not_safe(self):
        assert not self._make_asset(License.CC_BY_NC).is_commercial_safe

    def test_unknown_is_not_safe(self):
        assert not self._make_asset(License.UNKNOWN).is_commercial_safe

    def test_commercial_safe_set_completeness(self):
        """All safe licenses should be in the constant set."""
        safe_licenses = {License.PUBLIC_DOMAIN, License.CC0, License.CC_BY, License.CC_BY_SA, License.US_GOV}
        assert COMMERCIAL_SAFE_LICENSES == safe_licenses
