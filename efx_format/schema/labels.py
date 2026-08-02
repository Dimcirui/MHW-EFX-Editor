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
    # flowmap 8 件套 + 总开关：RIBBON / BILLBOARD2D / BILLBOARD3D / PLANE / LIGHTNING
    # 共用同名同义字段，统一在此给通用中文名（RIBBONBLADE 的「流光贴图」措辞由下面的
    # 按类型专属表覆盖；UVCONTROL 走 Field.label_zh 优先级更高，同样不受影响）。
    'enableFlowmap': '启用流动贴图',
    'flowmapSpeed': '流动贴图速度',
    'flowmapSpeedJitter': '流动贴图速度抖动',
    'flowmapSpeedCoef': '流动贴图加速度',
    'flowmapSpeedCoefJitter': '流动贴图加速度抖动',
    'flowmapStrength': '流动贴图强度',
    'flowmapStrengthJitter': '流动贴图强度抖动',
    'flowmapStrengthCoef': '流动贴图强度加速度',
    'flowmapStrengthCoefJitter': '流动贴图强度加速度抖动',
    # TUBELIGHT 全字段标签已折入 TUBELIGHT_ATTR 的 Field.label_zh，此处退休。
    'playSpeed': '动画速度',
    'width': '宽度',
    'widthJitter': '宽度抖动',
    'height': '高度',
    'heightJitter': '高度抖动',
    'length': '长度',
    'lengthJitter': '长度抖动',
    'section_length': '段长度',
    'visiblePreview': '可见性修正',
    'blendMode': '混合模式',
    'subdivisionCount': '细分数量',
    # RIBBON 柔体链的弹簧-阻尼参数组（原 restitution/inertial_excess/springiness）。
    'restoreStrength': '归位强度',
    'restoreStrengthJitter': '归位强度抖动',
    'inertia': '惯性',
    'inertiaJitter': '惯性抖动',
    'springiness': '弹性',
    'springiness_jitter': '弹性抖动',
    'brightnessJitter': '亮度抖动',
    # RIBBON flap 抖动组（原 base_flap_*/tip_flap_*；两组等效可叠加，非根部/尖端之分）。
    'flap1Frequency': '抖动1 频率',
    'flap1FrequencyJitter': '抖动1 频率抖动',
    'flap1Amount': '抖动1 幅度',
    'flap1AmountJitter': '抖动1 幅度抖动',
    'flap2Frequency': '抖动2 频率',
    'flap2FrequencyJitter': '抖动2 频率抖动',
    'flap2Amount': '抖动2 幅度',
    'flap2AmountJitter': '抖动2 幅度抖动',
    # RIBBON 自尾端施加的三向全局力（方向恒定，不随旋转变化）。
    'unknGlobalForceEnable': '启用全局力',
    'unknGlobalForceX': '全局力 X',
    'unknGlobalForceY': '全局力 Y（竖直）',
    'unknGlobalForceZ': '全局力 Z',
    'loopingOrientation': '贴图朝向',
    'loopingPad': '保留',
    # applicationRule/loopingMode 现为 Bitmask 字段（label 在 Field.label_zh），拆分子字段已退休。
}

