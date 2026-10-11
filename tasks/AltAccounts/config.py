# This Python file uses the following encoding: utf-8
from datetime import datetime
from typing import Any, Dict

from pydantic import Field, model_validator, model_serializer, ValidationError

from deploy.logger import logger
from tasks.Component.SwitchAccount.switch_account_config import AccountInfo
from tasks.Component.config_base import ConfigBase, DateTime, TimeDelta
from tasks.Component.config_scheduler import Scheduler as BaseScheduler


class Scheduler(BaseScheduler):
    # 轮换中个别小号失败时，半小时后重跑（已完成的小号会按记录跳过）
    failure_interval: TimeDelta = Field(
        default=TimeDelta(minutes=30), title='失败间隔',
        description='任务失败后到下次运行的间隔',
    )


class AltAccountInfo(AccountInfo):
    # 本小号上次完成每周琐事的时间，由脚本自动记录用于判断是否需要再次执行
    weekly_complete_time: DateTime = Field(
        default=DateTime.fromisoformat("2023-01-01 00:00:00"),
        description='alt_weekly_complete_time_help',
    )
    # 本小号上次完成地域鬼王的时间，由脚本自动记录
    area_boss_complete_time: DateTime = Field(
        default=DateTime.fromisoformat("2023-01-01 00:00:00"),
        description='alt_area_boss_complete_time_help',
    )


class AltAccountsConfig(ConfigBase):
    # 小号数量
    alt_account_count: int = Field(default=1, ge=1, description='alt_account_count_help')
    # 每个小号登录后是否执行每日琐事（具体项目在「每日琐事」配置页设置）
    run_daily_trifles: bool = Field(default=True, description='alt_run_daily_trifles_help')
    # 每个小号登录后是否执行每周琐事（具体项目在「每周琐事」配置页设置）
    run_weekly_trifles: bool = Field(default=True, description='alt_run_weekly_trifles_help')
    # 每周琐事锚定星期：0=周一 … 6=周日；本周未完成且到达该星期后统一执行，错过则本周内补跑
    weekly_anchor_weekday: int = Field(default=0, ge=0, le=6, description='alt_weekly_anchor_weekday_help')
    # 每个小号登录后是否挑战地域鬼王（挑战设置在「地域鬼王」配置页设置）
    run_area_boss: bool = Field(default=True, description='alt_run_area_boss_help')
    # 全部小号跑完后是否切回主力角色，避免后续任务登录在小号上
    login_back_enable: bool = Field(default=False, description='alt_login_back_enable_help')
    # 切回的主力角色名（需与本账号下已存在的角色名完全一致）
    login_back_character: str = Field(default='', description='alt_login_back_character_help')


class AltAccounts(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    alt_accounts_config: AltAccountsConfig = Field(default_factory=AltAccountsConfig)
    # 小号信息：同一账号下不同区服的角色列表
    alt_account_list: list[AltAccountInfo] = None

    # kind: daily=每日琐事 weekly=每周琐事 area_boss=地域鬼王
    def update_account_complete_time(self, account: AccountInfo, kind: str = 'daily'):
        field = {
            'daily': 'last_complete_time',
            'weekly': 'weekly_complete_time',
            'area_boss': 'area_boss_complete_time',
        }[kind]
        for info in self.alt_account_list:
            if info.character != account.character or info.svr != account.svr:
                continue
            setattr(info, field, datetime.now())
            break

    @model_validator(mode='before')
    @classmethod
    def validator_all(cls, v: dict) -> Any:
        alt_account_count = v.get('alt_accounts_config', {}).get('alt_account_count', 1)

        def validator_list(list_name, data, item_type=None, list_size=1):
            if list_name not in data:
                data[list_name] = []

            remove_keys = []
            for key, value in data.items():
                if list_name == key or list_name not in key:
                    continue
                try:
                    item = item_type(**value)
                    if item.is_valid():
                        data[list_name].append(item)
                    remove_keys.append(key)
                except ValidationError as e:
                    pass
                except TypeError as e:
                    pass

            for key in remove_keys:
                del data[key]

            if item_type is not None:
                if len(data[list_name]) < list_size:
                    for i in range(list_size - len(data[list_name])):
                        data[list_name].append(item_type())

        validator_list('alt_account_list', v, AltAccountInfo, alt_account_count)

        return v

    @model_serializer()
    def serializer_model(self, value: Any) -> Dict[str, Any]:
        properties = self.__dict__
        data = {}

        def v_dump(v):
            try:
                return v.model_dump()
            except AttributeError as e:
                logger.error(e)
                return v

        for key, value in properties.items():
            if isinstance(value, list):
                for index, v in enumerate(value):
                    data[f'{key}_{index + 1}'] = v_dump(v)
            else:
                data[key] = v_dump(value)
        return data


if __name__ == '__main__':
    alt = AltAccounts()
    print(alt.model_dump())
