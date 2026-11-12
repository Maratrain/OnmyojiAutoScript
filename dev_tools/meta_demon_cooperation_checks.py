"""超鬼王协同心跳、任务收尾截图与截图帧缓存兜底的离线校验。"""
from datetime import datetime, timedelta
import json
import pickle
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import numpy as np

from module.cooperation import Cooperation, prepare_task_cooperation
from module.exception import TaskEnd
from module.image import rpc as image_rpc
from module.image.rpc import ImageClient
from module.image.runtime import ImageRuntime, ImageServerSettings
from tasks.MetaDemon.boss_battle import BossBattle
from tasks.MetaDemon.config import AssistanceRole, MetaDemonMode
import tasks.MetaDemon.assistance as assistance
import tasks.MetaDemon.page as ipages


def write_config(root, name, *, role, peer):
    config = {
        'meta_demon': {
            'scheduler': {'enable': True, 'next_run': '2026-01-01 00:00:00'},
            'meta_demon_config': {'mode': [MetaDemonMode.BOSS_ASSIST.value]},
            'assistance_config': {'role': role.value, 'cooperation_script': peer},
        }
    }
    folder = root / 'config'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f'{name}.json').write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')


class CooperationHeartbeatChecks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        write_config(self.root, 'offer', role=AssistanceRole.OFFERING, peer='assist')
        write_config(self.root, 'assist', role=AssistanceRole.ASSIST, peer='offer')

    def runtime(self, name):
        return Cooperation(name, root=self.root)

    def test_ready_or_busy_peer_does_not_wait(self):
        a, b = self.runtime('offer'), self.runtime('assist')
        b.publish('MetaDemon')
        config = SimpleNamespace(task_delay=Mock())
        with patch('module.cooperation.time.sleep') as sleep:
            self.assertTrue(a.prepare(config, 'MetaDemon', 'assist', defer=False))
        sleep.assert_not_called()

        b.publish('ActivityShikigami')
        with patch('module.cooperation.time.sleep') as sleep:
            self.assertFalse(a.prepare(config, 'MetaDemon', 'assist', defer=False))
        sleep.assert_not_called()

    def test_prepare_rechecks_missing_and_expired_heartbeats_for_thirty_seconds(self):
        a, b = self.runtime('offer'), self.runtime('assist')
        config = SimpleNamespace(task_delay=Mock())
        for expired in (False, True):
            with self.subTest(expired=expired):
                if expired:
                    b.publish('MetaDemon')
                    with b.connect() as db:
                        db.execute('UPDATE runners SET heartbeat=heartbeat-60 WHERE name=?', ('assist',))
                with patch('module.cooperation.time.monotonic', side_effect=(0, 0, 5, 10, 15, 20, 25, 30)), \
                        patch('module.cooperation.time.sleep') as sleep:
                    self.assertFalse(a.prepare(config, 'MetaDemon', 'assist', defer=False))
                self.assertEqual(sleep.call_args_list, [call(5)] * 6)
                self.assertEqual(b.requested(), [])
        config.task_delay.assert_not_called()

    def test_prepare_continues_when_peer_heartbeat_arrives_during_retry(self):
        a, b = self.runtime('offer'), self.runtime('assist')
        config = SimpleNamespace(task_delay=Mock())
        for peer_task in ('', 'MetaDemon'):
            with self.subTest(peer_task=peer_task):
                with b.connect() as db:
                    db.execute('DELETE FROM runners WHERE name=?', ('assist',))
                with patch('module.cooperation.time.monotonic', return_value=0), \
                        patch('module.cooperation.time.sleep', side_effect=lambda seconds: b.publish(peer_task)) as sleep:
                    self.assertTrue(a.prepare(config, 'MetaDemon', 'assist', defer=False))
                sleep.assert_called_once_with(5)
                if peer_task == '':
                    self.assertEqual(b.requested(), [('MetaDemon', 'offer')])
                else:
                    self.assertEqual(b.requested(), [])

    def test_prepare_accepts_peer_heartbeat_on_last_retry(self):
        a, b = self.runtime('offer'), self.runtime('assist')
        config = SimpleNamespace(task_delay=Mock())
        elapsed = 0

        def advance_time(seconds):
            nonlocal elapsed
            elapsed += seconds
            if elapsed == 30:
                b.publish('MetaDemon')

        with patch('module.cooperation.time.monotonic', side_effect=lambda: elapsed), \
                patch('module.cooperation.time.sleep', side_effect=advance_time) as sleep:
            self.assertTrue(a.prepare(config, 'MetaDemon', 'assist', defer=False))
        self.assertEqual(sleep.call_args_list, [call(5)] * 6)


