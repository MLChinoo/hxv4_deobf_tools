"""
原HxNames.lst为了命中更多的hash名称会多出很多冗余条目，
若需发布，可用此方法从已有已反混淆的目录生成一份干净的HxNames.lst
"""
import os
from pathlib import Path

from utils.check_hash import is_name_hash, is_path_hash


def generate_clean_hxnames(deobfuscated_dir: Path, save_filepath: Path):
    path_hash_map = {}
    file_hash_map = {}
    save_file = open(save_filepath, mode="w", encoding="UTF-8")
    ignored_items = 0

    with open("../HxNames.lst", mode="r", encoding="UTF-8") as h:
        h_lines = h.readlines()
        for line in h_lines:
            if line.strip() == "":
                continue
            assert len(splitted := line.replace("\n", "").split(":")) == 2, line
            hx_hash, hx_name = splitted
            if len(hx_hash) == 16:  # path
                path_hash_map[hx_name] = hx_hash
            elif len(hx_hash) == 64:  # file
                file_hash_map[hx_name] = hx_hash
            else:
                raise Exception(hx_hash)

        for xp3_dir in deobfuscated_dir.iterdir():
            for child in xp3_dir.rglob('*'):
                if child.is_file():
                    hx_name = child.name
                    if is_name_hash(hx_name):
                        continue
                    print(hx_name)
                    if hx_name not in file_hash_map:
                        print(f"{hx_name} not in file hash map, ignored")
                        ignored_items += 1
                        continue
                    save_file.write(f"{file_hash_map[hx_name]}:{hx_name}\n")
                elif child.is_dir():
                    hx_name = str(child.relative_to(xp3_dir)).replace("\\", "/")
                    for subdir in hx_name.split("/"):
                        if is_path_hash(subdir):
                            continue
                    hx_name += "/"
                    print(hx_name)
                    if hx_name not in path_hash_map:
                        print(f"{hx_name} not in path hash map, ignored")
                        ignored_items += 1
                        continue
                    save_file.write(f"{path_hash_map[hx_name]}:{hx_name}\n")
                    
    save_file.close()
    print(f"\nclean hxnames generated, ignored {ignored_items} item(s).")
                    

if __name__ == "__main__":
    generate_clean_hxnames(
        deobfuscated_dir=Path(r"C:\Users\MLChinoo\Desktop\3lj_data_full"),
        save_filepath=Path(r"C:\Users\MLChinoo\PycharmProjects\hxv4_deobf_tools\HxNames-LLLJ.lst")
    )
