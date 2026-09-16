import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import wave

SKILL = Path(__file__).resolve().parents[2]
CLI = SKILL / 'scripts/make_video.py'


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


class ProductionContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        source = self.root / 'manuscript.txt'
        source.write_text('先聊天，再听孩子说完。', encoding='utf-8')
        audio = self.root / 'narration.wav'
        with wave.open(str(audio), 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b'\0\0' * 96000)
        align = self.root / 'tokens.json'
        align.write_text(json.dumps({'source': 'whisper_token_offsets', 'tokens': [
            {'text': '先聊天', 'start': 0, 'end': 2},
            {'text': '再听孩子说完', 'start': 2, 'end': 6}]}))
        self.job = {'schema_version': 2, 'render_mode': 'fixed-v55', 'duration': 6,
            'manuscript': {'path': str(source), 'sha256': digest(source)},
            'narration': {'path': str(audio), 'sha256': digest(audio),
                'source_sha256': digest(source), 'provider': 'Jianying official text reading',
                'voice_id': 'zh_female_mizai_saturn_bigtts'},
            'alignment': {'path': str(align), 'sha256': digest(align)},
            'opening': {'duration': 0},
            'captions': [
                {'text': '先聊天，', 'en': 'Start a conversation', 'start': 0, 'end': 2},
                {'text': '再听孩子说完。', 'en': 'Then listen to the child', 'start': 2, 'end': 6}],
            'visuals': [{'preset': 'listen', 'start': 0, 'end': 6,
                         'meaning': 'Parent listens to a child'}]}

    def tearDown(self):
        self.tmp.cleanup()

    def run_build(self, job=None, name='project'):
        f = self.root / (name + '.json')
        f.write_text(json.dumps(job or self.job, ensure_ascii=False))
        return subprocess.run([sys.executable, str(CLI), 'build', '--job', str(f),
            '--output', str(self.root / name)], capture_output=True, text=True)

    def test_doctor_has_a_self_contained_template(self):
        p = subprocess.run([sys.executable, str(CLI), 'doctor'], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertIn('TEMPLATE_OK', p.stdout)

    def test_long_scene_drift_keeps_speed_when_joining_the_middle_leg(self):
        source = (SKILL / 'assets/v55/index.html').read_text()
        match = re.search(r'duration:driftA,ease:(.*?)\},driftStart\);', source)
        self.assertIsNotNone(match, 'The first progressive drift must be auditable')
        easing = match.group(1).strip()
        if easing == 'driftJoinEase':
            definition = re.search(r'const driftJoinEase=(p=>[^;]+);', source)
            self.assertIsNotNone(definition, 'The join easing definition must be present')
            easing = '(' + definition.group(1) + ')'
        js = ('const {gsap}=require(' + json.dumps(str(SKILL / 'assets/v55/assets/gsap.min.js')) + ');'
              'const value=' + easing + ';'
              'const ease=typeof value==="function"?value:gsap.parseEase(value);'
              'const h=0.0001;const slope=(ease(1)-ease(1-h))/h;'
              'process.stdout.write(JSON.stringify({slope,monotone:Array.from({length:100},'
              '(_,i)=>ease((i+1)/100)>ease(i/100)).every(Boolean)}));')
        result = json.loads(subprocess.check_output(['node', '-e', js], text=True))
        self.assertTrue(result['monotone'])
        # The next leg moves the same x distance over 0.5 rather than 0.3 of
        # the drift. A terminal slope near 0.6 joins its speed without a hold.
        self.assertGreaterEqual(result['slope'], .55)
        self.assertLessEqual(result['slope'], .65)

    def test_changed_content_retains_fixed_renderer_and_canvas(self):
        p = self.run_build()
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        project = self.root / 'project'
        s = (project / 'index.html').read_text()
        self.assertIn('data-width="1280"', s)
        self.assertIn('data-height="720"', s)
        self.assertIn('先聊天', s)
        self.assertNotIn('孩子一放下手机', s)
        m = json.loads((project / 'build-manifest.json').read_text())
        self.assertEqual(m['status'], 'BUILT_NOT_REVIEWED')
        self.assertIn('template_sha256', m)

    def test_summary_instead_of_manuscript_is_rejected(self):
        j = copy.deepcopy(self.job)
        j['captions'][1]['text'] = '养成好习惯'
        p = self.run_build(j)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('MANUSCRIPT_MISMATCH', p.stderr)
        self.assertFalse((self.root / 'project').exists())

    def test_unapproved_voice_is_rejected(self):
        j = copy.deepcopy(self.job)
        j['narration']['provider'] = 'macos-say'
        p = self.run_build(j)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('VOICE_MISMATCH', p.stderr)

    def test_stale_audio_source_is_rejected(self):
        j = copy.deepcopy(self.job)
        j['narration']['source_sha256'] = '0' * 64
        p = self.run_build(j)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('AUDIO_SOURCE_MISMATCH', p.stderr)

    def test_missing_alignment_is_rejected(self):
        j = copy.deepcopy(self.job)
        j['alignment']['path'] = str(self.root / 'missing.json')
        p = self.run_build(j)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('MISSING_INPUT', p.stderr)

    def test_changed_punctuation_is_not_full_manuscript_preservation(self):
        j = copy.deepcopy(self.job)
        j['captions'][0]['text'] = '先聊天！'
        p = self.run_build(j)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('MANUSCRIPT_MISMATCH', p.stderr)

    def test_manual_caption_timing_cannot_replace_token_offsets(self):
        j = copy.deepcopy(self.job)
        j['captions'][0]['end'] = 3
        j['captions'][1]['start'] = 3
        p = self.run_build(j)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('CAPTION_ALIGNMENT_MISMATCH', p.stderr)

    def test_prepare_cli_reaches_input_contract_without_rendering(self):
        p = subprocess.run([sys.executable, str(CLI), 'prepare', '--manuscript',
            str(self.root / 'missing.md'), '--content-plan', str(self.root / 'missing-plan.json'),
            '--output', str(self.root / 'production')], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('MISSING_INPUT', p.stderr)
        self.assertNotIn('invalid choice', p.stderr)
        self.assertFalse((self.root / 'production').exists())

    def test_arbitrary_canvas_is_rejected(self):
        j = copy.deepcopy(self.job)
        j['width'] = 720
        p = self.run_build(j)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('UNKNOWN_FIELD', p.stderr)

    def test_unknown_illustration_cannot_fallback_to_generic_person(self):
        j = copy.deepcopy(self.job)
        j['visuals'][0]['preset'] = 'generic-person'
        p = self.run_build(j)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('UNKNOWN_PRESET', p.stderr)

    def test_original_project_is_never_overwritten(self):
        target = self.root / 'project'
        target.mkdir()
        (target / 'keep.txt').write_text('keep')
        p = self.run_build()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('OUTPUT_EXISTS', p.stderr)
        self.assertEqual((target / 'keep.txt').read_text(), 'keep')

    def test_template_tampering_is_rejected_before_render(self):
        p = self.run_build()
        self.assertEqual(p.returncode, 0, p.stderr)
        f = self.root / 'project/index.html'
        f.write_text(f.read_text().replace('width:1280px', 'width:720px'))
        p = subprocess.run([sys.executable, str(CLI), 'check', '--project',
            str(self.root / 'project')], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('PROJECT_TAMPERED', p.stderr)


if __name__ == '__main__':
    unittest.main()
