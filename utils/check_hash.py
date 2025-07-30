"""
检查给定的字符串是否为pathhash或namehash
"""

def is_path_hash(input: str) -> bool:
    if len(input) != 16:
        return False
    for char in input:
        if not char.isdigit() and not char.isupper():
            return False
    return True

def is_name_hash(input: str) -> bool:
    if len(input) != 64:
        return False
    for char in input:
        if not char.isdigit() and not char.isupper():
            return False
    return True