import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tasks.FrogBoss.frog_oas import (OasHistory, choose_follow, fetch_blogger_prediction,
                                     format_decision, format_result, parse_follow_post,
                                     parse_follow_side, parse_record_stamp, parse_side,
                                     same_lineup, side_name, slot_hour_of, slot_label)
from tasks.FrogBoss.oas_sources import DASHEN_BLOGGERS, blogger_name, resolve_follow_list


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
            # a/crowd 各 1 胜平滑为 2/3，b 1 负平滑为 1/3；左 = 2/3 + 1/3 - 1 ≈ 0
            self.assertAlmostEqual(second['scores']['LEFT'], 0, places=12)
            self.assertAlmostEqual(second['scores']['RIGHT'], 1 / 6, places=12)
            self.assertEqual(second['mode'], 'signed_win_rate')
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

    def test_bet_outcome_settlement_enters_weighted_mode(self):
        for side in ('LEFT', 'RIGHT'):
            for won in (True, False):
                with self.subTest(side=side, won=won), tempfile.TemporaryDirectory() as directory:
                    store = OasHistory(Path(directory) / 'history.jsonl')
                    left, right = (20, 10) if side == 'LEFT' else (10, 20)
                    first = store.choose('0' * 512, left, right, [{'uid': 'a', 'side': side}])
                    result = store.settle('0' * 512, bet_won=won)
                    expected = side if won else ('RIGHT' if side == 'LEFT' else 'LEFT')
                    self.assertEqual(result['winner'], expected)
                    self.assertEqual(result['id'], first['id'])
                    self.assertEqual(result['source'], 'bet_outcome')
                    self.assertEqual(store.reliability('a'), float(won))
                    self.assertIsNone(store.settle('0' * 512, bet_won=won))
                    reloaded = OasHistory(store.path)
                    second = reloaded.choose('1' * 512, left, right, [{'uid': 'a', 'side': side}])
                    self.assertEqual(second['mode'], 'signed_win_rate')

    def test_signed_weights_penalize_wrong_sources_and_leave_newcomers_neutral(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            for index in range(2):
                store.append('decision', id=f'p{index}', slot=f'2026-09-28:{5 + index}',
                             signature='1' * 512, votes={'wrong': 'LEFT', 'correct': 'RIGHT'})
                store.append('result', id=f'p{index}', winner='RIGHT')
            decision = store.choose('0' * 512, 20, 10, [
                {'uid': 'wrong', 'side': 'LEFT'},
                {'uid': 'correct', 'side': 'RIGHT'},
                {'uid': 'newcomer', 'side': 'LEFT'},
            ])
            # 连错来源平滑后 0.25、连对来源 0.75、无战绩 0.5：负向权重反推多数押的一侧
            self.assertEqual(decision['win_rates'], {
                'wrong': .25, 'correct': .75, 'newcomer': .5, 'crowd': .5})
            self.assertEqual(decision['weights'], {
                'wrong': -.25, 'correct': .25, 'newcomer': 0, 'crowd': 0})
            self.assertEqual(decision['scores'], {'LEFT': -.25, 'RIGHT': .25})
            self.assertEqual(decision['side'], 'RIGHT')
            self.assertEqual(decision['strategy_version'], 3)

    def test_negative_consensus_can_select_the_opposite_side(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            for index in range(2):
                store.append('decision', id=f'p{index}', slot=f'2026-09-28:{5 + index}',
                             signature='1' * 512, votes={'a': 'LEFT'})
                store.append('result', id=f'p{index}', winner='RIGHT')
            decision = store.choose('0' * 512, 20, 10, [{'uid': 'a', 'side': 'LEFT'}])
            self.assertEqual(decision['weights'], {'a': -.25, 'crowd': 0})
            self.assertEqual(decision['scores'], {'LEFT': -.25, 'RIGHT': 0})
            self.assertEqual(decision['side'], 'RIGHT')

    def test_signed_weights_use_smoothed_rate_and_randomize_zero_tie(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            for index in range(2):
                store.append('decision', id=f'p{index}', slot=f'2026-09-28:{5 + index}',
                             signature='1' * 512, votes={'a': 'LEFT', 'b': 'RIGHT'})
                store.append('result', id=f'p{index}', winner='RIGHT')
            decision = store.choose('0' * 512, 0, 0, [
                {'uid': 'a', 'side': 'LEFT'}, {'uid': 'b', 'side': 'RIGHT'}])
            self.assertEqual(decision['weights'], {'a': -.25, 'b': .25})
            self.assertEqual(decision['side'], 'RIGHT')
            with patch('tasks.FrogBoss.frog_oas.random.choice', return_value='LEFT') as choose:
                tied = store.choose('1' * 512, 0, 0, [
                    {'uid': 'a', 'side': 'LEFT'}, {'uid': 'b', 'side': 'LEFT'}])
            self.assertEqual(tied['scores'], {'LEFT': 0, 'RIGHT': 0})
            self.assertTrue(tied['random_tiebreak'])
            choose.assert_called_once_with(('LEFT', 'RIGHT'))

    def test_bet_outcome_rejects_missing_or_ambiguous_lineup(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            first = store.choose('0' * 512, 20, 10, [])
            self.assertIsNone(store.settle('1' * 512, bet_won=True))
            duplicate = dict(first)
            for key in ('kind', 'version', 'recorded_at'):
                duplicate.pop(key)
            duplicate['id'] = 'another-round'
            store.append('decision', **duplicate)
            self.assertIsNone(store.settle('0' * 512, bet_won=True))
            self.assertFalse(any(e['kind'] == 'result' for e in store.events))

    def test_winner_icons_take_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            store.choose('0' * 512, 20, 10, [])
            result = store.settle('0' * 512, 'RIGHT', bet_won=True)
            self.assertEqual(result['winner'], 'RIGHT')
            self.assertEqual(result['source'], 'winner_icons')

    def test_record_page_exact_round_and_dedup(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            store.append('decision', id='ten', slot='2026-09-30:5', side='LEFT',
                         votes={'a': 'LEFT', 'crowd': 'LEFT'})
            store.append('decision', id='twelve', slot='2026-09-30:6', side='RIGHT',
                         votes={'a': 'RIGHT', 'crowd': 'LEFT'})
            result = store.settle_record('2026.09.30 12:00', False)
            self.assertEqual(result['id'], 'twelve')
            self.assertEqual(result['winner'], 'LEFT')
            self.assertEqual(result['source'], 'record_page')
            self.assertEqual(store.reliability('a'), 0)
            self.assertEqual(store.reliability('crowd'), 1)
            self.assertIsNone(store.settle_record('2026.09.30 12:00', False))
            self.assertEqual(len([e for e in store.events if e['kind'] == 'result']), 1)
            self.assertEqual(store.settle_record('2026.09.30 10:00', True)['winner'], 'LEFT')

    def test_record_page_rejects_invalid_unknown_and_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            store.append('decision', id='a', slot='2026-09-30:6', side='LEFT', votes={})
            for stamp in ('12:00', '2026.09.30 13:00', '2026.09.30 12:30',
                          '2026.02.30 12:00', '2099.09.30 12:00', '2026.09.29 12:00'):
                self.assertIsNone(store.settle_record(stamp, True))
            self.assertIsNone(store.settle_record('2026.09.30 12:00', None))
            self.assertIsNotNone(store.settle_record('2026.09.30 12:00', True))
            self.assertIsNone(store.settle_record('2026.09.30 12:00', False))
            self.assertEqual(store.events[-1]['reason'], 'conflicting_record_result')

    def test_record_stamp_parses_ocr_merged_forms(self):
        """记录页 OCR 粘连时间戳必须能解析，且年份里的数字不得被误当场次小时"""
        cases = {
            '2026.09.30 12:00': datetime(2026, 9, 30, 12),
            '2026.09.301200': datetime(2026, 9, 30, 12),
            '2026.09.3022:00': datetime(2026, 9, 30, 22),
            '2026.09.302000': datetime(2026, 9, 30, 20),
            '2026.09.30100': datetime(2026, 9, 30, 10),
            '2026.10.01.10:00': datetime(2026, 10, 1, 10),
            '2026.10.0112:00': datetime(2026, 10, 1, 12),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_record_stamp(text), expected)
        for text in ('12:00', '2026.09.30 13:00', '2026.09.30 12:30', '2026.13.01 10:00'):
            with self.subTest(text=text):
                self.assertIsNone(parse_record_stamp(text))
        self.assertEqual(slot_label('2026.09.301200'), '09-30 第2场(12:00)')

    def test_settle_record_accepts_ocr_merged_stamp(self):
        """粘连时间戳应能归因到对应场次的决策"""
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            store.append('decision', id='ten', slot='2026-09-30:5', side='LEFT',
                         votes={'a': 'LEFT'})
            store.append('decision', id='twelve', slot='2026-09-30:6', side='RIGHT',
                         votes={'a': 'RIGHT'})
            self.assertEqual(store.settle_record('2026.09.30100', True)['id'], 'ten')
            self.assertEqual(store.settle_record('2026.09.301200', False)['id'], 'twelve')
            self.assertEqual(store.reliability('a'), 0.5)

    def test_record_page_does_not_guess_between_duplicate_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            for key in ('a', 'b'):
                store.append('decision', id=key, slot='2026-09-30:6', side='LEFT', votes={})
            self.assertIsNone(store.settle_record('2026.09.30 12:00', True))
            self.assertFalse(any(e['kind'] == 'result' for e in store.events))

    def test_selected_side_verifies_bet_and_keeps_raw_result(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            store.append('decision', id='a', slot='2026-09-30:6', side='RIGHT',
                         votes={'a': 'RIGHT', 'crowd': 'LEFT'})
            result = store.settle_record('2026.09.30 12:00', False, selected_side='RIGHT')
            self.assertEqual(result['winner'], 'LEFT')
            self.assertEqual(store.reliability('crowd'), 1)
            self.assertEqual(store.reliability('a'), 0)
            self.assertIsNone(store.settle_record('2026.09.30 12:00', False, selected_side='RIGHT'))
            self.assertEqual(len([e for e in store.events if e['kind'] == 'record']), 1)
            self.assertIsNone(store.settle_record('2026.09.30 10:00', True, selected_side='LEFT'))
            self.assertEqual(len([e for e in store.events if e['kind'] == 'record']), 2)

    def test_selected_side_mismatch_does_not_update_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            store.append('decision', id='a', slot='2026-09-30:6', side='LEFT', votes={'a': 'LEFT'})
            self.assertIsNone(store.settle_record('2026.09.30 12:00', False, selected_side='RIGHT'))
            self.assertEqual(store.events[-1]['reason'], 'record_bet_side_mismatch')
            self.assertEqual(store.reliability('a'), .5)

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

    def test_slot_hour_of(self):
        # 屏幕上是当前正在竞猜的场次：中途进场与场次末尾进场都向下取整
        self.assertEqual(slot_hour_of(datetime(2026, 10, 1, 13, 35)), 12)
        self.assertEqual(slot_hour_of(datetime(2026, 10, 1, 13, 45)), 12)
        self.assertEqual(slot_hour_of(datetime(2026, 10, 1, 11, 49)), 10)
        self.assertEqual(slot_hour_of(datetime(2026, 10, 1, 12, 50)), 12)
        self.assertEqual(slot_hour_of(datetime(2026, 10, 1, 10, 30)), 10)
        self.assertEqual(slot_hour_of(datetime(2026, 10, 1, 23, 50)), 22)
        # 首场开始前进场押的是即将开始的 10:00 场（补结算匹配所需）
        self.assertEqual(slot_hour_of(datetime(2026, 10, 1, 9, 45)), 10)

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

    def test_format_decision_and_result(self):
        follow = format_decision({'slot': '2026-09-30:11', 'left': 1792, 'right': 7019, 'side': 'RIGHT',
                                  'mode': 'follow_blogger', 'source_uid': DASHEN_BLOGGERS['面灵气喵'],
                                  'confidence': 58, 'upset': False})
        self.assertIn('2026-09-30 22:00-24:00 场次', follow)
        self.assertIn('跟单 面灵气喵 押 右(蓝)（预测胜率 58%）', follow)
        self.assertIn('当前人数 左 1792 : 右 7019', follow)
        fallback = format_decision({'slot': '2026-09-30:5', 'left': 1, 'right': 2, 'side': 'RIGHT',
                                    'mode': 'follow_fallback_majority'})
        self.assertIn('跟单博主全部无预测，回退押人数多的一方 右(蓝)', fallback)
        weighted = format_decision({'slot': '2026-09-30:5', 'left': 3, 'right': 4, 'side': 'LEFT',
                                    'mode': 'signed_win_rate', 'scores': {'LEFT': 1.5, 'RIGHT': -0.5},
                                    'weights': {'a': 1, 'b': -.8}})
        self.assertIn('按来源平滑胜率加权 押 左(红)（得分 左 1.50 : 右 -0.50，2 个来源）', weighted)
        cold = format_decision({'slot': '2026-09-30:5', 'left': 3, 'right': 4, 'side': 'RIGHT',
                                'mode': 'cold_start', 'expert_side': 'RIGHT', 'crowd_side': None,
                                'random_tiebreak': False})
        self.assertIn('冷启动投票 押 右(蓝)（专家多数 右(蓝)，人群 无）', cold)
        tie = format_decision({'slot': '2026-09-30:5', 'left': 0, 'right': 0, 'side': 'RIGHT',
                               'mode': 'follow_fallback_majority', 'random_tiebreak': True})
        self.assertIn('平票随机', tie)
        self.assertEqual(side_name('LEFT'), '左(红)')
        self.assertEqual(blogger_name(DASHEN_BLOGGERS['面灵气喵']), '面灵气喵')
        self.assertEqual(blogger_name('deadbeef' + '0' * 24), 'deadbeef')
        self.assertEqual(format_result({'winner': 'RIGHT',
                                        'outcomes': {DASHEN_BLOGGERS['面灵气喵']: True}}),
                         '右(蓝) 获胜（面灵气喵正确）')
        self.assertEqual(format_result({'winner': 'LEFT', 'outcomes': {}}), '左(红) 获胜')

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