# 类型专属中文名（键 =(TYPE_NAME, field_name)），优先于 _LABELS_GLOBAL。
# 仅 custom-codec 类型（定长块的 BY_TYPE 已折入各自 Field.label_zh）。
_LABELS_BY_TYPE = {
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
    ('LIGHTNING', 'unknAngle13_0'): '未知角度',
    # ── RIBBONBLADE ──
    ('RIBBONBLADE', 'widthDirection'): '宽度延伸方向',
    ('RIBBONBLADE', 'length'): '拖尾长度',
    ('RIBBONBLADE', 'lengthMode'): '拖尾长度模式',
    ('RIBBONBLADE', 'flowmapSpeed'): '流光贴图速度',
    ('RIBBONBLADE', 'flowmapSpeedJitter'): '流光贴图速度抖动',
    ('RIBBONBLADE', 'flowmapSpeedCoef'): '流光贴图加速度',
    ('RIBBONBLADE', 'flowmapSpeedCoefJitter'): '流光贴图加速度抖动',
    ('RIBBONBLADE', 'flowmapStrength'): '流光贴图强度',
    ('RIBBONBLADE', 'flowmapStrengthJitter'): '流光贴图强度抖动',
    ('RIBBONBLADE', 'flowmapStrengthCoef'): '流光贴图强度加速度',
    ('RIBBONBLADE', 'flowmapStrengthCoefJitter'): '流光贴图强度加速度抖动',
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


# ─────────────────────────────────────────────────────────────────────────────
# 英文标签冻结表
#
# 英文标签默认是 Blender 层从 ori_name 现推的（camelCase 拆词，见 panels.py::_friendly_name），
# 所以**改内部名会连带改掉英文界面**。内部名向官方 DTI 名对齐（Coef/Add/relation… 体系）时，
# 界面措辞要保持不变——沿用多年的社区叫法不动——故此处把改名前的派生结果显式钉住。
#
# 只登记「内部名已改、但界面要维持旧称」的字段；新字段/未改名字段不进表，继续走派生。
# ⚠ 表内 value 是**用户可见文案**，不写内部新名。
# ─────────────────────────────────────────────────────────────────────────────

_LABELS_EN_GLOBAL = {
    # flowmap 八件套（8 个类型共用同一套派生名）
    'flowmapSpeedCoef':              'Flowmap Acceleration',
    'flowmapSpeedCoefJitter':        'Flowmap Acceleration Jitter',
    'flowmapStrengthCoef':           'Flowmap Strength Acceleration',
    'flowmapStrengthCoefJitter':     'Flowmap Strength Acceleration Jitter',
}

_LABELS_EN_BY_TYPE = {
    # ── UVCONTROL：Offset/Add/Coef 体系 ──
    ('UVCONTROL', 'uv1_offset'):       'Uv1 initial Position',
    ('UVCONTROL', 'uv1_offsetAdd'):    'Uv1 speed',
    ('UVCONTROL', 'uv1_offsetCoef'):   'Uv1 acceleration',
    ('UVCONTROL', 'uv1_scaleAdd'):     'Uv1 scale Speed',
    ('UVCONTROL', 'uv1_scaleCoef'):    'Uv1 scale Acceleration',
    ('UVCONTROL', 'uv2_offset'):       'Uv2 initial Position',
    ('UVCONTROL', 'uv2_offsetAdd'):    'Uv2 speed',
    ('UVCONTROL', 'uv2_offsetCoef'):   'Uv2 acceleration',
    ('UVCONTROL', 'uv2_scaleAdd'):     'Uv2 scale Speed',
    ('UVCONTROL', 'uv2_scaleCoef'):    'Uv2 scale Acceleration',
    # ── UVSEQUENCE：PlaySpeed/PlaySpeedCoef + SequenceNo/PatternNo ──
    ('UVSEQUENCE', 'playSpeed'):           'Animation Speed',
    ('UVSEQUENCE', 'playSpeedJitter'):     'Animation Speed Jitter',
    ('UVSEQUENCE', 'playSpeedCoef'):       'Animation Acceleration',
    ('UVSEQUENCE', 'playSpeedCoefJitter'): 'Animation Acceleration Jitter',
    ('UVSEQUENCE', 'sequenceNo'):          'Uvs Index',
    ('UVSEQUENCE', 'sequenceNoJitter'):    'Uvs Index Jitter',
    ('UVSEQUENCE', 'patternNo'):           'Starting Frame',
    ('UVSEQUENCE', 'patternNoJitter'):     'Starting Frame Jitter',
    # ── ROTATEANIM ──
    ('ROTATEANIM', 'billboardRotationCoef'):       'Billboard Rotation Accel',
    ('ROTATEANIM', 'billboardRotationCoefJitter'): 'Billboard Rotation Accel Jitter',
    ('ROTATEANIM', 'spinSpeedCoefX'):              'Spin Acceleration X',
    ('ROTATEANIM', 'spinSpeedCoefXJitter'):        'Spin Acceleration XJitter',
    ('ROTATEANIM', 'spinSpeedCoefY'):              'Spin Acceleration Y',
    ('ROTATEANIM', 'spinSpeedCoefYJitter'):        'Spin Acceleration YJitter',
    ('ROTATEANIM', 'spinSpeedCoefZ'):              'Spin Acceleration Z',
    ('ROTATEANIM', 'spinSpeedCoefZJitter'):        'Spin Acceleration ZJitter',
    # ── VELOCITY2D / VELOCITY3D ──
    ('VELOCITY3D', 'speedCoef'):       'Acceleration',
    ('VELOCITY3D', 'speedCoefJitter'): 'Acceleration Jitter',
    ('VELOCITY2D', 'speedCoef'):       'Acceleration',
    ('VELOCITY2D', 'speedCoefJitter'): 'Acceleration Jitter',
    # ── PARENTOPTIONS ──
    ('PARENTOPTIONS', 'relationPos'):        'Translation tracking',
    ('PARENTOPTIONS', 'relationRot'):        'Angle tracking',
    ('PARENTOPTIONS', 'relationScl'):        'Scale tracking',
    ('PARENTOPTIONS', 'particleUseLocal'):   'Spawn Track',
    ('PARENTOPTIONS', 'constRelease'):       'Lock To Position Frame',
    ('PARENTOPTIONS', 'constReleaseJitter'): 'Lock To Position Frame Jitter',
    ('PARENTOPTIONS', 'jointNo'):            'Bone lim',
}


def field_label_en(type_name, field_name):
    """返回字段英文标签；无则 None（调用方回退 _friendly_name 派生）。

    查找顺序与 field_label_zh 对称：Field.label_en → 按类型表 → 全局表。
    """
    if type_name:
        h = NAME_TO_HASH.get(type_name)
        if h is not None:
            f = FIELD_REGISTRY.get((h, field_name))
            if f is not None and f.label_en:
                return f.label_en
        bt = _LABELS_EN_BY_TYPE.get((type_name, field_name))
        if bt is not None:
            return bt
    return _LABELS_EN_GLOBAL.get(field_name)
