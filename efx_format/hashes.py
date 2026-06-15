"""
EFX type hash constants, extracted from refs/EFX_Hashes.bt.

All values are 32-bit unsigned integers (BT 'long' / 'int' = 4 bytes, little-endian).
Provides:
  - NAME_TO_HASH : dict[str, int]  (name → hash value)
  - HASH_TO_NAME : dict[int, str]  (hash value → name, for display/debug)
  - ALL_HASHES   : frozenset[int]  (used for forward-scanning unknown attr blocks)

BT comment note: the byte-order comments in EFX_Hashes.bt are occasionally swapped
(e.g. PLAYEFX comment shows PLAYEMITTER bytes).  The *integer values* are authoritative.
"""

# ── Play type hashes ──────────────────────────────────────────────────────────
PLAYEFX             = 1965813039    # 0x752BED2F  external .efx file call
PLAYEMITTER         = 1152332069    # 0x44AF3125  internal body reference

# ── Attribute block (Main body) type hashes ───────────────────────────────────
TIML                = 1819109748    # 0x6C6D6974  keyframe animation (opaque in phase 0)
TRANSFORM3D         = 10286765      # 0x009CF6AD
PARENTOPTIONS       = 368199626     # 0x15F247CA
SPAWN               = 1921765292    # 0x728BCFAC
LIFE                = 1320868484    # 0x4EBADA84
EMITTERSHAPE3D      = 1003792849    # 0x3BD4A9D1
VELOCITY3D          = 222458580     # 0x0D4272D4
FADEBYDEPTH         = 859243212     # 0x3337022CC  (actually 0x330702CC)
RIBBONBLADE         = 319363982     # 0x131B8E8E  (0x131B8E8E)
BILLBOARD3D         = 1136904414    # 0x43C3C8DE
SCALEANIM           = 480396424     # 0x1CA24488
UVSEQUENCE          = 1698970185    # 0x65443A49
ALPHACORRECTION     = 61219887      # 0x03A6242F
SHADERSETTINGS      = 1978267738    # 0x75E9F85A
RGBFIRE             = 459578090     # 0x1B649AEA
MESH                = 276670093     # 0x107DA68D
ROTATEANIM          = 1774142981    # 0x69BF4605
PLEMISSIVE          = 597394907     # 0x239B85DB
GUIDE               = 1123011591    # 0x42EFCC07
LIGHTNING           = 1558046267    # 0x5CDDE63B
PARENTEMISSIVE      = 14579343      # 0x00DE768F
PTCOLLISION         = 280719621     # 0x10BB7105
PLSNOW              = 1267346617    # 0x4B8A2CB9
PTBEHAVIOR          = 1179069619    # 0x46472CB3
MATERIAL            = 1659025771    # 0x62E2B96B
PLANE               = 37870541      # 0x0241DBCD
RGBWATER            = 1660327299    # 0x62F69583
TURBULENCE          = 937428146     # 0x37E004B2
FADEBYEMITTERANGLE  = 2116359897    # 0x7E2516D9
RIBBON              = 733291506     # 0x2BB523F2
NOISE               = 523015778     # 0x1F2C9662
UVCONTROL           = 2020068998    # 0x7867CE86
FADEBYANGLE         = 1226136492    # 0x494915AC  (wait: 0x494915AC vs original)
EMITTERBOUNDARY     = 873436648     # 0x340F95E8
PTLIFE              = 493311524     # 0x1D675624
STRAINRIBBON        = 1062052310    # 0x3F4DA1D6
SCREENSPACECOLLISION= 697457224     # 0x2985A48  (0x299254A8)
RAYCAST             = 275476317     # 0x106F6F5D
EXTERNREFERENCE     = 351869514     # 0x14F91A4A
FAKEPLANE           = 1257264016    # 0x4AF05390
DUMMY               = 201720946     # 0x0C060472
RANDOMFIX           = 674258598     # 0x28305EA6
TRANSFORM2D         = 428328940     # 0x1987C7EC
BILLBOARD2D         = 1524169119    # 0x5AD8F99F
BLINK               = 1354601878    # 0x50BD9596
LUMINANCEBLEED      = 71967929      # 0x044A24B9
EMITTERSHAPE2D      = 584030352     # 0x22CF9890
VELOCITY2D          = 341394325     # 0x14594395
REFRACTION          = 957228464     # 0x3920B0E  (0x390E25B0)
MASTERONLY          = 1616705008    # 0x605CF5F0
TUBELIGHT           = 252064274     # 0x0F063212
SHOVEL              = 1240420851    # 0x49EF51F3
LAYOUT              = 156539255     # 0x09549977
FAKEDOF             = 212167510     # 0x0CA56B56
REPEATAREA          = 842043995     # 0x3230925B
LINKPARTSVISIBLE    = 812022019     # 0x30667903
PTTRIGGER           = 2115227124    # 0x7E13CDF4
PATHCHAIN           = 1217635032    # 0x48A3A2D8
HOMING              = 1535857470    # 0x5B8B533E
EMITTERSHAPEMESH    = 1111321825    # 0x423D6CE1
SPAWNBYANGLE        = 1916268445    # 0x724EF79D  (0x724EF79D matches 0x724EF79D)
CHECKPUREATTRIBUTE  = 283684959     # 0x10E8B05F
TONEMAPFILTER       = 845585410     # 0x32669C02
COLORCORRECTFILTER  = 1293936879    # 0x4D1FE8EF
SPAWNBYOCCLUSION    = 1913890808    # 0x7213A7F8
FADEBYOCCLUSION     = 64111316      # 0x03D242D4
PARENTSNOW          = 215153612     # 0x0CD2FBCC
OTOMOSNOW           = 180261702     # 0x0ABE9346
PARENTMATERIAL      = 638869640     # 0x26146088

