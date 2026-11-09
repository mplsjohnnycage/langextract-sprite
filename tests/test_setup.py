import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('setup_module', Path(__file__).resolve().parents[1] / 'quickstart.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class SetupTests(unittest.TestCase):
    def test_personalized_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = module.build_bundle('example-sprite', '/srv/langextract', Path(directory) / 'plugin.zip')
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                self.assertIn('plugin.json', names)
                self.assertEqual(len([n for n in names if n.endswith('SKILL.md')]), 4)
                orchestrator = z.read('skills/orchestrator/SKILL.md').decode()
                self.assertIn('example-sprite', orchestrator)
                self.assertIn('/srv/langextract/.venv/bin/python', orchestrator)
                self.assertNotIn('YOUR_AUTHORIZED_SPRITE', orchestrator)
                self.assertEqual(json.loads(z.read('plugin.json'))['version'], '0.1.3')
    def test_invalid_sprite(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                module.build_bundle('bad name', '/srv/app', Path(directory) / 'plugin.zip')
    def test_invalid_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                module.build_bundle('good', 'relative/path', Path(directory) / 'plugin.zip')
