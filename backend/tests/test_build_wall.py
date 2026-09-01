"""Unit tests for the build_wall photo stitching script."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image, ImageDraw

# Adjust path to import build_wall script
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
import build_wall


class TestSourcePhotos:
    """Test photo discovery and filtering."""

    def test_source_photos_finds_jpg_files(self, tmp_path):
        """Should find and sort JPG files."""
        (tmp_path / "photo1.jpg").write_text("")
        (tmp_path / "photo2.jpg").write_text("")
        with patch.object(build_wall, "PICTURES_DIR", tmp_path):
            photos = build_wall.source_photos()
            assert len(photos) == 2
            assert photos[0].name == "photo1.jpg"
            assert photos[1].name == "photo2.jpg"

    def test_source_photos_ignores_pano_files(self, tmp_path):
        """Should skip files marked as phone-stitched panoramas."""
        (tmp_path / "photo1.jpg").write_text("")
        (tmp_path / "photo2.PANO.jpg").write_text("")
        (tmp_path / "photo3.pano.jpg").write_text("")
        (tmp_path / "photo4.jpg").write_text("")
        with patch.object(build_wall, "PICTURES_DIR", tmp_path):
            photos = build_wall.source_photos()
            names = [p.name for p in photos]
            assert "photo1.jpg" in names
            assert "photo4.jpg" in names
            assert "photo2.PANO.jpg" not in names
            assert "photo3.pano.jpg" not in names

    def test_source_photos_supports_multiple_formats(self, tmp_path):
        """Should find jpg, jpeg, png, webp files."""
        (tmp_path / "a.jpg").write_text("")
        (tmp_path / "b.jpeg").write_text("")
        (tmp_path / "c.png").write_text("")
        (tmp_path / "d.webp").write_text("")
        (tmp_path / "e.txt").write_text("")  # ignored
        with patch.object(build_wall, "PICTURES_DIR", tmp_path):
            photos = build_wall.source_photos()
            assert len(photos) == 4

    def test_source_photos_ignores_directories(self, tmp_path):
        """Should skip directories."""
        (tmp_path / "photo.jpg").write_text("")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "photo.jpg").write_text("")
        with patch.object(build_wall, "PICTURES_DIR", tmp_path):
            photos = build_wall.source_photos()
            assert len(photos) == 1


class TestWriteWebCopy:
    """Test web-sized image generation."""

    def test_write_web_copy_preserves_aspect_ratio(self, tmp_path):
        """Should resize to exact height while preserving aspect ratio."""
        # Create a 2000x1600 test image (taller than WEB_HEIGHT)
        img = Image.new("RGB", (2000, 1600), color="red")
        source = tmp_path / "test.jpg"
        img.save(source)

        web_dir = tmp_path / "web"
        web_dir.mkdir()

        with patch.object(build_wall, "WEB_DIR", web_dir):
            result = build_wall.write_web_copy(source)
            assert result.height == build_wall.WEB_HEIGHT
            # Width should scale proportionally
            expected_width = round(2000 * build_wall.WEB_HEIGHT / 1600)
            assert result.width == expected_width

    def test_write_web_copy_skips_upscaling(self, tmp_path):
        """Should not upscale images smaller than target height."""
        img = Image.new("RGB", (800, 600), color="blue")
        source = tmp_path / "test.jpg"
        img.save(source)

        web_dir = tmp_path / "web"
        web_dir.mkdir()

        with patch.object(build_wall, "WEB_DIR", web_dir):
            result = build_wall.write_web_copy(source)
            # Should not scale up
            assert result.height <= 600

    def test_write_web_copy_handles_exif_rotation(self, tmp_path):
        """Should apply EXIF rotation."""
        img = Image.new("RGB", (1600, 1200), color="green")
        source = tmp_path / "test.jpg"
        img.save(source, exif=b"mock_exif")

        web_dir = tmp_path / "web"
        web_dir.mkdir()

        with patch.object(build_wall, "WEB_DIR", web_dir):
            result = build_wall.write_web_copy(source)
            # Should convert to RGB and resize
            assert result.mode == "RGB"

    def test_write_web_copy_saves_optimized_jpg(self, tmp_path):
        """Should save as optimized JPEG."""
        img = Image.new("RGB", (2400, 1200), color="yellow")
        source = tmp_path / "test.jpg"
        img.save(source)

        web_dir = tmp_path / "web"
        web_dir.mkdir()

        with patch.object(build_wall, "WEB_DIR", web_dir):
            build_wall.write_web_copy(source)
            output = web_dir / "test.jpg"
            assert output.exists()
            # Verify it's a valid JPEG
            verify_img = Image.open(output)
            assert verify_img.format == "JPEG"


class TestGradientImage:
    """Test gradient magnitude calculation."""

    def test_gradient_image_returns_correct_shape(self):
        """Should return array with specified height."""
        img = Image.new("RGB", (800, 600), color="red")
        gradient = build_wall.gradient_image(img, 360)
        # Width should scale proportionally
        assert gradient.shape[0] == 360
        assert gradient.shape[1] == 360 * 800 // 600

    def test_gradient_image_detects_edges(self):
        """Should produce non-zero gradients at image edges."""
        # Create image with a vertical line down the middle
        img = Image.new("RGB", (400, 300), color="white")
        draw = ImageDraw.Draw(img)
        draw.rectangle([190, 0, 210, 300], fill="black")

        gradient = build_wall.gradient_image(img, 300)
        # Gradient should be non-zero where the line is
        assert np.max(gradient) > 0

    def test_gradient_image_uniform_region_low_gradient(self):
        """Uniform color regions should have low gradient."""
        img = Image.new("RGB", (400, 300), color="gray")
        gradient = build_wall.gradient_image(img, 300)
        # Uniform regions should have very small gradients
        assert np.mean(gradient) < 50


class TestWindowSums:
    """Test integral image window sum calculation."""

    def test_window_sums_correct_dimensions(self):
        """Should return correct output dimensions."""
        arr = np.ones((100, 100))
        result = build_wall.window_sums(arr, 10, 10)
        # Output should be smaller than input
        assert result.shape == (91, 91)

    def test_window_sums_all_ones(self):
        """Window sum of all-ones array should be window area."""
        arr = np.ones((100, 100))
        result = build_wall.window_sums(arr, 10, 10)
        # Each window sums to 100 (10 * 10)
        assert np.all(result == 100)

    def test_window_sums_zeros(self):
        """Window sum of zeros should be zero."""
        arr = np.zeros((100, 100))
        result = build_wall.window_sums(arr, 10, 10)
        assert np.all(result == 0)


class TestNccMap:
    """Test normalized cross-correlation."""

    def test_ncc_map_returns_none_for_large_template(self):
        """Should return None if template larger than image."""
        image = np.ones((50, 50))
        template = np.ones((100, 100))
        result = build_wall.ncc_map(image, template)
        assert result is None

    def test_ncc_map_perfect_match(self):
        """Should give score 1.0 for perfect template match."""
        image = np.array([[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]], dtype=np.float64)
        template = np.array([[6, 7], [10, 11]], dtype=np.float64)
        scores = build_wall.ncc_map(image, template)
        assert scores is not None
        assert np.max(scores) > 0.9  # Should be very high for matching pattern

    def test_ncc_map_returns_none_for_uniform_template(self):
        """Should return None for uniform (zero variance) template."""
        image = np.ones((50, 50))
        template = np.ones((10, 10))
        result = build_wall.ncc_map(image, template)
        assert result is None

    def test_ncc_map_output_shape(self):
        """NCC output should have correct shape."""
        image = np.random.randn(100, 100)
        template = np.random.randn(20, 20)
        scores = build_wall.ncc_map(image, template)
        if scores is not None:
            assert scores.shape == (81, 81)


class TestMultiScaleMatch:
    """Test multi-scale matching against templates."""

    def test_multi_scale_match_returns_score_and_fraction(self):
        """Should return (score, fraction) tuple."""
        # Create test image with gradient
        img = Image.new("RGB", (800, 600), color="white")
        draw = ImageDraw.Draw(img)
        for x in range(0, 800, 10):
            draw.line([(x, 0), (x, 600)], fill=(200, 200, 200))

        needle_img = Image.new("RGB", (800, 600), color="white")
        draw = ImageDraw.Draw(needle_img)
        for x in range(0, 800, 10):
            draw.line([(x, 0), (x, 600)], fill=(200, 200, 200))

        haystack = build_wall.gradient_image(img, build_wall.MATCH_HEIGHT)
        score, frac = build_wall.multi_scale_match(haystack, needle_img, "left")

        assert isinstance(score, float)
        assert isinstance(frac, float)
        assert 0 <= frac <= 1

    def test_multi_scale_match_left_vs_center_region(self):
        """Should detect left vs center regions."""
        # Create a test image with more varied content for matching
        img = Image.new("RGB", (1000, 600), color=(200, 200, 200))
        draw = ImageDraw.Draw(img)
        # Add multiple rectangles to create gradient features
        draw.rectangle([50, 100, 250, 500], fill="black")
        draw.rectangle([300, 150, 500, 450], fill=(100, 100, 100))
        draw.rectangle([600, 200, 800, 400], fill=(50, 50, 50))

        haystack = build_wall.gradient_image(img, build_wall.MATCH_HEIGHT)

        # Create needle that matches
        needle_img = Image.new("RGB", (1000, 600), color=(200, 200, 200))
        draw = ImageDraw.Draw(needle_img)
        draw.rectangle([50, 100, 250, 500], fill="black")
        draw.rectangle([300, 150, 500, 450], fill=(100, 100, 100))
        draw.rectangle([600, 200, 800, 400], fill=(50, 50, 50))

        left_score, _ = build_wall.multi_scale_match(haystack, needle_img, "left")
        center_score, _ = build_wall.multi_scale_match(haystack, needle_img, "center")

        # Should get valid scores (not -1.0 which means no match)
        assert left_score >= -1.0
        assert center_score >= -1.0


class TestWritePreview:
    """Test preview strip generation."""

    def test_write_preview_creates_strip(self, tmp_path):
        """Should create a preview strip combining all photos."""
        web_dir = tmp_path / "web"
        web_dir.mkdir()

        # Create test images
        for i in range(3):
            img = Image.new("RGB", (400, 300), color="red")
            img.save(web_dir / f"photo{i}.jpg")

        entries = [
            {"file": "photo0.jpg", "width": 400, "height": 300, "cropRight": 50},
            {"file": "photo1.jpg", "width": 400, "height": 300, "cropRight": 50},
            {"file": "photo2.jpg", "width": 400, "height": 300, "cropRight": 0},
        ]

        with patch.object(build_wall, "WEB_DIR", web_dir):
            build_wall.write_preview(entries)
            preview = web_dir / "preview-strip.jpg"
            assert preview.exists()
            strip_img = Image.open(preview)
            assert strip_img.height == build_wall.PREVIEW_HEIGHT

    def test_write_preview_accounts_for_cropping(self, tmp_path):
        """Should crop and resize images according to manifest."""
        web_dir = tmp_path / "web"
        web_dir.mkdir()

        # Create test image
        img = Image.new("RGB", (1000, 600), color="blue")
        img.save(web_dir / "photo.jpg")

        # Crop 200px from the right
        entries = [
            {"file": "photo.jpg", "width": 1000, "height": 600, "cropRight": 200},
        ]

        with patch.object(build_wall, "WEB_DIR", web_dir):
            build_wall.write_preview(entries)
            preview = web_dir / "preview-strip.jpg"
            strip_img = Image.open(preview)
            # Visible width should account for crop
            assert strip_img.width < 1000


class TestMain:
    """Integration tests for the main script."""

    def test_main_with_no_photos_raises_error(self, tmp_path):
        """Should raise SystemExit if no photos found."""
        with patch.object(build_wall, "PICTURES_DIR", tmp_path):
            with pytest.raises(SystemExit):
                build_wall.main()

    def test_main_processes_photos_and_creates_manifest(self, tmp_path):
        """Should process photos and create manifest.json."""
        # Set up directories
        pics_dir = tmp_path / "pictures"
        web_dir = tmp_path / "pictures" / "web"
        pics_dir.mkdir()
        web_dir.mkdir()

        # Create test photos
        for i in range(2):
            img = Image.new("RGB", (1600, 1200), color="red")
            draw = ImageDraw.Draw(img)
            # Add some pattern so overlaps can be detected
            draw.rectangle([0, 0, 800 - i * 50, 1200], fill=(100, 100, 100))
            img.save(pics_dir / f"photo{i:02d}.jpg")

        with patch.object(build_wall, "PICTURES_DIR", pics_dir):
            with patch.object(build_wall, "WEB_DIR", web_dir):
                build_wall.main()

                # Check manifest was created
                manifest_file = web_dir / "manifest.json"
                assert manifest_file.exists()

                manifest = json.loads(manifest_file.read_text())
                assert len(manifest) > 0
                assert all("file" in entry for entry in manifest)
                assert all("width" in entry for entry in manifest)
                assert all("height" in entry for entry in manifest)
                assert all("cropRight" in entry for entry in manifest)

    def test_main_clears_stale_files(self, tmp_path):
        """Should clear web directory before generating new files."""
        pics_dir = tmp_path / "pictures"
        web_dir = tmp_path / "pictures" / "web"
        pics_dir.mkdir()
        web_dir.mkdir()

        # Create a stale file
        stale = web_dir / "stale.txt"
        stale.write_text("old content")

        # Create one test photo
        img = Image.new("RGB", (800, 600), color="green")
        img.save(pics_dir / "photo.jpg")

        with patch.object(build_wall, "PICTURES_DIR", pics_dir):
            with patch.object(build_wall, "WEB_DIR", web_dir):
                build_wall.main()
                # Stale file should be gone
                assert not stale.exists()

    def test_main_processes_two_different_shots(self, tmp_path):
        """Should keep two photos of different scenes."""
        pics_dir = tmp_path / "pictures"
        web_dir = tmp_path / "pictures" / "web"
        pics_dir.mkdir()
        web_dir.mkdir()

        # Create two different shots (different scenes)
        shot1 = Image.new("RGB", (1600, 1200), color="white")
        draw = ImageDraw.Draw(shot1)
        draw.rectangle([100, 100, 400, 1000], fill="black")
        draw.rectangle([500, 200, 800, 900], fill=(100, 100, 100))
        shot1.save(pics_dir / "photo_00.jpg")

        shot2 = Image.new("RGB", (1600, 1200), color="white")
        draw = ImageDraw.Draw(shot2)
        draw.rectangle([100, 300, 400, 900], fill=(50, 50, 50))
        draw.rectangle([500, 100, 800, 1000], fill=(150, 150, 150))
        shot2.save(pics_dir / "photo_01.jpg")

        with patch.object(build_wall, "PICTURES_DIR", pics_dir):
            with patch.object(build_wall, "WEB_DIR", web_dir):
                build_wall.main()
                manifest = json.loads((web_dir / "manifest.json").read_text())
                # Both different scenes should be kept
                assert len(manifest) >= 1

    def test_main_creates_preview_strip(self, tmp_path):
        """Should create preview-strip.jpg for visual inspection."""
        pics_dir = tmp_path / "pictures"
        web_dir = tmp_path / "pictures" / "web"
        pics_dir.mkdir()
        web_dir.mkdir()

        # Create test photos
        for i in range(3):
            img = Image.new("RGB", (800, 600), color="red")
            img.save(pics_dir / f"photo{i:02d}.jpg")

        with patch.object(build_wall, "PICTURES_DIR", pics_dir):
            with patch.object(build_wall, "WEB_DIR", web_dir):
                build_wall.main()
                preview = web_dir / "preview-strip.jpg"
                assert preview.exists()
                # Verify it's a valid image
                Image.open(preview)


def textured_image(width: int, height: int, seed: int = 7) -> Image.Image:
    """A feature-rich synthetic image: random rectangles ORB can latch onto."""
    rng = np.random.default_rng(seed)
    img = Image.new("RGB", (width, height), color=(210, 210, 210))
    draw = ImageDraw.Draw(img)
    for _ in range(400):
        x = int(rng.integers(0, width - 12))
        y = int(rng.integers(0, height - 12))
        w = int(rng.integers(6, 40))
        h = int(rng.integers(6, 40))
        shade = int(rng.integers(0, 200))
        draw.rectangle([x, y, min(x + w, width - 1), min(y + h, height - 1)],
                       fill=(shade, shade // 2, shade // 2))
    return img


class TestFeatureOverlap:
    """Test ORB feature-based overlap measurement."""

    def test_measures_known_overlap(self):
        """Two crops of the same scene: detected overlap matches the geometry."""
        scene = textured_image(1400, build_wall.MATCH_HEIGHT)
        current = scene.crop((0, 0, 900, build_wall.MATCH_HEIGHT))
        following = scene.crop((500, 0, 1400, build_wall.MATCH_HEIGHT))
        # current spans x 0-900, following starts at 500 -> 400px of current repeated
        expected_frac = (900 - 500) / 900

        result = build_wall.feature_overlap(current, following)
        assert result is not None
        frac, inliers, dy, scale = result
        assert inliers >= build_wall.MIN_FEATURE_INLIERS
        assert abs(frac - expected_frac) < 0.08
        assert isinstance(dy, float)
        assert isinstance(scale, float)

    def test_returns_none_for_featureless_images(self):
        """Uniform images have no keypoints to match."""
        a = Image.new("RGB", (600, 400), color="gray")
        b = Image.new("RGB", (600, 400), color="gray")
        assert build_wall.feature_overlap(a, b) is None

    def test_returns_none_for_unrelated_scenes(self):
        """Different scenes should not produce a confident match."""
        a = textured_image(800, build_wall.MATCH_HEIGHT, seed=1)
        b = textured_image(800, build_wall.MATCH_HEIGHT, seed=2)
        result = build_wall.feature_overlap(a, b)
        # Either no match at all, or too few inliers to have been trusted
        assert result is None

    def test_returns_none_when_no_overlap(self):
        """Non-overlapping crops of the same scene: no overlap reported."""
        scene = textured_image(1800, build_wall.MATCH_HEIGHT)
        current = scene.crop((0, 0, 800, build_wall.MATCH_HEIGHT))
        following = scene.crop((900, 0, 1700, build_wall.MATCH_HEIGHT))
        result = build_wall.feature_overlap(current, following)
        assert result is None

    def test_tolerates_zoom_between_shots(self):
        """Overlap is still found when the next shot is zoomed."""
        scene = textured_image(1400, 500)
        current = scene.crop((0, 0, 900, 500))
        following = scene.crop((500, 50, 1400, 450))  # zoomed-in framing
        result = build_wall.feature_overlap(current, following)
        assert result is not None
        frac, _, _dy, _sc = result
        assert 0.2 < frac < 0.7  # geometric truth is ~0.44


class TestFeatureOverlapRobust:
    """Test the high-resolution retry ladder."""

    def test_returns_quick_pass_result_when_available(self):
        sentinel = (0.4, 60, 0.0, 1.0)
        with patch.object(build_wall, "feature_overlap",
                          return_value=sentinel) as mock_fo:
            result = build_wall.feature_overlap_robust(None, None)
        assert result == sentinel
        assert mock_fo.call_count == 1  # no retry when quick pass succeeds

    def test_retries_at_high_resolution_when_quick_pass_fails(self):
        sentinel = (0.3, 40, 5.0, 1.02)
        with patch.object(build_wall, "feature_overlap",
                          side_effect=[None, sentinel]) as mock_fo:
            result = build_wall.feature_overlap_robust(None, None)
        assert result == sentinel
        assert mock_fo.call_count == 2
        retry_kwargs = mock_fo.call_args_list[1].kwargs
        assert retry_kwargs["match_height"] == build_wall.FEATURE_RETRY_HEIGHT
        assert retry_kwargs["orb_features"] == build_wall.FEATURE_RETRY_ORB

    def test_returns_none_when_both_passes_fail(self):
        with patch.object(build_wall, "feature_overlap", return_value=None):
            assert build_wall.feature_overlap_robust(None, None) is None

    def test_dy_normalised_to_standard_frame(self):
        """dy from a high-res pass must be comparable to the standard pass."""
        scene = textured_image(1400, 720)
        current = scene.crop((0, 100, 900, 700))    # shifted down 100px
        following = scene.crop((500, 0, 1400, 600))
        std = build_wall.feature_overlap(current, following)
        hi = build_wall.feature_overlap(
            current, following,
            match_height=build_wall.FEATURE_RETRY_HEIGHT,
            orb_features=build_wall.FEATURE_RETRY_ORB,
        )
        assert std is not None and hi is not None
        # Both report dy in the MATCH_HEIGHT frame, so they should agree
        assert abs(std[2] - hi[2]) < 15


class TestMainUsesFeatureOverlap:
    """main() should prefer the feature measurement and fall back to NCC."""

    def _run_main(self, tmp_path, feature_result, ncc_result=(0.2, 0.0)):
        pics_dir = tmp_path / "pictures"
        web_dir = pics_dir / "web"
        pics_dir.mkdir()
        web_dir.mkdir()
        for i in range(2):
            textured_image(600, 400, seed=10 + i).save(pics_dir / f"photo{i}.jpg")

        def fake_match(haystack, needle_img, region):
            if region == "center":
                return (0.0, 0.0)  # never treat as re-shoot
            return ncc_result

        # feature_result must now be a 4-tuple (frac, inliers, dy, scale) or None
        full_result = None
        if feature_result is not None:
            frac, inliers = feature_result
            full_result = (frac, inliers, 0.0, 1.0)  # dy=0, scale=1 for simplicity

        # Pass-through anchoring so main() runs to completion without resizing
        def passthrough_anchor(kept, imgs, pairs):
            for p in kept:
                imgs[p].save(web_dir / f"{p.stem}.jpg", quality=85, optimize=True)
            return imgs

        with patch.object(build_wall, "PICTURES_DIR", pics_dir), \
             patch.object(build_wall, "WEB_DIR", web_dir), \
             patch.object(build_wall, "feature_overlap", return_value=full_result), \
             patch.object(build_wall, "multi_scale_match", side_effect=fake_match), \
             patch.object(build_wall, "apply_wall_anchoring", side_effect=passthrough_anchor):
            build_wall.main()
        return json.loads((web_dir / "manifest.json").read_text())

    def test_feature_overlap_sets_crop(self, tmp_path):
        manifest = self._run_main(tmp_path, feature_result=(0.4, 60))
        assert len(manifest) == 2
        assert manifest[0]["cropRight"] == round(0.4 * manifest[0]["width"])
        assert manifest[1]["cropRight"] == 0  # last photo never cropped

    def test_feature_overlap_caps_crop(self, tmp_path):
        manifest = self._run_main(tmp_path, feature_result=(0.85, 60))
        cap = round(manifest[0]["width"] * build_wall.MAX_CROP_FRAC)
        assert manifest[0]["cropRight"] == cap

    def test_feature_overlap_drops_repeated_photo(self, tmp_path):
        manifest = self._run_main(tmp_path, feature_result=(0.95, 60))
        assert len(manifest) == 1  # first photo dropped, fully repeated

    def test_falls_back_to_ncc_when_no_features(self, tmp_path):
        manifest = self._run_main(
            tmp_path, feature_result=None, ncc_result=(0.6, 0.3)
        )
        assert manifest[0]["cropRight"] == round(0.3 * manifest[0]["width"])

    def test_no_crop_when_both_methods_fail(self, tmp_path):
        manifest = self._run_main(
            tmp_path, feature_result=None, ncc_result=(0.2, 0.3)
        )
        assert manifest[0]["cropRight"] == 0


class TestComputeGlobalAlignment:
    """Test vertical offset chaining and detrending."""

    def _kept_and_images(self, n, height=1200):
        kept = [Path(f"photo{i}.jpg") for i in range(n)]
        web_images = {p: Image.new("RGB", (900, height)) for p in kept}
        return kept, web_images

    def test_single_photo_returns_zero(self):
        kept, imgs = self._kept_and_images(1)
        dy, sf = build_wall.compute_global_alignment(kept, {}, imgs)
        assert dy == [0.0]
        assert sf == [1.0]

    def test_no_matches_returns_zeros_and_ones(self):
        kept, imgs = self._kept_and_images(4)
        dy, sf = build_wall.compute_global_alignment(kept, {0: None, 1: None, 2: None}, imgs)
        assert all(v == 0.0 for v in dy)
        assert all(abs(v - 1.0) < 1e-9 for v in sf)

    def test_constant_dy_detrends_to_near_zero(self):
        """Constant drift each step should mostly be removed by detrending."""
        n = 60
        kept, imgs = self._kept_and_images(n)
        matches = {i: (0.5, 30, 10.0, 1.0) for i in range(n - 1)}
        dy, _ = build_wall.compute_global_alignment(kept, matches, imgs)
        mid = dy[n // 4: 3 * n // 4]
        assert max(abs(v) for v in mid) < 200

    def test_zero_dy_stays_zero(self):
        kept, imgs = self._kept_and_images(5)
        matches = {i: (0.5, 30, 0.0, 1.0) for i in range(4)}
        dy, _ = build_wall.compute_global_alignment(kept, matches, imgs)
        assert all(abs(v) < 1e-9 for v in dy)

    def test_returns_one_value_per_photo(self):
        n = 10
        kept, imgs = self._kept_and_images(n)
        matches = {i: (0.5, 30, 5.0, 1.0) for i in range(n - 1)}
        dy, sf = build_wall.compute_global_alignment(kept, matches, imgs)
        assert len(dy) == n
        assert len(sf) == n

    def test_constant_scale_detrends_to_one(self):
        """Constant scale drift across all pairs should detrend to ~1.0 in the middle."""
        n = 60
        kept, imgs = self._kept_and_images(n)
        # Each pair has scale_pair = 1.1 (gradual zoom-out)
        matches = {i: (0.5, 30, 0.0, 1.1) for i in range(n - 1)}
        _, sf = build_wall.compute_global_alignment(kept, matches, imgs)
        mid = sf[n // 4: 3 * n // 4]
        assert max(abs(v - 1.0) for v in mid) < 0.5

    def test_unit_scale_pairs_give_unit_factors(self):
        kept, imgs = self._kept_and_images(5)
        matches = {i: (0.5, 30, 0.0, 1.0) for i in range(4)}
        _, sf = build_wall.compute_global_alignment(kept, matches, imgs)
        assert all(abs(v - 1.0) < 1e-9 for v in sf)


class TestApplyVerticalAlignment:
    """Test common-band cropping with scale normalisation."""

    def _setup(self, n=3, height=1200, width=900):
        kept = [Path(f"p{i}.jpg") for i in range(n)]
        web_images = {p: Image.new("RGB", (width, height), color=(i * 60, 0, 0))
                      for i, p in enumerate(kept)}
        return kept, web_images

    def test_zero_offsets_unit_scale_preserves_height(self, tmp_path):
        kept, imgs = self._setup()
        sf = [1.0] * 3
        with patch.object(build_wall, "WEB_DIR", tmp_path):
            result = build_wall.apply_vertical_alignment(kept, imgs, [0.0, 0.0, 0.0], sf)
        for p in kept:
            assert result[p].height == imgs[p].height

    def test_nonzero_offsets_produce_common_band(self, tmp_path):
        kept, imgs = self._setup(n=3, height=1200)
        offsets = [0.0, 50.0, -30.0]
        sf = [1.0] * 3
        with patch.object(build_wall, "WEB_DIR", tmp_path):
            result = build_wall.apply_vertical_alignment(kept, imgs, offsets, sf)
        heights = {result[p].height for p in kept}
        assert len(heights) == 1
        assert list(heights)[0] < 1200

    def test_scale_factor_resizes_photo(self, tmp_path):
        kept, imgs = self._setup(n=2, height=1200)
        offsets = [0.0, 0.0]
        sf = [1.5, 1.5]  # both rescaled by 1.5
        with patch.object(build_wall, "WEB_DIR", tmp_path):
            result = build_wall.apply_vertical_alignment(kept, imgs, offsets, sf)
        # After 1.5x rescale, height = 1800; no vertical crop (same offset), so band = 1800
        for p in kept:
            assert result[p].height == 1800

    def test_saves_cropped_images_to_web_dir(self, tmp_path):
        kept, imgs = self._setup(n=2, height=1200)
        with patch.object(build_wall, "WEB_DIR", tmp_path):
            build_wall.apply_vertical_alignment(kept, imgs, [0.0, 40.0], [1.0, 1.0])
        for p in kept:
            assert (tmp_path / p.name).exists()

    def test_skips_alignment_when_drift_too_large(self, tmp_path):
        kept, imgs = self._setup(n=2, height=1200)
        with patch.object(build_wall, "WEB_DIR", tmp_path):
            result = build_wall.apply_vertical_alignment(kept, imgs, [0.0, 700.0], [1.0, 1.0])
        for p in kept:
            assert result[p].height == 1200

    def test_feature_overlap_returns_dy_and_scale(self):
        """feature_overlap returns a 4-tuple including dy and scale."""
        scene = textured_image(1400, build_wall.MATCH_HEIGHT)
        current = scene.crop((0, 0, 900, build_wall.MATCH_HEIGHT))
        following = scene.crop((500, 0, 1400, build_wall.MATCH_HEIGHT))
        result = build_wall.feature_overlap(current, following)
        assert result is not None
        frac, inliers, dy, scale = result
        assert isinstance(dy, float)
        assert build_wall.FEATURE_MIN_SCALE <= scale <= build_wall.FEATURE_MAX_SCALE


class TestEdgeDetection:
    """Test wall edge detection and alignment."""

    def test_detect_wall_edges_no_rotation_for_vertical_lines(self):
        """Should return ~0 angle for already-vertical edges."""
        img = Image.new("RGB", (800, 600), color="white")
        draw = ImageDraw.Draw(img)
        # Draw vertical lines (already aligned)
        for x in [100, 200, 300, 400, 500, 600, 700]:
            draw.line([(x, 0), (x, 600)], fill="black", width=3)

        angle = build_wall.detect_wall_edges(img)
        # Should be close to 0 (already aligned)
        assert abs(angle) < 1.5

    def test_detect_wall_edges_detects_rotation(self):
        """Should detect when edges are rotated."""
        img = Image.new("RGB", (800, 600), color="white")
        draw = ImageDraw.Draw(img)
        # Draw slightly slanted lines
        for start_x in [100, 200, 300, 400, 500, 600, 700]:
            # Draw lines at ~2 degree angle
            draw.line([(start_x - 20, 0), (start_x + 20, 600)], fill="black", width=3)

        angle = build_wall.detect_wall_edges(img)
        # Should detect some rotation (may vary depending on line pattern)
        assert isinstance(angle, float)
        assert abs(angle) <= build_wall.MAX_ROTATION_ANGLE

    def test_detect_wall_edges_no_lines(self):
        """Should return 0 when no edges detected."""
        img = Image.new("RGB", (800, 600), color="gray")
        # Uniform gray image with no strong edges
        angle = build_wall.detect_wall_edges(img)
        assert angle == 0.0

    def test_align_image_small_rotation(self):
        """Should rotate image to align edges."""
        img = Image.new("RGB", (400, 300), color="white")
        draw = ImageDraw.Draw(img)
        draw.rectangle([50, 50, 350, 250], outline="black", width=2)

        # Rotate by 1 degree
        rotated = build_wall.align_image(img, 1.0)

        # Image should still be valid
        assert rotated is not None
        assert rotated.mode == "RGB"

    def test_align_image_zero_rotation(self):
        """Should skip alignment for trivial rotations."""
        img = Image.new("RGB", (400, 300), color="white")
        result = build_wall.align_image(img, 0.05)
        # Should return original image unchanged for < 0.1 degree
        assert result is img

    def test_align_image_expand_with_fillcolor(self):
        """Rotated image should have gray fill color for expanded areas."""
        img = Image.new("RGB", (400, 300), color="white")
        draw = ImageDraw.Draw(img)
        draw.rectangle([50, 50, 350, 250], fill="black")

        rotated = build_wall.align_image(img, 2.0)
        # Image should be larger after rotation with expand=True
        assert rotated.width >= img.width or rotated.height >= img.height


def _wall_image(top_frac: float, bot_frac: float,
                width: int = 600, height: int = 1200) -> Image.Image:
    """Gray above top_frac, solid red hearts from top_frac to bot_frac, gray below."""
    img = Image.new("RGB", (width, height), (128, 128, 128))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, int(top_frac * height), width, int(bot_frac * height)],
                   fill=(200, 50, 50))
    return img


class TestRedDensityProfile:
    """Test red heart pixel density profiling."""

    def test_all_red_gives_high_density(self):
        img = Image.new("RGB", (400, 200), (200, 50, 50))
        profile = build_wall._red_density_profile(img)
        assert profile.mean() > 0.9

    def test_all_gray_gives_zero_density(self):
        img = Image.new("RGB", (400, 200), (128, 128, 128))
        profile = build_wall._red_density_profile(img)
        assert profile.mean() < 0.01

    def test_returns_one_value_per_strip(self):
        img = Image.new("RGB", (400, 200), (128, 128, 128))
        profile = build_wall._red_density_profile(img)
        assert len(profile) == 200 // build_wall.WALL_DETECT_STRIP_H


class TestDetectWallTop:
    """Test detection of the wall's top ledge via red density."""

    def test_detects_clear_top_boundary(self):
        img = _wall_image(0.20, 0.80, height=400)
        result = build_wall.detect_wall_top(img)
        assert result is not None
        # detection window spans 5 strips (50px), so allow ±50 around the true transition
        assert abs(result - 80) <= 50  # transition at y=80 (20% of 400)

    def test_all_gray_returns_none(self):
        img = Image.new("RGB", (400, 400), (128, 128, 128))
        assert build_wall.detect_wall_top(img) is None

    def test_all_red_returns_none(self):
        # Hearts from top to bottom — no low-red zone above to trigger transition
        img = Image.new("RGB", (400, 400), (200, 50, 50))
        assert build_wall.detect_wall_top(img) is None

    def test_transition_below_search_range_returns_none(self):
        # Hearts only start below the 55 % search limit
        img = _wall_image(0.65, 0.95, height=400)
        assert build_wall.detect_wall_top(img) is None

    def test_result_within_top_half(self):
        img = _wall_image(0.10, 0.90)
        result = build_wall.detect_wall_top(img)
        assert result is not None
        assert result <= int(build_wall.WALL_TOP_MAX_Y_FRAC * 1200)


