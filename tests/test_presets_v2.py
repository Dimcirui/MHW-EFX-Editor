"""预设格式 v2 的字段规整规则。"""
import base64
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from efx_format import assembly as A
from efx_format import hashes as H
from efx_format.assembly.defaults import default_attribute


def _spawn_block(**fields):
    return {'type': 'SPAWN', 'fields': fields}


class NormalizeFieldsTest(unittest.TestCase):

    def test_missing_fields_take_defaults(self):
        log = []
        h, data = A.build_attribute(_spawn_block(spawnNum=7), filled_log=log)
        values = A.decode_attribute(h, data)
        default = default_attribute(H.SPAWN)
        self.assertEqual(values['spawnNum'], 7)
        self.assertEqual(values['maxParticles'], default['maxParticles'])
        self.assertIn('maxParticles', log[0][2])
        self.assertNotIn('spawnNum', log[0][2])

    def test_unknown_field_raises(self):
        with self.assertRaises(A.PresetError) as cm:
            A.build_attribute(_spawn_block(noSuchField=1))
        self.assertIn('noSuchField', str(cm.exception))

    def test_old_name_maps_through_aliases(self):
        aliases = {('SPAWN', 'burstCount'): 'spawnNum'}
        h, data = A.build_attribute(_spawn_block(burstCount=5), aliases=aliases)
        self.assertEqual(A.decode_attribute(h, data)['spawnNum'], 5)

    def test_alias_onto_present_field_is_unknown(self):
        aliases = {('SPAWN', 'burstCount'): 'spawnNum'}
        with self.assertRaises(A.PresetError):
            A.build_attribute(_spawn_block(burstCount=5, spawnNum=6), aliases=aliases)

    def test_extern_set_uses_main_type_aliases(self):
        aliases = {('SPAWN', 'burstCount'): 'spawnNum'}
        ext = {'attrType': 1, 'null0': 0, 'null1': 0,
               'items': [{'type': 'EXTERNSPAWN', 'unkn': 0, 'sets': [{'burstCount': 3}]}]}
        ea = A.build_extern(ext, aliases=aliases)
        sets = A.decode_extern_sets(ea.items[0].type_hash, ea.items[0].attr_count,
                                    ea.items[0].data_bytes)
        self.assertEqual(sets[0]['spawnNum'], 3)

    def test_stale_derived_key_is_ignored(self):
        fields = A.to_json(default_attribute(H.BILLBOARD3D))
        fields['path'] = 'vfx\\uvs\\cm\\cm_flow_000\u0000'
        fields['path_len'] = 1
        h, data = A.build_attribute({'type': 'BILLBOARD3D', 'fields': fields})
        values = A.decode_attribute(h, data)
        self.assertEqual(values['path'], b'vfx\\uvs\\cm\\cm_flow_000\x00')
        self.assertEqual(values['path_len'], len(values['path']))

    def test_written_preset_has_no_derived_keys(self):
        data = A.encode_attribute(H.PTBEHAVIOR, default_attribute(H.PTBEHAVIOR))
        fields = A.attribute_preset(H.PTBEHAVIOR, data)['attribute']['fields']
        self.assertNotIn('para_count', fields)
        self.assertNotIn('behav_type_len', fields)
        self.assertTrue(all('path_len' not in p for p in fields['params']))


class UpgradeTest(unittest.TestCase):

    def test_legacy_body_preset_upgrades(self):
        spawn = A.encode_attribute(H.SPAWN, default_attribute(H.SPAWN))
        v1 = {
            'efx_preset_kind': 'body', 'body_kind': 'standard', 'display_name': 'x',
            'props': {'body_type': str(0x1F68613A), 'unkn0': '0', 'attr_count': '1',
                      'null': '0', 'timl_length': '0'},
            'timl_bytes': '', 'raw': '',
            'blocks': [{'type_hash': str(H.SPAWN),
                        'data_bytes': base64.b64encode(spawn).decode('ascii')}],
            'source_counts': {'extern': 0, 'body': 3, 'play': 1},
        }
        v2 = A.upgrade_preset(v1)
        self.assertEqual(v2['efx_preset_kind'], 'entry')
        self.assertEqual(v2['format_version'], A.FORMAT_VERSION)
        self.assertEqual(v2['source_counts'], {'extern': 0, 'entry': 3, 'action': 1})
        body = A.build_preset(v2)
        self.assertEqual(body.attr_blocks[0].data_bytes, spawn)
        self.assertEqual(struct.unpack_from('<I', body.serialize(), 0)[0], 0x1F68613A)

    def test_unknown_version_raises(self):
        with self.assertRaises(A.PresetError):
            A.upgrade_preset({'efx_preset_kind': 'attribute', 'format_version': 99})


if __name__ == '__main__':
    unittest.main()