# ── Extern data type hashes ───────────────────────────────────────────────────
EXTERNTRANSFORM3D   = 500644368     # 0x1DD73A10
EXTERNMESH          = 1850314036    # 0x6E498D34
EXTERNPLEMISSIVE    = 725249589     # 0x2B3A6E35
EXTERNPTBEHAVIOR    = 1610366518    # 0x5FFC3E36
EXTERNRGBWATER      = 482524730     # 0x1CC2BE3A
EXTERNVELOCITY3D    = 351887441     # 0x14F96051
EXTERNEMITTERSHAPE3D= 1880343637    # 0x7013C455
EXTERNVELOCITY3D5   = 705591903     # 0x2A0E7A5F
EXTERNSPAWN         = 28559457      # 0x01B3C861
EXTERNRGBFIRE       = 2069124466    # 0x7B545572
EXTERNVELOCITY3D1   = 839790967     # 0x320E3177
EXTERNVELOCITY3D6   = 1879331968    # 0x70045480
EXTERNBILLBOARD3D   = 693979274     # 0x295D488A
EXTERNSCALEANIM     = 786529163     # 0x2EE17B8B
EXTERNVELOCITY3D0   = 1338793878    # 0x4FCC5F96
EXTERNUVSEQUENCE    = 2097096908    # 0x7CFF28CC
EXTERNVELOCITY3D7   = 805496014     # 0x3002E4CE
EXTERNVELOCITY3D2   = 283026906     # 0x10DEA5DA

# ── Root marker (not an attr hash; first int of a Root body) ─────────────────
ROOT_MARKER         = 1228515738    # 0x4939A99A

# ── Root sub-block type hashes (inside Root body) ────────────────────────────
UNITBOUNDARY        = 1413509420    # 0x54407120  (0x5440712C)
RENDERTARGET        = 2083659062    # 0x7C321D36
LAYOUTBANK          = 2050487542    # 0x7A37F4F6

