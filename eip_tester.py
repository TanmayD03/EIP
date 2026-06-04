import argparse
import time
import socket
import struct
import threading
import pandas as pd

from pymodbus.client import ModbusTcpClient
from ethernetip import EtherNetIPExpConnection, ENIP_UDP_PORT
from ethernetip.ethernetip import ForwardOpenReq, UnconnectedDataItem, CommandSpecificData, SendRRPacket, EncapsulationPacket, ForwardOpenResp, SocketAddressInfo, UnconnectedDataItemHdr, CI_SRV_FORWARD_OPEN, random, select

PROFILES = {
    0: {"name": "Tera Profile", "o_t_inst": 107, "o_t_size": 4, "t_o_inst": 117, "t_o_size": 40, "cfg_inst": 120, "cfg_size": 1},
    1: {"name": "Tera Basic Overload", "o_t_inst": 2, "o_t_size": 1, "t_o_inst": 50, "t_o_size": 1, "cfg_inst": 120, "cfg_size": 1},
    2: {"name": "Tera Extended Overload", "o_t_inst": 2, "o_t_size": 1, "t_o_inst": 51, "t_o_size": 1, "cfg_inst": 120, "cfg_size": 1},
    3: {"name": "Tera Basic Motor Starter", "o_t_inst": 3, "o_t_size": 1, "t_o_inst": 52, "t_o_size": 1, "cfg_inst": 120, "cfg_size": 1},
    4: {"name": "Tera Extended Contactor", "o_t_inst": 4, "o_t_size": 1, "t_o_inst": 53, "t_o_size": 1, "cfg_inst": 120, "cfg_size": 1},
    5: {"name": "Tera Extended Motor Starter 1", "o_t_inst": 4, "o_t_size": 1, "t_o_inst": 54, "t_o_size": 1, "cfg_inst": 120, "cfg_size": 1},
    6: {"name": "Tera Extended Motor Starter 2", "o_t_inst": 5, "o_t_size": 1, "t_o_inst": 54, "t_o_size": 1, "cfg_inst": 120, "cfg_size": 1},
    7: {"name": "Tera Control and Monitoring", "o_t_inst": 100, "o_t_size": 6, "t_o_inst": 110, "t_o_size": 8, "cfg_inst": 120, "cfg_size": 1},
    8: {"name": "Tera PKW", "o_t_inst": 101, "o_t_size": 8, "t_o_inst": 111, "t_o_size": 8, "cfg_inst": 120, "cfg_size": 1},
    9: {"name": "Tera PKW and Extended Motor Starter", "o_t_inst": 102, "o_t_size": 10, "t_o_inst": 112, "t_o_size": 10, "cfg_inst": 120, "cfg_size": 1},
    10: {"name": "Tera PKW and Management", "o_t_inst": 103, "o_t_size": 14, "t_o_inst": 113, "t_o_size": 16, "cfg_inst": 120, "cfg_size": 1},
    11: {"name": "Tera E_TeSys Tera Fast Access", "o_t_inst": 105, "o_t_size": 6, "t_o_inst": 115, "t_o_size": 12, "cfg_inst": 120, "cfg_size": 1},
    12: {"name": "Tera EIOS_TeSys Tera", "o_t_inst": 106, "o_t_size": 10, "t_o_inst": 116, "t_o_size": 128, "cfg_inst": 120, "cfg_size": 1}
}

