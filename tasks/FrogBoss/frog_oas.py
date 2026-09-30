"""Persistent, outcome-verified weighted voting. Scores are not win probabilities."""
import json
import re
import random
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import cv2
import requests

from tasks.FrogBoss.oas_sources import DASHEN_UIDS

# 跟单等待：最高优先级博主未发帖时每 45 秒重试，场次结束前 2 分钟停止等待。
FOLLOW_POLL_INTERVAL = 45
FOLLOW_DEADLINE_MARGIN_MINUTES = 2
# 只扫描博主最近若干条动态即可覆盖当前场次。
FOLLOW_FEED_LIMIT = 10


def fingerprint(image):
    # Only the two lineups: excludes countdown, votes, chest and result text.
    bits = []
    for x in (300, 807):
        crop = image[112:233, x:x + 398]
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        small = cv2.resize(gray, (33, 8))
        bits.extend((small[:, 1:] > small[:, :-1]).flatten())
    return ''.join('1' if bit else '0' for bit in bits)


def same_lineup(a, b):
    return len(a) == len(b) == 512 and sum(x != y for x, y in zip(a, b)) <= 20


def parse_side(text):
    # Ambiguous text is deliberately excluded rather than guessed by word order.
    red = bool(re.search(r'押红|押左|压红|压左|我红|我左|红优|红方胜|红色胜', text))
    blue = bool(re.search(r'押蓝|押右|压蓝|压右|我蓝|我右|蓝优|蓝方胜|蓝色胜', text))
    if re.search(r'不押|不压|别押|别压|不要押|不要压', text):
        return None
    return ('LEFT' if red else 'RIGHT') if red != blue else None


# 跟单帖的场次行，如「16:00 右(蓝) 65%±1%」「12:00 押翻盘 左(红) 51%±1%」。
# 只认行首 HH:00 的行，规避「上局 右(蓝)竞猜成功」这类复盘行的干扰。
FOLLOW_SLOT_LINE = re.compile(
    r'^\s*(\d{1,2}):00\s+(?:(押翻盘)\s+)?(左[（(]\s*红\s*[)）]|红[（(]\s*左\s*[)）]|右[（(]\s*蓝\s*[)）]|蓝[（(]\s*右\s*[)）])\s*(\d{1,3})?\s*%?')


def parse_follow_post(text):
    """解析跟单帖，返回 dict(side, slot_hour, confidence, upset)，非预测帖返回 None。"""
    for line in (text or '').splitlines():
        match = FOLLOW_SLOT_LINE.match(line)
        if match is None:
            continue
        hour, upset, direction, confidence = match.groups()
        side = 'LEFT' if direction.startswith(('左', '红')) else 'RIGHT'
        return dict(side=side, slot_hour=int(hour),
                    confidence=int(confidence) if confidence else None,
                    upset=bool(upset))
    return None


def parse_follow_side(text):
    """跟单降级解析：无「HH:00 方向」场次行的口语化预测（如徐清林）。

    必须带对弈竞猜关键词，方向词比 parse_side 放宽到裸的红色/蓝色/红方/蓝方；
    两侧同时出现或出现不押字样时按歧义处理返回 None。
    """
    if '对弈竞猜' not in (text or ''):
        return None
    red = bool(re.search(r'押红|押左|压红|压左|我红|我左|红优|红方胜|红色胜|红色|红方', text))
    blue = bool(re.search(r'押蓝|押右|压蓝|压右|我蓝|我右|蓝优|蓝方胜|蓝色胜|蓝色|蓝方', text))
    if re.search(r'不押|不压|别押|别压|不要押|不要压', text):
        return None
    return ('LEFT' if red else 'RIGHT') if red != blue else None


