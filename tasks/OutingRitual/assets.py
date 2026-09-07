# This Python file uses the following encoding: utf-8
from module.atom.image import RuleImage
from module.atom.click import RuleClick


class OutingRitualAssets:
    C_OR_START = RuleClick(
        roi_front=(1165, 603, 65, 45), roi_back=(1140, 580, 110, 85),
        name='outing_ritual_start')
    C_OR_DUEL_THROW = RuleClick(
        roi_front=(1045, 485, 85, 70), roi_back=(1010, 450, 155, 135),
        name='outing_ritual_duel_throw')
    C_OR_STAGE_SELECT = RuleClick(
        roi_front=(1025, 385, 85, 70), roi_back=(985, 345, 165, 145),
        name='outing_ritual_stage_select')
    C_OR_CHALLENGE = RuleClick(
        roi_front=(1135, 575, 95, 85), roi_back=(1100, 540, 155, 145),
        name='outing_ritual_challenge')
    I_OR_COURTYARD_ENTRY = RuleImage(
        roi_front=(451, 205, 84, 73), roi_back=(390, 170, 220, 200),
        threshold=0.72, method='Template matching',
        file='./tasks/OutingRitual/or/or_courtyard_entry.png')
    I_OR_HUB_PAGE = RuleImage(
        roi_front=(136, 7, 218, 62), roi_back=(104, 0, 280, 84),
        threshold=0.78, method='Template matching',
        file='./tasks/OutingRitual/or/or_hub_page.png')
    I_OR_HUB_ENTRY = RuleImage(
        roi_front=(1061, 137, 72, 211), roi_back=(1015, 92, 150, 306),
        threshold=0.72, method='Template matching',
        file='./tasks/OutingRitual/or/or_hub_entry.png')
    I_OR_PAGE = RuleImage(
        roi_front=(137, 7, 190, 61), roi_back=(105, 0, 250, 82),
        threshold=0.65, method='Template matching',
        file='./tasks/OutingRitual/or/or_page.png')
    I_OR_START = RuleImage(
        roi_front=(1142, 589, 112, 78), roi_back=(1094, 548, 180, 153),
        threshold=0.72, method='Template matching',
        file='./tasks/OutingRitual/or/or_start.png')
    I_OR_DUEL_THROW = RuleImage(
        roi_front=(472, 265, 344, 161), roi_back=(410, 210, 470, 270),
        threshold=0.78, method='Template matching',
        file='./tasks/OutingRitual/or/or_duel_throw.png')
    I_OR_STAGE_SELECT = RuleImage(
        roi_front=(480, 17, 326, 55), roi_back=(430, 0, 430, 100),
        threshold=0.75, method='Template matching',
        file='./tasks/OutingRitual/or/or_stage_select.png')
    I_OR_CHALLENGE = RuleImage(
        roi_front=(1105, 548, 149, 139), roi_back=(1065, 505, 205, 205),
        threshold=0.75, method='Template matching',
        file='./tasks/OutingRitual/or/or_challenge.png')
