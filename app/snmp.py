"""Read interface status and traffic counters over SNMP v2c.

Standard library only: SNMP messages are small BER-encoded packets sent over
UDP, so this module encodes and decodes them by hand instead of adding a
package. It only reads (GetNext). It never writes to a device.

Only a saved device's validated IP address is contacted, on the configured
SNMP port (161 unless ZYBER_SNMP_PORT says otherwise, which is how the local
simulator in tools/snmp_simulator.py is reached).
"""

import os
import socket
import time

# BER tags used by SNMP.
INTEGER = 0x02
OCTET_STRING = 0x04
NULL = 0x05
OBJECT_ID = 0x06
SEQUENCE = 0x30
COUNTER32 = 0x41
GAUGE32 = 0x42
TIMETICKS = 0x43
COUNTER64 = 0x46
NO_SUCH_OBJECT = 0x80
NO_SUCH_INSTANCE = 0x81
END_OF_MIB_VIEW = 0x82
GET_REQUEST = 0xA0
GET_NEXT_REQUEST = 0xA1
GET_RESPONSE = 0xA2

SNMP_V2C = 1

# IF-MIB columns. Each row of a column is the column OID plus the interface index.
IF_DESCR = (1, 3, 6, 1, 2, 1, 2, 2, 1, 2)
IF_OPER_STATUS = (1, 3, 6, 1, 2, 1, 2, 2, 1, 8)
IF_IN_OCTETS = (1, 3, 6, 1, 2, 1, 2, 2, 1, 10)
IF_OUT_OCTETS = (1, 3, 6, 1, 2, 1, 2, 2, 1, 16)
IF_HC_IN_OCTETS = (1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 6)
IF_HC_OUT_OCTETS = (1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 10)

# ifOperStatus numbers from RFC 2863.
OPER_STATUS = {1: "up", 2: "down", 3: "testing", 4: "unknown", 5: "dormant", 6: "notPresent", 7: "lowerLayerDown"}

MAX_INTERFACES = 48
MAX_NAME_LENGTH = 100


class SnmpError(RuntimeError):
    """The device answered with something this reader cannot use."""


class SnmpTimeout(SnmpError):
    """The device did not answer in time."""


# ---------------------------------------------------------------- encoding

def _encode_length(length):
    if length < 0x80:
        return bytes([length])
    body = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def encode_tlv(tag, body):
    return bytes([tag]) + _encode_length(len(body)) + body


