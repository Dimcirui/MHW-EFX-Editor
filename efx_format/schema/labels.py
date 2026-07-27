# -*- coding: utf-8 -*-
"""
efx_format/schema/labels.py — 字段中文标签（纯数据 + 单一 accessor，零 bpy 依赖）

标签归属统一在 schema 层：
  · 定长块（走 typed Attribute）：标签就是 Field.label_zh，权威、单一声明处。
  · custom-codec 块（字段仍是裸 tuple、不进 FIELD_REGISTRY）：标签存本模块的残余表；
    将来 custom schema 若也升级成 Field，这两张表自然折入、随之退休。

accessor field_label_zh(type_name, field_name)：
  1. Field.label_zh（NAME_TO_HASH→FIELD_REGISTRY 反查）——定长块权威；
  2. _LABELS_BY_TYPE[(type_name, field_name)]——同名字段跨类型语义不同时的专属覆盖；
  3. _LABELS_GLOBAL[field_name]——跨类型通用中文名。
  未命中返回 None（Blender 层据此回退英文友好名 _friendly_name）。
"""

from .fields_model import FIELD_REGISTRY
from ..hashes import NAME_TO_HASH


# 跨类型通用中文名（仅保留仍被 custom-codec 块字段用到的；定长块名已折入 Field.label_zh）。
_LABELS_GLOBAL = {
    'rotationOrder': '旋转顺序',
    'direction': '方向',
    'rotation': '旋转',
    'rotationJitter': '旋转抖动',
    'color': '颜色',
    'color1': '颜色1',
    'color2': '颜色2',
    'colorRange': '颜色范围',
    'useColorRange': '启用颜色范围',
    'emissiveColor': '自发光颜色',
    'emissiveColorRange': '自发光颜色范围',
    'useEmissiveColor': '启用自发光颜色',
    'useEmissiveColorRange': '启用自发光颜色范围',
    'useEmission': '启用自发光',
    'enableIntensity1': '亮度增强1',
    'enableIntensity2': '亮度增强2',
    'enableEmissiveIntensity': '自发光亮度增强',
    'disableAllColorRange': '禁用所有颜色范围',
    'emissive_saturation': '自发光饱和度',
    'emissive_saturation_j': '自发光饱和度抖动',
    'emissive_brightness': '自发光亮度',
    'emissive_brightness_j': '自发光亮度抖动',
    'brightness': '亮度',
    'opacity': '不透明度',
    'headColor': '光柱起点颜色',
    'tailColor': '光柱终点颜色',
    'headColorEpvSlot': '起点颜色 EPV 颜色槽',
    'columnLength': '光柱长度',
    'columnLengthModifier': '光柱长度修正',
    'columnRadius': '光柱半径',
    'columnRadiusJitter': '光柱半径抖动',
    'columnEdgeSoftness': '光柱边缘柔化',
    'lightIntensity': '光照强度',
    'lightIntensityJitter': '光照强度抖动',
    'tailGlowSpread': '尾光扩散(变长+边缘虚化)',
    'backFaceTintMode': '反向区域受起点色染色',
    'frontFaceTintMode': '朝向区域受终点色染色',
    'tailPlaneOffset': '终点发光面前后位置',
    'animationSpeed': '动画速度',
    'width': '宽度',
    'widthJitter': '宽度抖动',
    'height': '高度',
    'heightJitter': '高度抖动',
    'length': '长度',
    'lengthJitter': '长度抖动',
    'section_length': '段长度',
    'visiblePreview': '可见性修正',
    'randomBrightnessMult': '随机亮度乘数',
    'blendMode': '混合模式',
    'loopingOrientation': '贴图朝向',
    'loopingPad': '保留',
    'applicationRuleFlowmap': '流动贴图组',
    'applicationRuleMode': '应用模式',
    'applicationRuleReserved': '保留位',
}