# ── "Unused so far" / interface hashes (from EFX_Hashes.bt) ──────────────────
EFFECTATTRCOLORTBL                              = 1690896576
MHEFFECTDECALBEHAVIOR                           = 1128324015
MHEFFECTDECALBEHAVIOR_GETTOTALFIRELIFEFRAME     = 1250245974
MHEFFECTDECALBEHAVIOR_GETTOTALSMOKELIFEFRAME    = 409149100
MHEFFECTDECALBEHAVIOR_GETTOTALSPECULARLIFEFRAME = 173467491
MHEFFECTDECALBEHAVIOR_GETTOTALSHEETLIFEFRAME    = 1969325070
MHEFFECTDECALBEHAVIOR_GETTOTALGTOBLIFEFRAME     = 1296538020
CCOORDPARAMETER                                 = 1892103853
IEFFECTITEM                                     = 19434345
ITEM                                            = 1215086948
DYNAMICRAY                                      = 1708014292
FLOWMAPSETTINGS                                 = 1184613359
EFFECTEXECUTOR                                  = 1213896611
EXTERNFADEBYANGLE                               = 1415485201
EXTERNFADEBYDEPTH                               = 779931249
EXTERNSTRAINRIBBON                              = 167781675
EXTERNUVCONTROL                                 = 1243935109
EXTERNTURBULENCE                                = 777721399
EXTERNITEM                                      = 1226458230
BASICEXTERNITEM                                 = 1771113640
EFFECTEVENT                                     = 1923506186
EVENTBEHAVIORPROPERTY                           = 346395602
DECALBEHAVIOR                                   = 657374606
VARIANT                                         = 588732697
LIGHTBEHAVIOR                                   = 603167555
POINTLIGHTBEHAVIOR                              = 110612213
SPOTLIGHTBEHAVIOR                               = 804054309
UEFFECTRADIALBLURFILTER                         = 1183727815
FILTERBEHAVIOR                                  = 618247822
RADIALBLURFILTERBEHAVIOR                        = 1161774816
EFFECTDATA                                      = 1135895459
EMITTEREXECUTOR                                 = 2097355886
TYPEMIE3D                                       = 1771758423
GROUPITEM                                       = 2043222009
GPUPHYSICS                                      = 393634900
EMITTERSHAPE3DOVERRIDER                         = 1105989980
MEMOITEM                                        = 1484483739
IITEMPROPERTYINFO                               = 716000960
EFFECTDATABASE_ITEMPROPERTYINFO                 = 997811050
EFFECTDATABASE                                  = 1987779161
TIMELINERESOURCE                                = 610766284
TIMELINELISTRESOURCE                            = 1650401859
INODE                                           = 881621517
NODE                                            = 1376259135
ROOT                                            = 1099111713
GROUP                                           = 256197774
EMITTER                                         = 668609413
ACTION                                          = 1956806151
FIELD                                           = 963659027
EXTERN                                          = 242552826
NODE_GETTYPE                                    = 1929273712
VELOCITYBASE                                    = 261120345
TYPEBILLBOARDBASE                               = 1590369728
EFFECTGROUPDATA                                 = 1608814288
EFFECTGROUP                                     = 617098856
BOUNDARYBASE                                    = 1100150108
RENDERTARGET_TARGET                             = 1478767196
TEXTUREPATH                                     = 386986771
TYPELIGHTNING_BRANCH                            = 2120416030
TYPERIBBONBLADESECTION                          = 19293690
TUBELIGHTSECTION                                = 292704954
EFFECTSETTINGPRESET                             = 712996915
EFFECTTIMEREDEEMPRESET                          = 916096233
MATERIAL_MATERIALPARAM                          = 312479394
MATERIAL_MATERIALNODEDATA                       = 1851897063
SHAPEMESHHOLDER                                 = 738773001
CEFFECTPROVIDERCUSTOMDATA_ACTIONELEMENT         = 510816299
CEFFECTPROVIDERCUSTOMDATA_UNITELEMENT           = 1178760989
CEFFECTPROVIDERCUSTOMDATA                       = 1867843721
PLEMISSIVEMANAGER                               = 910471525
EXTERNGUIDE                                     = 766474541
EXTERNPARENTSNOW                                = 74649634
EXTERNOTOMOSNOW                                 = 1181241355
GUIDE_MOVETYPE_ALWAYSTHROUGH                    = 1168412664
GUIDE_MOVETYPE_SKIPNEAR                         = 889775412
GUIDE_MOVETYPE_OLDTYPE                          = 594406925

# ── Lookup tables ─────────────────────────────────────────────────────────────
import sys as _sys

def _build_tables():
    """Collect all module-level integer constants into NAME_TO_HASH and HASH_TO_NAME."""
    module = _sys.modules[__name__]
    n2h = {}
    h2n = {}
    for name, value in vars(module).items():
        if name.startswith('_'):
            continue
        if isinstance(value, int) and not isinstance(value, bool):
            n2h[name] = value
            # first-registered name wins for display
            if value not in h2n:
                h2n[value] = name
    return n2h, h2n

