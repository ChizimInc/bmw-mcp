"""Test fara masina: ECU-ul simulat TMODE. Ruleaza cu Python 32-bit."""
import os
import struct
import sys

print("Python pe", struct.calcsize("P") * 8, "biti")
ebin = r"C:\EDIABAS\Bin"
os.environ["PATH"] = ebin + os.pathsep + os.environ.get("PATH", "")
if hasattr(os, "add_dll_directory"):
    os.add_dll_directory(ebin)

from pydiabas import PyDIABAS

with PyDIABAS() as p:
    r = p.job("TMODE", "LESE_INTERFACE_TYP")
    print("jobstatus:", r.jobstatus)
    print("TYP:", r["TYP"])
    print("systemSet:", r.systemSet)
    print("jobSets:", r.jobSets)
    try:
        print("as_dicts:", r.as_dicts())
    except Exception as e:
        print("as_dicts a esuat:", e)
print("OK")
