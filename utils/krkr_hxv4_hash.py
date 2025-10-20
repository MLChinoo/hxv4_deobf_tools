import ctypes

import config

mylib = ctypes.CDLL(config.krkrhxv4hash_dll)

mylib.get_filename_hash.argtypes = [ctypes.c_wchar_p]
mylib.get_filename_hash.restype = ctypes.POINTER(ctypes.c_uint8)

mylib.get_path_hash.argtypes = [ctypes.c_wchar_p]
mylib.get_path_hash.restype = ctypes.c_uint64

def str_to_utf16_ptr(s: str):
    utf16_bytes = s.encode("utf-16le") + b"\x00\x00"
    buf = ctypes.create_string_buffer(utf16_bytes)
    return ctypes.cast(buf, ctypes.c_wchar_p)

def get_filehash(filename: str) -> str:
    ptr = str_to_utf16_ptr(filename)
    arr_ptr = mylib.get_filename_hash(ptr)
    hash_result = ''.join(f"{arr_ptr[i]:02X}" for i in range(32))
    return hash_result

def get_pathhash(pathname: str) -> str:
    ptr = str_to_utf16_ptr(pathname)
    num = mylib.get_path_hash(ptr)
    hash_result = f"{num:016X}"
    return hash_result

if __name__ == "__main__":
    print(get_pathhash("/"))
    print(get_pathhash(""))
    print(get_pathhash("﻿"))
    print(get_filehash(""))