# 类型专属中文名（键 =(TYPE_NAME, field_name)），优先于 _LABELS_GLOBAL。
# 仅 custom-codec 类型（定长块的 BY_TYPE 已折入各自 Field.label_zh）。
_LABELS_BY_TYPE = {
    # ── UVSEQUENCE ──
    ('UVSEQUENCE', 'playbackMode'): '播放模式',
    ('UVSEQUENCE', 'flipCode'): '翻转码',
    # ── LIGHTNING ──
    ('LIGHTNING', 'unkn05_01'): '实例模式标志',
    ('LIGHTNING', 'sineWaveFreq'): '正弦波频率',
    ('LIGHTNING', 'sineWaveFreqJitter'): '正弦波频率抖动',
    ('LIGHTNING', 'alphaThreshold'): 'alpha 阈值',
    ('LIGHTNING', 'unkn05_05'): '分支禁用标志',
    ('LIGHTNING', 'unkn05_06'): '分支起始偏移距离',
    ('LIGHTNING', 'outwardsExpansionSpeed'): '向外扩展速度',
    ('LIGHTNING', 'outwardsExpansionSpeedJitter'): '向外扩展速度抖动',
    ('LIGHTNING', 'unkn05_10'): '闪电不透明度',
    ('LIGHTNING', 'unkn05_11'): '闪电透明度等级B',
    ('LIGHTNING', 'unkn05_12'): '流光与淡出模式',
    ('LIGHTNING', 'targetBoneID'): '靶骨 ID',
    ('LIGHTNING', 'inflectionPointCount'): '拐点计数',
    ('LIGHTNING', 'uInflectionAngleLimit'): '倾角限制',
    ('LIGHTNING', 'uInflectionAngleLimitJitter'): '倾角限制抖动',
    ('LIGHTNING', 'vInflectionAngleLimit'): '弯曲角极限',
    ('LIGHTNING', 'vInflectionAngleLimitJitter'): '弯曲角极限抖动',
    ('LIGHTNING', 'inflectionPointCount2'): '拐点计数2',
    ('LIGHTNING', 'uInflectionAngleLimit2'): '倾角限制2',
    ('LIGHTNING', 'uInflectionAngleLimitJitter2'): '倾角限制2抖动',
    ('LIGHTNING', 'vInflectionAngleLimit2'): '弯曲角极限2',
    ('LIGHTNING', 'vInflectionAngleLimitJitter2'): '弯曲角极限2抖动',
    ('LIGHTNING', 'glow'): '发光',
    ('LIGHTNING', 'glowJitter'): '发光抖动',
    ('LIGHTNING', 'startWidth'): '开始宽度',
    ('LIGHTNING', 'uvRepetitionStart'): 'UV 重复开始',
    ('LIGHTNING', 'endWidth'): '结束宽度',
    ('LIGHTNING', 'uvRepetitionEnd'): 'UV 重复结束',
    ('LIGHTNING', 'unkn05_47'): '支路闪电数量A',
    ('LIGHTNING', 'unkn05_48'): '支路闪电数量B',
    ('LIGHTNING', 'radiusLimit'): '半径极限',
    ('LIGHTNING', 'radiusLimitJitter'): '半径极限抖动',
    ('LIGHTNING', 'unkn07_02'): '支线弯曲角极限',
    ('LIGHTNING', 'unkn07_03'): '支线弯曲角极限抖动',
    ('LIGHTNING', 'unkn07_04'): '支线流动模式B开关',
    ('LIGHTNING', 'unkn07_05'): '支线复杂度/扩散随机性',
    ('LIGHTNING', 'unkn07_06'): '支线复杂度抖动',
    ('LIGHTNING', 'unkn07_09'): '支线发光',
    ('LIGHTNING', 'unkn07_10'): '支线发光抖动',
    ('LIGHTNING', 'branchLength'): '支路长度',
    ('LIGHTNING', 'branchLengthJitter'): '支路长度抖动',
    ('LIGHTNING', 'unkn07_13'): '支线开始宽度',
    ('LIGHTNING', 'unkn07_14'): '支线结束宽度',
    ('LIGHTNING', 'unkn07_15'): '支线开始宽度抖动',
    ('LIGHTNING', 'unkn07_16'): '支线 UV 重复开始',
    ('LIGHTNING', 'unkn07_17'): '支线 UV 重复结束',
    ('LIGHTNING', 'unkn07_18'): '支线结束宽度抖动',
    ('LIGHTNING', 'emissive'): '自发光颜色',
    ('LIGHTNING', 'EPVColorSlot1'): 'EPV 颜色槽1',
    ('LIGHTNING', 'EPVColorSlot2'): 'EPV 颜色槽2',
    # ── RIBBONBLADE ──
    ('RIBBONBLADE', 'widthDirection'): '宽度延伸方向',
    ('RIBBONBLADE', 'length'): '拖尾长度',
    ('RIBBONBLADE', 'lengthMode'): '拖尾长度模式',
    ('RIBBONBLADE', 'flowmapSpeed'): '流光贴图速度',
    ('RIBBONBLADE', 'flowmapSpeedJitter'): '流光贴图速度抖动',
    ('RIBBONBLADE', 'flowmapAcceleration'): '流光贴图加速度',
    ('RIBBONBLADE', 'flowmapAccelerationJitter'): '流光贴图加速度抖动',
    ('RIBBONBLADE', 'flowmapStrength'): '流光贴图强度',
    ('RIBBONBLADE', 'flowmapStrengthJitter'): '流光贴图强度抖动',
    ('RIBBONBLADE', 'flowmapStrengthAcceleration'): '流光贴图强度加速度',
    ('RIBBONBLADE', 'flowmapStrengthAccelerationJitter'): '流光贴图强度加速度抖动',
}


def field_label_zh(type_name, field_name):
    """返回字段中文标签；无则 None（调用方回退英文友好名）。"""
    if type_name:
        h = NAME_TO_HASH.get(type_name)
        if h is not None:
            f = FIELD_REGISTRY.get((h, field_name))
            if f is not None and f.label_zh:
                return f.label_zh
        bt = _LABELS_BY_TYPE.get((type_name, field_name))
        if bt is not None:
            return bt
    return _LABELS_GLOBAL.get(field_name)
