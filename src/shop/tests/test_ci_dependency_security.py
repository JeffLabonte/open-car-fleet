import tomllib
import unittest
from pathlib import Path


class CIDependencySecurityTests(unittest.TestCase):
    def test_locked_dependencies_use_hashed_registry_wheels(self):
        lockfile = Path(__file__).resolve().parents[3] / "poetry.lock"
        packages = tomllib.loads(lockfile.read_text(encoding="utf-8"))["package"]

        self.assertTrue(packages)
        for package in packages:
            with self.subTest(package=package["name"]):
                self.assertNotIn("source", package)
                files = package["files"]
                self.assertTrue(any(file["file"].endswith(".whl") for file in files))
                for file in files:
                    self.assertRegex(file["hash"], r"^sha256:[0-9a-f]{64}$")
