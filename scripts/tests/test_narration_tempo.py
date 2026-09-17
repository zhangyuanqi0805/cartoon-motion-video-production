import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

CLI = Path(__file__).resolve().parents[1] / 'make_video.py'


class NarrationTempo(unittest.TestCase):
    def test_prepare_passes_new_default_and_respects_explicit_original_speed(self):
        spec = importlib.util.spec_from_file_location('cartoon_tempo_test', CLI)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        import paper_input
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['script.md', 'plan.json', 'config.json', 'model.bin']:
                (root/name).write_text('{}')
            base = [str(CLI), 'prepare', '--manuscript', str(root/'script.md'),
                    '--content-plan', str(root/'plan.json'), '--config', str(root/'config.json'),
                    '--whisper-model', str(root/'model.bin'), '--output', str(root/'new-production')]
            for extra, expected in [([], 1.10), (['--tempo', '1.0'], 1.0)]:
                with self.subTest(extra=extra), patch.object(sys, 'argv', base+extra), \
                     patch.object(paper_input, 'prepare_new', return_value={'status':'fixture'}) as prepare, \
                     contextlib.redirect_stdout(io.StringIO()):
                    module.main()
                    self.assertEqual(prepare.call_count, 1)
                    self.assertEqual(prepare.call_args.args[-1], expected)


if __name__ == '__main__':
    unittest.main()
