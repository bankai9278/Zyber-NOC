"""A small local SNMP agent for trying Poll SNMP without a switch."""

import argparse
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import snmp  # noqa: E402

# name, oper status (1 up, 2 down), bits per second in, bits per second out
INTERFACES = (
    ("GigabitEthernet0/1", 1, 40_000_000, 12_000_000),
    ("GigabitEthernet0/2", 1, 3_000_000, 1_000_000),
    ("GigabitEthernet0/3", 2, 0, 0),
    ("Vlan10", 1, 800_000, 600_000),
)


class SimulatedAgent:
    """Answer SNMP requests from an in-memory interface table."""

    def __init__(self, community="public", counters64=True, clock=time.monotonic):
        self.community = community.encode("utf-8")
        self.counters64 = counters64
        self.clock = clock
        self.started = clock()

    def table(self):
        """Return a sorted list of (oid, tag, value) for the whole MIB view."""
        elapsed = self.clock() - self.started
        rows = []
        for index, (name, oper, rate_in, rate_out) in enumerate(INTERFACES, start=1):
            octets_in = 5_000_000 * index + int(rate_in / 8 * elapsed)
            octets_out = 2_000_000 * index + int(rate_out / 8 * elapsed)
            rows.append((snmp.IF_DESCR + (index,), snmp.OCTET_STRING, name.encode()))
            rows.append((snmp.IF_OPER_STATUS + (index,), snmp.INTEGER, oper))
            rows.append((snmp.IF_IN_OCTETS + (index,), snmp.COUNTER32, octets_in % 2 ** 32))
            rows.append((snmp.IF_OUT_OCTETS + (index,), snmp.COUNTER32, octets_out % 2 ** 32))
            if self.counters64:
                rows.append((snmp.IF_HC_IN_OCTETS + (index,), snmp.COUNTER64, octets_in))
                rows.append((snmp.IF_HC_OUT_OCTETS + (index,), snmp.COUNTER64, octets_out))
        return sorted(rows)

    def answer(self, data):
        """Return the reply packet for one request, or None to stay silent."""
        try:
            community, pdu_tag, request_id, _status, varbinds = snmp.decode_message(data)
        except snmp.SnmpError:
            return None
        if community != self.community or pdu_tag not in (snmp.GET_REQUEST, snmp.GET_NEXT_REQUEST):
            return None
        table = self.table()
        replies = []
        for oid, _tag, _value in varbinds:
            if pdu_tag == snmp.GET_REQUEST:
                match = next((row for row in table if row[0] == oid), None)
                replies.append(match or (oid, snmp.NO_SUCH_OBJECT, None))
            else:
                match = next((row for row in table if row[0] > oid), None)
                replies.append(match or (oid, snmp.END_OF_MIB_VIEW, None))
        return snmp.encode_message(self.community, snmp.GET_RESPONSE, request_id, replies)


def serve(agent, host="127.0.0.1", port=1161, ready=None, stop=None):
    """Answer requests until ``stop`` is set. Puts the bound port in ``ready``."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    sock.settimeout(0.2)
    if ready is not None:
        ready.append(sock.getsockname()[1])
    try:
        while stop is None or not stop.is_set():
            try:
                data, sender = sock.recvfrom(65535)
            except socket.timeout:
                continue
            reply = agent.answer(data)
            if reply is not None:
                sock.sendto(reply, sender)
    finally:
        sock.close()


def start_in_background(agent):
    """Start an agent on a free port. Returns (port, stop_event). Used by tests."""
    ready, stop = [], threading.Event()
    thread = threading.Thread(target=serve, args=(agent, "127.0.0.1", 0, ready, stop), daemon=True)
    thread.start()
    while not ready:
        time.sleep(0.01)
    return ready[0], stop


def main():
    parser = argparse.ArgumentParser(description="Local SNMP v2c simulator for Zyber NOC.")
    parser.add_argument("--port", type=int, default=1161)
    parser.add_argument("--community", default="public")
    parser.add_argument("--counters32", action="store_true", help="only offer 32-bit counters")
    args = parser.parse_args()
    print(f"SNMP simulator on 127.0.0.1:{args.port}, community '{args.community}'. Ctrl+C stops it.")
    try:
        serve(SimulatedAgent(args.community, counters64=not args.counters32), port=args.port)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
