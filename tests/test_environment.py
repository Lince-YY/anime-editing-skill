import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import probe_environment as probe
import plan_environment as planner
PROFILES = json.loads((ROOT / 'assets/tool-profiles.json').read_text())


def fixture(vram=None, vendor='NVIDIA', memory_kind='dedicated', cuda='available'):
    return {'schema_version':'1.0','generated_at':'2026-10-12T00:00:00Z','host':{'os':'Linux','arch':'x86_64','cpu':'fixture','ram_gb':64,'disk_free_gb':100},
            'gpus':([] if vendor is None else [{'vendor':vendor,'model':'fixture','memory_gb':vram,'memory_kind':memory_kind}]),
            'tools':{name:{'status':'found'} for name in PROFILES['tools']},
            'backends':{'cuda':{'status':cuda},'mps':{'status':'unavailable'},'cpu':{'status':'available'},'torch':{'status':'available'}}}


def task(env, name, pilot=None):
    return planner.plan(env, [name], PROFILES, pilot)['tasks'][0]


class EnvironmentTests(unittest.TestCase):
    def test_nvidia_reference_eligible_is_not_smoke(self):
        result = task(fixture(80), 'animation')
        self.assertEqual(result['route'], 'local_gpu')
        self.assertFalse(result['execution_ready'])
        self.assertEqual(result['pilot_evidence']['status'], 'unknown')

    def test_nvidia_reference_below(self):
        result = task(fixture(24), 'animation')
        self.assertEqual(result['route'], 'cloud')
        self.assertFalse(result['cloud_authorized'])
        self.assertTrue(any('not a measured minimum' in x for x in result['reasons']))

    def test_multigpu_not_added(self):
        env = fixture(40)
        env['gpus'].append(copy.deepcopy(env['gpus'][0]))
        self.assertEqual(task(env, 'animation')['route'], 'cloud')

    def test_apple_unified_is_not_vram(self):
        env = fixture(128, 'Apple', 'unified', 'unavailable')
        env['backends']['mps']['status'] = 'available'
        self.assertEqual(task(env,'animation')['route'], 'cloud')
        self.assertEqual(task(env,'voice')['backend_candidate'],'cpu')

    def test_cpu_and_unknown(self):
        env = fixture(None, None, cuda='unknown')
        self.assertEqual(task(env,'animation')['route'],'manual_check')
        self.assertEqual(task(env,'lineart')['route'],'local')

    def test_missing_and_unknown_are_different(self):
        env = fixture(80)
        env['tools']['tooncomposer']['status'] = 'missing'
        missing = task(env,'animation')
        self.assertIn('tooncomposer',missing['missing_tools'])
        self.assertEqual(missing['install_plan'][0]['action'],'install_if_this_route_is_selected')
        env['tools']['tooncomposer']['status'] = 'unknown'
        unknown = task(env,'animation')
        self.assertNotIn('tooncomposer',unknown['missing_tools'])
        self.assertEqual(unknown['install_plan'][0]['action'],'inspect_existing_installation')
        env['tools']['tooncomposer']['status'] = 'found'
        self.assertEqual(task(env,'animation')['install_plan'],[])

    def test_pilot_matching_is_scoped(self):
        pilot = {'schema_version':'1.0','checks':[{'name':'some_other_test','status':'passed','scope':'tiny','backend':'cuda'}]}
        self.assertEqual(task(fixture(80),'animation',pilot)['pilot_evidence']['status'],'unknown')
        pilot['checks'].append({'name':'animation','status':'passed','scope':'480p/8 frames fixture','backend':'cuda'})
        result = task(fixture(80),'animation',pilot)
        self.assertEqual(result['pilot_evidence']['status'],'passed')
        self.assertFalse(result['execution_ready'])

    def test_real_smoke_ffmpeg_maps_only_editing_technical_part(self):
        smoke = {'schema_version':'1.0','checks':[{'name':'ffmpeg','status':'passed','scope':'synthetic_media_smoke','backend':None,'details':{'effect_acceptance':False,'outputs':[]}}]}
        editing = task(fixture(80),'editing',smoke)
        self.assertEqual(editing['pilot_evidence']['partial_checks'][0]['status'],'passed')
        self.assertEqual(editing['pilot_evidence']['partial_checks'][0]['evidence_level'],'synthetic_media_technical_only')
        self.assertEqual(editing['pilot_evidence']['status'],'unknown')
        self.assertFalse(editing['execution_ready'])
        self.assertEqual(task(fixture(80),'animation',smoke)['pilot_evidence']['partial_checks'],[])

    def test_real_smoke_torch_and_case_do_not_verify_model(self):
        smoke = {'schema_version':'1.0','checks':[
            {'name':'torch','status':'passed','scope':'tensor_smoke','backend':'cuda','details':{'model_verified':False}},
            {'name':'case','status':'passed','scope':'user_model_case','backend':'cuda','details':{'model_identity':'user_declared_unverified','backend_verified':False,'effect_acceptance':False}}]}
        result = task(fixture(80),'animation',smoke)
        evidence = result['pilot_evidence']
        self.assertEqual([c['evidence_level'] for c in evidence['partial_checks']],['backend_tensor_only','user_case_outputs_only_model_identity_unverified'])
        self.assertEqual(evidence['status'],'unknown')
        self.assertFalse(evidence['model_verified'])
        self.assertFalse(evidence['effect_acceptance'])
        self.assertEqual(evidence['partial_checks'][1]['task_attribution'],'unknown')
        self.assertFalse(result['execution_ready'])
        self.assertEqual(task(fixture(None,None,cuda='unavailable'),'voice',smoke)['pilot_evidence']['partial_checks'],[])

    def test_smoke_alias_requires_exact_scope_and_backend(self):
        smoke = {'checks':[{'name':'ffmpeg','status':'passed','scope':'unrelated','backend':None},{'name':'torch','status':'passed','scope':'tensor_smoke','backend':'mps'},{'name':'case','status':'passed','scope':'user_model_case','backend':'auto'}]}
        self.assertEqual(task(fixture(80),'editing',smoke)['pilot_evidence']['status'],'unknown')
        self.assertEqual(task(fixture(80),'animation',smoke)['pilot_evidence']['partial_checks'],[])

    def test_command_timeout_failure_absence(self):
        with mock.patch.object(probe.subprocess,'run',side_effect=subprocess.TimeoutExpired('fixture',1)):
            self.assertEqual(probe.run_command(['fixture'])['reason'],'timeout')
        with mock.patch.object(probe.subprocess,'run',return_value=subprocess.CompletedProcess(['fixture'],2,'')):
            self.assertEqual(probe.run_command(['fixture'])['status'],'unknown')
        with mock.patch.object(probe.subprocess,'run',side_effect=FileNotFoundError()):
            self.assertEqual(probe.run_command(['fixture'])['status'],'missing')

    def test_parsers(self):
        self.assertEqual(probe.parse_nvidia('NVIDIA A800, 81920\n')[0]['memory_gb'],80)
        self.assertIsNone(probe.parse_nvidia('NVIDIA A800, N/A\n')[0]['memory_gb'])
        with self.assertRaises(ValueError): probe.parse_nvidia('bad, unexpected, fields')
        result = probe.parse_mac_displays(json.dumps({'SPDisplaysDataType':[{'sppci_model':'Apple M4'}]}),32)
        self.assertEqual(result[0]['memory_kind'],'unified')
        self.assertEqual(result[0]['memory_gb'],32)
        self.assertEqual(probe.parse_windows_host('[{"cpu":"fixture"}]')['cpu'],'fixture')

    def test_unknown_inventory_does_not_become_no_gpu(self):
        with mock.patch.object(probe,'run_command',return_value={'status':'missing','reason':'executable_not_found'}):
            gpus, detection, warnings = probe.probe_gpus('Linux',32,{'status':'missing'})
        self.assertEqual(gpus,[])
        self.assertEqual(detection,'unknown')
        self.assertTrue(warnings)

    def test_torch_failure_unknown_not_unavailable(self):
        with mock.patch.object(probe,'run_command',return_value={'status':'unknown','reason':'timeout'}):
            self.assertEqual(probe.probe_backends(True)['cuda']['status'],'unknown')
        with mock.patch.object(probe,'run_command',return_value={'status':'found','output':'not-json'}):
            self.assertEqual(probe.probe_backends(True)['torch']['status'],'unknown')

    def test_mac_sysctl_failure_recovers_without_identifiers(self):
        response = json.dumps({'SPHardwareDataType':[{'chip_type':'Apple M4','physical_memory':'32 GB','serial_number':'not-retained'}]})
        with mock.patch.object(probe,'run_command',side_effect=[{'status':'unknown','reason':'exit_code_1'},{'status':'unknown','reason':'exit_code_1'},{'status':'found','output':response}]):
            host, warnings = probe.probe_host('Darwin','.')
        self.assertEqual(host['ram_gb'],32)
        self.assertEqual(host['cpu'],'Apple M4')
        self.assertNotIn('not-retained',json.dumps(host))

    def test_atomic_json_and_cli_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'env.json'
            probe.atomic_json(path,fixture(80))
            self.assertEqual(json.loads(path.read_text())['schema_version'],'1.0')
            output = Path(folder)/'plan.json'
            result = subprocess.run([sys.executable,str(ROOT/'scripts/plan_environment.py'),'--environment',str(path),'--tasks','animation,panel','--out',str(output)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(len(json.loads(output.read_text())['tasks']),2)
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()),['env.json','plan.json'])


if __name__ == '__main__':
    unittest.main()