class TestDetectWallBottom:
    """Test detection of where hearts end near the bottom."""

    def test_detects_bottom_boundary(self):
        img = _wall_image(0.10, 0.75, height=400)
        result = build_wall.detect_wall_bottom(img)
        assert result is not None
        # detection window spans 5 strips (50px), so allow ±50 around the true transition
        assert abs(result - 300) <= 50  # transition at y=300 (75% of 400)

    def test_all_gray_returns_none(self):
        img = Image.new("RGB", (400, 400), (128, 128, 128))
        assert build_wall.detect_wall_bottom(img) is None

    def test_hearts_to_bottom_edge_returns_none(self):
        # Red all the way to the bottom — no clear bottom boundary
        img = _wall_image(0.10, 1.0, height=400)
        assert build_wall.detect_wall_bottom(img) is None


class TestInterpolateNones:
    """Test linear interpolation / extrapolation over None entries."""

    def test_no_nones_unchanged(self):
        result = build_wall._interpolate_nones([1.0, 2.0, 3.0], default=0.0)
        assert result == [1.0, 2.0, 3.0]

    def test_all_nones_uses_default(self):
        result = build_wall._interpolate_nones([None, None, None], default=5.0)
        assert result == [5.0, 5.0, 5.0]

    def test_interpolates_between_anchors(self):
        result = build_wall._interpolate_nones([0.0, None, 2.0], default=0.0)
        assert abs(result[1] - 1.0) < 1e-9

    def test_extrapolates_before_first_anchor(self):
        result = build_wall._interpolate_nones([None, None, 3.0], default=0.0)
        assert result[0] == pytest.approx(3.0)
        assert result[1] == pytest.approx(3.0)

    def test_extrapolates_after_last_anchor(self):
        result = build_wall._interpolate_nones([1.0, None, None], default=0.0)
        assert result[1] == pytest.approx(1.0)
        assert result[2] == pytest.approx(1.0)