class CustomEtherNetIPExpConnection(EtherNetIPExpConnection):
    def sendFwdOpenReq(self, inputinst, outputinst, configinst, multiplier=1,
                       torpi=1000, otrpi=1000, multicast=False, inputsz=None,
                       outputsz=None, fwdo=None, configData=None,
                       keyring_vendor=0, keyring_devicetype=0, keyring_productcode=0,
                       keyring_major=0, keyring_minor=0, keyring_compat=False,
                       path_class=0x04, fixed_connection_size=True,
                       priority=ForwardOpenReq.FORWARD_OPEN_CONN_PRIO_SCHEDULED,
                       direction=ForwardOpenReq.FORWARD_OPEN_TRANSPORT_DIRECTION_CLIENT,
                       trigger=ForwardOpenReq.FORWARD_OPEN_TRANSPORT_TRIGGER_CYCLIC,
                       transport_class=ForwardOpenReq.FORWARD_OPEN_TRANSPORT_CLASS_1):
        rand = random.randint(1, 0xffff) + 0xE4190000
        torpi *= 1000
        otrpi *= 1000

        # Override to remove Run/Idle header size addition
        # Standard library adds 6 for O->T (4 bytes run/idle + 2 seq)
        # We only add 2 (seq) to bypass run/idle check
        outputsz += 2
        inputsz += 2   # seq num

        if multicast is False:
            mcast = 2  # p2p
        else:
            mcast = 1
        if fixed_connection_size is True:
            fixed = 0
        else:
            fixed = 1  # variable connection size

        type_trigger = (transport_class | direction << ForwardOpenReq.FORWARD_OPEN_TRANSPORT_DIRECTION_BIT
                        | trigger << ForwardOpenReq.FORWARD_OPEN_TRANSPORT_TRIGGER_BIT)

        keyring_maj = keyring_major & 0x7F
        if keyring_compat:
            keyring_maj += 128  # set compatibility flag
        path = (struct.pack(">H", 0x3404)
                + struct.pack("H", keyring_vendor)
                + struct.pack("HH", keyring_devicetype, keyring_productcode)
                + struct.pack(">BB", keyring_maj, keyring_minor))
        if path_class is not None:
            path += struct.pack(">BB", 0x20, path_class)
        if configinst is not None:
            path += struct.pack("B", 0x24) + struct.pack("B", configinst)
        if outputinst is not None:
            path += struct.pack("B", 0x2c) + struct.pack("B", outputinst)
        if inputinst is not None:
            path += struct.pack("B", 0x2c) + struct.pack("B", inputinst)
        plen = int(len(path) / 2)
        if configData is not None:
            if len(configData) > 512:
                return 1
            path += struct.pack("BB", 0x80, int(len(configData) / 2))
            path += configData
            plen = int(len(path) / 2)
        if fwdo is None:
            self.conn_serial_num += 1
            fwdo = ForwardOpenReq(otconnid=rand, toconnid=rand - 1,
                                  conn_serial=self.conn_serial_num,
                                  multiplier=multiplier,
                                  mkpath=self.mkReqPath(clas=0x06, inst=0x01, attr=None),
                                  torpi=torpi,
                                  otrpi=otrpi,
                                  toparams=(int(inputsz)
                                            | (priority << ForwardOpenReq.FORWARD_OPEN_CONN_PARAM_BIT_PRIORITY)
                                            | (fixed << ForwardOpenReq.FORWARD_OPEN_CONN_PARAM_BIT_FIXED_VAR)
                                            | (mcast << ForwardOpenReq.FORWARD_OPEN_CONN_PARAM_BIT_CONN_TYPE)),
                                  otparams=(int(outputsz)
                                            | (priority << ForwardOpenReq.FORWARD_OPEN_CONN_PARAM_BIT_PRIORITY)
                                            | (fixed << ForwardOpenReq.FORWARD_OPEN_CONN_PARAM_BIT_FIXED_VAR)
                                            | (0x2 << ForwardOpenReq.FORWARD_OPEN_CONN_PARAM_BIT_CONN_TYPE)),
                                  type_trigger=type_trigger,
                                  plen=plen,
                                  data=path)
        dsz = len(fwdo) + 1
        cpf2 = UnconnectedDataItem(type_id=CommandSpecificData.TYPE_ID_UNCONNECTED_MESSAGE,
                                   length=dsz, data=fwdo,
                                   service=(CI_SRV_FORWARD_OPEN | UnconnectedDataItem.UNCONN_DATA_ITEM_SERVICE_REQUEST))
        cpf = CommandSpecificData(type_id=CommandSpecificData.TYPE_ID_NULL,
                                  item_count=2, length=0, data=cpf2)
        srr = SendRRPacket(interface_handle=0, timeout=0, data=cpf)
        pkt = EncapsulationPacket(command=EncapsulationPacket.ENCAP_CMD_SENDRRDATA,
                                  length=len(srr), session=self.session,
                                  sender_context=random.randint(1, 4026531839).to_bytes(8, byteorder='big'),
                                  data=srr)
        self.sock.send(pkt.pack())
        inp, out, err = select.select([self.sock], [], [], 10)
        if len(inp) != 0:
            data = self.sock.recv(1024)
            pkt = EncapsulationPacket()
            pkt.unpack(data)
            if pkt.status == EncapsulationPacket.ENCAP_STATUS_SUCCESS \
               and pkt.command == EncapsulationPacket.ENCAP_CMD_SENDRRDATA:
                srr = SendRRPacket(pkt.data)
                csd = CommandSpecificData(srr.data)
                udi = UnconnectedDataItem(csd.data)
                if udi.data[1] == 0:  # Forward Open Status
                    fworsp = ForwardOpenResp(udi.data)
                    if csd.item_count > 2:
                        ucdih = UnconnectedDataItemHdr(fworsp.data)
                        otaddrinfo = SocketAddressInfo(ucdih.data)
                        if b'' != otaddrinfo.data:
                            ucdih2 = UnconnectedDataItemHdr(otaddrinfo.data)
                            SocketAddressInfo(ucdih2.data)
                    self.otconnid = fworsp.otconnid
                    self.toconnid = fworsp.toconnid
                    self.otapi = fworsp.otapi / 1000
                    if self.otapi < 8:
                        self.otapi = 8
                    self.toapi = fworsp.toapi / 1000
                    if self.toapi < 8:
                        self.toapi = 8
                    return 0
                elif udi.data[1] == 0x01:  # Forward open failed with Connection Failure
                    if udi.data[2] > 0:
                        extended_status, = struct.unpack("H", udi.data[3:5])
                        return extended_status
        return None

    def sendUdpIO(self, runidle=True):
        from ethernetip.ethernetip import UdpSendDataPacket
        output = b""
        # Overridden to support runidle argument being completely skipped if False
        if runidle:
            output += b"\x01\x00\x00\x00"
        cnt = 0
        val = 0
        for bit in self.outAssem:
            if bit is True:
                val += 1 << cnt
            cnt += 1
            if cnt == 8:
                cnt = 0
                output += struct.pack("B", val)
                val = 0

        # Run/idle header is 4 bytes. If it's missing, the payload length is smaller.
        runidle_sz = 4 if runidle else 0
        pkt = UdpSendDataPacket(seq_num=self.seqnum, seq_count=self.seqnum & 0xffff,
                                conn_id=self.otconnid,
                                len_conn_data=int((len(self.outAssem) / 8) + 2 + runidle_sz),
                                data=output)
        self.seqnum += 1
        self.prodsock.sendto(pkt.pack(), (self.ipaddr, ENIP_UDP_PORT))

