# This Python file uses the following encoding: utf-8
"""
一键应用「拟人化调度」档案，降低账号的行为风控特征。

用法（必须先停止对应实例的调度，再执行）:
    python dev_tools/apply_stealth_schedule.py              # 应用到默认实例
    python dev_tools/apply_stealth_schedule.py 小号 逆迴十六夜

档案内容（全部使用项目现有机制，不新增功能）:
  1. 防风控作息(AntiBan): 00:00-08:00 睡眠窗（覆盖 0 点机器人高峰与凌晨维护/封禁批处理窗口）,
     每日活跃上限 3 小时, 触发后强制休息 2 小时;
  2. 连续任务休息: 每 45-90 分钟随机休息 2-20 分钟;
  3. 空闲策略: 队列空了立即关游戏, 空闲超过 30 分钟连模拟器一起关（不再 7x24 挂庭院）;
  4. 任务囤积: 15 分钟窗口内到期的任务合并到一个时段执行, 减少上线次数;
  5. 运行时间抖动: 所有启用任务的 float_time 统一为 1 小时随机浮动;
  6. 0 点机器人高峰期(server_update 00:0x)的任务改到 10:00 档, 错开扎堆时段。
"""
import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / 'log'
CONFIG_DIR = BASE_DIR / 'config'
DEFAULT_CONFIGS = ['小号', '逆迴十六夜', '大号-绘卷']

# 实例日志在多少秒内有写入就视为正在运行, 拒绝修改其配置
RUNNING_CHECK_SECONDS = 600

ANTI_BAN_PROFILE = {
    'enable': True,
    'sleep_start': '00:00:00',
    'sleep_end': '08:00:00',
    'daily_active_limit': '00 03:00:00',
    'long_rest_duration': '00 02:00:00',
}

DEVICE_PROFILE = {
    'continuous_task_rest_enable': True,
    'continuous_task_rest_interval': '45,90',
}

OPTIMIZATION_PROFILE = {
    'task_hoarding_duration': 15,
    'when_task_queue_empty': 'close_emulator_or_close_game',
    'close_game_limit_time': '00:05:00',
    'close_emulator_limit_time': '00:30:00',
}

FLOAT_TIME_PROFILE = '01:00:00'
# 0 点是脚本扎堆上线的高峰期, 该时段的任务统一改到 10:00 档
MIDNIGHT_SERVER_UPDATES = {'00:00:00', '00:05:00', '00:06:00', '00:10:00', '00:15:00', '00:30:00'}
MIDNIGHT_REPLACE_TO = '10:00:00'


def is_instance_running(config_name: str) -> bool:
    """根据实例日志的最后写入时间判断实例是否正在运行。"""
    now = time.time()
    for log_file in LOG_DIR.glob(f'*_{config_name}.txt'):
        if now - log_file.stat().st_mtime <= RUNNING_CHECK_SECONDS:
            return True
    return False


def apply_profile(config_name: str) -> list[str]:
    """把拟人化档案写入单个配置, 返回变更摘要。"""
    config_file = CONFIG_DIR / f'{config_name}.json'
    if not config_file.exists():
        raise FileNotFoundError(f'配置不存在: {config_file}')
    if is_instance_running(config_name):
        raise RuntimeError(
            f'实例「{config_name}」的日志 10 分钟内有写入, 疑似正在运行。'
            f'请先在 WebUI 停止该实例的调度再执行本工具, 避免配置被运行中的调度器覆盖'
        )

    with open(config_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    changes: list[str] = []
    script_section = data.get('script', {})

    anti_ban = script_section.setdefault('anti_ban', {})
    for key, value in ANTI_BAN_PROFILE.items():
        if anti_ban.get(key) != value:
            changes.append(f'anti_ban.{key}: {anti_ban.get(key)} -> {value}')
            anti_ban[key] = value

    device = script_section.setdefault('device', {})
    for key, value in DEVICE_PROFILE.items():
        if device.get(key) != value:
            changes.append(f'device.{key}: {device.get(key)} -> {value}')
            device[key] = value

    optimization = script_section.setdefault('optimization', {})
    for key, value in OPTIMIZATION_PROFILE.items():
        if optimization.get(key) != value:
            changes.append(f'optimization.{key}: {optimization.get(key)} -> {value}')
            optimization[key] = value

    for task_name, task in data.items():
        if not isinstance(task, dict):
            continue
        scheduler = task.get('scheduler')
        if not isinstance(scheduler, dict) or not scheduler.get('enable'):
            continue
        if scheduler.get('float_time') != FLOAT_TIME_PROFILE:
            changes.append(f'{task_name}.scheduler.float_time: '
                           f'{scheduler.get("float_time")} -> {FLOAT_TIME_PROFILE}')
            scheduler['float_time'] = FLOAT_TIME_PROFILE
        if scheduler.get('server_update') in MIDNIGHT_SERVER_UPDATES:
            old = scheduler.get('server_update')
            scheduler['server_update'] = MIDNIGHT_REPLACE_TO
            changes.append(f'{task_name}.scheduler.server_update: {old} -> {MIDNIGHT_REPLACE_TO}')

    if changes:
        content = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False, default=str)
        with open(config_file, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
    return changes


def main() -> None:
    names = sys.argv[1:] or DEFAULT_CONFIGS
    failed = False
    for name in names:
        try:
            changes = apply_profile(name)
        except Exception as e:
            failed = True
            print(f'[失败] {name}: {e}')
            continue
        if not changes:
            print(f'[跳过] {name}: 已符合拟人化档案, 无需修改')
            continue
        print(f'[完成] {name}, 共 {len(changes)} 处变更:')
        for change in changes:
            print(f'  - {change}')
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