class SingleCooperationRuntimeChecks(unittest.TestCase):
    """调度循环只能有一个协同实例，否则心跳会把已发布的任务名清空。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_second_runtime_clears_published_task(self):
        published = Cooperation('offer', root=self.root)
        heartbeat = Cooperation('offer', root=self.root)
        published.publish('MetaDemon')
        heartbeat.publish('')
        self.assertEqual(published.runner_task('offer'), '')

    def test_ensure_reuses_published_runtime(self):
        from script import Script

        owner = object.__new__(Script)
        owner.config_name = 'offer'
        owner.config = SimpleNamespace()
        runtime = Cooperation('offer', root=self.root)
        runtime.start()
        self.addCleanup(runtime.close)
        owner._cooperation = runtime

        self.assertIs(owner.ensure_cooperation_runtime(), runtime)
        self.assertIs(owner.config.cooperation_runtime, runtime)
        self.assertFalse(hasattr(owner, '_cooperation_runtime'))

        runtime.publish('MetaDemon')
        runtime.publish()  # 心跳沿用同一实例的 active_task
        self.assertEqual(runtime.runner_task('offer'), 'MetaDemon')


class MetaDemonModeGateChecks(unittest.TestCase):
    """改成鬼王战斗后，不得再被历史协同配对拉进校验。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        write_config(self.root, 'offer', role=AssistanceRole.OFFERING, peer='assist')
        write_config(self.root, 'assist', role=AssistanceRole.ASSIST, peer='offer')

    def config(self, mode, *, reload=None, task_call=None):
        model = SimpleNamespace(meta_demon=SimpleNamespace(
            meta_demon_config=SimpleNamespace(mode=[mode]),
            assistance_config=SimpleNamespace(cooperation_script='assist'),
            scheduler=SimpleNamespace(enable=True),
        ))
        config = SimpleNamespace(model=model, config_name='offer',
                                 cooperation_runtime=Mock(peers={}),
                                 reload=reload or Mock(), task_call=task_call or Mock())
        return config

    def test_battle_mode_skips_stale_cooperation_peer(self):
        config = self.config(MetaDemonMode.BOSS_BATTLE)
        prepare_task_cooperation(config, 'MetaDemon')
        config.cooperation_runtime.prepare.assert_not_called()

    def test_assist_mode_still_prepares_peer(self):
        config = self.config(MetaDemonMode.BOSS_ASSIST)
        prepare_task_cooperation(config, 'MetaDemon')
        config.cooperation_runtime.prepare.assert_called_once_with(config, 'MetaDemon', 'assist')

    def test_wake_next_ignores_request_in_battle_mode(self):
        own, peer = Cooperation('offer', root=self.root), Cooperation('assist', root=self.root)
        peer.publish('MetaDemon')
        with own.connect() as db:
            db.execute('INSERT OR REPLACE INTO wakes VALUES (?, ?, ?, ?)',
                       ('offer', 'MetaDemon', 'assist', time.time()))
        self.assertIsNone(own.wake_next(self.config(MetaDemonMode.BOSS_BATTLE)))
        self.assertEqual(own.requested(), [])

    def test_wake_next_accepts_request_in_assist_mode(self):
        own, peer = Cooperation('offer', root=self.root), Cooperation('assist', root=self.root)
        peer.publish('MetaDemon')
        with own.connect() as db:
            db.execute('INSERT OR REPLACE INTO wakes VALUES (?, ?, ?, ?)',
                       ('offer', 'MetaDemon', 'assist', time.time()))
        self.assertEqual(own.wake_next(self.config(MetaDemonMode.BOSS_ASSIST)), 'MetaDemon')
        self.assertEqual(own.requested(), [])


class FinishTaskChecks(unittest.TestCase):
    def test_finish_task_refreshes_screenshot_before_returning_to_main(self):
        owner = object.__new__(BossBattle)
        owner.goto_page = Mock()
        with self.assertRaises(TaskEnd):
            owner.finish_task()
        owner.goto_page.assert_called_once_with(ipages.page_main, skip_first_screenshot=False)


class AssistanceEntryScreenshotChecks(unittest.TestCase):
    """协同等待最长 30 秒，进入鬼王页前必须重新截图。"""

    @staticmethod
    def fake_task():
        swipe = SimpleNamespace(roi_front=(100, 100, 100, 100), roi_back=(100, 500, 100, 100))
        task = Mock()
        task.S_MD_SWIPE_UP = swipe
        task.start_time = datetime.now()
        task.limit_time = timedelta(seconds=60)
        task.total_count = 0
        task.limit_count = 10
        task.State.done = True
        return task

    def test_assistant_entry_refreshes_screenshot(self):
        task = self.fake_task()
        link = Mock()
        link.peer_in_task.return_value = False
        assistance.GhostAssistant(task, link).run()
        task.goto_page.assert_called_once_with(
            assistance.pages.page_meta_demon_boss, skip_first_screenshot=False)

    def test_offering_entry_refreshes_screenshot(self):
        task = self.fake_task()
        assistance.run_offering(task, Mock())
        task.goto_page.assert_called_once_with(
            assistance.pages.page_meta_demon_boss, skip_first_screenshot=False)


