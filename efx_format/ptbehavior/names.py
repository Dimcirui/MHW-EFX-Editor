"""
efx_format/ptbehavior_names.py  —  PTBEHAVIOR 属性 key 哈希 → 名（自动生成，勿手改主体）

key = jamcrc(属性名)。来源：RE Engine DTI 属性 dump（dti_prop_dump.h + wip_dump，权威）
+ 少量 "m/mp 前缀 + mrl3 槽名" jamcrc 爆破补充。哈希全局共享，同名跨 b_type 通用。
未知 key 在 UI 显示 0x%08X。

2026-09-12 补 7 条（RadialBlurFilterBehavior 目录里剩下的未知 key）：把 DTI dump 里
出现过的全部字段名做 m/mp 前缀 jamcrc 爆破，逐个唯一命中——
  0x05A87D45 mBrightThreshold      0x30676711 mChromaticAberration
  0x42629FCF mEndW                 0x6409650F mStartW
  0xCF6A923A mEndH                 0xE90168FA mStartH
  0x4970F55B mWPos
其中 mBrightThreshold 另有独立佐证：DTI 的
nEffect::nTimelineParam::RadialBlurFilterBehavior 本就列着 BrightThreshold，
且 timl/names.py 的 0x0ECBFA29 BrightThreshold 轨道只挂在这个 TLP 下。
该 b_type 仍余 0x5A636C3C（bool，44 次）未爆出。

2026-09-14 补 nEffect::MhEffectDecalBehavior 的 0x3E5CBC12 → mPlayOrder：
DTI 只列了 mPlayOrderEnum（class，枚举镜像，见 dti_extra.py 顶部说明），跟
已确认的 mPlayType/mPlayTypeEnum 是同一种"真实字段不带 Enum 后缀"模式——
jamcrc('mPlayOrder') 精确命中语料里这个 t=0x06(u32)、出现 1408 次的未知 key，
且位置正落在 mPlaySpeed/mPlaySpeedCoef/mPlayType 这一簇播放参数里，非巧合。
含义未实机验证，但从命名看很可能是播放顺序（正放/倒放）开关。
"""

