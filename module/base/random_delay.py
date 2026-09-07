import math
import random


def lognormal_delay(*, mean: float, variance: float, minimum: float,
                    maximum: float, digits: int = 1) -> float:
    """按实际均值/方差采样有界对数正态延迟。"""
    mean = float(mean)
    variance = float(variance)
    lower, upper = sorted((float(minimum), float(maximum)))
    if mean <= 0 or variance < 0:
        raise ValueError('lognormal delay mean must be positive and variance non-negative')

    if variance == 0:
        value = mean
    else:
        sigma_squared = math.log1p(variance / (mean * mean))
        mu = math.log(mean) - sigma_squared / 2
        value = random.lognormvariate(mu, math.sqrt(sigma_squared))

    # 限制极端长尾，避免一次异常采样让脚本看起来卡死。
    return round(min(max(value, lower), upper), digits)


FIRST_OPERATION_DELAY = {
    'mean': 0.72,
    'variance': 0.018,
    'minimum': 0.5,
    'maximum': 1.0,
    'digits': 1,
}

CONTINUOUS_CONFIRM_DELAY = {
    'mean': 0.88,
    'variance': 0.020,
    'minimum': 0.7,
    'maximum': 1.2,
    'digits': 1,
}

BATTLE_SETTLEMENT_DELAY = {
    'mean': 1.05,
    'variance': 0.160,
    'minimum': 0.5,
    'maximum': 2.0,
    'digits': 1,
}
