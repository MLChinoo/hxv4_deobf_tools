"""
检查给定目录下未混淆文件名和目录名占全部文件名和目录名的百分比

即反混淆进度
"""
import os

from check_hash import is_path_hash, is_name_hash

def get_progress_percent(root_dir: str) -> float:
    total_path = 0
    total_file = 0
    hashed_path = 0
    hashed_file = 0
    for root, dirs, files in os.walk(root_dir):
        for d in dirs:
            total_path += 1
            if is_path_hash(d):
                hashed_path += 1
        for file in files:
            total_file += 1
            if is_name_hash(file):
                hashed_file += 1
    return 1 - (hashed_path + hashed_file) / (total_path + total_file)

if __name__ == "__main__":
    print(f"{100 * get_progress_percent(r"C:\Users\MLChinoo\Desktop\3lj_data_full")}%")
