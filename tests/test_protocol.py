import unittest

import mido

import mpkill8


class ProtocolTests(unittest.TestCase):
    def make_payload(self):
        payload = bytearray(0xF4)
        payload[mpkill8.K8_OFFSET + 0] = 0
        payload[mpkill8.K8_OFFSET + 1] = 77
        payload[mpkill8.K8_OFFSET + 2] = 0
        payload[mpkill8.K8_OFFSET + 3] = 127
        payload[
            mpkill8.K8_OFFSET + 4 : mpkill8.K8_OFFSET + 20
        ] = b"K8" + b"\x00" * 14
        return bytes(payload)

    def test_decode_k8(self):
        k8 = mpkill8.decode_knob(self.make_payload())
        self.assertEqual(k8.mode, 0)
        self.assertEqual(k8.cc, 77)
        self.assertEqual(k8.minimum, 0)
        self.assertEqual(k8.maximum, 127)
        self.assertEqual(k8.name, "K8")

    def test_patch_changes_only_mode_byte(self):
        original = self.make_payload()
        patched = mpkill8.patch_k8_mode(original, 2)

        changed = [
            i for i, (a, b) in enumerate(zip(original, patched)) if a != b
        ]
        self.assertEqual(changed, [mpkill8.K8_OFFSET])
        self.assertEqual(patched[mpkill8.K8_OFFSET], 2)

    def test_query_framing(self):
        msg = mpkill8.make_query(3)
        self.assertEqual(
            list(msg.data),
            [0x47, 0x7F, 0x49, 0x66, 0x00, 0x01, 0x03],
        )

    def test_write_framing(self):
        payload = bytes([1, 2, 3])
        msg = mpkill8.make_write(0, payload)
        # wire size = payload + program-id = 4
        self.assertEqual(
            list(msg.data),
            [0x47, 0x7F, 0x49, 0x64, 0x00, 0x04, 0x00, 1, 2, 3],
        )

    def test_parse_reply(self):
        payload = self.make_payload()
        wire_size = len(payload) + 1
        msg = mido.Message(
            "sysex",
            data=[
                0x47,
                0x00,
                0x49,
                0x67,
                (wire_size >> 7) & 0x7F,
                wire_size & 0x7F,
                1,
                *payload,
            ],
        )
        parsed = mpkill8.parse_program_reply(msg, 1)
        self.assertEqual(parsed, payload)


if __name__ == "__main__":
    unittest.main()
