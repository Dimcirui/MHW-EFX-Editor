# -*- coding: utf-8 -*-
"""LayoutBank_Block 结构化编辑与 LAYOUT 前缀列开关。"""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from efx_format.assembly import layoutbank as lb
from efx_format.schema.custom_codecs import (unpack_layoutbank_block, pack_layoutbank_block,
                                             unpack_layout, pack_layout)


def _block():
    """两行：列 0、1、6。"""
    return {'count': 2, 'columns': [
        {'blockType': 0, 'values': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]},
        {'blockType': 1, 'values': [lb.bits_from_half(v) for v in (0.5, 1.0, -2.0, 0.0,
                                                                   1.5, 0.0, 0.0, 3.0)]},
        {'blockType': 6, 'values': [7, 300, 4, 93, 100, 7]},
    ]}


def _roundtrip(block):
    data = pack_layoutbank_block(block)
    back, end = unpack_layoutbank_block(data, 0)
    assert end == len(data)
    return back


class TestHalf(unittest.TestCase):

    def test_half_roundtrip(self):
        for v in (0.0, 1.0, -2.0, 0.1, 100.0, 65504.0):
            self.assertEqual(lb.half_from_bits(lb.bits_from_half(v)),
                             struct.unpack('<e', struct.pack('<e', v))[0])

    def test_half_clamps_out_of_range(self):
        self.assertEqual(lb.half_from_bits(lb.bits_from_half(1e9)), 65504.0)
        self.assertEqual(lb.half_from_bits(lb.bits_from_half(-1e9)), -65504.0)


class TestRows(unittest.TestCase):

    def test_get_row_converts_half(self):
        self.assertEqual(lb.get_row(_block(), 1, 0), [0.5, 1.0, -2.0, 0.0])
        self.assertEqual(lb.get_row(_block(), 6, 1), [93, 100, 7])

    def test_add_row_copies_source_and_packs(self):
        b = lb.add_row(_block(), copy_from=0)
        self.assertEqual(b['count'], 3)
        self.assertEqual(lb.get_row(b, 0, 2), [1.0, 2.0, 3.0])
        self.assertEqual(lb.get_row(b, 6, 2), [7, 300, 4])
        self.assertEqual(_roundtrip(b), b)

    def test_add_row_inserts_zero_row(self):
        b = lb.add_row(_block(), index=1)
        self.assertEqual(lb.get_row(b, 0, 1), [0.0, 0.0, 0.0])
        self.assertEqual(lb.get_row(b, 0, 2), [4.0, 5.0, 6.0])

    def test_remove_row(self):
        b = lb.remove_row(_block(), 0)
        self.assertEqual(b['count'], 1)
        self.assertEqual(lb.get_row(b, 6, 0), [93, 100, 7])
        self.assertEqual(_roundtrip(b), b)

    def test_cannot_remove_last_row(self):
        b = lb.remove_row(_block(), 0)
        with self.assertRaises(lb.LayoutBankError):
            lb.remove_row(b, 0)

    def test_set_row_keeps_unchanged_bits(self):
        b = _block()
        b['columns'][1]['values'][3] = -32768            # -0.0 的位模式
        lb.set_row(b, 1, 0, [0.5, 1.0, -2.0, 0.0])      # 0.0 == -0.0，保留原位模式
        self.assertEqual(b['columns'][1]['values'][3], -32768)
        lb.set_row(b, 1, 0, [0.25, 1.0, -2.0, 0.0])
        self.assertEqual(lb.get_row(b, 1, 0)[0], 0.25)


class TestColumns(unittest.TestCase):

    def test_addable_respects_parents(self):
        b = _block()
        self.assertEqual(lb.addable_columns(b), [2, 4, 7])
        lb.add_column(b, 2)
        self.assertIn(3, lb.addable_columns(b))

    def test_child_needs_parent(self):
        with self.assertRaises(lb.LayoutBankError):
            lb.add_column(_block(), 3)

    def test_add_column_sorted_and_packs(self):
        b = lb.add_column(_block(), 4)
        self.assertEqual(lb.column_types(b), [0, 1, 4, 6])
        self.assertEqual(lb.get_row(b, 4, 1), [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(_roundtrip(b), b)

    def test_add_column_7_with_sub_count(self):
        b = lb.add_column(_block(), 7, sub_count=2)
        self.assertEqual(len(lb.get_row(b, 7, 0)), 8)
        self.assertEqual(_roundtrip(b), b)

    def test_remove_parent_drops_child(self):
        b = lb.add_column(lb.add_column(_block(), 2), 3)
        lb.remove_column(b, 2)
        self.assertEqual(lb.column_types(b), [0, 1, 6])


class TestLayoutFlags(unittest.TestCase):

    def test_sync_flags_follow_columns(self):
        prefix = {'typeFlag': 1, 'unknFixed1_0_0': 0, 'unknFlag1_0_3': 1,
                  'useColumn0': 0, 'useColumn1': 0, 'useColumn2': 1, 'useColumn4': 1,
                  'useColumn6': 0, 'useColumn7': 1}
        out = lb.sync_layout_flags(prefix, lb.add_column(_block(), 4))
        self.assertEqual((out['useColumn0'], out['useColumn1'], out['useColumn2'],
                          out['useColumn4'], out['useColumn6'], out['useColumn7']),
                         (1, 1, 0, 1, 1, 0))
        self.assertEqual(out['unknFlag1_0_3'], 1)                 # 非列开关不动

    def test_sync_only_touched_columns(self):
        prefix = {'useColumn0': 1, 'useColumn1': 1, 'useColumn2': 1, 'useColumn4': 0,
                  'useColumn6': 1, 'useColumn7': 0}
        b = lb.add_column(_block(), 4)
        out = lb.sync_layout_flags(prefix, b, columns=[4])
        self.assertEqual(out['useColumn4'], 1)
        self.assertEqual(out['useColumn2'], 1)                    # 未改动的列保持原值

    def test_layout_prefix_bytes_roundtrip(self):
        block = pack_layoutbank_block(_block())
        data = (struct.pack('<ii', 3, 16) + bytes((0, 1, 1, 1, 0, 0, 1, 0))
                + struct.pack('<ii', 0, -1) + block)
        values, end = unpack_layout(data, 0)
        self.assertEqual(end, len(data))
        self.assertEqual((values['useColumn0'], values['useColumn1'], values['unknFlag1_0_3'],
                          values['useColumn6']), (1, 1, 1, 1))
        self.assertEqual(pack_layout(values), data)


class TestPresetSplit(unittest.TestCase):

    def test_old_layout_preset_fields_are_split(self):
        from efx_format.assembly.preset import normalize_fields
        from efx_format.hashes import LAYOUT
        fields = {'typeFlag': 1, 'unknFixed0_1': 16, 'unknEnum1_0': 16843008,
                  'unknEnum1_1': 65793, 'unknFixed1_2': 0, 'unknFixed1_3': -1,
                  'layoutBank': _block()}
        out, _filled = normalize_fields('attributes', LAYOUT, fields)
        self.assertEqual((out['unknFixed1_0_0'], out['useColumn0'], out['useColumn1'],
                          out['unknFlag1_0_3']), (0, 1, 1, 1))
        self.assertEqual((out['useColumn2'], out['useColumn4'], out['useColumn6'],
                          out['useColumn7']), (1, 1, 1, 0))
        self.assertNotIn('unknEnum1_0', out)


if __name__ == '__main__':
    unittest.main()
