#!/usr/bin/env python3
"""Build "Profinet Poll" as a single standalone Windows .exe.

Two backends are supported:

  python build_profinet_poll.py            # default: PyInstaller (fast, low RAM)
  python build_profinet_poll.py --nuitka   # Nuitka (true compile, needs >6 GB free RAM)

Both produce ONE self-contained exe with:
  * an embedded ``requireAdministrator`` UAC manifest (prompts for admin on launch), and
  * the official Npcap installer bundled inside, which the program offers to run
    on first start when it detects the packet driver is missing.

Output: dist/Profinet Poll.exe

Requirements
------------
  pip install pyinstaller            # for the default backend
  pip install nuitka ordered-set zstandard   # for --nuitka (plus MSVC Build Tools on Py>=3.13)

Note on Nuitka + memory
-----------------------
Nuitka compiles scapy to C; cl.exe needs several GB of free RAM. On a machine
with little free memory it fails with "compiler is out of heap space" (C1002)
or stalls swapping. Use --nuitka only where >6 GB RAM is free, or use the
default PyInstaller backend, which does not compile C and builds in <1 GB.
"""
import os, sys, subprocess, glob, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SRC  = os.path.join(HERE, "profinet_commander.py")
NAME = "Profinet Poll"


def _find_npcap():
    for p in glob.glob(os.path.join(HERE, "npcap", "npcap*.exe")) + \
             glob.glob(os.path.join(HERE, "npcap*.exe")):
        return p
    return None


def build_pyinstaller(npcap):
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--onefile", "--console", "--name", NAME,
            "--uac-admin", "--collect-all", "scapy", "--hidden-import", "netifaces"]
    if npcap:
        args += ["--add-data", f"{npcap};."]
    args.append(SRC)
    print("Running:", " ".join(args))
    return subprocess.call(args, cwd=HERE)


def build_nuitka(npcap):
    args = [sys.executable, "-m", "nuitka", "--onefile",
            "--assume-yes-for-downloads", "--low-memory", "--lto=no",
            "--windows-uac-admin", "--enable-plugin=no-qt",
            "--include-module=scapy.all", "--include-module=netifaces",
            # trim heavy, unused scapy layers to cut compile size/RAM
            "--nofollow-import-to=scapy.layers.tls",
            "--nofollow-import-to=scapy.layers.kerberos",
            "--nofollow-import-to=scapy.layers.bluetooth",
            "--nofollow-import-to=scapy.layers.bluetooth4LE",
            "--nofollow-import-to=scapy.layers.smb",
            "--nofollow-import-to=scapy.layers.smb2",
            "--nofollow-import-to=scapy.layers.smbserver",
            "--nofollow-import-to=scapy.layers.smbclient",
            "--nofollow-import-to=scapy.layers.ntlm",
            "--nofollow-import-to=scapy.layers.msrpce",
            "--nofollow-import-to=scapy.contrib",
            "--nofollow-import-to=matplotlib",
            "--nofollow-import-to=IPython",
            "--nofollow-import-to=tkinter",
            "--nofollow-import-to=PyQt5",
            "--company-name=PROFINET Tools",
            "--product-name=Profinet Poll",
            "--file-description=PROFINET Commander (Profinet Poll)",
            "--product-version=1.0.0",
            f"--output-filename={NAME}.exe",
            "--output-dir=dist", "--remove-output"]
    if npcap:
        args.append(f"--include-data-files={npcap}={os.path.basename(npcap)}")
    args.append(SRC)
    print("Running:", " ".join(args))
    return subprocess.call(args, cwd=HERE)


def main():
    use_nuitka = "--nuitka" in sys.argv
    npcap = _find_npcap()
    print("Npcap installer:", npcap or "NONE (will not be bundled)")
    rc = build_nuitka(npcap) if use_nuitka else build_pyinstaller(npcap)
    out = os.path.join(HERE, "dist", f"{NAME}.exe")
    if rc == 0 and os.path.exists(out):
        print(f"\nOK -> {out}  ({os.path.getsize(out)/1e6:.1f} MB)")
    else:
        print(f"\nBUILD FAILED (rc={rc}). See output above.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