def encode_integer(value, tag=INTEGER):
    if tag == INTEGER:
        size = max(1, (value + (value < 0)).bit_length() // 8 + 1)
        return encode_tlv(tag, value.to_bytes(size, "big", signed=True))
    # Counters and gauges are unsigned. A leading zero byte keeps the top bit clear.
    size = max(1, value.bit_length() // 8 + 1)
    return encode_tlv(tag, value.to_bytes(size, "big"))


def encode_oid(oid):
    oid = tuple(oid)
    if len(oid) < 2:
        raise SnmpError("An OID needs at least two parts.")
    body = bytearray([oid[0] * 40 + oid[1]])
    for part in oid[2:]:
        chunk = [part & 0x7F]
        part >>= 7
        while part:
            chunk.append(0x80 | (part & 0x7F))
            part >>= 7
        body.extend(reversed(chunk))
    return encode_tlv(OBJECT_ID, bytes(body))


def encode_value(tag, value):
    if tag == NULL or tag in (NO_SUCH_OBJECT, NO_SUCH_INSTANCE, END_OF_MIB_VIEW):
        return encode_tlv(tag, b"")
    if tag == OCTET_STRING:
        return encode_tlv(tag, value if isinstance(value, bytes) else str(value).encode("utf-8"))
    if tag == OBJECT_ID:
        return encode_oid(value)
    return encode_integer(int(value), tag)


def encode_message(community, pdu_tag, request_id, varbinds, error_status=0, error_index=0):
    """Build one SNMP v2c message. ``varbinds`` is a list of (oid, tag, value)."""
    binds = b"".join(
        encode_tlv(SEQUENCE, encode_oid(oid) + encode_value(tag, value)) for oid, tag, value in varbinds
    )
    pdu = encode_tlv(
        pdu_tag,
        encode_integer(request_id) + encode_integer(error_status) + encode_integer(error_index)
        + encode_tlv(SEQUENCE, binds),
    )
    community_bytes = community.encode("utf-8") if isinstance(community, str) else community
    return encode_tlv(SEQUENCE, encode_integer(SNMP_V2C) + encode_tlv(OCTET_STRING, community_bytes) + pdu)


# ---------------------------------------------------------------- decoding

def _read_tlv(data, offset):
    if offset + 2 > len(data):
        raise SnmpError("The SNMP reply was cut short.")
    tag = data[offset]
    length = data[offset + 1]
    offset += 2
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or count > 4 or offset + count > len(data):
            raise SnmpError("The SNMP reply has a bad length.")
        length = int.from_bytes(data[offset:offset + count], "big")
        offset += count
    end = offset + length
    if end > len(data):
        raise SnmpError("The SNMP reply was cut short.")
    return tag, data[offset:end], end


def _decode_oid(body):
    if not body:
        raise SnmpError("The SNMP reply has an empty OID.")
    first = body[0]
    oid = [min(first // 40, 2), first - 40 * min(first // 40, 2)]
    part = 0
    for byte in body[1:]:
        part = (part << 7) | (byte & 0x7F)
        if not byte & 0x80:
            oid.append(part)
            part = 0
    return tuple(oid)


def _decode_value(tag, body):
    if tag == INTEGER:
        return int.from_bytes(body, "big", signed=True) if body else 0
    if tag in (COUNTER32, GAUGE32, TIMETICKS, COUNTER64):
        return int.from_bytes(body, "big") if body else 0
    if tag == OCTET_STRING:
        return bytes(body)
    if tag == OBJECT_ID:
        return _decode_oid(body)
    return None


def decode_message(data):
    """Return (community, pdu_tag, request_id, error_status, varbinds).

    ``varbinds`` is a list of (oid, tag, value).
    """
    tag, body, _ = _read_tlv(data, 0)
    if tag != SEQUENCE:
        raise SnmpError("The SNMP reply is not a message.")
    tag, version, offset = _read_tlv(body, 0)
    if tag != INTEGER or _decode_value(INTEGER, version) != SNMP_V2C:
        raise SnmpError("The SNMP reply is not version 2c.")
    tag, community, offset = _read_tlv(body, offset)
    if tag != OCTET_STRING:
        raise SnmpError("The SNMP reply has no community.")
    pdu_tag, pdu, _ = _read_tlv(body, offset)
    _, request_id, offset = _read_tlv(pdu, 0)
    _, error_status, offset = _read_tlv(pdu, offset)
    _, _error_index, offset = _read_tlv(pdu, offset)
    tag, binds, _ = _read_tlv(pdu, offset)
    if tag != SEQUENCE:
        raise SnmpError("The SNMP reply has no variable list.")
    varbinds = []
    offset = 0
    while offset < len(binds):
        _, bind, offset = _read_tlv(binds, offset)
        oid_tag, oid_body, inner = _read_tlv(bind, 0)
        if oid_tag != OBJECT_ID:
            raise SnmpError("The SNMP reply has a bad variable.")
        value_tag, value_body, _ = _read_tlv(bind, inner)
        varbinds.append((_decode_oid(oid_body), value_tag, _decode_value(value_tag, value_body)))
    return (
        bytes(community),
        pdu_tag,
        _decode_value(INTEGER, request_id),
        _decode_value(INTEGER, error_status),
        varbinds,
    )


# ---------------------------------------------------------------- client

class _Session:
    """One UDP socket to one device, with request ids and a deadline."""

    def __init__(self, ip, port, community, timeout_seconds, deadline):
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        self.sock = socket.socket(family, socket.SOCK_DGRAM)
        self.target = (ip, port)
        self.community = community.encode("utf-8")
        self.timeout = timeout_seconds
        self.deadline = deadline
        self.request_id = int.from_bytes(os.urandom(3), "big")

    def close(self):
        self.sock.close()

    def get_next(self, oid):
        self.request_id = (self.request_id + 1) & 0x7FFFFFFF
        packet = encode_message(self.community, GET_NEXT_REQUEST, self.request_id, [(oid, NULL, None)])
        for _attempt in range(2):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise SnmpTimeout("The SNMP poll took too long.")
            self.sock.settimeout(min(self.timeout, remaining))
            self.sock.sendto(packet, self.target)
            try:
                while True:
                    data, sender = self.sock.recvfrom(65535)
                    if sender[0] != self.target[0]:
                        continue  # Not our device: ignore it.
                    community, pdu_tag, request_id, error_status, varbinds = decode_message(data)
                    if pdu_tag != GET_RESPONSE or request_id != self.request_id or community != self.community:
                        continue
                    if error_status:
                        raise SnmpError(f"The device returned SNMP error {error_status}.")
                    if len(varbinds) != 1:
                        raise SnmpError("The SNMP reply has the wrong number of variables.")
                    return varbinds[0]
            except (socket.timeout, ConnectionResetError, ConnectionRefusedError):
                # Windows reports a closed SNMP port as a reset. Either way: no answer.
                continue
        raise SnmpTimeout("No SNMP reply.")

    def walk(self, column, limit):
        """Read one IF-MIB column. Returns {interface index: (tag, value)}."""
        rows = {}
        oid = column
        while len(rows) < limit:
            next_oid, tag, value = self.get_next(oid)
            if tag in (NO_SUCH_OBJECT, NO_SUCH_INSTANCE, END_OF_MIB_VIEW):
                break
            if next_oid[: len(column)] != column or len(next_oid) != len(column) + 1:
                break
            if next_oid <= oid:
                raise SnmpError("The device returned OIDs out of order.")
            rows[next_oid[-1]] = (tag, value)
            oid = next_oid
        return rows


def poll_interfaces(ip, *, community="public", port=161, timeout_seconds=2, total_seconds=15):
    """Read every interface's name, operational status, and octet counters.

    Returns a list of dicts sorted by interface index. 64-bit counters are
    used when the device has them, otherwise the 32-bit ones.
    Raises SnmpTimeout when the device does not answer, SnmpError otherwise.
    """
    session = _Session(ip, int(port), community, timeout_seconds, time.monotonic() + total_seconds)
    try:
        names = session.walk(IF_DESCR, MAX_INTERFACES)
        if not names:
            raise SnmpError("The device has no interface table.")
        status = session.walk(IF_OPER_STATUS, MAX_INTERFACES)
        counter_bits = 64
        in_octets = session.walk(IF_HC_IN_OCTETS, MAX_INTERFACES)
        out_octets = session.walk(IF_HC_OUT_OCTETS, MAX_INTERFACES)
        if not in_octets:
            counter_bits = 32
            in_octets = session.walk(IF_IN_OCTETS, MAX_INTERFACES)
            out_octets = session.walk(IF_OUT_OCTETS, MAX_INTERFACES)
    finally:
        session.close()

    interfaces = []
    for index in sorted(names):
        name_tag, name = names[index]
        text = name.decode("utf-8", "replace") if isinstance(name, bytes) else str(name)
        text = "".join(ch for ch in text if ch.isprintable()).strip()[:MAX_NAME_LENGTH] or f"Interface {index}"
        oper = status.get(index, (None, None))[1]
        interfaces.append(
            {
                "if_index": index,
                "name": text,
                "oper_status": OPER_STATUS.get(oper, "unknown"),
                "in_octets": _counter(in_octets.get(index)),
                "out_octets": _counter(out_octets.get(index)),
                "counter_bits": counter_bits,
            }
        )
    return interfaces


def _counter(entry):
    if not entry:
        return None
    tag, value = entry
    if tag not in (COUNTER32, COUNTER64, GAUGE32) or not isinstance(value, int) or value < 0:
        return None
    return value


def traffic_rate_bps(previous, current, seconds, counter_bits):
    """Bits per second between two saved counter readings.

    A 32-bit counter that went backwards is treated as one wrap. A 64-bit
    counter that went backwards means the device restarted, so there is no rate.
    """
    if previous is None or current is None or not seconds or seconds <= 0:
        return None
    delta = current - previous
    if delta < 0:
        if counter_bits == 32 and previous > 2 ** 31:
            delta += 2 ** 32
        else:
            return None
    return round(delta * 8 / seconds)
