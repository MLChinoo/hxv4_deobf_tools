"""
遍历目录并将"94D4A97C61498621"目录下的文件移动至上一层级目录

"94D4A97C61498621"为BOM字符﻿的hash，即目录里的文件应在上一级目录下，而不是错误地新开一个目录
"""
import hashlib
import os
import shutil

def files_identical(fp1: str, fp2: str, chunk=8192) -> bool:
    """快速判断两个文件是否完全一致（大小+hash）。"""
    if os.path.getsize(fp1) != os.path.getsize(fp2):
        return False
    h1 = hashlib.blake2b()
    h2 = hashlib.blake2b()
    with open(fp1, "rb") as f1, open(fp2, "rb") as f2:
        while True:
            b1, b2 = f1.read(chunk), f2.read(chunk)
            if not b1 and not b2:
                break
            h1.update(b1); h2.update(b2)
    return h1.digest() == h2.digest()

def merge_dir(src: str, dest: str):
    """把 src 目录合并进 dest 目录；dest 已存在"""
    for item in os.listdir(src):
        src_item = os.path.join(src, item)
        dest_item = os.path.join(dest, item)

        # 若目标已存在
        if os.path.exists(dest_item):
            if os.path.isdir(src_item) and os.path.isdir(dest_item):
                # 递归合并子目录
                merge_dir(src_item, dest_item)
            elif os.path.isfile(src_item) and os.path.isfile(dest_item):
                # 判重；完全一致则跳过，否则改名保存
                if files_identical(src_item, dest_item):
                    # 内容相同，无需处理
                    os.remove(src_item)
                else:
                    new_name = get_unique_name(dest_item)
                    shutil.move(src_item, new_name)
            else:
                # 文件夹 vs 文件冲突，可自选策略；这里改名保存
                new_name = get_unique_name(dest_item)
                shutil.move(src_item, new_name)
        else:
            # 目标不存在，直接移动
            shutil.move(src_item, dest_item)

    # src 目录若为空则删除
    if not os.listdir(src):
        os.rmdir(src)

def get_unique_name(dest_path):
    """
    如果路径已存在，自动添加 _1, _2 等后缀，返回唯一名称
    """
    base, ext = os.path.splitext(dest_path)
    counter = 1
    new_path = dest_path

    while os.path.exists(new_path):
        new_path = f"{base}_{counter}{ext}"
        counter += 1

    return new_path

def move_bomhash_files(root_dir):
    for current_dir, dirs, files in os.walk(root_dir, topdown=False):
        if "94D4A97C61498621" in dirs:
            target_path = os.path.join(current_dir, "94D4A97C61498621")
            print(f"处理目录: {target_path}")

            # 遍历目标子目录中的所有文件和文件夹
            for item in os.listdir(target_path):
                src = os.path.join(target_path, item)
                dest = os.path.join(current_dir, item)

                # 如果目标位置已存在，则重命名
                if os.path.exists(dest):
                    dest = get_unique_name(dest)

                shutil.move(src, dest)
                print(f"移动: {src} -> {dest}")

            # 删除空目录
            shutil.rmtree(target_path)
            print(f"已删除目录: {target_path}")

if __name__ == "__main__":
    root_directory = r"C:\Users\MLChinoo\Desktop\tenshi_hikari_dumps"  # 替换为你的实际路径
    move_bomhash_files(root_directory)
