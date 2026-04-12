from __future__ import annotations

from pathlib import Path

from FuzVoicePreview.runtime import _select_vendor_site_packages


def test_select_vendor_site_packages_prefers_matching_versioned_directory(tmp_path: Path):
    vendor_dir = tmp_path / "vendor"
    versioned = vendor_dir / "site-packages-py312"
    fallback = vendor_dir / "site-packages"
    versioned.mkdir(parents=True)
    fallback.mkdir(parents=True)

    selected = _select_vendor_site_packages(vendor_dir, (3, 12))

    assert selected == versioned


def test_select_vendor_site_packages_falls_back_to_plain_directory(tmp_path: Path):
    vendor_dir = tmp_path / "vendor"
    fallback = vendor_dir / "site-packages"
    fallback.mkdir(parents=True)

    selected = _select_vendor_site_packages(vendor_dir, (3, 11))

    assert selected == fallback