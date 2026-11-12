"""超鬼王协同心跳等待与任务收尾截图的离线校验。"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.cooperation import Cooperation, prepare_task_cooperation
from module.exception import TaskEnd
from tasks.MetaDemon.boss_battle import BossBattle
from tasks.MetaDemon.config import AssistanceRole, MetaDemonMode
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


if __name__ == '__main__':
    unittest.main()
