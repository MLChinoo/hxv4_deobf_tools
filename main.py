import os
import shutil

import config
from PlaintextDictionary import PlaintextDictionary
from utils.move_bomhash_files import get_unique_name, merge_dir

dictionary = (PlaintextDictionary(
    pathnames=[
        "scenario/transitions/"
    ],
    filenames=[
        "rule_19.png",
        "base.stage",
        "cglist.csv",
        "soundlist.csv",
        "charvoice.csv"
    ]
)
              #.from_unobfuscated_directory(r"C:\Users\MLChinoo\Desktop\3lj_data")
              #.scan_psb_and_decompile(r"C:\Users\MLChinoo\Desktop\3lj_data_full\scn")
              #.from_base_stage(r"C:\Users\MLChinoo\Desktop\3lj_data_full\bgimage\base.stage")
              #.from_cglist_csv(r"C:\Users\MLChinoo\Desktop\3lj_data_full\data\main\cglist.csv")
              #.from_soundlist_csv(r"C:\Users\MLChinoo\Desktop\3lj_data_full\data\main\soundlist.csv")
              #.add_char_sys_voices(r"C:\Users\MLChinoo\Desktop\3lj_data_full\data\main\charvoice.csv")
              .from_krkrdump_logs(r"C:\Users\MLChinoo\Desktop\krkrdump")
              .duplicate_lower()
              )

path_hash_map = {}
file_hash_map = {}
if not os.path.exists("HxNames.lst"):
    # os.mknod("HxNames.lst")
    open("HxNames.lst", mode="w", encoding="UTF-8")
with open("HxNames.lst", mode="r", encoding="UTF-8") as h:
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

path_to_hash: set = dictionary.pathname_plaintexts - set(path_hash_map.keys())
file_to_hash: set = dictionary.filename_plaintexts - set(file_hash_map.keys())
print(f"新增hash：")
for to_hash in (path_to_hash, file_to_hash):
    for t in to_hash:
        print(t)

# krkr_hxv4_dumphash在命令运行目录下生成文件，而不是游戏目录下
with (open("files.txt", "w", encoding="utf-16le") as f,
      open("dirs.txt", "w", encoding="utf-16le") as d):
    for pathname_plaintext in path_to_hash:
        d.write(f"{pathname_plaintext}\n")
    for filename_plaintext in file_to_hash:
        f.write(f"{filename_plaintext}\n")

os.startfile(config.game_exe)
input("计算完成后手动按回车继续：")

with (open("files_match.txt", "r", encoding="utf-16le") as fm,
      open("dirs_match.txt", "r", encoding="utf-16le") as dm):

    fm_lines = fm.readlines()
    for line in fm_lines:
        line = line.replace("\ufeff", "")  # remove bom
        if line.strip() == "":
            continue
        if len(splitted := line.replace("\n", "").split(",")) != 2:
            print(f"illegal line ignored: {line}")
            continue
        hx_name, hx_hash = splitted
        file_hash_map[hx_name] = hx_hash

    dm_lines = dm.readlines()
    for line in dm_lines:
        line = line.replace("\ufeff", "")  # remove bom
        if line.strip() == "":
            continue
        if len(splitted := line.replace("\n", "").split(",")) != 2:
            print(f"illegal line ignored: {line}")
            continue
        hx_name, hx_hash = splitted
        path_hash_map[hx_name] = hx_hash

with open("HxNames.lst", mode="w", encoding="UTF-8") as h:
    for hash_map in (path_hash_map, file_hash_map):
        for name, hash in hash_map.items():
            if name.strip() == "":
                continue
            h.write(f"{hash}:{name}\n")

if config.rename_dir != "":
    renamed_file_count = 0
    renamed_dir_count = 0
    hash_path_map = {value: key for key, value in path_hash_map.items()}
    hash_file_map = {value: key for key, value in file_hash_map.items()}
    for root, dirs, files in os.walk(config.rename_dir, topdown=False):
        for f in files:
            filepath = os.path.join(root, f)
            if f in hash_file_map.keys():
                new_name = hash_file_map[f]
                new_path = os.path.join(root, new_name)
                new_path = get_unique_name(new_path)
                try:
                    os.rename(filepath, new_path)
                    renamed_file_count += 1
                    print(f"文件重命名成功: {filepath} -> {new_path}")
                except Exception as e:
                    print(f"文件重命名失败: {filepath} -> {new_path}，原因: {e}")
        for d in dirs:
            dirpath = os.path.join(root, d)
            if d in hash_path_map.keys():
                assert hash_path_map[d][-1] == "/"
                target_rel_path = hash_path_map[d].rstrip("/\\")  # locale/jp
                dest_path = os.path.join(root, target_rel_path)  # .../locale/jp

                parent_dir = os.path.dirname(dest_path)  # .../locale
                os.makedirs(parent_dir, exist_ok=True)

                try:
                    if os.path.exists(dest_path):
                        merge_dir(dirpath, dest_path)
                    else:
                        shutil.move(dirpath, dest_path)
                    renamed_dir_count += 1
                    print(f"目录重命名成功: {dirpath} -> {dest_path}")
                except Exception as e:
                    print(f"目录重命名失败: {dirpath} -> {dest_path}，原因: {e}")
    print(f"重命名完成：共重命名文件 {renamed_file_count} 个，目录 {renamed_dir_count} 个")
