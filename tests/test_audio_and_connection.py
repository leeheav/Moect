"""Synthetic SILK conversion and connection lifecycle regressions; no live account."""
import hashlib
import json
import math
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import pysilk

from core.data import Archive
from core.exporting import export_session
from core.media_codec import MediaCodec, silk_stream
from core.service import Service
from tests.test_core import fixture,SESSION
from tests.test_resources import ASSETS,media_fixture


def silk_fixture(milliseconds=200, sample_rate=24000):
    count = sample_rate * milliseconds // 1000
    samples = [int(7000 * math.sin(2 * math.pi * 440 * i / sample_rate)) for i in range(count)]
    return pysilk.encode(struct.pack('<%sh' % count, *samples), sample_rate=sample_rate)


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.codec=MediaCodec(lambda:None)

    def test_tencent_and_standard_silk_produce_real_playable_pcm_wav(self):
        blob=silk_fixture()
        for number,source in enumerate((blob,blob[1:]+b'\xff\xff')):
            with self.subTest(container=number):
                target=self.root/('%s.wav'%number)
                self.assertEqual(self.codec.audio(source,target),target)
                with wave.open(str(target),'rb') as audio:
                    self.assertEqual((audio.getnchannels(),audio.getsampwidth(),audio.getframerate()),(1,2,24000))
                    self.assertAlmostEqual(audio.getnframes()/audio.getframerate(),.2,places=2)
                    pcm=audio.readframes(audio.getnframes())
                    self.assertGreater(max(struct.unpack('<%sh'%(len(pcm)//2),pcm)),100)

    def test_truncated_or_excessive_silk_is_rejected_before_native_decode(self):
        blob=silk_fixture()
        invalid=(blob[:-1],b'\x02#!SILK_V3\xff\x7f',b'\x02#!SILK_V3'+b'\0\0'*30001,
                 blob+b'\0\0',blob+b'\x00',blob+b'\xfe\xff',
                 b'\x02#!SILK_V3'+struct.pack('<h',1251)+b'x'*1251)
        with patch('pysilk.decode',side_effect=AssertionError('Invalid packets reached native decoder')):
            for source in invalid:
                self.assertIsNone(self.codec.audio(source,self.root/'bad.wav'))
                self.assertEqual(self.codec.audio_reason,'invalid_silk_packets')
        self.assertFalse((self.root/'bad.wav').exists())

    def test_silk_headers_end_markers_and_single_packet_have_correct_duration(self):
        for rate in (8000, 16000, 24000):
            for duration in (20, 40, 200):
                blob = silk_fixture(duration, rate)
                standard = blob[1:]
                variants = (blob, standard, standard + b'\xff\xff',
                            blob[:10] + b'\n' + blob[10:],
                            standard[:9] + b'\r\n' + standard[9:] + b'\xff\xff')
                for number, source in enumerate(variants):
                    with self.subTest(rate=rate, duration=duration, variant=number):
                        stream, packets = silk_stream(source, lambda: None)
                        self.assertTrue(stream.startswith(b'\x02#!SILK_V3'))
                        self.assertTrue(stream.endswith(b'\xff\xff'))
                        self.assertEqual(packets, duration // 20)
                        target = self.root/'normalized.wav'
                        self.assertEqual(self.codec.audio(source, target), target)
                        self.assertEqual(self.codec.audio_reason, '')
                        with wave.open(str(target), 'rb') as audio:
                            self.assertEqual(audio.getnframes(), 24000 * duration // 1000)

    def test_missing_decoder_has_a_distinct_reason_and_recovers_on_next_call(self):
        blob = silk_fixture()
        target = self.root/'component.wav'
        with patch.dict(sys.modules, {'pysilk': None}):
            self.assertIsNone(self.codec.audio(blob, target))
        self.assertEqual(self.codec.audio_reason, 'silk_decoder_unavailable')
        self.assertFalse(target.exists())
        self.assertEqual(self.codec.audio(blob, target), target)
        self.assertEqual(self.codec.audio_reason, '')

    def test_export_and_forward_voice_are_wav_and_failed_conversion_is_reported(self):
        lib=media_fixture(self.root)
        with patch('core.media_codec.app_data_root',return_value=self.root/'app-state'):
            archive=Archive(lib)
            try:
                original=next(archive.messages(SESSION))
                voice=dict(original,server_id='voice',kind='voice',text='[语音]',extra={})
                forward=dict(original,server_id='forward',kind='chatrecord',forward={'title':'Synthetic forward','messages':[dict(voice,server_id='nested-voice')]})
                for bad in (False,True):
                    folder=self.root/('bad' if bad else 'good');folder.mkdir()
                    with patch.object(archive,'messages',side_effect=lambda *a,**k:iter([voice] if bad else [voice,forward])),patch.object(archive.data,'voice_blob',return_value=b'\x02#!SILK_V3\xff\x7f' if bad else silk_fixture()):
                        result=export_session(archive,archive.sessions()[0],{'format':'json','includeAvatars':False},folder,ASSETS,lambda _:None,lambda:None)
                    rows=json.loads(Path(result['path']).read_text(encoding='utf-8'))['messages']
                    if bad:
                        self.assertEqual(rows[0]['resource_status'],'unsupported')
                        self.assertEqual(result['resource_summary']['unsupported'],1)
                        self.assertEqual(result['resource_summary']['missing'],0)
                        self.assertEqual(rows[0]['resources'][0]['kind'],'original')
                        report_path = next(folder.glob('*_assets/resource-report.jsonl'))
                        report = json.loads(report_path.read_text(encoding='utf-8').splitlines()[0])
                        self.assertEqual(report['audio_diagnostics']['reason'], 'invalid_silk_packets')
                    else:
                        for row in (rows[0],rows[1]['forward']['messages'][0]):
                            resource=row['resources'][0]
                            self.assertEqual((resource['kind'],resource['status']),('audio','available'))
                            with wave.open(str(folder/resource['path']),'rb') as audio:self.assertGreater(audio.getnframes(),0)
            finally:archive.close()


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        state=self.root/'state';state.mkdir();(state/'config.json').write_text(json.dumps({'app_onboarding_seen':True,'auto_reconnect_on_startup':True}),encoding='utf-8')
        self.service=Service(ASSETS,state)
        self.addCleanup(self.service.shutdown)
        self.account=dict(path=str(self.root/'account'),db_storage=str(self.root/'account/db_storage'),dir_name='wxid_fixture',wxid='wxid_fixture')
        Path(self.account['db_storage']).mkdir(parents=True)
        self.token=hashlib.sha256(self.account['db_storage'].encode()).hexdigest()[:16]

    def test_first_start_backup_and_demo_do_not_detect_or_connect(self):
        for lib in (None,{'name':'backup','root':'unused'},{'name':'demo','demo':True}):
            with self.subTest(library=lib):
                self.service.library=lib;self.service._startup_reconnect_done=False
                with patch.object(self.service,'detect',side_effect=AssertionError('Unexpected detection')):
                    self.assertEqual(self.service.call('startup_reconnect',{}),{'skipped':True})

    def test_startup_only_reconnects_previous_account_once_across_document_reload(self):
        self.service.library={'name':'fixture','account_dir':self.account['path']}
        other=dict(self.account,path=str(self.root/'other'),db_storage=str(self.root/'other/db_storage'))
        with patch('wx4.paths.list_account_dirs',return_value=[other,self.account]),patch('wx4.key.find_weixin_processes',return_value=[{'pid':1}]),patch.object(self.service,'connect',return_value={'job':'synthetic-job'}) as connect:
            self.assertEqual(self.service.startup_reconnect(),{'job':'synthetic-job'})
            self.assertEqual(self.service.startup_reconnect(),{'job':'synthetic-job'})
            connect.assert_called_once_with(self.token)

    def test_first_launch_never_detects_or_reconnects_even_with_a_saved_account(self):
        for flag in (None,False,'true',1):
            with self.subTest(seen=flag):
                folder=self.root/('first-'+str(flag));folder.mkdir()
                (folder/'config.json').write_text(json.dumps({'app_onboarding_seen':flag,'library':{'name':'Synthetic legacy account','account_dir':self.account['path']}}),encoding='utf-8')
                service=Service(ASSETS,folder)
                try:
                    with patch.object(service,'detect',side_effect=AssertionError('First launch must not inspect WeChat')),patch.object(service,'connect',side_effect=AssertionError('First launch must stay manual')):
                        self.assertEqual(service.startup_reconnect(),{'skipped':True})
                        service.call('tutorial_seen',{'kind':'app'})
                        self.assertEqual(service.startup_reconnect(),{'skipped':True})
                finally:service.shutdown()

    def test_displaying_tutorial_before_startup_call_still_skips_until_next_process(self):
        folder=self.root/'tutorial-race';folder.mkdir()
        (folder/'config.json').write_text(json.dumps({'auto_reconnect_on_startup':True,'library':{'name':'Synthetic legacy account','account_dir':self.account['path']}}),encoding='utf-8')
        service=Service(ASSETS,folder)
        try:
            service.call('tutorial_seen',{'kind':'app'})
            with patch.object(service,'detect',side_effect=AssertionError('Tutorial display must not enable reconnection')):
                self.assertEqual(service.startup_reconnect(),{'skipped':True})
            service.accounts[self.token]=self.account
            with patch.object(service.pool,'submit'):
                self.assertTrue(service.connect(self.token)['job'])
        finally:service.shutdown()
        reloaded=Service(ASSETS,folder)
        try:
            with patch('wx4.paths.list_account_dirs',return_value=[self.account]),patch('wx4.key.find_weixin_processes',return_value=[{'pid':1}]),patch.object(reloaded,'connect',return_value={'job':'next-start'}) as connect:
                self.assertEqual(reloaded.startup_reconnect(),{'job':'next-start'})
                self.assertEqual(reloaded.startup_reconnect(),{'job':'next-start'})
                connect.assert_called_once_with(self.token)
        finally:reloaded.shutdown()

    def test_closed_wechat_and_missing_previous_account_never_switch_accounts(self):
        self.service.library={'name':'fixture','account_dir':str(self.root/'missing')}
        for running in ([],[{'pid':1}]):
            self.service._startup_reconnect_done=False
            with patch('wx4.paths.list_account_dirs',return_value=[self.account]),patch('wx4.key.find_weixin_processes',return_value=running),patch.object(self.service,'connect',side_effect=AssertionError('Must not switch to another account')):
                self.assertIn('notice',self.service.startup_reconnect())

    def test_manual_directory_can_reconnect_outside_discovery_roots(self):
        self.service.library={'name':'fixture','account_dir':self.account['path']}
        with patch('wx4.paths.list_account_dirs',return_value=[]),patch('wx4.key.find_weixin_processes',return_value=[{'pid':1}]),patch.object(self.service,'connect',return_value={'job':'synthetic-job'}) as connect:
            self.service.startup_reconnect();connect.assert_called_once_with(self.token)

    def test_logout_persists_empty_library_preserves_tasks_files_and_export_jobs(self):
        self.service.library=self.service.config['library']={'name':'fixture','account_dir':self.account['path']}
        connect=self.service._new_job('connect','Synthetic connect')
        export=self.service._new_job('export','Synthetic export')
        marker=self.root/'export.txt';marker.write_text('synthetic',encoding='utf-8')
        self.service.logout()
        self.assertTrue(self.service.events[connect['id']].is_set())
        self.assertFalse(self.service.events[export['id']].is_set())
        self.assertIsNone(self.service.state()['library']);self.assertTrue(marker.exists())
        self.assertEqual(len(self.service.state()['tasks']),2)
        self.assertIsNone(json.loads(self.service.config_path.read_text(encoding='utf-8'))['library'])
        with patch.object(self.service,'detect',side_effect=AssertionError('Logged out')):
            self.assertEqual(self.service.startup_reconnect(),{'skipped':True})

    def test_logout_during_connection_prevents_stale_snapshot_commit(self):
        self.service.accounts[self.token]=self.account
        with patch.object(self.service.pool,'submit') as submit:
            result=self.service.connect(self.token)
            with self.assertRaisesRegex(ValueError,'正在连接'):self.service.connect(self.token)
        def decrypt(keys,source,destination,**kwargs):
            fixture(Path(destination),count=2)
            return {'failed':[]}
        with patch('wx4.key.KeyExtractor'),patch('wx4.key.load_keys',return_value={'synthetic':'not-a-real-key'}),patch('wx4.decrypt.decrypt_all',side_effect=decrypt),patch.object(self.service,'hydrate_profile',side_effect=lambda *a:self.service.logout()):
            fn,*args=submit.call_args.args;fn(*args)
        self.assertIsNone(self.service.state()['library'])
        self.assertEqual(self.service.state()['tasks'][0]['status'],'cancelled')
        self.assertFalse(list((self.root/'state/archives').rglob('snapshot_*')))
        self.assertTrue(result['job'])

    def test_startup_reconnect_disabled_by_default_and_toggleable(self):
        folder=self.root/'auto-reconnect-toggle';folder.mkdir()
        service=Service(ASSETS,folder)
        try:
            self.assertFalse(service.config['auto_reconnect_on_startup'])
            self.assertFalse(service.state()['auto_reconnect_on_startup'])
            service.library={'name':'fixture','account_dir':self.account['path']}
            with patch.object(service,'detect',side_effect=AssertionError('Must not detect when disabled')):
                self.assertEqual(service.startup_reconnect(),{'skipped':True})
            updated=service.settings({'auto_reconnect_on_startup':True})
            self.assertTrue(updated['auto_reconnect_on_startup'])
            self.assertTrue(service.config['auto_reconnect_on_startup'])
            with self.assertRaises(ValueError):
                service.settings({'auto_reconnect_on_startup':'invalid'})
        finally:service.shutdown()

    def test_reuse_saved_keys_setting_and_cached_flow(self):
        folder=self.root/'reuse-keys-toggle';folder.mkdir()
        service=Service(ASSETS,folder)
        try:
            self.assertTrue(service.config['reuse_saved_keys'])
            self.assertTrue(service.state()['reuse_saved_keys'])
            updated=service.settings({'reuse_saved_keys':False})
            self.assertFalse(updated['reuse_saved_keys'])
            self.assertFalse(service.config['reuse_saved_keys'])
            with self.assertRaises(ValueError):
                service.settings({'reuse_saved_keys':'invalid'})
        finally:service.shutdown()

    def test_sync_session_validations_and_success_flow(self):
        folder=self.root/'sync-session-test';folder.mkdir()
        service=Service(ASSETS,folder)
        try:
            # 1. Missing username
            with self.assertRaisesRegex(ValueError,'缺少会话标识'):
                service.sync_session({})

            # 2. No library
            with self.assertRaisesRegex(ValueError,'请先连接微信'):
                service.sync_session({'username':'friend_wxid_123'})

            # 3. Demo library
            service.library={'name':'demo','demo':True}
            with self.assertRaisesRegex(ValueError,'演示模式或备份归档不支持实时同步'):
                service.sync_session({'username':'friend_wxid_123'})

            # 4. Live library but WeChat not running
            account_storage=folder/'test_account'
            (account_storage/'db_storage').mkdir(parents=True)
            snapshot_dir=folder/'archives/acc1/snapshot_test'
            snapshot_dir.mkdir(parents=True)
            keys_file=snapshot_dir.parent/'keys.json'
            keys_file.write_text(json.dumps({
                'session.db':{'enc_key':'aabbcc','salt':'1122'},
                'message_0.db':{'enc_key':'ddeeff','salt':'3344'},
            }),encoding='utf-8')

            service.library={
                'name':'live_test',
                'account_dir':str(account_storage),
                'root':str(snapshot_dir),
                'wxid':'wxid_tester'
            }

            with patch.object(service,'detect',return_value={'running':False,'accounts':[]}):
                with self.assertRaisesRegex(ValueError,'请先打开并登录电脑微信'):
                    service.sync_session({'username':'friend_wxid_123'})

            # 5. Live library and WeChat running -> successfully runs decrypt_all and syncs
            def mock_decrypt(keys,db_storage,out_dir,**kwargs):
                for k in keys:
                    p=Path(out_dir)/k
                    p.parent.mkdir(parents=True,exist_ok=True)
                    p.write_bytes(b'SQLite format 3\x00' + b'\x00'*4080)
                return {'ok':list(keys.keys()),'failed':[]}

            with patch.object(service,'detect',return_value={'running':True,'accounts':[]}), \
                 patch('wx4.decrypt.decrypt_all',side_effect=mock_decrypt), \
                 patch.object(service,'read_archive') as mock_archive_ctx:
                mock_archive=unittest.mock.MagicMock()
                mock_archive.sessions.return_value=[
                    {'username':'friend_wxid_123','summary':'最新测试消息','last_time':1700000000}
                ]
                mock_archive_ctx.return_value.__enter__.return_value=mock_archive
                mock_archive_ctx.return_value.__exit__.return_value=None

                result=service.sync_session({'username':'friend_wxid_123'})
                self.assertTrue(result['ok'])
                self.assertEqual(result['username'],'friend_wxid_123')
                self.assertEqual(result['session']['summary'],'最新测试消息')
        finally:service.shutdown()

    def test_parallel_decrypt_all_execution_and_progress(self):
        from wx4 import decrypt
        test_dir = self.root / 'parallel-decrypt-test'
        src_dir = test_dir / 'source'
        dst_dir = test_dir / 'destination'
        src_dir.mkdir(parents=True)
        dst_dir.mkdir(parents=True)

        keys = {}
        for i in range(8):
            rel = f'msg/shard_{i}.db'
            p = src_dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'x' * 4096)
            keys[rel] = {'enc_key': '0123456789abcdef0123456789abcdef', 'salt': 'aabb'}

        # Add 1 missing file to test skipped
        keys['missing/ghost.db'] = {'enc_key': '0123456789abcdef0123456789abcdef', 'salt': 'ccdd'}

        progress_calls = []
        def track_progress(msg):
            progress_calls.append(msg)

        def mock_decrypt_file(src, dst, key, **kwargs):
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            Path(dst).write_bytes(b'SQLite format 3\x00' + b'\x00' * 4080)
            return {'pages': 1, 'wal_frames': 0}

        with patch('wx4.decrypt.decrypt_file', side_effect=mock_decrypt_file), \
             patch('wx4.decrypt.quick_check', return_value=True):
            res = decrypt.decrypt_all(keys, str(src_dir), str(dst_dir),
                                      progress=track_progress, max_workers=4)

            self.assertEqual(len(res['ok']), 8)
            self.assertEqual(len(res['skipped']), 1)
            self.assertEqual(res['skipped'][0][0], 'missing/ghost.db')
            self.assertEqual(len(res['failed']), 0)
            self.assertEqual(len(progress_calls), 9)

            # Check output files exist
            for i in range(8):
                self.assertTrue((dst_dir / f'msg/shard_{i}.db').is_file())

    def test_global_search_and_media_filter_in_demo_and_service(self):
        folder = self.root / 'search-service-test'
        folder.mkdir()
        service = Service(ASSETS, folder)
        try:
            service.demo()
            # 1. Search for a keyword present in demo messages
            res = service.call('global_search', {'query': '日落'})
            self.assertGreaterEqual(res['total'], 1)
            self.assertGreaterEqual(res['sessions_hit'], 1)
            self.assertTrue(any('日落' in item['text'] for item in res['items']))
            self.assertIn('日落', res['items'][0]['snippet'])
            self.assertIn('session_groups', res)

            # 2. Search for a non-existing keyword
            empty_res = service.call('global_search', {'query': '这是一条绝不存在的搜索词xyz999'})
            self.assertEqual(empty_res['total'], 0)
            self.assertEqual(len(empty_res['items']), 0)

            # 3. Empty query returns empty
            zero_res = service.call('global_search', {'query': ''})
            self.assertEqual(zero_res['total'], 0)

            # 4. Search with kind='media'
            media_res = service.call('global_search', {'query': '', 'kind': 'media'})
            self.assertGreaterEqual(media_res['total'], 1)
            self.assertTrue(all(item['kind'] in ('image', 'video') for item in media_res['items']))

            # 5. Search with kind='file'
            file_res = service.call('global_search', {'query': '', 'kind': 'file'})
            self.assertGreaterEqual(file_res['total'], 1)
            self.assertTrue(all(item['kind'] == 'file' for item in file_res['items']))
            self.assertIn('filename', file_res['items'][0]['extra'])

            # 6. qce_preview with kind='file' and kind='media'
            sessions = service.sessions()
            first_user = sessions[0]['username']
            prev_file = service.call('qce_preview', {
                'peer': {'peerUid': first_user},
                'filter': {'kind': 'file'}
            })
            self.assertGreaterEqual(prev_file['totalCount'], 1)
            self.assertTrue(all(m.get('kind') == 'file' for m in prev_file['messages']))

            prev_media = service.call('qce_preview', {
                'peer': {'peerUid': first_user},
                'filter': {'kind': 'media'}
            })
            self.assertGreaterEqual(prev_media['totalCount'], 1)
            self.assertTrue(all(m.get('kind') in ('image', 'video') for m in prev_media['messages']))
        finally:
            service.shutdown()


if __name__=='__main__':unittest.main()
