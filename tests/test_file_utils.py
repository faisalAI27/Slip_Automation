from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from utils.file_utils import (
    MAX_PROCESSING_DIMENSION,
    InvalidImageError,
    UnsupportedImageError,
    remove_files,
    save_uploaded_image,
)


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (12, 8), color="white").save(output, format="PNG")
    return output.getvalue()


def _webp_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (12, 8), color="white").save(output, format="WEBP")
    return output.getvalue()


class FileUtilsTests(unittest.TestCase):
    def test_valid_image_uses_generated_name(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            saved = save_uploaded_image(_png_bytes(), "private-name.png", root, 1)

            self.assertTrue(saved.exists())
            self.assertTrue(saved.name.startswith("upload-"))
            self.assertNotIn("private-name", saved.name)

    def test_phone_image_variant_with_jpeg_name_is_normalized(self) -> None:
        with TemporaryDirectory() as directory:
            saved = save_uploaded_image(
                _webp_bytes(),
                "IMG_0474.jpeg",
                Path(directory),
                1,
            )

            self.assertEqual(saved.suffix, ".jpg")
            with Image.open(saved) as normalized:
                self.assertEqual(normalized.format, "JPEG")
                self.assertEqual(normalized.size, (12, 8))

    def test_phone_jpeg_orientation_is_applied_during_normalization(self) -> None:
        output = BytesIO()
        source = Image.new("RGB", (12, 8), color="white")
        exif = Image.Exif()
        exif[274] = 6
        source.save(output, format="JPEG", exif=exif)

        with TemporaryDirectory() as directory:
            saved = save_uploaded_image(
                output.getvalue(),
                "IMG_0475.jpeg",
                Path(directory),
                1,
            )

            with Image.open(saved) as normalized:
                self.assertEqual(normalized.size, (8, 12))
                self.assertNotIn(274, normalized.getexif())

    def test_high_resolution_phone_photo_is_downscaled_for_local_vision(self) -> None:
        output = BytesIO()
        Image.new("RGB", (3024, 4032), color="white").save(
            output,
            format="JPEG",
            quality=95,
        )

        with TemporaryDirectory() as directory:
            saved = save_uploaded_image(
                output.getvalue(),
                "IMG_0476.jpeg",
                Path(directory),
                12,
            )

            with Image.open(saved) as normalized:
                self.assertLessEqual(max(normalized.size), MAX_PROCESSING_DIMENSION)
                self.assertEqual(normalized.size, (1200, 1600))

    def test_unsupported_suffix_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(UnsupportedImageError):
                save_uploaded_image(_png_bytes(), "image.gif", Path(directory), 1)

    def test_invalid_image_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(InvalidImageError):
                save_uploaded_image(b"not-an-image", "image.png", Path(directory), 1)

    def test_remove_files_stays_inside_allowed_directory(self) -> None:
        with TemporaryDirectory() as allowed, TemporaryDirectory() as elsewhere:
            allowed_file = Path(allowed) / "temporary.txt"
            external_file = Path(elsewhere) / "keep.txt"
            allowed_file.write_text("remove", encoding="utf-8")
            external_file.write_text("keep", encoding="utf-8")

            remove_files([allowed_file, external_file], Path(allowed))

            self.assertFalse(allowed_file.exists())
            self.assertTrue(external_file.exists())


if __name__ == "__main__":
    unittest.main()