def print_menu():
    print("=== TeSys Tera EIP Tester ===")
    print("Available Profiles:")
    for key, val in PROFILES.items():
        print(f"[{key}] {val['name']}")

def run_test_cases(profile_id, df, eip_conn, monitor_sock, ip):
    print(f"\n--- Running Test Cases from Excel for Profile {profile_id} ---")

    tests_run = 0
    for idx, row in df.iterrows():
        title = str(row.get('Title', ''))
        action = str(row.get('Step Action', ''))
        expected = str(row.get('Step Expected Result', ''))

        if pd.isna(action) or action.strip() == "" or action.lower() == "nan":
            continue

        print(f"\n=== Test Case {row.get('S.No.', idx)}: {title} ===")
        print(f"Action: {action}")
        print(f"Expected: {expected}")

        # Reset bits before next action
        eip_conn.outAssem = [False] * len(eip_conn.outAssem)

        action_lower = action.lower()

        # Map actions to specific bits based on the Modbus map commands index
        if "forward start" in action_lower:
            eip_conn.outAssem[0] = True
            print(">> INJECTING: Forward Start (Bit 0)")
        elif "reverse start" in action_lower:
            eip_conn.outAssem[3] = True
            print(">> INJECTING: Reverse Start (Bit 3)")
        elif "stop command" in action_lower:
            eip_conn.outAssem[2] = True
            print(">> INJECTING: Stop (Bit 2)")
        elif "self test with trip" in action_lower:
            eip_conn.outAssem[15] = True
            print(">> INJECTING: Self Test With Trip (Bit 15)")
        elif "self trip without trip" in action_lower or "self test without trip" in action_lower:
            eip_conn.outAssem[14] = True
            print(">> INJECTING: Self Test Without Trip (Bit 14)")
        elif "logic test command" in action_lower or "logic test input" in action_lower:
            eip_conn.outAssem[13] = True
            print(">> INJECTING: Logic Test Input (Bit 13)")
        elif "trip reset" in action_lower:
            eip_conn.outAssem[5] = True
            print(">> INJECTING: Trip Reset (Bit 5)")
        elif "reset commands one by one" in action_lower:
            # Testing reset starts counter (7), reset stops counter (8), thermal (9), run hour (10), energy (11)
            eip_conn.outAssem[7] = True
            eip_conn.outAssem[8] = True
            eip_conn.outAssem[9] = True
            eip_conn.outAssem[10] = True
            eip_conn.outAssem[11] = True
            print(">> INJECTING: Multiple Reset Commands (Bits 7, 8, 9, 10, 11)")
        elif "class1 connection" in action_lower:
            print(">> ACTION: Establishing Class 1 Connection (Already completed globally)")

        print("Executing step and waiting for response packets...")
        # Give the cyclic thread time to send the new O->T assembly and device to respond
        time.sleep(1)

        # Monitor the resulting T->O packets
        packets_checked = 0
        validation_passed = False

        while packets_checked < 5:
            try:
                data, addr = monitor_sock.recvfrom(1024)
                if addr[0] == ip:
                    if len(data) >= 16:
                        item_count = struct.unpack("<H", data[0:2])[0]
                        if item_count >= 2:
                            # Item 1 is Sequenced Address Item: Type(2) + Length(2) + ConnID(4) + SeqNum(4) = 12 bytes total.
                            # So Item 2 starts at offset 2 + 12 = 14
                            type2 = struct.unpack("<H", data[14:16])[0]
                            len2 = struct.unpack("<H", data[16:18])[0]
                            if type2 == 0x00b1:
                                payload = data[18:18+len2]
                                hex_payload = payload.hex()
                                bin_payload = " ".join(f"{b:08b}" for b in payload)
                                print(f"[{time.strftime('%H:%M:%S')}] T->O Data: HEX={hex_payload} | BIN={bin_payload}")

                                all_zero = all(b == 0 for b in payload)
                                if all_zero:
                                    print("Validation: Bits are all 0.")
                                else:
                                    print("Validation: Bits are active!")

                                packets_checked += 1
                                validation_passed = True
            except socket.timeout:
                print("Waiting for EIP cyclic data...")
                packets_checked += 1

        if not validation_passed:
            print("Warning: Did not receive sufficient cyclic validation packets (or CPF offset parsing failed).")

        tests_run += 1

    print(f"\n--- Completed {tests_run} test cases from the Excel file ---")

