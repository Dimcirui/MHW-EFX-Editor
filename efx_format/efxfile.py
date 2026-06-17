"""
EFXFile: opaque roundtrip parser for MHW .efx effect files.

Phase 0 strategy:
  - Header (72 B) → fully parsed
  - EFX_Type (labelSize B) → kept as raw bytes + label list
  - Play (countPlay entries) → parsed per BT (with opaque fallback)
  - Extern (countExtern entries) → parsed header, Extern_Data kept opaque
  - Main (countBody entries) → each body:
      - Root (type==ROOT_MARKER): header + opaque payload
      - Main_Data: 20-byte header + timl_length opaque TIML + attr blocks
        - Known attr types: fully parsed for exact size
        - Unknown attr types: opaque blob (forward-scan to next known hash)
  - Subselect (subselectionSize B) → parsed per BT
  - End (countEOF ints) → list of ints

All sections serialize back to byte-perfect bytes.

Type widths (BT convention, little-endian):
  long/ulong = 4 B,  int/uint = 4 B,  short = 2 B,  byte = 1 B
  int64/uint64 = 8 B,  float = 4 B
"""

from __future__ import annotations
import struct
from dataclasses import dataclass, field
from typing import List, Optional

from .hashes import (
    ROOT_MARKER, PLAYEFX, PLAYEMITTER, ATTR_HASHES,
    HASH_TO_NAME, TIML,
    # known attr types with fixed sizes
    TRANSFORM3D, PARENTOPTIONS, SPAWN, LIFE, EMITTERSHAPE3D, VELOCITY3D,
    FADEBYDEPTH, BILLBOARD3D, SCALEANIM, UVSEQUENCE, ALPHACORRECTION,
    SHADERSETTINGS, RGBFIRE, MESH, ROTATEANIM, PLEMISSIVE, GUIDE, LIGHTNING,
    PARENTEMISSIVE, PTCOLLISION, PLSNOW, PTBEHAVIOR, PLANE, RGBWATER,
    TURBULENCE, FADEBYEMITTERANGLE, RIBBON, NOISE, UVCONTROL, FADEBYANGLE,
    EMITTERBOUNDARY, PTLIFE, STRAINRIBBON, SCREENSPACECOLLISION, RAYCAST,
    EXTERNREFERENCE, FAKEPLANE, DUMMY, RANDOMFIX, TRANSFORM2D, BILLBOARD2D,
    BLINK, LUMINANCEBLEED, EMITTERSHAPE2D, VELOCITY2D, REFRACTION, MASTERONLY,
    TUBELIGHT, SHOVEL, LAYOUT, FAKEDOF, REPEATAREA, LINKPARTSVISIBLE, PTTRIGGER,
    PATHCHAIN, HOMING, EMITTERSHAPEMESH, SPAWNBYANGLE, CHECKPUREATTRIBUTE,
    TONEMAPFILTER, COLORCORRECTFILTER, SPAWNBYOCCLUSION, FADEBYOCCLUSION,
    PARENTSNOW, OTOMOSNOW, PARENTMATERIAL, RIBBONBLADE, MATERIAL,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helper: compute exact byte size of a known attr block (INCLUDING 4-byte type hash)
# Returns None for unknown types → caller must forward-scan.
# ─────────────────────────────────────────────────────────────────────────────

def _xyz_size(xyz_type: int) -> int:
    """Return byte size of an XYZ struct body (EFX_Utils.bt) for given type."""
    if xyz_type == 0:
        return 24  # float fixed_x, random_x, fixed_y, random_y, fixed_z, random_z
    elif xyz_type == 1:
        return 12  # int x, y, z
    elif xyz_type == 2:
        return 4   # ubyte x, y, z, pad
    elif xyz_type == 3:
        return 12  # float x, y, z
    return 0


def _known_attr_size(data: bytes, pos: int, type_hash: int) -> Optional[int]:
    """
    Return total byte size (including the 4-byte type hash prefix) of a known
    attribute block at *pos*.  Returns None if type is unknown or has variable
    length that requires byte inspection (will be handled by forward-scan fallback).

    All sizes computed from EFX_Subtypes.bt / EFX_Play.bt with long=4B rule.
    """
    def rd_i(offset: int) -> int:
        return struct.unpack_from('<i', data, pos + offset)[0]
    def rd_I(offset: int) -> int:
        return struct.unpack_from('<I', data, pos + offset)[0]

    h = type_hash

    # ExternTransform3D structure size = 4+72+4+144+4 = 228B
    # XYZ(0)=24B, translate+rotate+resize=3*24=72B, 6 vel XYZs=144B
    EXTERN_TRANSFORM3D_SIZE = 228
    # Transform3D = 4(type) + 228 = 232B
    if h == TRANSFORM3D:
        return 4 + EXTERN_TRANSFORM3D_SIZE

    # ParentOptions = 4(type) + 4 + 3*12 + 4 + 4 + 4 + 4 + 4 = 64B
    # XYZ(1) = 3 ints = 12B
    if h == PARENTOPTIONS:
        return 4 + 4 + 12 + 12 + 12 + 4 + 4 + 4 + 4 + 4  # = 64

    # Spawn: 4(type) + ExternSpawn = 4 + 64B
    # ExternSpawn: 16 ints = 64B
    if h == SPAWN:
        return 4 + 4*18  # = 76 (ExternSpawn: 18 ints)

    # Life: 4(type) + 12*long = 4 + 48 = 52B
    if h == LIFE:
        return 4 + 4*12  # = 52

    # EmitterShape3D: 4(type) + ExternEmitterShape3D
    # ExternEmitterShape3D: int unkn0(4) + XYZ transform(0)(24B) +
    #   patternControl(4) + unkn2(4) + unkn3_f0(4) +
    #   trayX(4)+trayY(4)+trayZ(4) + unkn3_i0(4) + spawnAngleLimits(4) + unkn3_f1(4) +
    #   spawnPerCycle(4) + spawnTotal(4) + radiusEnd(4) + radiusOrigin(4) + unknRadiusRelated(4) + unkn4(4)
    # = 4 + 24 + 15*4 = 88B; total with type = 92B
    if h == EMITTERSHAPE3D:
        return 4 + 4 + 24 + 15*4  # = 92

    # Velocity3D: 4(type) + ExternVelocity3D(108B)
    if h == VELOCITY3D:
        return 4 + 108

    # FadeByDepth: 4(type) + int unkn0 + 4 floats = 4+4+16 = 24B
    if h == FADEBYDEPTH:
        return 4 + 4 + 4*4  # = 24

    # Billboard3D: 4(type) + ExternBillboard3D (variable: has path_len)
    # billboard_data (26 fields total):
    #   unkn0(4)+appRule(4)+XYZ(2)[2](8)+brightness(4)+unkn20(4)+EPVColorBlend(4)+unkn22(4)+
    #   EPVColorSlot1(4)+SlotOverride1(4)+unknDim(4)+unknDimJ(4)+scale(4)+scaleJ(4)+
    #   width(4)+widthJ(4)+height(4)+heightJ(4)+
    #   flowmapSpeed(4)+j(4)+Accel(4)+j(4)+Strength(4)+j(4)+StrengthAccel(4)+j(4)+path_len(4)
    #   = 4+4+8+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4 = 108B total billboard_data
    # ExternBillboard3D extras: unkn5(4) + unkn6(uint64=8B) + unkn7(4) + unkn8(4) + unkn9(4) = 24B
    # path[path_len] at the end.
    # path_len field is the LAST int of billboard_data, at offset 4(type)+108-4 = 108 from block start
    # Total = 4(type) + 108(billboard_data incl path_len) + 24(extras) + path_len = 136 + path_len
    if h == BILLBOARD3D:
        path_len_val = rd_i(4 + 104)  # type(4) + 104B of billboard_data before path_len
        return 4 + 108 + 24 + path_len_val  # = 136 + path_len

    # ScaleAnim: 4(type) + ExternScaleAnim(76B)
    # ExternScaleAnim: int unkn0(4) + float animSpeed(4) + long NULL(4) + float scaleSpeed(4) +
    #   scaleSpeedJ(4) + float unkn1[2](8) + float scaleAccel(4) + scaleAccelJ(4) +
    #   float unkn2[8](32) + int delay(4) + int delayJ(4) = 4+4+4+4+4+8+4+4+32+4+4 = 76B
    if h == SCALEANIM:
        return 4 + 76  # = 80

    # UVSequence: 4(type) + ExternUVSequence (variable: has path_len)
    # Fixed part: int unkn0(4) + int uvs_index(4) + long NULL(4) + int startFrame(4) +
    #   startFrameJ(4) + float animSpeed(4) + animSpeedJ(4) + animAccel(4) + animAccelJ(4) +
    #   int loopEnum(4) + int path_len(4) = 11*4 = 44B
    # Then path[path_len]
    # path_len at type+4+44 = +48
    if h == UVSEQUENCE:
        # type(4) + unkn0+uvs_index+NULL+startFrame+j+animSpeed+j+animAccel+j+loopEnum (10 fields=40B) + path_len(4B)
        # path_len is at offset 44 from block start (type@0, then 10 fields before path_len)
        path_len_val = rd_i(44)   # path_len field at offset 44 from block start
        return 4 + 40 + 4 + path_len_val  # = 48 + path_len

    # AlphaCorrection: 4(type) + int unkn0(4) + float unkn1(4) + float transparent(4) + long NULL(4) + int unkn2(4) = 24B
    if h == ALPHACORRECTION:
        return 4 + 4 + 4 + 4 + 4 + 4  # = 24

    # ShaderSettings: 4(type) + int*2(8) + int spacer(4) + int unkn2(4) + float*2(8) + int*2(8) + int ctrl(4) +
    #   float*16(64) + byte*4(4) + int visOnPreview(4) + int*2(8) = 128B
    if h == SHADERSETTINGS:
        return 4 + 8 + 4 + 4 + 8 + 8 + 4 + 64 + 4 + 4 + 8  # = 120... let me recount
        # unkn0(4)+unkn1(4)+spacer(4)+unkn2(4)+zDepthModStart(4)+zDepthModEnd(4)+
        # unkn3_0(4)+unkn3_1(4)+controlBitflag(4)+float unkn4[16](64)+
        # byte[4](4)+visibleOnPreview(4)+unkn5[2](8) = 9*4+64+4+4+8 = 116B after type
        return 4 + 4*9 + 64 + 4 + 4 + 8  # = 4+36+64+16 = 120

    # RgbFire: 4(type) + ExternRgbFire (FIXED size, NO path)
    # ExternRgbFire from BT (EFX_Subtypes.bt):
    # int unkn0(4) + XYZ color1(2)(4) + float bright1(4) + XYZ color2(2)(4) + float bright2(4) +
    # float unkn4(4) + float bright3(4) + float bright4(4) + ColorParam color1Param(40) + ColorParam color2Param(40)
    # ColorParam = 10 ints = 40B
    # = 4+4+4+4+4+4+4+4+40+40 = 112B
    # RgbFire total = 4(type) + 112 = 116B (empirically confirmed in 010.efx)
    if h == RGBFIRE:
        return 4 + 112  # = 116B (no path_len, fixed size)

    # Mesh: 4(type) + Mod3Properties(174B) + byte BeginMod3(1B) + string path1 + string path2
    # Mod3Properties size: int unkn0[2](8)+long CD1(4)+float emissive_sat(4)+float emissive_sat_j(4)+
    #   float emissive_bright(4)+float emissive_bright_j(4)+XYZ rotation(0)(24)+
    #   float unkn5_2(4)+float unkn5_3(4)+XYZ scale(0)(24)+
    #   float global_scale(4)+float global_scale_j(4)+int starting_model_viscon(4)+int end_model_viscon(4)+
    #   colour[4](16)+int unkn7[3](12)+int tracking_flags(4)+int unkn40(4)+int affectedByLight(4)+
    #   int shadowCastBitflag(4)+int epv_color_slot1(4)+int unkn5(4)+int epv_color_slot2(4)+
    #   int unkn6_1(4)+byte colorize_material1[4](4)+byte colorize_material2[4](4)+
    #   int randommizeViscon(4)+short NULL1(2)
    #   = 8+4+4+4+4+4+24+4+4+24+4+4+4+4+16+12+4+4+4+4+4+4+4+4+4+4+4+2 = 174B
    # ExternMesh = Mod3Properties(174) + byte BeginMod3(1) + string path1(null-term) + string path2(null-term)
    # Total = 4(type) + 174 + 1 = 179B fixed + two null-terminated strings
    if h == MESH:
        path1_start = pos + 179
        null1 = data.index(b'\x00', path1_start)
        null2 = data.index(b'\x00', null1 + 1)
        return null2 - pos + 1  # includes both null terminators

    # RotateAnim: 4(type) + int*2(8) + long*2(8) + XYZ(0)(24B) + float*2(8) + float(4) + XYZ(0)(24B) + float(4)
    # Wait from BT:
    # long type(4) + int unkn0[2](8) + long NULL[2](8) + XYZ spin_velocity(0)(24B) +
    # float unkn1_0(4) + float unkn1_1(4) + float momentum_conservation(4) + XYZ spin_acceleration(0)(24B) + float unkn1_2(4)
    # = 4+8+8+24+4+4+4+24+4 = 84B
    if h == ROTATEANIM:
        return 4 + 8 + 8 + 24 + 4 + 4 + 4 + 24 + 4  # = 84

    # PlEmissive: 4(type) + ExternPlEmissive
    # ExternPlEmissive: int unkn0[2](8)+float unkn1(4)+ubyte body_p,wp_p,short NULL(4)+int epv(4)+
    #   XYZ(2)(4)+float unkn4(4)+float area[2](8)+float bright(4)+int area_of_aura(4)+
    #   float radii[3](12)+float unkn5[5](20)
    # = 8+4+4+4+4+4+8+4+4+12+20 = 76B
    if h == PLEMISSIVE:
        return 4 + 76  # = 80

    # Guide (EFX_Crimson.bt): type(4) + 23 floats + int[2] + float[3]
    # type(4) + initialPos(4)+initialPosJ(4)+speed(4)+speedJ(4)+accel(4)+accelJ(4)+
    #   innerRadius(4)+innerRadiusJ(4)+outerRadius(4)+outerRadiusJ(4)        (10 floats)
    #   restitutionDelay(4)+restitutionDelayJ(4)+restitutionEcc(4)+restitutionEccJ(4)+
    #   restitutionElasticity(4)+restitutionElasticityJ(4)+unkn16(4)+unkn17(4)+unkn18(4)+unkn19(4) (10 floats)
    #   unkn20(4)+unkn21(4)+unkn22(4)                                        (3 floats)
    #   int_unkn1[2](8)+float_unkn2[3](12)
    # = 4 + 23*4 + 8 + 12 = 4+92+8+12 = 116B
    if h == GUIDE:
        return 4 + 92 + 8 + 12  # = 116

    # Lightning: type(4)+unkn00[2](8)+spacer0(4)+XYZ(2)(4)*3+unkn02-04(12)+group05(100)+
    #   inflection1(20)+inflection2(20)+glow/length(16)+width(8)+startWidth group(16)+
    #   unkn05_45-48(16)+unkn06[2](8)+unkn07_00-09(40)+unkn07_10-27(72)+
    #   unkn08[2](8)+unkn09[20](80)+unkn10[4](16)+unkn11[2](8)+unkn12[2](8)+
    #   unkn13[6](24)+unkn14[3](12)+unkn15[9](36)+short unkn16(2)+int path_len(4)+path
    # Fixed portion before path_len: 550B; path_len at offset 550; total = 554 + path_len
    if h == LIGHTNING:
        path_len_val = rd_i(550)  # int path_len at offset 550 from block start
        return 554 + path_len_val

    # ParentEmissive: 4(type) + long unkn0[2](8) + float unkn2(4) + long unkn3(4) + XYZ(2)(4) +
    #   float bright(4) + float rimParam[3](12) + long unkn4(4) + float blendParam[3](12) + float unkn8[5](20)
    # = 4+8+4+4+4+4+12+4+12+20 = 76B
    if h == PARENTEMISSIVE:
        return 4 + 8 + 4 + 4 + 4 + 4 + 12 + 4 + 12 + 20  # = 76

    # PtCollision: type(4)+int unkn00-unkn07(8*4=32)+float unkn1[3](12)+int unkn2[2](8)+
    #   float bounceElasticity+j+Mult+horiz+unkn34-37 (8 floats=32B)+int unkn38(4)+
    #   int unkn4[2](8)+int ieIndex(4)+int unkn6[3](12) = 4+32+12+8+32+4+8+4+12 = 116B
    if h == PTCOLLISION:
        return 4 + 32 + 12 + 8 + 32 + 4 + 8 + 4 + 12  # = 116

    # PlSnow: 4(type) + various fixed fields
    # From BT: long type(4) + int*2(8) + long spacer(4) + ...
    # int unkn0[2](8)+long spacer(4)+int body_p(4)+int weapon_id(4)+colour(4)+int epvcolorslot(4)+
    # int alpha_effect(4)+float[4](16)+long unkn5(4)+float[8](32)+
    # Actually: unkn0[2](8)+long spacer(4)+body_part_id(4)+weapon_id(4)+colour(4)+epvcolorslot(4)+alpha_effect(4)+
    # normal_map_strength(4)+alpha_threshold(4)+unkn4_0(4)+unkn4_1(4)+long unkn5(4)+
    # roughness(4)+metallicness(4)+subsurface(4)+unkn6_0(4)+craquelure_effect(4)+craquelure_threshold(4)+
    # unkn6_1(4)+craquelure_smoothing(4)
    # = 8+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4 = 4+19*4 = 80B after type? let me count:
    # type(4) + unkn0[2](8) + long spacer(4) + body_part_id(4) + weapon_id(4) + colour(4) + epvcolorslot(4) +
    # alpha_effect(4) + normal_map_strength(4) + alpha_threshold(4) + unkn4_0(4) + unkn4_1(4) + long unkn5(4) +
    # roughness(4) + metallicness(4) + subsurface(4) + unkn6_0(4) + craquelure_effect(4) + craquelure_threshold(4) +
    # unkn6_1(4) + craquelure_smoothing(4) = 4 + 20*4 = 84B
    if h == PLSNOW:
        return 4 + 20*4  # = 84

    # PtBehavior: long type(4) + EFX_Behavior
    # EFX_Behavior: int unkn0(4) + int behav_type_len(4) + int para_count(4) + char b_type[behav_type_len]
    #               + EFX_Behav[para_count]
    # EFX_Behav: long unkn(4) + long const0(4) + int t(4) + data depending on t
    if h == PTBEHAVIOR:
        behav_type_len = rd_i(4 + 4)  # type(4) + unkn0(4) + behav_type_len(4) = at pos+8
        para_count = rd_i(4 + 8)      # at pos+12
        if behav_type_len < 0 or behav_type_len > 200 or para_count < 0 or para_count > 200:
            return None  # fallback to forward scan
        p = 4 + 12 + behav_type_len   # pos offset to first EFX_Behav
        for _ in range(para_count):
            t = rd_i(p + 8)           # int t at offset 8 within each EFX_Behav
            base = 12                  # long unkn(4) + long const0(4) + int t(4)
            if t == 0x03:
                extra = 4             # long NULL
            elif t == 0x05:
                extra = 2             # short unkn0
            elif t == 0x06:
                extra = 4             # int decal_epv_color_slot
            elif t == 0x0C:
                extra = 4             # float unkn0
            elif t == 0x0F:
                extra = 4             # XYZ(2) = ubyte[3]+pad = 4B
            elif t == 0x14:
                extra = 12            # XYZ(3) = float[3] = 12B
            elif t == 0x15:
                extra = 16            # float+long+float+long = 16B
            elif t in (0x36, 0x37):
                extra = 8             # int[2]
            elif t == 0x40:
                extra = 8             # int64
            elif t == 0x80:
                # long file_type(4) + int path_len(4) + char p[path_len]
                # Note: BT says "long NULL" for path_len field but the 4B at p+16 IS path_len
                path_len_val = rd_i(p + 12 + 4)  # path_len at p+16 (file_type=4B then path_len)
                extra = 4 + 4 + path_len_val     # file_type(4) + path_len_field(4) + path bytes
            else:
                extra = 4             # long unkn_type fallback
            p += base + extra
        return p                      # total size from pos

    # Material: long type(4) + int64 unkn00(8) + int block_count(4) = 16B header
    # Then block_count Tex_Block entries:
    #   Tex_Block: long mat_name_hash(4) + long mat_shader(4) + long unkn03(4) + int set_count(4) = 16B
    #   Then set_count Tex_Set entries:
    #     Tex_Set: long set(4) + int unkn0(4) + long t(4) + int type(4) = 16B base
    #     type=0x80: long head(4)+long NULL(4)+int path_len(4)+char p[path_len]
    #     type=0x06: int64 NULL(8)+int unkn(4) = 12B
    #     type=0x03/0x0A/0x0C: long NULL[3] = 12B
    #     type=0x15: float[6] = 24B
    #     else: long unkn_type = 4B
    if h == MATERIAL:
        block_count = rd_i(12)     # at pos+12
        p = 16                     # skip type(4)+int64(8)+block_count(4)
        for _ in range(block_count):
            set_count = rd_i(p + 12)   # int set_count at offset 12 within Tex_Block
            p += 16                     # Tex_Block header
            for _ in range(set_count):
                type_ = rd_i(p + 12)   # int type at offset 12 within Tex_Set
                p += 16                 # Tex_Set base
                if type_ == 0x80:
                    path_len_val = rd_i(p + 4 + 4)  # head(4)+NULL(4)+path_len
                    p += 4 + 4 + 4 + path_len_val
                elif type_ == 0x06:
                    p += 12             # int64(8) + int(4)
                elif type_ in (0x03, 0x0A, 0x0C):
                    p += 12             # long[3]
                elif type_ == 0x15:
                    p += 24             # float[6]
                else:
                    p += 4              # long unkn_type
        return p                    # total size from pos

    # Plane: dds_data(112B) + int unkn5[4](16) + XYZ rotate(0)(24B) + uint64 unkn7(8) + char p[path_len]
    # Note: dds_data INCLUDES the type field (long type + 26 more fields = 112B total):
    #   type(4)+unkn0(4)+applicationRule(4)+XYZ(2)[2](8)+brightness(4)+unkn20(4)+EPVColorBlend(4)+unkn22(4)+
    #   EPVColorSlot1(4)+EPVColorSlot2(4)+SlotOverride1(4)+SlotOverride2(4)+
    #   scale(4)+scaleJ(4)+width(4)+widthJ(4)+height(4)+heightJ(4)+
    #   flowmapSpeed(4)+flowmapSpeedJ(4)+flowmapAccel(4)+flowmapAccelJ(4)+
    #   flowmapStrength(4)+flowmapStrengthJ(4)+flowmapStrengthAccel(4)+flowmapStrengthAccelJ(4)+
    #   path_len(4) = 3*4+8+23*4 = 12+8+92 = 112B; path_len at offset 108 from block start
    # Total Plane block = 160 + path_len
    if h == PLANE:
        path_len_val = rd_i(108)  # path_len is the last field of dds_data at offset 108
        return 160 + path_len_val

    # RgbWater: 4(type) + ExternRgbWater (variable: has path_len)
    # ExternRgbWater: int unkn0(4)+XYZ(2)[2](8)+float*7(28)+int*3(12)+int unkn2[26](104)+int path_len(4)+path
    # fixed: 4+8+28+12+104+4 = 160B
    if h == RGBWATER:
        path_len_val = rd_i(4 + 156)
        return 4 + 156 + 4 + path_len_val

    # Turbulence: 4(type) + int unkn0(4)+int path_len(4)+char p[path_len]+float forceMultiplier(4)+
    #   float unkn1[2](8)+XYZ offsetPos(0)(24)+XYZ offsetPosVel(0)(24)+XYZ offsetAngle(0)(24)+
    #   XYZ offsetAngleVel(0)(24)+XYZ offsetScale(0)(24)+float unkn3[5](20)
    # path is BEFORE the rest of the floats! path_len at type+8
    if h == TURBULENCE:
        path_len_val = rd_i(4 + 4)  # type(4) + unkn0(4) = at +8, path_len at +8
        return 4 + 4 + 4 + path_len_val + 4 + 8 + 24*5 + 20

    # FadeByEmitterAngle: 4(type) + int*2(8) + long unkn(4) + float*4(16) = 36B
    if h == FADEBYEMITTERANGLE:
        return 4 + 8 + 4 + 16  # = 32

    # Ribbon: 364B fixed + null-terminated path string
    # Struct (EFX_Subtypes.bt): type(4)+unkn0(4)+section_length(4)+spacer0(4)+
    #   color(2)(4)+spacer1(4)+color2(2)(4)+spacer2(4)+brightness(4)+unkn4[2](8)+
    #   scale(4)+scaleJ(4)+width(4)+widthJ(4)+length(4)+lengthJ(4)+
    #   uv_map_height(4)+mat_tess_density(4)+mat_tess_j(4)+uv_map_width(4)+
    #   horiz_physics(4)+vert_physics(4)+unkn15(4)+
    #   restitution_dir(4)+unkn16[4](16)+startingAngle(4)+startingAngleJ(4)+
    #   unkn16_0[2](8)+short unkn16_1(2)+short unkn16_2(2)+spacer3(4)+
    #   unkn17(4)+spacer4(4)+lengthwise_offset(4)+unknown19_0(4)+
    #   restitution(4)+restitutionJ(4)+inertial_excess(4)+inertialJ(4)+
    #   springiness(4)+springinessJ(4)+spacer5(4)+
    #   unkn20[4](16)+unkn21(4)+unkn22[3](12)+tailTiedToBone(4)+unkn23[8](32)+
    #   unkn24(4)+epvcolor[2](8)+spacer7(4)+base_width_mult(4)+base_opacity(4)+
    #   tip_width_mult(4)+tip_opacity(4)+spacer8(4)+unkn27[2](8)+
    #   visiblePreview(2)+spacer9(2)+
    #   base_flap_freq(4)+base_flap_freqJ(4)+base_flap_amount(4)+base_flap_amountJ(4)+
    #   tip_flap_freq(4)+tip_flap_freqJ(4)+tip_flap_amount(4)+tip_flap_amountJ(4)+
    #   ib_junk[32](32)
    #   = 364B fixed + string path1 (null-terminated)
    if h == RIBBON:
        path_start = pos + 364
        null_pos = data.index(b'\x00', path_start)
        return null_pos - pos + 1  # 364 + len(path) + 1(null)

    # Noise: 4(type) + long NULL(4) + int section_length(4) + long spacer(4) + float*8(32) = 48B
    if h == NOISE:
        return 4 + 4 + 4 + 4 + 32  # = 48

    # UVControl: 4(type) + Material_Animation_Data[2](each 7*4*4=112B) + int unkn2(4) + float*8(32) = 4+224+4+32 = 264B
    # Material_Animation_Data: int unkn0(4) + uv_transform*7(each 4*4=16B) = 4+7*16=116B? No:
    # initialPos,speed,acceleration,scale,scaleSpeed,scaleAcceleration = 6 uv_transforms + int unkn0
    # uv_transform = float u,uJ,v,vJ = 16B
    # Material_Animation_Data = 4 + 6*16 = 100B
    # UVControl = 4(type) + 2*100B + int unkn2(4) + float*8(32) = 4+200+4+32 = 240B
    if h == UVCONTROL:
        return 4 + 200 + 4 + 32  # = 240

    # FadeByAngle: 4(type) + int*2(8) + float*4(16) + int64 NULL(8) + int*2(8) = 44B
    if h == FADEBYANGLE:
        return 4 + 8 + 16 + 8 + 8  # = 44

    # EmitterBoundary: 4(type) + int*2(8) + float*8(32) = 44B
    if h == EMITTERBOUNDARY:
        return 4 + 8 + 32  # = 44

    # PtLife: 4(type) + short*10(20) = 24B
    if h == PTLIFE:
        return 4 + 10*2  # = 24

    # StrainRibbon (EFX_Crimson.bt): type(4)+固定 340B+path_len(4)+path
    # path_len 在偏移 344，总长 = 348 + path_len（18 实例验证，均落在下一块）
    if h == STRAINRIBBON:
        path_len_val = rd_i(344)
        if path_len_val < 0 or path_len_val > 4096:
            return None  # 异常 → 回退 forward-scan
        return 348 + path_len_val

    # ScreenSpaceCollision: 4(type) + int*2(8) + long spacer(4) + float*3(12) + int*2(8) + float bounce*(6*4=24)...
    # = 4+8+4+4+4+4+4+4+4 = 40? From BT:
    # long type(4)+int*2(8)+long spacer(4)+float unkn1(4)+float bounce(4)+float bounceJ(4)+
    # int lifespan(4)+int lifespanJ(4)+float bounceConditional(4) = 4+8+4+4*6 = 40B
    if h == SCREENSPACECOLLISION:
        return 4 + 8 + 4 + 4*6  # = 40

    # RayCast: type(4)+unknown0(4)+fixed70(4)+spacer0(4)+distanceMod0(4)+j(4)+prop1(4)+j(4)+
    #   spacer1-3(12)+prop2(4)+XYZ(3)(12)+direction(4)+distanceMod1(4)+j(4)+spacer(4)+unknown1(4)+short(2) = 82B
    if h == RAYCAST:
        return 82

    # ExternReference: 4(type) + int unkn0(4) + int referenceIndex(4) + int unkn1[7](28) = 40B
    if h == EXTERNREFERENCE:
        return 4 + 4 + 4 + 4*7  # = 40

    # FakePlane (EFX_Crimson.bt): type(4)+int unkn0[2](8)+byte unkn1[4](4)+
    #   float unkn2(4)+int unkn3(4)+long unkn4(4)+float unkn5[9](36) = 64B
    if h == FAKEPLANE:
        return 4 + 8 + 4 + 4 + 4 + 4 + 36  # = 64

    # Dummy: 4(type) + int*2(8) + byte(1) = 13B
    if h == DUMMY:
        return 4 + 8 + 1  # = 13

    # RandomFix: 4(type) + int*10(40) = 44B
    if h == RANDOMFIX:
        return 4 + 40  # = 44

    # Transform2D: 4(type) + int(4) + float[2](8) + float(4) + float[2](8) = 28B
    if h == TRANSFORM2D:
        return 4 + 4 + 8 + 4 + 8  # = 28

    # Billboard2D (EFX_Subtypes.bt): type(4)+long unkn0[2](8)+XYZ(2)color[2](8)+
    #   float emissionMin,Max(8)+int unkn3[4](16)+
    #   float rotJitter[2]+scaleJitter[2]+imageResX+scaleX+imageResY+scaleY(8 floats=32)+
    #   float unkn4[8](32)+int path_len(4)+int unkn5[2](8)+char p[path_len]
    # 固定部分 120B，path_len 在偏移 108；总长 = 120 + path_len。
    # XYZ(2)=3 ubyte+1 NULL=4B。实测全语料 580 实例 / 121 文件 0 错。
    if h == BILLBOARD2D:
        path_len_val = rd_i(108)
        if path_len_val < 0 or path_len_val > 1024:
            return None  # 异常 → 回退 forward-scan
        return 120 + path_len_val

    # Blink: 4(type) + int*2(8) + float*11(44) = 56B
    if h == BLINK:
        return 4 + 8 + 44  # = 56

    # LuminanceBleed: long type(4) + long unkn0(4) + float unkn1[3](12) = 20B
    # (per BT: typedef struct { long type; long unkn0; float unkn1[3]; } LuminanceBleed;)
    if h == LUMINANCEBLEED:
        return 4 + 4 + 12  # = 20B

    # EmitterShape2D (EFX_Subtypes.bt): type(4)+int unkn0(4)+
    #   float offsetX,XJitter,Y,YJitter(16)+int unkn20,spawnCount,unkn22,unkn22(16) = 40B
    # ⚠ 旧值 36B 漏算了最后一个 int（BT 尾部是 4 个 int 非 3 个）；实测全语料 292 实例恒 40B。
    if h == EMITTERSHAPE2D:
        return 4 + 4 + 16 + 16  # = 40

    # Velocity2D (EFX_Subtypes.bt): type(4)+int unkn0[2](8)+
    #   float unkn10,expansionRadius,expRJ,expRElast,expRElastJ,unkn15,unkn16,energyX,energyY(9 floats=36)+
    #   int expansionType(4)+float gravity,gravityJitter(8)+
    #   int expDelay,expDelayJ,gravDelay,gravDelayJ(16) = 4+8+36+4+8+16 = 76B
    # ⚠ 旧值 72B 少 4B（少数 1 个 float）；实测全语料 277 实例恒 76B。
    if h == VELOCITY2D:
        return 4 + 8 + 36 + 4 + 8 + 16  # = 76

    # Refraction: 4(type) + int unkn0(4) + int pixelNormOffset(4) + int unkn2(4) = 16B
    if h == REFRACTION:
        return 4 + 4 + 4 + 4  # = 16

    # MasterOnly: 4(type) + int unkn0(4) = 8B
    if h == MASTERONLY:
        return 4 + 4  # = 8

    # TubeLight (EFX_Crimson.bt): type(4)+unkn0[3](12)+unkn1[11](44)+unkn2[2](8)+
    #   unkn3[4](16)+unkn4[4](16)+unkn5[2](8)+unkn6[4](16)+unkn7(4)+path_len(4)+path
    # 固定部分 132B，path_len 在偏移 128，总长 = 132 + path_len
    if h == TUBELIGHT:
        path_len_val = rd_i(128)
        if path_len_val < 0 or path_len_val > 1024:
            return None  # 异常 → 回退 forward-scan
        return 132 + path_len_val

    # Shovel: variable-ish (ends with short) - actually from BT it has fixed fields but ends with short:
    # type(4)+long*2(8)+long spacer(4)+float*6(24)+long unkn9(4)+long unkn10(4)+float unkn11(4)+
    # long*3(12)+long pattern(4)+long unkn16(4)+short unkn17(2) = 4+8+4+24+4+4+4+12+4+4+2 = 74B
    if h == SHOVEL:
        return 4 + 8 + 4 + 24 + 4 + 4 + 4 + 12 + 4 + 4 + 2  # = 74

    # Layout: 4(type) + int*2(8) + long*4(16) + LayoutBank_Block (variable!)
    if h == LAYOUT:
        return None  # variable: LayoutBank_Block

    # RepeatArea: 实测全 135 实例恒 52B → 4(type) + 52 = 56B 定长
    if h == REPEATAREA:
        return 4 + 52  # = 56

    # FakeDoF: variable (32B / 52B 两种，含 length 字段)
    if h == FAKEDOF:
        return None  # variable

    # LinkPartsVisible: 4(type) + int*3(12) = 16B
    if h == LINKPARTSVISIBLE:
        return 4 + 12  # = 16

    # PtTrigger: 4(type) + int*2(8) + long unkn1(4) + int unkn2(4) = 20B
    if h == PTTRIGGER:
        return 4 + 8 + 4 + 4  # = 20

    # PathChain: 4(type) + int*2(8) + long(4) + float(4) + int(4) + float*6(24) + int*8(32) + byte(1) = 81B
    if h == PATHCHAIN:
        return 4 + 8 + 4 + 4 + 4 + 24 + 32 + 1  # = 81

    # Homing: 4(type) + int*2(8) + long spacer(4) + float*6(24) + long*2(8) + int*2(8) = 56B
    # BT: type+unknown+unknown0+spacer+f0+speed+speedMultiplier+f3+f4+radius+i0+i1+enableRadialVanish+unknown1
    if h == HOMING:
        return 4 + 8 + 4 + 24 + 8 + 8  # = 56

    # EmitterShapeMesh (EFX_Crimson.bt): type(4)+int unkn0[2](8)+long unkn1[3](12)+
    #   byte unkn2[8](8)+int unkn3(4) = 36B fixed + null-terminated string path1 (Mod3 path)
    # ⚠ 务必精确定界：path1 让块总长不是 4 的倍数，会把后续块推到奇数地址；旧版
    #   靠 forward_scan(只探 4 对齐)会跳过全部后续块、把它们吞进本块，导致 body
    #   边界错乱、吃进下一个 body（em013_046 实证）。
    if h == EMITTERSHAPEMESH:
        path1_start = pos + 36
        null1 = data.index(b'\x00', path1_start)
        return null1 - pos + 1  # 36 + len(path1) + 1(null)

    # SpawnByAngle: 4(type) + int*2(8) + long(4) + float(4) + int(4) + short(2) = 26B
    if h == SPAWNBYANGLE:
        return 4 + 8 + 4 + 4 + 4 + 2  # = 26

    # CheckPureAttribute: 4(type) + int*2(8) + long(4) + int*7(28) = 44B
    if h == CHECKPUREATTRIBUTE:
        return 4 + 8 + 4 + 28  # = 44

    # TonemapFilter: 4(type) + int*2(8) + long(4) + float*3(12) + int path_len(4) + path
    if h == TONEMAPFILTER:
        path_len_val = rd_i(4 + 8 + 4 + 12)
        return 4 + 8 + 4 + 12 + 4 + path_len_val

    # ColorCorrectFilter: 4(type) + int*4(16) + float*168(672) = 692B
    if h == COLORCORRECTFILTER:
        return 4 + 16 + 672  # = 692

    # SpawnByOcclusion: 4(type) + int*2(8) + long(4) + float(4) + int(4) = 24B
    if h == SPAWNBYOCCLUSION:
        return 4 + 8 + 4 + 4 + 4  # = 24

    # FadeByOcclusion: 4(type) + int*2(8) + long(4) + float*3(12) = 28B
    if h == FADEBYOCCLUSION:
        return 4 + 8 + 4 + 12  # = 28

    # ParentSnow: 4(type) + int*2(8) + long(4) + int unkn2(4) + XYZ(2)(4) + long*2(8) + float*13(52) = 84B
    if h == PARENTSNOW:
        return 4 + 8 + 4 + 4 + 4 + 8 + 52  # = 84

    # OtomoSnow: 4(type) + int*2(8) + long(4) + int*2(8) + XYZ(2)(4) + int(4) + long(4) + float*4(16) + long(4) + float*8(32) = 88B
    if h == OTOMOSNOW:
        return 4 + 8 + 4 + 8 + 4 + 4 + 4 + 16 + 4 + 32  # = 88

    # ParentMaterial: 4(type) + int*2(8) + float(4) = 16B
    if h == PARENTMATERIAL:
        return 4 + 8 + 4  # = 16

    # RibbonBlade: variable (has path_len near end)
    # Structure: type(4)+unkn0[2](8)+spacer0(4)+unkn03(4)+unkn04(4)+unkn05[2](8)+spacer1(4)+unkn07[2](8)+
    #   5 floats(20)+spacer2(4)+unkn10(4)+uvRep(4)+unkn12[3](12)+spacer3(4)+
    #   EPVColorSlot head(36)+EPVColorSlot tailEnd(36)+4*(float+long)(32)+
    #   short NULL9(2)+int path_len(4)+char p[path_len]
    # Fixed size before path = 202B; path_len at offset 198; total = 202 + path_len
    if h == RIBBONBLADE:
        path_len_val = rd_i(198)  # path_len field at offset 198 from block start
        return 202 + path_len_val

    return None  # truly unknown type


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EFXHeader:
    """72-byte file header (fully parsed)."""
    signature: bytes        # b"EFX\x00"
    version: int
    constant: tuple         # 5 ints
    efxr: bytes             # b"efxr"
    unkn0: int
    unkn1: int
    count_body: int
    label_size: int
    count_play: int
    count_extern: int
    count_subselect: int
    subselect_size: int
    count_eof: int
    double_buffer: int

    STRUCT = struct.Struct('<4s i 5i 4s 10I')
    SIZE = 72

    def serialize(self) -> bytes:
        return self.STRUCT.pack(
            self.signature, self.version,
            *self.constant,
            self.efxr,
            self.unkn0, self.unkn1,
            self.count_body, self.label_size,
            self.count_play, self.count_extern,
            self.count_subselect, self.subselect_size,
            self.count_eof, self.double_buffer,
        )


@dataclass
class PlayEntry:
    """One entry within a PlayData block: either PlayEFX or PlayEmitter."""
    type_hash: int
    raw: bytes  # the entry bytes EXCLUDING the 4-byte type_hash prefix

    def serialize(self) -> bytes:
        return struct.pack('<I', self.type_hash) + self.raw


@dataclass
class PlayData:
    """One countPlay entry in the Play section."""
    play_type: int      # the 'long type' of PlayData
    entries: List[PlayEntry]

    def serialize(self) -> bytes:
        out = struct.pack('<Ii', self.play_type, len(self.entries))
        for e in self.entries:
            out += e.serialize()
        return out


@dataclass
class ExternDataItem:
    """One Extern_Data sub-item within an Extern_Attribute (opaque payload)."""
    type_hash: int
    unkn: int           # int (4B) after type hash
    attr_count: int     # int (4B): number of structs in data_bytes
    data_bytes: bytes   # attr_count * struct_size bytes (opaque)

    def serialize(self) -> bytes:
        return struct.pack('<Iii', self.type_hash, self.unkn, self.attr_count) + self.data_bytes


@dataclass
class ExternAttribute:
    """One entry in the Extern section (Extern_Attribute)."""
    attr_type: int      # long (4B)
    null0: int          # long (4B) = 0
    null1: int          # long (4B) = 0
    items: List[ExternDataItem]

    def serialize(self) -> bytes:
        out = struct.pack('<IiIi', self.attr_type, self.null0, len(self.items), self.null1)
        for item in self.items:
            out += item.serialize()
        return out


@dataclass
class AttrBlock:
    """One attribute block within a Main_Data body."""
    type_hash: int
    data_bytes: bytes   # bytes AFTER the 4-byte type hash

    @property
    def name(self) -> str:
        return HASH_TO_NAME.get(self.type_hash, f'0x{self.type_hash:08X}')

    def serialize(self) -> bytes:
        return struct.pack('<I', self.type_hash) + self.data_bytes

    def decode(self) -> Optional[dict]:
        """
        Decode data_bytes into a named-field dict using the registered schema
        for this block's type_hash.  Returns None if no schema is registered
        (block stays opaque).

        For fixed-size types, uses the schema from ATTR_SCHEMA_MAP.
        For variable/dispatch types (schema == '_custom'), uses ATTR_CUSTOM_CODEC.
        """
        from .structs import ATTR_SCHEMA_MAP, ATTR_CUSTOM_CODEC, unpack
        entry = ATTR_SCHEMA_MAP.get(self.type_hash)
        if entry is None:
            return None
        schema, expected_size = entry

        # Variable/dispatch types: route to custom codec
        if schema == '_custom':
            custom = ATTR_CUSTOM_CODEC.get(self.type_hash)
            if custom is None:
                return None
            unpack_fn, _ = custom
            values, consumed = unpack_fn(self.data_bytes, 0)
            if consumed != len(self.data_bytes):
                raise ValueError(
                    f'AttrBlock.decode (custom): {self.name} '
                    f'consumed {consumed} bytes but data_bytes is {len(self.data_bytes)} bytes'
                )
            return values

        # Fixed-size schema
        if len(self.data_bytes) != expected_size:
            raise ValueError(
                f'AttrBlock.decode: {self.name} '
                f'data_bytes length {len(self.data_bytes)} '
                f'!= expected {expected_size}'
            )
        values, consumed = unpack(schema, self.data_bytes, 0)
        if consumed != expected_size:
            raise ValueError(
                f'AttrBlock.decode: {self.name} '
                f'schema consumed {consumed} bytes but data_bytes is {expected_size} bytes'
            )
        return values

    def encode(self, values: dict) -> None:
        """
        Re-encode *values* (as returned by decode()) back into data_bytes
        in-place, using the registered schema.  Raises ValueError if the
        resulting bytes differ in length from the original data_bytes.
        """
        from .structs import ATTR_SCHEMA_MAP, ATTR_CUSTOM_CODEC, pack
        entry = ATTR_SCHEMA_MAP.get(self.type_hash)
        if entry is None:
            raise ValueError(
                f'AttrBlock.encode: no schema for {self.name} '
                f'(0x{self.type_hash:08X})'
            )
        schema, expected_size = entry

        # Variable/dispatch types: route to custom codec
        if schema == '_custom':
            custom = ATTR_CUSTOM_CODEC.get(self.type_hash)
            if custom is None:
                raise ValueError(
                    f'AttrBlock.encode: no custom codec for {self.name} '
                    f'(0x{self.type_hash:08X})'
                )
            _, pack_fn = custom
            encoded = pack_fn(values)
            if len(encoded) != len(self.data_bytes):
                raise ValueError(
                    f'AttrBlock.encode (custom): {self.name} '
                    f'encoded {len(encoded)} bytes but original data_bytes is '
                    f'{len(self.data_bytes)} bytes'
                )
            self.data_bytes = encoded
            return

        # Fixed-size schema
        encoded = pack(schema, values)
        if len(encoded) != expected_size:
            raise ValueError(
                f'AttrBlock.encode: {self.name} '
                f'encoded {len(encoded)} bytes but expected {expected_size}'
            )
        self.data_bytes = encoded


@dataclass
class MainDataBody:
    """A Main_Data body (non-Root)."""
    body_type: int          # type hash (= jamcrc32 of label)
    unkn0: int
    attr_count: int         # expected number of attr blocks
    null: int
    timl_length: int
    timl_bytes: bytes       # timl_length bytes (opaque)
    attr_blocks: List[AttrBlock]

    def serialize(self) -> bytes:
        # evc 哨兵：attr_count 为负数时 range() 为空 → 解析出 0 块，但原始字段值需保留
        count = self.attr_count if (not self.attr_blocks and self.attr_count != 0) else len(self.attr_blocks)
        head = struct.pack('<IiiiI', self.body_type, self.unkn0,
                           count, self.null, self.timl_length)
        out = head + self.timl_bytes
        for blk in self.attr_blocks:
            out += blk.serialize()
        return out


@dataclass
class MainDataBodyExtended:
    """
    A Main_Data body with an extended 36-byte header (body_type == 1).

    Extended header layout (36 B):
      +0:  body_type (4B) = 1
      +4:  unkn0     (4B) = 0
      +8:  null0     (4B) = 0
      +12: null1     (4B) = 0
      +16: unkn1     (4B) = opaque (sometimes equals jamcrc32 of a label)
      +20: unkn2     (4B)
      +24: attr_count(4B)
      +28: null2     (4B) = 0
      +32: timl_length(4B)
      +36: timl data (timl_length bytes, opaque)
    followed by attr_count attribute blocks.
    """
    body_type: int       # = 1
    unkn0: int           # = 0
    null0: int           # = 0
    null1: int           # = 0
    unkn1: int           # opaque
    unkn2: int           # opaque
    attr_count: int      # number of attr blocks
    null2: int           # = 0
    timl_length: int
    timl_bytes: bytes    # timl_length bytes
    attr_blocks: List[AttrBlock]

    def serialize(self) -> bytes:
        head = struct.pack(
            '<IiiiIiiIi',
            self.body_type, self.unkn0, self.null0, self.null1,
            self.unkn1, self.unkn2, len(self.attr_blocks), self.null2,
            self.timl_length,
        )
        out = head + self.timl_bytes
        for blk in self.attr_blocks:
            out += blk.serialize()
        return out


@dataclass
class RootUnitBoundary:
    """
    Root 子条目 UnitBoundary（EFX_Root.bt）。固定 44 字节：
      long type(4) = ROOT_UNITBOUNDARY
      int  ints[2] (8)        —— 单位/边界相关整型（语义未完全逆向）
      float floats[8] (32)    —— 实测后段含包围盒式数值；.bt 标注 7 float + 1 long NULL，
                                 但官方数据该尾字段常为非零 float，故统一按 8 float 存取。
    """
    ints: tuple    # (int0, int1)
    floats: tuple  # 8 floats

    def serialize(self) -> bytes:
        return (struct.pack('<i', RootBody.UNITBOUNDARY)
                + struct.pack('<2i', *self.ints)
                + struct.pack('<8f', *self.floats))


@dataclass
class RootOpaqueEntry:
    """Root 子条目中尚未结构化的类型（RenderTarget / LayoutBank），原样存取。"""
    raw: bytes   # 整个子条目字节（含前导 type）

    def serialize(self) -> bytes:
        return self.raw


@dataclass
class RootBody:
    """
    Root body（type == ROOT_MARKER）。

    16B 头（root_type + const0 + count + const1）后跟 count 个子条目。
    UnitBoundary 结构化为可编辑字段；RenderTarget/LayoutBank 保留 opaque。
    若 raw 非 None（旧式/无法结构化的整段不透明回退），serialize 直接重发 raw。
    """
    # 子条目 type marker（EFX_Root.bt）
    UNITBOUNDARY = 1413509420
    RENDERTARGET = 2083659062
    LAYOUTBANK   = 2050487542

    root_type: int = ROOT_MARKER
    const0: int = 1
    const1: int = 0
    entries: list = field(default_factory=list)   # RootUnitBoundary | RootOpaqueEntry
    raw: bytes = None   # 整段不透明回退（unknown 兜底用）

    def serialize(self) -> bytes:
        if self.raw is not None:
            return self.raw
        out = struct.pack('<iiii', self.root_type, self.const0,
                          len(self.entries), self.const1)
        for e in self.entries:
            out += e.serialize()
        return out


@dataclass
class SubselectTable:
    """One table in the Subselect section."""
    table_type: int     # long (4B)
    unkn0: tuple        # long[3] (12B)
    entries: List[int]  # int[count]

    def serialize(self) -> bytes:
        out = struct.pack('<I3I', self.table_type, *self.unkn0)
        out += struct.pack('<i', len(self.entries))
        for e in self.entries:
            out += struct.pack('<i', e)
        return out


# ─────────────────────────────────────────────────────────────────────────────
# Main EFX parser/serializer
# ─────────────────────────────────────────────────────────────────────────────

class EFXFile:
    """
    Parses and re-serializes a MHW .efx file.

    Usage::

        efx = EFXFile.parse(open('foo.efx', 'rb').read())
        assert efx.serialize() == open('foo.efx', 'rb').read()
    """

    def __init__(self):
        self.header: EFXHeader = None
        self.label_bytes: bytes = b''         # raw EFX_Type section
        self.labels: List[str] = []
        self.play: List[PlayData] = []
        self.extern: List[ExternAttribute] = []
        self.main: List = []                  # List[MainDataBody | RootBody]
        self.subselect: List[SubselectTable] = []
        self.eof_ints: List[int] = []
        self.eof_tail: bytes = b''     # eof 之后的不透明尾字节（部分游戏文件有，如 4 字节 footer）
        # ── main 段不可解析时的不透明回退 ──────────────────────────────────────
        # 某些文件 main 段含我们尚无法定界的块（forward_scan 启发式越界），整段
        # 解析会崩。此时把 main 起点到 EOF 的全部字节（main+subselect+eof+tail）
        # 原样存为 opaque blob，serialize 时 verbatim 重发 → 仍 byte-perfect、可导入。
        # 代价：此文件 main 段不可在 Blender 内逐块编辑（整体只读）。
        self.main_opaque: bool = False
        self.opaque_main_tail: bytes = b''

    # ── Public API ──────────────────────────────────────────────────────────

    @classmethod
    def parse(cls, data: bytes) -> 'EFXFile':
        obj = cls()
        pos = 0

        # ── Header ──────────────────────────────────────────────────────────
        raw = EFXHeader.STRUCT.unpack_from(data, pos)
        pos += EFXHeader.SIZE
        sig, ver, c0, c1, c2, c3, c4, efxr, u0, u1, cb, ls, cp, ce, cs, ss, ceof, db = raw
        obj.header = EFXHeader(
            signature=sig, version=ver,
            constant=(c0, c1, c2, c3, c4),
            efxr=efxr,
            unkn0=u0, unkn1=u1,
            count_body=cb, label_size=ls,
            count_play=cp, count_extern=ce,
            count_subselect=cs, subselect_size=ss,
            count_eof=ceof, double_buffer=db,
        )
        hdr = obj.header

        # ── EFX_Type (label table) ───────────────────────────────────────────
        obj.label_bytes = data[pos:pos + hdr.label_size]
        obj.labels = [
            s.decode('utf-8', errors='replace')
            for s in obj.label_bytes.rstrip(b'\x00').split(b'\x00')
            if s
        ]
        pos += hdr.label_size

        # ── Play ─────────────────────────────────────────────────────────────
        obj.play, pos = cls._parse_play(data, pos, hdr.count_play)

        # ── Extern ───────────────────────────────────────────────────────────
        obj.extern, pos = cls._parse_extern(data, pos, hdr.count_extern)

        # ── Main（+ Subselect + End）─────────────────────────────────────────
        # main 段含未定界块时 _parse_main 会崩。此时整段（main 起点→EOF）转 opaque
        # 回退，保证文件仍能 byte-perfect 导入（代价：main 不可逐块编辑）。
        main_start = pos
        try:
            obj.main, pos = cls._parse_main(data, pos, hdr.count_body)

            # ── Subselect ────────────────────────────────────────────────────
            if hdr.subselect_size > 0:
                obj.subselect, pos = cls._parse_subselect(data, pos, hdr.count_subselect)
            else:
                obj.subselect = []

            # ── End ──────────────────────────────────────────────────────────
            obj.eof_ints = list(struct.unpack_from(f'<{hdr.count_eof}I', data, pos))
            pos += hdr.count_eof * 4

            # eof 之后的尾字节：部分游戏文件在 eof 后有不透明 footer（如 jichu1.efx
            # 末尾多 4 字节）。捕获为 opaque tail 原样保留（78 样本 tail 为空）。
            obj.eof_tail = data[pos:]
        except Exception:
            # main 解析失败：整段（含 subselect/eof/tail）转 opaque，verbatim 重发。
            obj.main = []
            obj.subselect = []
            obj.eof_ints = []
            obj.eof_tail = b''
            obj.main_opaque = True
            obj.opaque_main_tail = data[main_start:]

        return obj

    def serialize(self) -> bytes:
        out = self.header.serialize()
        out += self.label_bytes

        for pd in self.play:
            out += pd.serialize()

        for ea in self.extern:
            out += ea.serialize()

        # main 段不可解析时走 opaque 回退：main 起点之后全部字节 verbatim 重发。
        if self.main_opaque:
            out += self.opaque_main_tail
            return out

        for body in self.main:
            out += body.serialize()

        for tbl in self.subselect:
            out += tbl.serialize()

        for v in self.eof_ints:
            out += struct.pack('<I', v)

        out += self.eof_tail   # eof 后不透明 footer（多数文件为空）

        return out

    # ── Internal section parsers ─────────────────────────────────────────────

    @staticmethod
    def _parse_play(data: bytes, pos: int, count: int):
        """Parse countPlay PlayData entries."""
        results = []
        for _ in range(count):
            play_type = struct.unpack_from('<I', data, pos)[0]
            entry_count = struct.unpack_from('<i', data, pos + 4)[0]
            pos += 8
            entries = []
            for _ in range(entry_count):
                type_hash = struct.unpack_from('<I', data, pos)[0]
                pos += 4
                if type_hash == PLAYEFX:
                    # PlayEFX layout (all fields after type_hash):
                    # int unkn0(4) + int path_len(4) + long type(4) + int unkn[7](28)
                    # + XYZ xyz(3)(12) + int NULL[3](12) + char p[path_len]
                    # = 4+4+4+28+12+12 = 64B fixed + path_len
                    path_len = struct.unpack_from('<i', data, pos + 4)[0]
                    entry_size = 64 + path_len
                    entry_raw = data[pos:pos + entry_size]
                    pos += entry_size
                elif type_hash == PLAYEMITTER:
                    # PlayEmitter layout:
                    # int unkn[7](28) + XYZ xyz(3)(12) + int NULL[3](12) + int target_count(4) + int targets[target_count]
                    # = 28+12+12+4 = 56B fixed + 4*target_count
                    target_count = struct.unpack_from('<i', data, pos + 52)[0]
                    entry_size = 56 + 4 * target_count
                    entry_raw = data[pos:pos + entry_size]
                    pos += entry_size
                else:
                    raise ValueError(
                        f'Unknown Play typeHash 0x{type_hash:08X} at offset {pos-4}'
                    )
                entries.append(PlayEntry(type_hash=type_hash, raw=entry_raw))
            results.append(PlayData(play_type=play_type, entries=entries))
        return results, pos

    @staticmethod
    def _parse_extern(data: bytes, pos: int, count: int):
        """Parse countExtern Extern_Attribute entries."""
        results = []
        for _ in range(count):
            # Extern_Attribute: long type(4) + long NULL0(4) + int count(4) + long NULL1(4)
            attr_type = struct.unpack_from('<I', data, pos)[0]
            null0 = struct.unpack_from('<i', data, pos + 4)[0]
            item_count = struct.unpack_from('<i', data, pos + 8)[0]
            null1 = struct.unpack_from('<i', data, pos + 12)[0]
            pos += 16

            items = []
            for _ in range(item_count):
                # Extern_Data: long t(4) + int unkn(4) + int attri_count(4) + data
                t = struct.unpack_from('<I', data, pos)[0]
                unkn = struct.unpack_from('<i', data, pos + 4)[0]
                attri_count = struct.unpack_from('<i', data, pos + 8)[0]
                pos += 12
                item_size = EFXFile._extern_data_size(t, attri_count, data, pos)
                item_bytes = data[pos:pos + item_size]
                pos += item_size
                items.append(ExternDataItem(
                    type_hash=t, unkn=unkn, attr_count=attri_count, data_bytes=item_bytes
                ))
            results.append(ExternAttribute(
                attr_type=attr_type, null0=null0, null1=null1, items=items
            ))
        return results, pos

    @staticmethod
    def _efx_behavior_size(data: bytes, pos: int) -> int:
        """
        Return byte size of one EFX_Behavior struct at *pos* (EFX_Crimson.bt):
          int unkn0(4) + int behav_type_len(4) + int para_count(4)
          + char b_type[behav_type_len] + EFX_Behav[para_count]
        EFX_Behav = long unkn(4) + long const0(4) + int t(4) + 变长 data（按 t 分派）。
        与主体 PTBEHAVIOR 块的 EFX_Behavior 共用同一编码（见 _known_attr_size::PTBEHAVIOR）。
        """
        behav_type_len = struct.unpack_from('<i', data, pos + 4)[0]
        para_count = struct.unpack_from('<i', data, pos + 8)[0]
        p = pos + 12 + behav_type_len   # skip unkn0/behav_type_len/para_count + b_type
        for _ in range(para_count):
            t = struct.unpack_from('<i', data, p + 8)[0]  # int t at offset 8 in EFX_Behav
            base = 12                  # long unkn(4) + long const0(4) + int t(4)
            if t == 0x03:
                extra = 4              # long NULL
            elif t == 0x05:
                extra = 2              # short unkn0
            elif t == 0x06:
                extra = 4              # int decal_epv_color_slot
            elif t == 0x0C:
                extra = 4              # float unkn0
            elif t == 0x0F:
                extra = 4              # XYZ(2) = ubyte[3]+pad
            elif t == 0x14:
                extra = 12            # XYZ(3) = float[3]
            elif t == 0x15:
                extra = 16            # float+long+float+long
            elif t in (0x36, 0x37):
                extra = 8             # int[2]
            elif t == 0x40:
                extra = 8             # int64
            elif t == 0x80:
                path_len_val = struct.unpack_from('<i', data, p + 12 + 4)[0]
                extra = 4 + 4 + path_len_val  # file_type(4) + path_len(4) + path
            else:
                extra = 4             # long unkn_type fallback
            p += base + extra
        return p - pos

    @staticmethod
    def _extern_data_size(type_hash: int, attri_count: int,
                          data: bytes = b'', pos: int = 0) -> int:
        """Return total data bytes (after the 12-byte Extern_Data header) for a known extern type.
        data/pos are required for variable-length types."""
        # Fixed sizes (bytes per element)
        FIXED = {
            500644368: 228,   # EXTERNTRANSFORM3D  (ExternTransform3D)
            351887441: 108,   # EXTERNVELOCITY3D
            786529163: 76,    # EXTERNSCALEANIM
            2069124466: 112,  # EXTERNRGBFIRE
            28559457: 72,     # EXTERNSPAWN (EFX_Crimson.bt: ExternSpawn = long unkn[18] = 72B)
            1880343637: 88,   # EXTERNEMITTERSHAPE3D (EFX_Crimson.bt: long unkn[22] = 88B)
            725249589: 76,    # EXTERNPLEMISSIVE
            1338793878: 48,   # EXTERNVELOCITY3D0 (long unkn[12] = 48B)
            283026906: 84,    # EXTERNVELOCITY3D2 (long unkn[21] = 84B)
            705591903: 72,    # EXTERNVELOCITY3D5 (long unkn[18] = 72B)
            1879331968: 80,   # EXTERNVELOCITY3D6 (long unkn[20] = 80B)
            0x3002E4CE: 288,  # EXTERNVELOCITY3D7 (long unkn[72] = 288B, brute-force verified)
            0x295D488A: 133,  # EXTERNBILLBOARD3D (133B/elem, confirmed via structural analysis)
            0x320E3177: 361,  # EXTERNVELOCITY3D1 (361B/elem, confirmed via structural analysis)
            0x1CC2BE3A: 161,  # EXTERNRGBWATER (161B/elem, roundtrip verified)
            0x7CFF28CC: 45,   # EXTERNUVSEQUENCE (45B/elem, confirmed via structural analysis)
        }
        if type_hash in FIXED:
            return attri_count * FIXED[type_hash]

        # Variable-length: EXTERNMESH - each element has 175B fixed + 2 null-terminated strings
        # ExternMesh = Mod3Properties(174B) + byte BeginMod3(1) + string path + string placement
        if type_hash == 1850314036:  # EXTERNMESH
            p = pos
            for _ in range(attri_count):
                path1_start = p + 175
                null1 = data.index(b'\x00', path1_start)
                null2 = data.index(b'\x00', null1 + 1)
                p = null2 + 1
            return p - pos

        # Variable-length: EXTERNPTBEHAVIOR - data = EFX_Behavior efx_behaiv[attri_count]
        # (EFX_Extern.bt). EFX_Behavior 与主体 PTBEHAVIOR 块同源：int unkn0(4) +
        # int behav_type_len(4) + int para_count(4) + char b_type[behav_type_len] +
        # EFX_Behav[para_count]（每个参数变长，按 t 分派）。
        # ⚠ 旧实现把 b_type 当 null 结尾串、尾巴写死 16B —— 参数数组变长导致整段错位，
        #   后续 extern 项落进字符串区（em024_062 / em026_001 实证）。
        if type_hash == 0x5FFC3E36:  # EXTERNPTBEHAVIOR
            p = pos
            for _ in range(attri_count):
                p += EFXFile._efx_behavior_size(data, p)
            return p - pos

        # Variable-length types that are not yet seen in samples - raise for diagnosis
        raise ValueError(
            f'Cannot compute size for unknown Extern_Data type 0x{type_hash:08X} '
            f'({HASH_TO_NAME.get(type_hash, "UNKNOWN")}). '
            f'attri_count={attri_count}. '
            f'This type needs manual size implementation.'
        )

    @staticmethod
    def _parse_main(data: bytes, pos: int, count: int):
        """Parse countBody Main bodies."""
        results = []
        for body_idx in range(count):
            if pos + 4 > len(data):
                raise ValueError(f'EOF reached while reading Main body {body_idx} at pos {pos}')
            first_int = struct.unpack_from('<I', data, pos)[0]
            if first_int == ROOT_MARKER:
                body, pos = EFXFile._parse_root_body(data, pos)
            else:
                body, pos = EFXFile._parse_main_data_body(data, pos)
            results.append(body)
        return results, pos

    @staticmethod
    def _parse_root_body(data: bytes, start_pos: int):
        """
        Parse a Root body opaquely.

        Root body structure (EFX_Root.bt):
          long type (4B, = ROOT_MARKER)
          int CONST0 (4B, = 1)
          int count  (4B)
          int CONST1 (4B, = 0)
          for count sub-entries: each starts with a known hash and has its own fixed/variable size.

        For phase 0, we parse until we find the end of the root body by scanning forward.
        Strategy: parse sub-entries by hash until we've consumed `count` of them.
        But since Root sub-entry structures are complex (LayoutBank has variable blocks),
        we store the entire Root body as opaque bytes bounded by:
          - next body's known type hash at a 4B-aligned position, OR
          - end of Main section (calculated from file structure).

        We cannot know the end without forward-scanning or using total-file structure.
        For now, parse header + count sub-entries opaquely using known sub-structure.
        """
        pos = start_pos
        root_type = struct.unpack_from('<I', data, pos)[0]   # = ROOT_MARKER
        const0 = struct.unpack_from('<i', data, pos + 4)[0]  # = 1
        count = struct.unpack_from('<i', data, pos + 8)[0]
        const1 = struct.unpack_from('<i', data, pos + 12)[0] # = 0
        pos += 16

        # Parse count sub-entries (UnitBoundary, RenderTarget, LayoutBank)
        UNITBOUNDARY = RootBody.UNITBOUNDARY
        RENDERTARGET = RootBody.RENDERTARGET
        LAYOUTBANK   = RootBody.LAYOUTBANK

        entries = []
        for i in range(count):
            sub_type = struct.unpack_from('<i', data, pos)[0]
            ent_start = pos
            if sub_type == UNITBOUNDARY:
                # long type(4) + int*2(8) + float*8(32) = 44B
                ints = struct.unpack_from('<2i', data, pos + 4)
                floats = struct.unpack_from('<8f', data, pos + 12)
                entries.append(RootUnitBoundary(ints=ints, floats=floats))
                pos += 44
            elif sub_type == RENDERTARGET:
                # long type(4) + int path_count(4, = 6 hardcoded) + 6*RenderTarget_Path + long NULL(4) + int*6(24) + float*9(36)
                # RenderTarget_Path = int path_len(4) + char p[path_len]
                pos += 4 + 4  # type + path_count
                for _ in range(6):
                    p_len = struct.unpack_from('<i', data, pos)[0]
                    pos += 4 + p_len
                pos += 4 + 24 + 36  # NULL + unkn0[6] + unkn1[9]
                entries.append(RootOpaqueEntry(raw=data[ent_start:pos]))
            elif sub_type == LAYOUTBANK:
                # LayoutBank: long type(4) + int unkn0(4) + int block_count(4) + block_count*LayoutBank_Block
                # LayoutBank_Block = int count(4) + if count>0: while ReadInt()!=-1: LayoutBank_B; long end
                # LayoutBank_B = int block_type(4) + data depending on block_type
                pos = EFXFile._parse_layout_bank(data, pos)
                entries.append(RootOpaqueEntry(raw=data[ent_start:pos]))
            else:
                # Unknown sub-type in Root body - should not happen in well-formed files
                raise ValueError(
                    f'Unknown Root sub-entry type 0x{sub_type:08X} at pos {pos}'
                )

        return RootBody(root_type=root_type, const0=const0, const1=const1,
                        entries=entries), pos

    @staticmethod
    def _parse_layout_bank(data: bytes, pos: int) -> int:
        """Parse a LayoutBank struct and return the new position."""
        lb_type = struct.unpack_from('<i', data, pos)[0]      # long type
        unkn0 = struct.unpack_from('<i', data, pos + 4)[0]    # int unkn0
        block_count = struct.unpack_from('<i', data, pos + 8)[0]  # int block_count
        pos += 12

        for _ in range(block_count):
            # LayoutBank_Block: int count(4); if count>0: while ReadInt()!=-1: LayoutBank_B; long end
            count = struct.unpack_from('<i', data, pos)[0]
            pos += 4
            if count > 0:
                while True:
                    sentinel = struct.unpack_from('<i', data, pos)[0]
                    if sentinel == -1:
                        pos += 4  # consume the -1 sentinel (long end = 8B? or 4B?)
                        # BT says 'long end' = 4B
                        break
                    # LayoutBank_B: int block_type(4) + data
                    block_type = sentinel
                    pos += 4  # consume block_type
                    if 0 < block_type < 6:
                        # UN p[count*2]
                        pos += count * 2 * 4
                    elif block_type == 0 or block_type == 6:
                        # UN p[count*3]
                        pos += count * 3 * 4
                    elif block_type == 7:
                        # int unkn0; UN p[count*2*unkn0]
                        sub_unkn0 = struct.unpack_from('<i', data, pos)[0]
                        pos += 4
                        pos += count * 2 * sub_unkn0 * 4
                    else:
                        raise ValueError(f'LayoutBank_B: unknown block_type={block_type} at pos {pos-4}')
        return pos

    @staticmethod
    def _parse_main_data_body(data: bytes, start_pos: int):
        """Parse a Main_Data body (20B header + TIML + attr blocks)."""
        pos = start_pos
        body_type = struct.unpack_from('<I', data, pos)[0]

        # Detect extended 36-byte header: body_type < 256 is not a valid jamcrc32 result,
        # so it indicates the extended header format used by body_type=1 bodies.
        if body_type < 256:
            # Extended 36-byte header layout:
            # type(4)+unkn0(4)+null0(4)+null1(4)+unkn1(4)+unkn2(4)+attr_count(4)+null2(4)+timl_length(4)
            unkn0  = struct.unpack_from('<i', data, pos + 4)[0]
            null0  = struct.unpack_from('<i', data, pos + 8)[0]
            null1  = struct.unpack_from('<i', data, pos + 12)[0]
            unkn1  = struct.unpack_from('<I', data, pos + 16)[0]
            unkn2  = struct.unpack_from('<i', data, pos + 20)[0]
            attr_count = struct.unpack_from('<i', data, pos + 24)[0]
            null2  = struct.unpack_from('<i', data, pos + 28)[0]
            timl_length = struct.unpack_from('<i', data, pos + 32)[0]
            pos += 36

            timl_bytes = data[pos:pos + timl_length]
            pos += timl_length

            attr_blocks, pos = EFXFile._parse_attr_blocks(data, pos, attr_count)

            return MainDataBodyExtended(
                body_type=body_type, unkn0=unkn0, null0=null0, null1=null1,
                unkn1=unkn1, unkn2=unkn2, attr_count=attr_count, null2=null2,
                timl_length=timl_length, timl_bytes=timl_bytes,
                attr_blocks=attr_blocks,
            ), pos

        # Standard 20-byte header
        unkn0 = struct.unpack_from('<i', data, pos + 4)[0]
        attr_count = struct.unpack_from('<i', data, pos + 8)[0]
        null = struct.unpack_from('<i', data, pos + 12)[0]
        timl_length = struct.unpack_from('<i', data, pos + 16)[0]
        pos += 20

        # TIML (opaque)
        timl_bytes = data[pos:pos + timl_length]
        pos += timl_length

        # Attribute blocks
        attr_blocks, pos = EFXFile._parse_attr_blocks(data, pos, attr_count)

        return MainDataBody(
            body_type=body_type, unkn0=unkn0, attr_count=attr_count,
            null=null, timl_length=timl_length,
            timl_bytes=timl_bytes, attr_blocks=attr_blocks,
        ), pos

    @staticmethod
    def _parse_attr_blocks(data: bytes, pos: int, attr_count: int):
        """Parse attr_count attribute blocks; use forward-scan for unknown types."""
        blocks = []
        for blk_idx in range(attr_count):
            if pos + 4 > len(data):
                raise ValueError(
                    f'EOF reached reading attr block {blk_idx}/{attr_count} at pos {pos}'
                )
            type_hash = struct.unpack_from('<I', data, pos)[0]
            block_size = _known_attr_size(data, pos, type_hash)

            if block_size is not None:
                # Known type: exact size
                block_data = data[pos + 4:pos + block_size]
                blocks.append(AttrBlock(type_hash=type_hash, data_bytes=block_data))
                pos += block_size
            else:
                # Unknown or variable type: forward-scan to find next block boundary
                scan_start = pos + 4  # after the type hash we just read
                remaining_blocks = attr_count - blk_idx - 1
                end_pos = EFXFile._forward_scan(
                    data, scan_start, remaining_blocks
                )
                block_data = data[pos + 4:end_pos]
                blocks.append(AttrBlock(type_hash=type_hash, data_bytes=block_data))
                pos = end_pos

        return blocks, pos

    @staticmethod
    def _forward_scan(data: bytes, scan_start: int, remaining_blocks: int) -> int:
        """
        Scan forward from scan_start to find the position of the NEXT attribute block's
        type hash (if remaining_blocks > 0) or the end of this body's attribute data.

        The heuristic: the next block starts at the first 4B-aligned offset that reads
        a value in ATTR_HASHES (and is preceded by valid data).  We scan every 4B.

        If remaining_blocks == 0, there is no next block; we must guess the end.
        In that case we scan for any known hash OR body/section boundary.

        Since we don't have explicit body end markers, we can only scan for known hashes.
        If no known hash is found before EOF, return remaining data up to EOF
        (this would be wrong for the middle of a file, but safe for opaque storage).
        """
        if remaining_blocks > 0:
            # Scan for the next known attr hash
            i = scan_start
            while i + 4 <= len(data):
                candidate = struct.unpack_from('<I', data, i)[0]
                if candidate in ATTR_HASHES:
                    return i
                i += 4
            # No next known hash found - return to end of data (edge case)
            return len(data)
        else:
            # Last block in body: scan for next body's type hash OR next known hash
            # We don't have a body boundary marker, so just return scan_start
            # and record the remaining body bytes.
            # This is tricky without explicit lengths.  For now, return scan_start
            # (zero bytes for the payload), which will be wrong but detectable.
            # TODO: improve this case if needed for specific types.
            i = scan_start
            while i + 4 <= len(data):
                candidate = struct.unpack_from('<I', data, i)[0]
                if candidate in ATTR_HASHES or candidate == ROOT_MARKER:
                    return i
                i += 4
            return len(data)

    @staticmethod
    def _parse_subselect(data: bytes, pos: int, count: int):
        """Parse countSubselect Subselect_Table entries."""
        results = []
        for _ in range(count):
            tbl_type = struct.unpack_from('<I', data, pos)[0]
            unkn0 = struct.unpack_from('<3I', data, pos + 4)
            entry_count = struct.unpack_from('<i', data, pos + 16)[0]
            pos += 20
            entries = list(struct.unpack_from(f'<{entry_count}i', data, pos))
            pos += 4 * entry_count
            results.append(SubselectTable(table_type=tbl_type, unkn0=unkn0, entries=entries))
        return results, pos