PTBEHAVIOR_NAMES = {
    0x0093F600: 'rb',
    0x00F1680E: 'mFireFactor',
    0x0115ACDB: 'mDistortionScreenFade',
    0x02571B8D: 'mMetalic',
    0x05A87D45: 'mBrightThreshold',
    0x05E0C76B: 'mRadius',
    0x07BDD7DB: 'mShadowMaxDepthBias',
    0x09CAFB64: 'mSmokeLifeType',
    0x0ABA2F93: 'mGtoBVanishFrame',
    0x0B85D35D: 'mDecalType',
    0x0C7CA9AA: 'mRangeScaleMode',
    0x0E24B8A2: 'mMultiplyRadiusSquare',
    0x0FC95803: 'mGtoBKeepFrame',
    0x0FF5554F: 'mDistortionFactor',
    0x100DE642: 'mUseSheetLife',
    0x10B7AA7B: 'mpEmissiveMap',
    0x116D717D: 'mDistortionEnable',
    0x12399297: 'mSpecularAppearFrame',
    0x13DC04FC: 'mWaterIntensitySpecular',
    0x1507637F: 'mFlowStrengthCoef',
    0x158255DC: 'mHorizontalFlip',
    0x17791F18: 'mPass',
    0x183B164F: 'mFireColor',
    0x19A1D4F7: 'mWaterColorSpecular',
    0x1AB819B2: 'mStartZ',
    0x1BB0EB80: 'mEmissiveMapFactorIntensity',
    0x1CFF6306: 'mDistortionColor',
    0x1F7C6BB9: 'mShadingMode',
    0x20067C8E: 'lt',
    0x21BA894E: 'mShadowDepthBias',
    0x2399DDD8: 'MaskTexture',
    0x23DAC894: 'mUseScreenAlpha',
    0x24BA34BB: 'mGtoBAppearFrame',
    0x255E7380: 'mEdgeFade',
    0x261DDB49: 'mLightVoxelMapFactorIntensity',
    0x2F6C58EC: 'mBlurStart',
    0x30676711: 'mChromaticAberration',
    0x367AD10F: 'mProjectionRotationZ',
    0x371BBC04: 'mRoughness',
    0x3B32C686: 'mAlphaMapUVFix',
    0x3C0F484C: 'mBlurWidth',
    0x3C3989BF: 'mSpecularVanishFrame',
    0x3CD3E372: 'mEndZ',
    0x3E2F0BF2: 'mSmokeKeepFrame',
    0x3E5CBC12: 'mPlayOrder',
    0x3F061AAF: 'mSequenceNo',
    0x4205622B: 'mWaterLerpGtoB',
    0x42290949: 'mSpread',
    0x42629FCF: 'mEndW',
    0x4301A06E: 'mFlowEnable',
    0x46222707: 'mNormalBlendRate',
    0x483CB738: 'mEffectiveRadius',
    0x48E118D6: 'mUseGtoBLife',
    0x4970F55B: 'mWPos',
    0x49C16A85: 'mSmokeColor',
    0x4A10AC4B: 'mBlendStateType',
    0x4A28ECBA: 'mPriority',
    0x4B10C55B: 'mFireLifeType',
    0x4B3203B5: 'mOcclusionSphereRadius',
    0x4C8157C7: 'mDistanceFadeRange',
    0x4EC38C97: 'mMode',
    0x4EEB0717: 'mUseFireLife',
    0x4F2167A4: 'mUseOcclusionBlurWidth',
    0x532D9150: 'mSheetKeepFrame',
    0x54F3132E: 'mCone',
    0x577D419C: 'mSyncEmitterColor',
    0x57941CDC: 'mSheetAppearFrame',
    0x5C064DC6: 'mAxis',
    0x5C521961: 'mpUVSequence',
    0x5CA3C65D: 'mMappingMode',
    0x5E05FE41: 'mSpecularKeepHoldFlag',
    0x5EA20A73: 'mAlphaCorrectionMin',
    0x5F18DFD2: 'mDisp',
    0x62AF352A: 'mAlphaCorrectionMax',
    0x6409650F: 'mStartW',
    0x6CEB1104: 'mGtoBKeepHoldFlag',
    0x6E33C088: 'mRange',
    0x71BCF0AA: 'mFlowSpeed',
    0x7524965A: 'mWaterColorRate',
    0x799407F4: 'mSheetVanishFrame',
    0x7A286EE6: 'mDistortionAngle',
    0x7B11B9DC: 'mSmokeFactor',
    0x7E6C4215: 'mCenter',
    0x801246A7: 'mBlendFactor',
    0x8117E5CA: 'mGtoBLifeType',
    0x812F8624: 'mWaterColorSheet',
    0x86743996: 'mSpecularKeepFrame',
    0x869DDA81: 'mFresnel',
    0x880BFCF1: 'mFireKeepFrame',
    0x8A747FCC: 'mShadowMapSize',
    0x8CC3EEAD: 'mUseSpecularLife',
    0x8D2DF9F1: 'mpCubeMap',
    0x8E110AEE: 'mFlowSpeedCoef',
    0x8FB30AAD: 'mAlphaMapChannel',
    0x902C6057: 'mProjectionScale',
    0x9074DE04: 'mGroup',
    0x94A79998: 'mPrimary',
    0x94AECC76: 'mProjectionOffset',
    0x966B3A72: 'mShadowSlopedDepthBias',
    0x972821BF: 'mPlayType',
    0x9A702469: 'mSamples',
    0x9AD52D16: 'mUseOcclusionAlpha',
    0x9B17682A: 'mUseSmokeLife',
    0x9BE2D228: 'mColor',
    0xA01B7821: 'mEmissiveMapFactor',
    0xA3D00CD9: 'mNearClipDistance',
    0xA87484BF: 'mpNormalMap',
    0xA89A72B0: 'mpAlbedoMap',
    0xA99C1A25: 'mWaterNormalSharpness',
    0xAA98AFDC: 'mFireColorRate',
    0xB52636D6: 'mIntensity',
    0xB87405A5: 'mWaterIntensityAlpha',
    0xB96F2B66: 'mLimitAngle',
    0xBC5DBECD: 'mSmokeLighting',
    0xBF4ECBD7: 'mSheetKeepHoldFlag',
    0xBFB12AB7: 'mPatternNo',
    0xC207B8B4: 'mFlowStrength',
    0xC31C0DA1: 'mChaosFrame',
    0xC3313840: 'mNormalBC5',
    0xC453D17C: 'mPlaySpeed',
    0xC83DF7A2: 'mpTexture',
    0xCA412373: 'mBlendFactorCorrectNo',
    0xCC8F5FE6: 'mFalloff',
    0xCF6A923A: 'mEndH',
    0xD11A6AA0: 'mOcclusionBlurWidthOffset',
    0xD201377F: 'mpAlphaTestMap',
    0xD38B57B7: 'mFireAppearFrame',
    0xD5089E67: 'mColorCorrectNo',
    0xD64C685C: 'mPlaySpeedCoef',
    0xD6B4B271: 'mSheetLifeType',
    0xDABB238B: 'mFireAlphaFactor',
    0xDB7FD5EF: 'mSmokeAppearFrame',
    0xDD7D5B1C: 'mEmissiveMapFactorCorrectNo',
    0xDE326D50: 'mBlendMode',
    0xE0D06BD5: 'mLightVoxelMapFactorCorrectNo',
    0xE2275471: 'mEnumMappingMode',
    0xE2E3CF7B: 'mIntensityRange',
    0xE57A3E9B: 'mVerticalFlip',
    0xE5A2CE4C: 'mWaterIntensityCubeMap',
    0xE8744CE5: 'mUpVector',
    0xE90168FA: 'mStartH',
    0xEB5E1675: 'mDoLPVInjection',
    0xECA1C627: 'mSmokeLerpAlphaToB',
    0xEE6D3A56: 'mUVRange',
    0xEF5D9053: 'mSpecularLifeType',
    0xEFA8AD2D: 'mWaterIntensitySheet',
    0xF4854277: 'mLightVoxelMapFactor',
    0xF57FCEC7: 'mSmokeVanishFrame',
    0xF8860B8C: 'mShadowCast',
    0xF94CDEA0: 'mpFlowMap',
    0xFBD6C37A: 'mOcclusionBlurWidthScale',
    0xFC588D70: 'mMinRoughness',
    0xFD8B4C9F: 'mFireVanishFrame',
    0xFE8780F2: 'mFireLighting',
}


def name_for(key: int) -> str:
    """返回 key 的可读名；未知时返回 0x%08X。"""
    key &= 0xFFFFFFFF
    return PTBEHAVIOR_NAMES.get(key, f"0x{key:08X}")


# ── 颜色型参数判定 ───────────────────────────────────────────────────────────
# t==0x15（4×float32）的参数默认拆成四个独立 float 行；名字以 Color 结尾的（目前只有
# mColor）改画成色轮 + A 滑块，跟其余颜色字段的观感一致（见 fields._init_ptbehavior_attribute
# / panels 的 PTBEHAVIOR 分支）。注意值域不是 0-1：语料里 mColor 最大到 20（HDR 倍率），
# 故底层仍原样存 float，色块只是显示层。

def is_color_param(key: int) -> bool:
    """key 对应的参数是否为颜色（名字以 Color 结尾）。未知 key 一律 False。"""
    name = PTBEHAVIOR_NAMES.get(key & 0xFFFFFFFF)
    return bool(name) and name.endswith('Color')
