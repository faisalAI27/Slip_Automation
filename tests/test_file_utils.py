from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from utils.file_utils import (
    InvalidImageError,
    UnsupportedImageError,
    remove_files,
    save_uploaded_image,
)


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (12, 8), color="white").save(output, format="PNG")
    return output.getvalue()


class FileUtilsTests(unittest.TestCase):
    def test_valid_image_uses_generated_name(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            saved = save_uploaded_image(_png_bytes(), "private-name.png", root, 1)

            self.assertTrue(saved.exists())
            self.assertTrue(saved.name.startswith("upload-"))
            self.assertNotIn("private-name", saved.name)

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