def main():
    parser = argparse.ArgumentParser(description="Terminal version of EIPScan tool for TeSys Tera")
    parser.add_argument("--ip", required=True, help="IP address of the target device")
    parser.add_argument("--profile", type=int, choices=PROFILES.keys(), help="Profile ID to test. If omitted, will prompt interactively.")
    parser.add_argument("--test-file", type=str, default="/app/profile0_RDOL_testing report.xlsx", help="Excel test case file")
    args = parser.parse_args()

    profile_id = args.profile
    if profile_id is None:
        print_menu()
        while True:
            try:
                choice = int(input("Select a profile (0-12): "))
                if choice in PROFILES:
                    profile_id = choice
                    break
                else:
                    print("Invalid choice, please select between 0 and 12.")
            except ValueError:
                print("Please enter a valid number.")

    selected_profile = PROFILES[profile_id]
    print(f"Selected Profile: {selected_profile['name']}")

    try:
        df = pd.read_excel(args.test_file)
        print("Loaded Test Excel Report successfully.")
    except Exception as e:
        print(f"Could not load test file {args.test_file}: {e}")
        df = None

    # Step 2: Modbus Configuration
    try:
        print(f"Connecting to Modbus at {args.ip}:502...")
        client = ModbusTcpClient(args.ip)
        if client.connect():
            print(f"Writing profile ID {profile_id} to Modbus register 4877...")
            res = client.write_register(4877, profile_id)
            if res.isError():
                print(f"Modbus write error: {res}")
            else:
                print("Modbus profile selection successful.")
            client.close()
        else:
            print("Failed to connect to Modbus server.")
    except Exception as e:
        print(f"Modbus Error: {e}")

    # Step 3: EIP Class 1 connection
    try:
        print(f"Connecting to EIP via ethernetip at {args.ip}...")

        ot_size = selected_profile["o_t_size"]
        to_size = selected_profile["t_o_size"]

        eip_conn = CustomEtherNetIPExpConnection(args.ip)
        res = eip_conn.registerSession()
        if res:
            print(f"Failed to register EIP session: {res}")
            return

        print("EIP session registered.")

        # Test Acyclic Class 3 Explicit Messaging
        print("Testing Acyclic Class 3 (Explicit Messaging) - Reading Identity Object...")
        try:
            # Identity Object: Class 0x01, Instance 0x01, Attribute 0x01 (Vendor ID)
            # By calling getAttrSingle, we send an unconnected/explicit message
            # Note: The library handles encapsulation for explicit messages
            identity_resp = eip_conn.getAttrSingle(0x01, 0x01, 0x01)
            if identity_resp:
                # The response will typically contain the 2-byte vendor ID in the data segment
                print(f"Acyclic Class 3 response received (Raw): {identity_resp}")
            else:
                print("Acyclic Class 3 request failed or timed out.")
        except Exception as explicit_err:
            print(f"Acyclic Class 3 Error: {explicit_err}")

        print(f"Sending Forward Open request (O->T: {selected_profile['o_t_inst']} size {ot_size}, T->O: {selected_profile['t_o_inst']} size {to_size}, Cfg: {selected_profile['cfg_inst']})...")

        config_data = b'\x00' if selected_profile["cfg_size"] > 0 else None

        fwd_open_status = eip_conn.sendFwdOpenReq(
            inputinst=selected_profile["t_o_inst"],
            outputinst=selected_profile["o_t_inst"],
            configinst=selected_profile["cfg_inst"],
            inputsz=to_size,
            outputsz=ot_size,
            configData=config_data,
            torpi=10,
            otrpi=10
        )

        if fwd_open_status == 0:
            print("Forward Open successful!")
        else:
            print(f"Forward Open failed with status: {fwd_open_status}")
            eip_conn.unregisterSession()
            return

        eip_conn.outAssem = [False] * (ot_size * 8)
        def prod_worker():
            while getattr(eip_conn, 'prod_state', 0) == 1:
                eip_conn.sendUdpIO(runidle=False)
                time.sleep(eip_conn.otapi / 1000)

        eip_conn.prod_state = 1
        threading.Thread(target=prod_worker, daemon=True).start()

    except Exception as e:
        print(f"EIP Error: {e}")
        return

    # Execute Excel tests automation and monitoring
    try:
        monitor_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        monitor_sock.bind(("0.0.0.0", 2222))
        monitor_sock.settimeout(2.0)

        if df is not None:
            run_test_cases(profile_id, df, eip_conn, monitor_sock, args.ip)
        else:
            print("No Excel file loaded. Running basic generic monitoring...")
            packets_checked = 0
            while packets_checked < 5:
                try:
                    data, addr = monitor_sock.recvfrom(1024)
                    if addr[0] == args.ip:
                        if len(data) >= 20:
                            type2 = struct.unpack("<H", data[16:18])[0]
                            len2 = struct.unpack("<H", data[18:20])[0]
                            if type2 == 0x00b1:
                                payload = data[20:20+len2]
                                print(f"[{time.strftime('%H:%M:%S')}] T->O Data: HEX={payload.hex()}")
                                packets_checked += 1
                except socket.timeout:
                    print("Waiting for EIP cyclic data...")
                    packets_checked += 1

        print("\nStopping monitor and closing EIP session...")
        eip_conn.prod_state = 0
        eip_conn.sendFwdCloseReq(selected_profile["t_o_inst"], selected_profile["o_t_inst"], selected_profile["cfg_inst"])
        eip_conn.unregisterSession()
        monitor_sock.close()

    except Exception as e:
        print(f"Test Execution/Monitoring Error: {e}")

if __name__ == "__main__":
    main()