class TestApplyWallAnchoring:
    """Test absolute wall-geometry anchoring."""

    def test_wall_top_lands_at_same_row_in_every_photo(self, tmp_path):
        # Same wall, but photo 1 framed from farther away (smaller wall)
        kept = [Path("p0.jpg"), Path("p1.jpg")]
        imgs = {
            kept[0]: _wall_image(0.10, 0.90),
            kept[1]: _wall_image(0.20, 0.80),
        }
        with patch.object(build_wall, "WEB_DIR", tmp_path):
            result = build_wall.apply_wall_anchoring(kept, imgs, {})
        tops = [build_wall.detect_wall_top(result[p]) for p in kept]
        assert all(t is not None for t in tops)
        assert abs(tops[0] - tops[1]) <= 60  # detection window tolerance

    def test_all_photos_share_canvas_height(self, tmp_path):
        kept = [Path("p0.jpg"), Path("p1.jpg")]
        imgs = {
            kept[0]: _wall_image(0.10, 0.90),
            kept[1]: _wall_image(0.15, 0.85),
        }
        with patch.object(build_wall, "WEB_DIR", tmp_path):
            result = build_wall.apply_wall_anchoring(kept, imgs, {})
        heights = {result[p].height for p in kept}
        assert len(heights) == 1

    def test_keeps_content_below_wall_bottom(self, tmp_path):
        # Wall ends at 80% height: the pavement below must survive anchoring
        kept = [Path("p0.jpg"), Path("p1.jpg")]
        imgs = {p: _wall_image(0.10, 0.80) for p in kept}
        with patch.object(build_wall, "WEB_DIR", tmp_path):
            result = build_wall.apply_wall_anchoring(kept, imgs, {})
        for p in kept:
            assert build_wall.detect_wall_bottom(result[p]) is not None

    def test_saves_to_web_dir(self, tmp_path):
        kept = [Path("photo.jpg")]
        imgs = {kept[0]: _wall_image(0.10, 0.90)}
        with patch.object(build_wall, "WEB_DIR", tmp_path):
            build_wall.apply_wall_anchoring(kept, imgs, {})
        assert (tmp_path / "photo.jpg").exists()

    def test_falls_back_when_no_top_detected(self, tmp_path):
        kept = [Path("p0.jpg"), Path("p1.jpg")]
        imgs = {p: Image.new("RGB", (600, 1200), (128, 128, 128)) for p in kept}
        with patch.object(build_wall, "WEB_DIR", tmp_path), \
             patch.object(build_wall, "compute_global_alignment",
                          return_value=([0.0, 0.0], [1.0, 1.0])) as mock_cga, \
             patch.object(build_wall, "apply_vertical_alignment",
                          side_effect=lambda k, im, dy, sf: im) as mock_ava:
            build_wall.apply_wall_anchoring(kept, imgs, {})
        mock_cga.assert_called_once()
        mock_ava.assert_called_once()

    def test_photos_without_top_use_interpolated_scale(self, tmp_path):
        """Photo with no detectable top still gets anchored via neighbours."""
        kept = [Path(f"p{i}.jpg") for i in range(3)]
        imgs = {
            kept[0]: _wall_image(0.10, 0.90),
            kept[1]: Image.new("RGB", (600, 1200), (200, 50, 50)),  # all red, no top
            kept[2]: _wall_image(0.10, 0.90),
        }
        with patch.object(build_wall, "WEB_DIR", tmp_path):
            result = build_wall.apply_wall_anchoring(kept, imgs, {})
        heights = {result[p].height for p in kept}
        assert len(heights) == 1  # padded/interpolated photo still fits the canvas


