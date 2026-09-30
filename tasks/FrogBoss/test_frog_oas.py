import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tasks.FrogBoss.frog_oas import (OasHistory, choose_follow, fetch_blogger_prediction,
                                     parse_follow_post, parse_follow_side, parse_side, same_lineup)
from tasks.FrogBoss.oas_sources import DASHEN_BLOGGERS, resolve_follow_list


class OasTests(unittest.TestCase):
    def test_persistence_rewards_and_dedup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.jsonl'
            store = OasHistory(path)
            decision = store.choose('0' * 512, 20, 10, [
                {'uid': 'a', 'side': 'LEFT'}, {'uid': 'b', 'side': 'RIGHT'}])
            self.assertEqual(store.reliability('a'), .5)
            self.assertEqual(store.choose('0' * 512, 10, 20, [])['id'], decision['id'])
            self.assertIsNone(store.settle('1' * 512, 'LEFT'))
            store.settle('0' * 512, 'LEFT')
            self.assertIsNone(store.settle('0' * 512, 'LEFT'))
            reloaded = OasHistory(path)
            self.assertEqual(reloaded.reliability('a'), 1)
            self.assertEqual(reloaded.reliability('b'), 0)
            self.assertEqual(reloaded.reliability('crowd'), 1)
            second = reloaded.choose('1' * 512, 10, 20, [
                {'uid': 'a', 'side': 'LEFT'}, {'uid': 'b', 'side': 'LEFT'}])
            self.assertEqual(second['scores'], {'LEFT': 1, 'RIGHT': 1})
            self.assertEqual(second['mode'], 'win_rate')
            reloaded.settle('1' * 512, 'RIGHT')
            self.assertEqual(reloaded.reliability('a'), .5)
            self.assertEqual(reloaded.reliability('b'), 0)
            self.assertEqual(reloaded.reliability('crowd'), 1)

    def test_fallback_and_missing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            self.assertEqual(store.choose('0' * 512, 1, 2, [])['side'], 'RIGHT')
            self.assertEqual(store.reliability('crowd'), .5)
            with patch('tasks.FrogBoss.frog_oas.random.choice', return_value='LEFT'):
                self.assertEqual(store.choose('1' * 512, 0, 0, [])['side'], 'LEFT')

    def test_cold_start_two_equal_groups(self):
        predictions = [{'uid': str(i), 'side': 'LEFT' if i < 6 else 'RIGHT'} for i in range(9)]
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            agreed = store.choose('0' * 512, 20, 10, predictions)
            self.assertEqual(agreed['side'], 'LEFT')
            self.assertEqual(agreed['scores'], {'LEFT': 2, 'RIGHT': 0})
            with patch('tasks.FrogBoss.frog_oas.random.choice', return_value='RIGHT') as choose:
                opposed = store.choose('1' * 512, 10, 20, predictions)
                self.assertEqual(opposed['scores'], {'LEFT': 1, 'RIGHT': 1})
                self.assertEqual(opposed['side'], 'RIGHT')
                choose.assert_called_once_with(('LEFT', 'RIGHT'))

    def test_ambiguous_text_and_signature(self):
        self.assertEqual(parse_side('本场押红'), 'LEFT')
        self.assertIsNone(parse_side('不押红，押蓝'))
        self.assertIsNone(parse_side('押红还是押蓝'))
        self.assertTrue(same_lineup('0' * 512, '1' * 10 + '0' * 502))
        self.assertFalse(same_lineup('0' * 512, '1' * 512))


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, feeds):
        self._feeds = feeds

    def get(self, url, params=None, timeout=None):
        return _FakeResponse({'result': {'feeds': self._feeds}})


def _feed(text, create_time_ms):
    return {'id': f'feed_{create_time_ms}', 'createTime': create_time_ms,
            'content': json.dumps({'type': 2, 'body': {'text': text}}, ensure_ascii=False)}


