import copy
import struct
import sys
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch
import test_contract

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import generated_assets as g
import make_video as m

def fixture_png(path,bbox=(80,60,840,660),opaque=False):
    w,h=1000,800;x0,y0,bw,bh=bbox;rows=[]
    for y in range(h):
        row=bytearray()
        for x in range(w):
            row.extend((20,155,190,255) if x0<=x<x0+bw and y0<=y<y0+bh else (255,255,255,255 if opaque else 0))
        rows.append(b'\0'+row)
    def chunk(t,b):return struct.pack('>I',len(b))+t+b+struct.pack('>I',zlib.crc32(t+b)&0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b''))

class OnDemandContract(unittest.TestCase):
    def setUp(self):
        self.fixture=test_contract.ProductionContract();self.fixture.setUp()
        self.root=self.fixture.root;self.job=copy.deepcopy(self.fixture.job)
        self.job['render_mode']='diverse-v55';self.job['visuals'][0]['preset']='choices'
        self.source=self.root/'fixture.png';fixture_png(self.source)
        self.job_path=self.root/'job.json';g.write(self.job_path,self.job)
    def tearDown(self):self.fixture.tearDown()
    def entry(self):
        b=self.root/'brief.json';g.brief('choices','synthetic test only','alpha',b)
        ev=self.root/'synthetic-evidence.png';fixture_png(ev)
        r=self.root/'review.json';g.write(r,{'source_sha256':g.sha(self.source),'preset':'choices',
            'background_mode':'alpha','decision':'candidate_pass','reviewer':'synthetic-test',
            'checks':{k:True for k in g.CHECKS},'observations':'Synthetic gate test, not a real visual review',
            'evidence':[{'path':str(ev),'sha256':g.sha(ev)}]})
        return g.admit(self.source,b,r,self.root/'library')
    def bundle(self):
        e=self.entry()
        return g.bind(self.job_path,[{'visual_index':0,'entry':e['entry']}],self.root/'bundle')
    def test_default_requests_generation(self):
        self.job.pop('render_mode')
        with self.assertRaisesRegex(ValueError,'ASSET_GENERATION_REQUIRED'):m.resolve_asset_selection(self.job)
    def test_fixed_never_reads_library(self):
        self.job['render_mode']='fixed-v55'
        with patch.object(g,'load_bundle',side_effect=AssertionError('unexpected read')):
            r=m.resolve_asset_selection(self.job)
        self.assertIsNone(r['opening']);self.assertEqual(r['visuals'],[])
    def test_fake_alpha_rejected(self):
        fixture_png(self.source,opaque=True)
        self.assertIn('REAL_ALPHA_REQUIRED',g.measure(self.source,'choices','alpha')['findings'])
    def test_crop_rejected(self):
        fixture_png(self.source,(0,0,999,790))
        self.assertIn('SUBJECT_TOUCHES_EDGE',g.measure(self.source,'choices','alpha')['findings'])
    def test_tiny_rejected(self):
        fixture_png(self.source,(400,300,120,140))
        self.assertIn('SUBJECT_TOO_SMALL',g.measure(self.source,'choices','alpha')['findings'])
    def test_incompatible_aspect_rejected(self):
        fixture_png(self.source,(300,50,300,700))
        self.assertIn('ASPECT_INCOMPATIBLE_WITH_SLOT',g.measure(self.source,'choices','alpha')['findings'])
    def test_placement_preserves_aspect_and_slot(self):
        r=g.measure(self.source,'choices','alpha');ov=r['placement'];slot=r['slot']
        self.assertAlmostEqual(ov['width']/ov['height'],1000/800)
        bx,by,bw,bh=r['bounds'];scale=ov['width']/1000
        self.assertGreaterEqual(ov['left']+bx*scale,slot['left']-1e-6)
        self.assertLessEqual(ov['left']+(bx+bw)*scale,slot['left']+slot['width']+1e-6)
    def test_no_review_no_admission(self):
        b=self.root/'brief.json';g.brief('choices','test','alpha',b)
        r=self.root/'review.json';g.write(r,{'source_sha256':g.sha(self.source),'preset':'choices','background_mode':'alpha'})
        with self.assertRaisesRegex(ValueError,'VISUAL_REVIEW_REQUIRED'):g.admit(self.source,b,r,self.root/'library')
    def test_file_tamper_rejected(self):
        e=self.entry();p=Path(e['entry']).parent/'source.png';p.write_bytes(p.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'ENTRY_TAMPERED'):g.load_entry(e['entry'])
    def test_report_or_html_without_portable_frame_rejected(self):
        ev=self.root/'review.html';ev.write_text('<p>Synthetic report without portable visual frame</p>')
        review={'source_sha256':g.sha(self.source),'preset':'choices','background_mode':'alpha',
            'decision':'candidate_pass','reviewer':'synthetic-test','checks':{k:True for k in g.CHECKS},
            'observations':'Synthetic fixture, not real visual approval',
            'evidence':[{'path':str(ev),'sha256':g.sha(ev)}]}
        with self.assertRaisesRegex(ValueError,'PORTABLE_PREVIEW_FRAME_REQUIRED'):
            g.review_valid(review,g.sha(self.source),'choices','alpha',require_frame=True)
    def test_other_manuscript_rejected(self):
        self.job['asset_bundle']=self.bundle();self.job['manuscript']['sha256']='a'*64
        with self.assertRaisesRegex(ValueError,'ASSET_BUNDLE_MANUSCRIPT'):m.resolve_asset_selection(self.job)
    def test_wrong_slot_rejected(self):
        e=self.entry();job=copy.deepcopy(self.job);job['visuals'][0]['preset']='notes'
        jp=self.root/'wrong.json';g.write(jp,job)
        with self.assertRaisesRegex(ValueError,'BINDING_PRESET'):g.bind(jp,[{'visual_index':0,'entry':e['entry']}],self.root/'bundle')
    def test_build_retains_captions_and_motion(self):
        self.job['asset_bundle']=self.bundle();jp=self.root/'ready.json';g.write(jp,self.job);out=self.root/'out'
        m.build(jp,out);self.assertEqual(m.check(out)['render_mode'],'diverse-v55')
        selection=g.read(out/'asset-selection.json');self.assertIsNone(selection['opening'])
        self.assertEqual(g.sha(out/selection['visuals'][0]['output_path']),g.sha(self.source))
        self.assertTrue((out/'asset-evidence/bundle.json').is_file())
        self.assertEqual(m.check(out)['asset_coverage']['replaced_segments'],1)
        fixed=copy.deepcopy(self.job);fixed['render_mode']='fixed-v55';fixed.pop('asset_bundle')
        a,ac,_=m.compose(fixed,6);b,bc,_=m.compose(self.job,6)
        self.assertEqual(ac,bc)
        self.assertEqual(a[a.index('// V31: general English'):],b[b.index('// V31: general English'):])
    def test_history_requests_fresh_asset(self):
        e=self.entry();h=self.root/'history.json'
        g.write(h,{'runs':[{'manuscript_sha256':'a'*64,'asset_ids':[Path(e['entry']).parent.name]}]})
        r=g.plan(self.job_path,self.root/'library',self.root/'plan.json',history=h)
        self.assertEqual(r['rows'][0]['action'],'generate')
    def test_empty_cache_has_generation_plan(self):
        r=g.plan(self.job_path,self.root/'library',self.root/'plan.json')
        self.assertEqual(r['rows'][0]['action'],'generate');self.assertEqual(r['opening'],'keep_baseline')
    def test_opening_replacement_rejected(self):
        self.job['asset_bundle']=self.bundle();self.job['opening']['variant_id']='cover-03'
        with self.assertRaisesRegex(ValueError,'OPENING_LAYOUT_LOCKED'):m.resolve_asset_selection(self.job)

    def test_history_counts_distinct_manuscripts_not_render_versions(self):
        e=self.entry();asset=Path(e['entry']).parent.name
        runs=[{'manuscript_sha256':c*64,'asset_ids':[asset if c=='a' else 'synthetic-'+c]} for c in 'abcde']
        runs.extend([{'manuscript_sha256':'e'*64,'asset_ids':['synthetic-e-v2']} for _ in range(6)])
        h=self.root/'history.json';g.write(h,{'runs':runs})
        r=g.plan(self.job_path,self.root/'library',self.root/'plan.json',history=h)
        self.assertEqual(r['rows'][0]['action'],'generate')

if __name__=='__main__':unittest.main()