class ImageFramePayloadChecks(unittest.TestCase):
    """帧临近 TTL 时客户端必须随请求附上图像数据。"""

    def setUp(self):
        self.image = np.full((4, 4, 3), 5, dtype=np.uint8)
        original = dict(image_rpc._LAST_REGISTERED_FRAME)
        self.addCleanup(image_rpc._LAST_REGISTERED_FRAME.update, original)

    def test_fresh_frame_skips_payload(self):
        image_rpc._LAST_REGISTERED_FRAME.update(
            frame_id='fresh', registered_at=time.time(), expire_seconds=10.0)
        self.assertIsNone(ImageClient._encode_image_payload(self.image, 'fresh'))

    def test_stale_frame_attaches_payload(self):
        image_rpc._LAST_REGISTERED_FRAME.update(
            frame_id='stale', registered_at=time.time() - 30, expire_seconds=10.0)
        payload = ImageClient._encode_image_payload(self.image, 'stale')
        self.assertIsNotNone(payload)
        np.testing.assert_array_equal(pickle.loads(payload), self.image)

    def test_unknown_frame_and_no_frame_attach_payload(self):
        image_rpc._LAST_REGISTERED_FRAME.update(
            frame_id='current', registered_at=time.time(), expire_seconds=10.0)
        for frame_id in ('other', None):
            with self.subTest(frame_id=frame_id):
                payload = ImageClient._encode_image_payload(self.image, frame_id)
                self.assertIsNotNone(payload)
                np.testing.assert_array_equal(pickle.loads(payload), self.image)
        self.assertIsNone(ImageClient._encode_image_payload(None, 'current'))

    def test_register_frame_records_id_and_server_ttl(self):
        client = object.__new__(ImageClient)
        client.client = Mock()
        client.client.register_frame.return_value = {'frame_id': 'abc', 'expire_seconds': 7.0}
        self.assertEqual(client.register_frame(self.image, 'demo')['frame_id'], 'abc')
        self.assertEqual(image_rpc._LAST_REGISTERED_FRAME['frame_id'], 'abc')
        self.assertEqual(image_rpc._LAST_REGISTERED_FRAME['expire_seconds'], 7.0)


class ImageFrameFallbackChecks(unittest.TestCase):
    """服务端帧被清理后，带图像数据的请求应回退成功而非抛 KeyError。"""

    def setUp(self):
        self.runtime = ImageRuntime(ImageServerSettings(
            frame_cache_expire_seconds=10.0, cleanup_interval_seconds=3600))
        self.addCleanup(self.runtime.shutdown)

    def register(self, image):
        return self.runtime.register_frame(pickle.dumps(image), 'demo')['frame_id']

    def expire(self, frame_id):
        with self.runtime._lock:
            self.runtime._frames[frame_id].last_access_at -= 60

    def test_expired_frame_falls_back_to_payload(self):
        frame_id = self.register(np.zeros((4, 4, 3), dtype=np.uint8))
        self.expire(frame_id)
        expected = np.full((4, 4, 3), 7, dtype=np.uint8)
        np.testing.assert_array_equal(
            self.runtime._resolve_image(frame_id, pickle.dumps(expected)), expected)
        self.assertEqual(self.runtime._cache_stats['frame_fallbacks'], 1)

    def test_expired_frame_without_payload_still_raises(self):
        frame_id = self.register(np.zeros((4, 4, 3), dtype=np.uint8))
        self.expire(frame_id)
        with self.assertRaises(KeyError):
            self.runtime._resolve_image(frame_id, None)
        self.assertEqual(self.runtime._cache_stats['frame_fallbacks'], 0)

    def test_live_frame_prefers_cached_image(self):
        cached = np.full((4, 4, 3), 3, dtype=np.uint8)
        frame_id = self.register(cached)
        uploaded = np.full((4, 4, 3), 9, dtype=np.uint8)
        np.testing.assert_array_equal(
            self.runtime._resolve_image(frame_id, pickle.dumps(uploaded)), cached)
        self.assertEqual(self.runtime._cache_stats['frame_fallbacks'], 0)

    def test_client_payload_survives_server_frame_eviction(self):
        image = np.full((4, 4, 3), 6, dtype=np.uint8)
        client = object.__new__(ImageClient)
        client.client = Mock()
        client.client.register_frame.side_effect = (
            lambda payload, name, ttl: self.runtime.register_frame(payload, name))
        client.register_frame(image, 'demo')
        frame_id = image_rpc._LAST_REGISTERED_FRAME['frame_id']
        original = dict(image_rpc._LAST_REGISTERED_FRAME)
        self.addCleanup(image_rpc._LAST_REGISTERED_FRAME.update, original)

        # 模拟协同等待 30 秒：客户端判定帧已临近 TTL，服务端也已清理该帧。
        image_rpc._LAST_REGISTERED_FRAME['registered_at'] -= 30
        payload = ImageClient._encode_image_payload(image, frame_id)
        self.assertIsNotNone(payload)
        self.expire(frame_id)
        np.testing.assert_array_equal(self.runtime._resolve_image(frame_id, payload), image)
        self.assertEqual(self.runtime._cache_stats['frame_fallbacks'], 1)


if __name__ == '__main__':
    unittest.main()