class FollowTests(unittest.TestCase):
    NOW = datetime(2026, 9, 30, 17, 45, 0)

    def _ms(self, hour, minute):
        return int(datetime(2026, 9, 30, hour, minute).timestamp() * 1000)

    def test_parse_follow_post(self):
        parsed = parse_follow_post('十周年对弈竞猜第一天\n16:00 右(蓝) 65%±1%\n\n#阴阳师# #面灵气喵# #对弈竞猜#')
        self.assertEqual(parsed, {'side': 'RIGHT', 'slot_hour': 16, 'confidence': 65, 'upset': False})
        parsed = parse_follow_post('十周年对弈竞猜第一天\n12:00 押翻盘 左(红) 51%±1%')
        self.assertEqual(parsed, {'side': 'LEFT', 'slot_hour': 12, 'confidence': 51, 'upset': True})
        parsed = parse_follow_post('【对弈竞猜体验服】\n22:00 右(蓝) 90%+')
        self.assertEqual(parsed['side'], 'RIGHT')
        self.assertEqual(parsed['confidence'], 90)
        self.assertEqual(parse_follow_post('【对弈竞猜体验服】\n18:00 押翻盘 左(红)')['upset'], True)
        self.assertEqual(parse_follow_post('16:00 红(左) 60%')['side'], 'LEFT')
        self.assertEqual(parse_follow_post('16:00 蓝（右）')['side'], 'RIGHT')
        # 复盘行与日常动态不算预测
        self.assertIsNone(parse_follow_post('上局 右(蓝)竞猜成功.jpg'))
        self.assertIsNone(parse_follow_post('【拾光回忆录】阴阳师年度报告\n十年一梦'))
        # 同一行既有本局又有复盘时，只认行首场次的方向
        self.assertEqual(parse_follow_post('16:00 左(红) 上局右(蓝)竞猜成功')['side'], 'LEFT')

    def test_resolve_follow_list(self):
        self.assertEqual(resolve_follow_list('面灵气喵,徐清林'),
                         [DASHEN_BLOGGERS['面灵气喵'], DASHEN_BLOGGERS['徐清林']])
        hex_uid = 'A' * 32
        self.assertEqual(resolve_follow_list(f'{hex_uid} 面灵气喵、{hex_uid.lower()},未知博主'),
                         [hex_uid.lower(), DASHEN_BLOGGERS['面灵气喵']])
        self.assertEqual(resolve_follow_list(''), [])
        self.assertEqual(resolve_follow_list(None), [])

    def test_parse_follow_side_loose_posts(self):
        # 徐清林真实动态样本：无「HH:00 方向」场次行的口语化预测
        self.assertEqual(parse_follow_side(
            '#对弈竞猜# #阴阳师# 这一局相信黄毛和小樱！输的话评论区抽一个小伙伴送花合战。只要蓝不赢可以一直压红。'), 'LEFT')
        self.assertEqual(parse_follow_side(
            '#对弈竞猜# 红赢了一天！也该我蓝色螺螺锤显神威了！蓝色'), 'RIGHT')
        self.assertEqual(parse_follow_side(
            '#对弈竞猜# 九月30日16-18点局红色且看我犬咬死对面。'), 'LEFT')
        # 无关键词、无方向、庆祝帖与复盘歧义均不认
        self.assertIsNone(parse_follow_side('红色且看我犬咬死对面'))
        self.assertIsNone(parse_follow_side('#对弈竞猜# 拿下！'))
        self.assertIsNone(parse_follow_side('#对弈竞猜# 上一局红色赢了，这局蓝色也说不定'))
        self.assertIsNone(parse_follow_side('#对弈竞猜# 别压红，这局不稳'))

    def _choose(self, store, uids, left=20, right=10, wait=None, fetch_side_effect=None):
        now = self.NOW
        signature = '0' * 512
        if fetch_side_effect is None:
            prediction = {'uid': uids[0], 'side': 'LEFT', 'feed_id': 'f1', 'confidence': 79, 'upset': False}
            fetch_side_effect = [prediction]
        with patch('tasks.FrogBoss.frog_oas.datetime') as fake_dt, \
                patch('tasks.FrogBoss.frog_oas.fetch_blogger_prediction',
                      side_effect=list(fetch_side_effect)) as fetch_mock:
            fake_dt.now.return_value = now
            fake_dt.combine = datetime.combine
            fake_dt.min = datetime.min
            fake_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            decision = choose_follow(store, signature, left, right, uids, now=now, wait=wait)
        return decision, fetch_mock

    def test_primary_and_settle(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            uid = DASHEN_BLOGGERS['面灵气喵']
            decision, fetch_mock = self._choose(store, [uid])
            self.assertEqual(decision['side'], 'LEFT')
            self.assertEqual(decision['mode'], 'follow_blogger')
            self.assertEqual(decision['votes'], {uid: 'LEFT'})
            self.assertEqual(decision['source_index'], 0)
            self.assertEqual(decision['confidence'], 79)
            fetch_mock.assert_called_once()
            store.settle('0' * 512, 'LEFT')
            self.assertEqual(store.reliability(uid), 1)

    def test_frozen_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            uids = [DASHEN_BLOGGERS['面灵气喵'], DASHEN_BLOGGERS['徐清林']]
            first, _ = self._choose(store, uids)
            second, fetch_mock = self._choose(store, uids, left=1, right=2)
            self.assertEqual(second['id'], first['id'])
            fetch_mock.assert_not_called()

    def test_fallback_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            uids = [DASHEN_BLOGGERS['面灵气喵'], DASHEN_BLOGGERS['徐清林']]
            prediction = {'uid': uids[1], 'side': 'RIGHT', 'feed_id': 'f2', 'confidence': None, 'upset': False}
            decision, fetch_mock = self._choose(store, uids, fetch_side_effect=[None, prediction])
            self.assertEqual(decision['side'], 'RIGHT')
            self.assertEqual(decision['source_index'], 1)
            self.assertEqual(fetch_mock.call_count, 2)

    def test_terminal_majority(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            uids = [DASHEN_BLOGGERS['面灵气喵'], DASHEN_BLOGGERS['徐清林']]
            decision, _ = self._choose(store, uids, left=20, right=10,
                                       fetch_side_effect=[None, None])
            self.assertEqual(decision['mode'], 'follow_fallback_majority')
            self.assertEqual(decision['side'], 'LEFT')
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            uids = [DASHEN_BLOGGERS['面灵气喵'], DASHEN_BLOGGERS['徐清林']]
            decision, _ = self._choose(store, uids, left=10, right=10,
                                       fetch_side_effect=[None, None])
            self.assertEqual(decision['side'], 'RIGHT')

    def test_polling_until_declined(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            uids = [DASHEN_BLOGGERS['面灵气喵']]
            waits = []

            def wait(seconds_left):
                waits.append(seconds_left)
                return len(waits) < 2  # 第一次继续轮询，第二次声明放弃

            decision, fetch_mock = self._choose(store, uids, wait=wait,
                                                fetch_side_effect=[None, None])
            self.assertEqual(len(waits), 2)
            # 17:45 → 场次 18:00 结束前 2 分钟，可等 13 分钟
            self.assertAlmostEqual(waits[0], 13 * 60, delta=5)
            self.assertEqual(fetch_mock.call_count, 2)
            self.assertEqual(decision['mode'], 'follow_fallback_majority')

    def test_fetch_blogger_prediction_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            uid = DASHEN_BLOGGERS['面灵气喵']
            strict_feed_id = 'feed_' + str(self._ms(17, 32))
            feeds = [
                _feed('【对弈竞猜体验服】\n16:00 左(红) 80%', self._ms(17, 20)),
                _feed('十周年对弈竞猜第一天\n18:00 右(蓝) 70%', self._ms(17, 50)),
                _feed('十周年对弈竞猜第一天\n16:00 右(蓝) 65%±1%', self._ms(17, 32)),
                _feed('十周年对弈竞猜第一天\n14:00 左(红) 79%±1%', self._ms(15, 23)),
                _feed('【拾光回忆录】阴阳师年度报告', self._ms(16, 0)),
                _feed('#对弈竞猜# 九月30日16-18点局蓝色必胜。', self._ms(17, 10)),
            ]
            with patch('tasks.FrogBoss.frog_oas.datetime') as fake_dt:
                fake_dt.now.return_value = self.NOW
                fake_dt.fromtimestamp = datetime.fromtimestamp
                fake_dt.combine = datetime.combine
                fake_dt.min = datetime.min
                fake_dt.side_effect = lambda *a, **k: datetime(*a, **k)
                prediction = fetch_blogger_prediction(_FakeSession(feeds), uid,
                                                      self.NOW.date(), 16, store, set())
                self.assertIsNotNone(prediction)
                self.assertEqual(prediction['side'], 'RIGHT')
                self.assertEqual(prediction['confidence'], 65)
                self.assertFalse(prediction['upset'])
                # 严格帖用过之后，同博主本场口语帖仍可接棒
                prediction = fetch_blogger_prediction(_FakeSession(feeds), uid,
                                                      self.NOW.date(), 16, store,
                                                      {(uid, strict_feed_id)})
                self.assertIsNotNone(prediction)
                self.assertEqual(prediction['side'], 'RIGHT')
                self.assertIsNone(prediction['confidence'])
                # 场次已变时不再接受
                self.assertIsNone(fetch_blogger_prediction(_FakeSession(feeds), uid,
                                                           self.NOW.date(), 18, store, set()))


if __name__ == '__main__':
    unittest.main()