NAME_TO_HASH, HASH_TO_NAME = _build_tables()

# The set used for forward-scanning attribute block boundaries.
# Includes all known attr hashes PLUS play/extern/root sub-block hashes.
ALL_HASHES: frozenset = frozenset(NAME_TO_HASH.values())

# Convenience: just the attr-block hashes (excludes play/extern/root helpers)
ATTR_HASHES: frozenset = frozenset([
    TIML, TRANSFORM3D, PARENTOPTIONS, SPAWN, LIFE, EMITTERSHAPE3D, VELOCITY3D,
    FADEBYDEPTH, RIBBONBLADE, BILLBOARD3D, SCALEANIM, UVSEQUENCE, ALPHACORRECTION,
    SHADERSETTINGS, RGBFIRE, MESH, ROTATEANIM, PLEMISSIVE, GUIDE, LIGHTNING,
    PARENTEMISSIVE, PTCOLLISION, PLSNOW, PTBEHAVIOR, MATERIAL, PLANE, RGBWATER,
    TURBULENCE, FADEBYEMITTERANGLE, RIBBON, NOISE, UVCONTROL, FADEBYANGLE,
    EMITTERBOUNDARY, PTLIFE, STRAINRIBBON, SCREENSPACECOLLISION, RAYCAST,
    EXTERNREFERENCE, FAKEPLANE, DUMMY, RANDOMFIX, TRANSFORM2D, BILLBOARD2D,
    BLINK, LUMINANCEBLEED, EMITTERSHAPE2D, VELOCITY2D, REFRACTION, MASTERONLY,
    TUBELIGHT, SHOVEL, LAYOUT, FAKEDOF, REPEATAREA, LINKPARTSVISIBLE, PTTRIGGER,
    PATHCHAIN, HOMING, EMITTERSHAPEMESH, SPAWNBYANGLE, CHECKPUREATTRIBUTE,
    TONEMAPFILTER, COLORCORRECTFILTER, SPAWNBYOCCLUSION, FADEBYOCCLUSION,
    PARENTSNOW, OTOMOSNOW, PARENTMATERIAL,
    # "unused so far" hashes also seen in practice
    EFFECTATTRCOLORTBL, MHEFFECTDECALBEHAVIOR, FLOWMAPSETTINGS, EFFECTEXECUTOR,
    EFFECTEVENT, EVENTBEHAVIORPROPERTY, DECALBEHAVIOR, VARIANT, LIGHTBEHAVIOR,
    POINTLIGHTBEHAVIOR, SPOTLIGHTBEHAVIOR, UEFFECTRADIALBLURFILTER, FILTERBEHAVIOR,
    RADIALBLURFILTERBEHAVIOR, EFFECTDATA, EMITTEREXECUTOR, TYPEMIE3D, GROUPITEM,
    GPUPHYSICS, EMITTERSHAPE3DOVERRIDER, MEMOITEM, TIMELINERESOURCE,
    TIMELINELISTRESOURCE, INODE, NODE, GROUP, EMITTER, ACTION, FIELD, EXTERN,
    VELOCITYBASE, TYPEBILLBOARDBASE, EFFECTGROUPDATA, EFFECTGROUP, BOUNDARYBASE,
    RENDERTARGET_TARGET, TEXTUREPATH, TYPELIGHTNING_BRANCH, TYPERIBBONBLADESECTION,
    TUBELIGHTSECTION, EFFECTSETTINGPRESET, EFFECTTIMEREDEEMPRESET,
    MATERIAL_MATERIALPARAM, MATERIAL_MATERIALNODEDATA, SHAPEMESHHOLDER,
    CEFFECTPROVIDERCUSTOMDATA_ACTIONELEMENT, CEFFECTPROVIDERCUSTOMDATA_UNITELEMENT,
    CEFFECTPROVIDERCUSTOMDATA, PLEMISSIVEMANAGER, EXTERNGUIDE,
    GUIDE_MOVETYPE_ALWAYSTHROUGH, GUIDE_MOVETYPE_SKIPNEAR, GUIDE_MOVETYPE_OLDTYPE,
    IEFFECTITEM, ITEM, DYNAMICRAY, CCOORDPARAMETER,
])
