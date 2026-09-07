# This Python file uses the following encoding: utf-8
from module.atom.click import RuleClick
from module.atom.image import RuleImage


class DivineBarrierAssets:
    C_DB_HUB_ENTRY = RuleClick(
        roi_front=(600, 365, 65, 175), roi_back=(570, 325, 115, 245),
        name='divine_barrier_hub_entry')
    C_DB_CHALLENGE = RuleClick(
        roi_front=(1160, 604, 55, 42), roi_back=(1135, 580, 105, 85),
        name='divine_barrier_challenge')
    I_DB_HUB_ENTRY = RuleImage(
        roi_front=(590, 339, 83, 224), roi_back=(550, 295, 150, 300),
        threshold=0.75, method='Template matching',
        file='./tasks/DivineBarrier/db/db_hub_entry.png')
    I_DB_PAGE = RuleImage(
        roi_front=(136, 7, 205, 62), roi_back=(103, 0, 270, 84),
        threshold=0.72, method='Template matching',
        file='./tasks/DivineBarrier/db/db_page.png')
    I_DB_CHALLENGE = RuleImage(
        roi_front=(1108, 548, 147, 141), roi_back=(1068, 505, 200, 205),
        threshold=0.75, method='Template matching',
        file='./tasks/DivineBarrier/db/db_challenge.png')