class OasHistory:
    def __init__(self, path):
        self.path = Path(path)
        self.events = []
        if self.path.exists():
            for line in self.path.read_text(encoding='utf-8').splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue  # Ignore a truncated final record after interruption.
                if isinstance(event, dict):
                    self.events.append(event)

    def append(self, kind, **data):
        event = dict(version=1, kind=kind, recorded_at=datetime.now().isoformat(), **data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Leading newline separates a possible truncated tail from the new event.
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write('\n' + json.dumps(event, ensure_ascii=False) + '\n')
            stream.flush()
        self.events.append(event)
        return event

    def reliability(self, source):
        decisions = {e['id']: e for e in self.events if e.get('kind') == 'decision'}
        correct = total = 0
        seen = set()
        for result in self.events:
            if result.get('kind') != 'result' or result['id'] in seen:
                continue
            seen.add(result['id'])
            vote = decisions.get(result['id'], {}).get('votes', {}).get(source)
            if vote in ('LEFT', 'RIGHT'):
                total += 1
                correct += vote == result['winner']
        # Unverified newcomers start neutral; verified sources use raw win rate.
        return correct / total if total else 0.5

    def settle(self, signature, winner=None, *, bet_won=None):
        if winner not in ('LEFT', 'RIGHT') and type(bet_won) is not bool:
            self.append('unverified_result', signature=signature,
                        reason='missing_winner_and_bet_outcome')
            return None
        # Include already settled records when checking ambiguity: never transfer
        # an old result to a newer decision with an identical lineup.
        matches = [e for e in self.events if e.get('kind') == 'decision'
                   and same_lineup(e['signature'], signature)]
        if len(matches) != 1:
            self.append('unverified_result', signature=signature, winner=winner,
                        reason='missing_or_ambiguous_decision')
            return None
        decision = matches[0]
        if any(e.get('kind') == 'result' and e['id'] == decision['id'] for e in self.events):
            return None
        source = 'winner_icons'
        if winner not in ('LEFT', 'RIGHT'):
            side = decision.get('side')
            if side not in ('LEFT', 'RIGHT'):
                self.append('unverified_result', signature=signature,
                            reason='missing_bet_side')
                return None
            winner = side if bet_won else ('RIGHT' if side == 'LEFT' else 'LEFT')
            source = 'bet_outcome'
        return self.append('result', id=decision['id'], winner=winner,
                           source=source, bet_won=bet_won,
                           outcomes={s: v == winner for s, v in decision['votes'].items()})

    def settle_record(self, time_text, bet_won, selected_side=None):
        """按「日期+整点场次」精确关联最新可见记录，绝不按阵容猜测。"""
        match = re.fullmatch(r'\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s+(\d{1,2})[:：](\d{2})\s*', str(time_text))
        played = None
        if match:
            try:
                played = datetime(*map(int, match.groups()))
            except ValueError:
                pass
        if (played is None or played.hour not in range(10, 24, 2)
                or played.minute != 0 or played > datetime.now()
                or type(bet_won) is not bool):
            self.append('unverified_result', time_text=str(time_text),
                        reason='invalid_record_time_or_outcome')
            return None
        slot = f'{played.date()}:{played.hour // 2}'
        if selected_side in ('LEFT', 'RIGHT'):
            observed_winner = selected_side if bet_won else ('RIGHT' if selected_side == 'LEFT' else 'LEFT')
            observations = [e for e in self.events if e.get('kind') == 'record' and e.get('slot') == slot]
            if any(e['winner'] != observed_winner or e['selected_side'] != selected_side for e in observations):
                self.append('unverified_result', slot=slot, reason='conflicting_record_observation')
                return None
            if not observations:
                self.append('record', slot=slot, winner=observed_winner,
                            selected_side=selected_side, bet_won=bet_won, time_text=str(time_text))
        matches = [e for e in self.events if e.get('kind') == 'decision' and e.get('slot') == slot]
        if len(matches) != 1 or matches[0].get('side') not in ('LEFT', 'RIGHT'):
            self.append('unverified_result', slot=slot,
                        reason='missing_or_ambiguous_record_decision')
            return None
        decision = matches[0]
        side = selected_side if selected_side is not None else decision['side']
        if side not in ('LEFT', 'RIGHT') or side != decision['side']:
            self.append('unverified_result', slot=slot, selected_side=selected_side,
                        reason='record_bet_side_mismatch')
            return None
        winner = side if bet_won else ('RIGHT' if side == 'LEFT' else 'LEFT')
        previous = [e for e in self.events if e.get('kind') == 'result' and e.get('id') == decision['id']]
        if previous:
            if any(e['winner'] != winner for e in previous):
                self.append('unverified_result', slot=slot, winner=winner,
                            reason='conflicting_record_result')
            return None
        return self.append('result', id=decision['id'], slot=slot, winner=winner,
                           source='record_page', bet_won=bet_won, selected_side=side,
                           outcomes={s: v == winner for s, v in decision['votes'].items()})

    def choose(self, signature, left, right, predictions):
        now = datetime.now()
        # Re-entry in the same slot reuses the original frozen decision.
        slot = f'{now.date()}:{now.hour // 2}'
        for e in reversed(self.events):
            if e.get('kind') == 'decision' and e['slot'] == slot and same_lineup(e['signature'], signature):
                return e
        crowd = ('LEFT' if left > right else 'RIGHT') if left != right and left + right > 0 else None
        votes = {p['uid']: p['side'] for p in predictions if p.get('side') in ('LEFT', 'RIGHT')}
        expert_left = sum(v == 'LEFT' for v in votes.values())
        expert_right = sum(v == 'RIGHT' for v in votes.values())
        expert_side = ('LEFT' if expert_left > expert_right else 'RIGHT') if expert_left != expert_right else None
        if crowd:
            votes['crowd'] = crowd
        cold_start = not any(e.get('kind') == 'result' for e in self.events)
        weights = {} if cold_start else {uid: self.reliability(uid) for uid in votes}
        scores = {'LEFT': 0.0, 'RIGHT': 0.0}
        if cold_start:
            # Two equal votes: the expert majority as a whole and the crowd.
            for vote in (expert_side, crowd):
                if vote:
                    scores[vote] += 1
        else:
            for uid, vote in votes.items():
                scores[vote] += weights[uid]
        tied = abs(scores['LEFT'] - scores['RIGHT']) < 1e-12
        side = random.choice(('LEFT', 'RIGHT')) if tied else max(scores, key=scores.get)
        return self.append('decision', id=uuid4().hex, slot=slot, signature=signature,
                           left=left, right=right, votes=votes, weights=weights,
                           scores=scores, side=side, strategy_version=2,
                           mode='cold_start' if cold_start else 'win_rate',
                           expert_counts={'LEFT': expert_left, 'RIGHT': expert_right},
                           expert_side=expert_side, crowd_side=crowd, random_tiebreak=tied)


def fetch_predictions(history):
    now = datetime.now()
    used = {(e.get('uid'), e.get('feed_id')) for e in history.events
            if e.get('kind') == 'fetch' and e.get('accepted')}
    predictions = []
    with requests.Session() as session:
        for uid in DASHEN_UIDS:
            feed_id = None
            try:
                response = session.get('https://inf.ds.163.com/v1/web/feed/basic/getSomeOneFeeds',
                                       params={'feedTypes': '1,2,3,4,6,7,10,11', 'someOneUid': uid}, timeout=(3, 5))
                response.raise_for_status()
                feeds = response.json().get('result', {}).get('feeds', [])
                if not feeds:
                    history.append('fetch', uid=uid, accepted=False, reason='no_feed')
                    continue
                feed_id = feeds[0]['id']
                response = session.get('https://inf.ds.163.com/v1/web/feed/basic/facade',
                                       params={'feedId': feed_id}, timeout=(3, 5))
                response.raise_for_status()
                feed = response.json()['result']['feed']
                content = feed['content']
                if isinstance(content, str):
                    content = json.loads(content)
                body = content['body']['text']
                raw_time = feed.get('createTime')
                published = None
                try:
                    published = datetime.fromtimestamp(float(raw_time) / 1000)
                except (TypeError, ValueError, OverflowError, OSError):
                    pass
                side = parse_side(body)
                fresh = published is not None and published.date() == now.date() and published.hour // 2 == now.hour // 2 and published <= now
                accepted = fresh and side is not None and (uid, feed_id) not in used
                history.append('fetch', uid=uid, feed_id=feed_id, create_time=raw_time,
                               body=body, side=side, accepted=accepted,
                               reason='accepted' if accepted else 'stale_unknown_ambiguous_or_duplicate')
                if accepted:
                    predictions.append(dict(uid=uid, side=side, feed_id=feed_id))
            except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
                history.append('fetch', uid=uid, feed_id=feed_id, accepted=False,
                               reason='request_or_parse_error', error=str(exc))
    return predictions


def fetch_blogger_prediction(session, uid, slot_date, slot_hour, history, used):
    """拉取单个博主当前场次的跟单帖；无可用预测返回 None，每次尝试都记入 fetch 事件。"""
    feed_id = None
    try:
        response = session.get('https://inf.ds.163.com/v1/web/feed/basic/getSomeOneFeeds',
                               params={'feedTypes': '1,2,3,4,6,7,10,11', 'someOneUid': uid}, timeout=(3, 5))
        response.raise_for_status()
        feeds = response.json().get('result', {}).get('feeds', [])
        for feed in feeds[:FOLLOW_FEED_LIMIT]:
            content = feed.get('content')
            if isinstance(content, str):
                content = json.loads(content)
            body = content['body']['text']
            if '体验服' in body:
                continue  # 体验服预测与正式服场次无关
            feed_id = feed['id']
            published = None
            try:
                published = datetime.fromtimestamp(float(feed.get('createTime')) / 1000)
            except (TypeError, ValueError, OverflowError, OSError):
                pass
            fresh = (published is not None and published.date() == slot_date
                     and published.hour // 2 == slot_hour // 2 and published <= datetime.now())
            parsed = parse_follow_post(body)
            if parsed is not None:
                if parsed['slot_hour'] != slot_hour:
                    # 文案标注的是其他场次（如提前发下一场），整帖方向只对那一场有效
                    history.append('fetch', uid=uid, feed_id=feed_id, accepted=False,
                                   reason='slot_mismatch', slot_hour=parsed['slot_hour'])
                    continue
                side, confidence, upset = parsed['side'], parsed['confidence'], parsed['upset']
            else:
                # 无场次行的口语化预测（如徐清林），无场次标注只能信任发布时间
                side = parse_follow_side(body)
                confidence, upset = None, False
            if side is None:
                continue  # 非预测动态（复盘、日常等）
            if not fresh or (uid, feed_id) in used:
                history.append('fetch', uid=uid, feed_id=feed_id, accepted=False,
                               reason='stale_or_duplicate')
                continue
            prediction = dict(uid=uid, side=side, feed_id=feed_id,
                              confidence=confidence, upset=upset)
            history.append('fetch', uid=uid, feed_id=feed_id, accepted=True,
                           body=body, side=side, confidence=confidence)
            return prediction
        history.append('fetch', uid=uid, feed_id=None, accepted=False, reason='no_prediction_yet')
        return None
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
        history.append('fetch', uid=uid, feed_id=feed_id, accepted=False,
                       reason='request_or_parse_error', error=str(exc))
        return None


def choose_follow(history, signature, left, right, uids, now=None, wait=None):
    """跟单指定博主：按优先级取第一位有当前场次预测的博主，全部扑空回退押人数多的一方。

    wait(seconds_left) 由调用方注入：等待期间保持设备心跳，返回 False 或剩余时间
    耗尽（场次结束前 FOLLOW_DEADLINE_MARGIN_MINUTES 分钟）则停止轮询。
    同一场次同一阵容重复进入时复用已冻结的决策，不会重复下注或改单。
    """
    now = now or datetime.now()
    slot_date, slot_hour = now.date(), now.hour // 2 * 2
    slot = f'{slot_date}:{slot_hour // 2}'
    for event in reversed(history.events):
        if (event.get('kind') == 'decision' and event['slot'] == slot
                and event.get('mode', '').startswith('follow')
                and same_lineup(event['signature'], signature)):
            return event
    used = {(e.get('uid'), e.get('feed_id')) for e in history.events
            if e.get('kind') == 'fetch' and e.get('accepted')}
    slot_end = datetime.combine(slot_date, datetime.min.time()).replace(hour=slot_hour) + timedelta(hours=2)
    deadline = slot_end - timedelta(minutes=FOLLOW_DEADLINE_MARGIN_MINUTES)
    prediction = None
    source_index = None
    with requests.Session() as session:
        for index, uid in enumerate(uids):
            while True:
                prediction = fetch_blogger_prediction(session, uid, slot_date, slot_hour, history, used)
                if prediction is not None:
                    break
                if index > 0 or wait is None:
                    break  # 降级博主只做一次即时抓取，不再等待
                seconds_left = (deadline - datetime.now()).total_seconds()
                if seconds_left <= 0 or not wait(seconds_left):
                    break
            if prediction is not None:
                source_index = index
                break
    if prediction is not None:
        return history.append('decision', id=uuid4().hex, slot=slot, signature=signature,
                              left=left, right=right, votes={prediction['uid']: prediction['side']},
                              weights={}, scores={'LEFT': 0.0, 'RIGHT': 0.0}, side=prediction['side'],
                              strategy_version=3, mode='follow_blogger', source_index=source_index,
                              source_uid=prediction['uid'], confidence=prediction['confidence'],
                              upset=prediction['upset'])
    # 全部博主无预测：回退跟场上人数多的一方，平票与 Majority 策略一致押右
    side = 'LEFT' if left > right else 'RIGHT'
    return history.append('decision', id=uuid4().hex, slot=slot, signature=signature,
                          left=left, right=right, votes={}, weights={},
                          scores={'LEFT': 0.0, 'RIGHT': 0.0}, side=side,
                          strategy_version=3, mode='follow_fallback_majority')