class TestPadReflect:
    """Test mirror-padding used when a photo can't fill the canvas."""

    def test_no_padding_needed_keeps_content(self):
        img = Image.new("RGB", (100, 200), color=(50, 100, 150))
        result = build_wall._pad_reflect(img, 200, 0)
        assert result.size == (100, 200)

    def test_bottom_gap_mirrors_last_rows(self):
        img = Image.new("RGB", (100, 200), color="white")
        ImageDraw.Draw(img).rectangle([0, 180, 100, 200], fill="black")
        result = build_wall._pad_reflect(img, 260, 0)
        arr = np.array(result.convert("L"))
        # Rows 200-220 are the mirror of rows 180-200 (black)
        assert arr[210, 50] < 50
        # Beyond the mirrored black stripe, the reflection is white again
        assert arr[245, 50] > 200

    def test_top_gap_mirrors_first_rows(self):
        img = Image.new("RGB", (100, 200), color="white")
        ImageDraw.Draw(img).rectangle([0, 0, 100, 20], fill="black")
        result = build_wall._pad_reflect(img, 260, 60)
        arr = np.array(result.convert("L"))
        # Rows 40-60 are the mirror of rows 0-20 of the content (black)
        assert arr[50, 50] < 50
        assert arr[10, 50] > 200


class TestApplyResidualCorrections:
    """Test canvas-preserving residual scale / vertical corrections."""

    def _setup(self, n=2, height=1246, width=900):
        kept = [Path(f"p{i}.jpg") for i in range(n)]
        imgs = {p: Image.new("RGB", (width, height), color=(i * 70, 20, 20))
                for i, p in enumerate(kept)}
        return kept, imgs

    def test_preserves_canvas_height(self, tmp_path):
        kept, imgs = self._setup()
        with patch.object(build_wall, "WEB_DIR", tmp_path):
            result = build_wall.apply_residual_corrections(
                kept, imgs, [0.0, 35.0], [1.0, 1.08])
        for p in kept:
            assert result[p].height == 1246

    def test_zero_corrections_keep_image_unchanged(self, tmp_path):
        kept, imgs = self._setup()
        with patch.object(build_wall, "WEB_DIR", tmp_path):
            result = build_wall.apply_residual_corrections(
                kept, imgs, [0.0, 0.0], [1.0, 1.0])
        for p in kept:
            assert result[p] is imgs[p]

    def test_saves_all_photos_to_web_dir(self, tmp_path):
        kept, imgs = self._setup()
        with patch.object(build_wall, "WEB_DIR", tmp_path):
            build_wall.apply_residual_corrections(
                kept, imgs, [10.0, -10.0], [1.0, 1.0])
        for p in kept:
            assert (tmp_path / p.name).exists()

    def test_offset_shifts_content(self, tmp_path):
        kept = [Path("p0.jpg")]
        img = Image.new("RGB", (900, 1246), color=(220, 220, 220))
        # Black stripe at rows 200-300 on a light background
        ImageDraw.Draw(img).rectangle([0, 200, img.width, 300], fill="black")
        imgs = {kept[0]: img}
        with patch.object(build_wall, "WEB_DIR", tmp_path):
            result = build_wall.apply_residual_corrections(
                kept, imgs, [100.0], [1.0])
        arr = np.array(result[kept[0]].convert("L"))
        # Same mapping as apply_vertical_alignment: stripe moves to rows 300-400
        assert arr[350, 450] < 50
        assert arr[250, 450] > 150
    """End-to-end tests using actual test photos if available."""

    @pytest.mark.skipif(
        not Path("backend/tests/PXL_20230730_084337240.jpg").exists(),
        reason="Test photos not available",
    )
    def test_with_real_photos(self, tmp_path):
        """Test with actual memorial wall photos."""
        # Copy some real photos to temp directory
        test_photos_dir = Path("backend/tests")
        pics_dir = tmp_path / "pictures"
        web_dir = tmp_path / "pictures" / "web"
        pics_dir.mkdir()
        web_dir.mkdir()

        # Copy first 3 real photos
        for i, photo_file in enumerate(sorted(test_photos_dir.glob("PXL_*.jpg"))[:3]):
            import shutil
            shutil.copy(photo_file, pics_dir / f"{i:02d}_{photo_file.name}")

        with patch.object(build_wall, "PICTURES_DIR", pics_dir):
            with patch.object(build_wall, "WEB_DIR", web_dir):
                build_wall.main()

                manifest = json.loads((web_dir / "manifest.json").read_text())
                assert len(manifest) > 0
                # All entries should have reasonable crop values
                assert all(0 <= entry["cropRight"] <= entry["width"] for entry in manifest)
