import csv
import json
import os
import re
import shutil
import subprocess
import traceback
from itertools import product
from json import JSONDecodeError
from pathlib import Path
from contextlib import suppress
from collections.abc import Iterable

import json5

import config
from utils.check_hash import is_path_hash, is_name_hash
from utils.tjs_parser import parse_base_stage_to_json5


class PlainDict:
    pathname_plaintexts, filename_plaintexts = set(), set()

    def __init__(self, pathnames: list | tuple = (), filenames: list | tuple = ()):
        self.pathname_plaintexts.update(pathnames)
        self.filename_plaintexts.update(filenames)

    """
    从已有的目录名和文件名提取filename和pathname
    此来源多用于从同游戏的体验版或加密较弱的初始发行版的明文目录结构获取明文信息
    """
    def from_unobfuscated_directory(self, base_dir: str):
        for root, dirs, files in os.walk(base_dir):
            rel_path = os.path.relpath(root, base_dir).replace("\\", "/")
            if rel_path == ".":
                rel_path = ""
            else:
                rel_path += "/"

            levels = rel_path.strip("/").split("/") if rel_path else []

            full_path = ""
            for level in levels:
                full_path += level + "/"
                if not is_path_hash(level):
                    self.pathname_plaintexts.add(full_path)
                else:
                    break

            for i in range(len(levels)):
                suffix_levels = levels[i:]
                if all(not is_path_hash(l) for l in suffix_levels):
                    self.pathname_plaintexts.add("/".join(suffix_levels) + "/")

            for file in files:
                if not is_name_hash(file.split(".")[0]):
                    self.filename_plaintexts.add(file)

        return self

    """
    将现有pathname_plaintexts和filename_plaintexts复制一份小写副本并添加
    如AppConfig.tjs则再添加一个appconfig.tjs
    """
    def duplicate_lower(self):
        self.pathname_plaintexts.update((_.lower() for _ in self.pathname_plaintexts.copy()))
        self.filename_plaintexts.update((_.lower() for _ in self.filename_plaintexts.copy()))
        return self

    """
    扫描给定目录下的文件，对可能的psb文件进行decompile并获取信息
    """
    def scan_psb_and_decompile(self, scn_dir: str):
        def is_psb_file(path: str | Path) -> bool:
            path = Path(path)
            if not path.is_file():
                return False
            try:
                with path.open("rb") as f:
                    header = f.read(3)
                    return header == b"PSB" or header == b"mdf"
            except OSError:
                return False
            
        def convert_to_custom_extension(filename: str, new_extension: str) -> str:
            if not new_extension.startswith("."):
                new_extension = "." + new_extension
            if "." in filename and not filename.startswith("."):
                base = ".".join(filename.split(".")[:-1])
            else:
                base = filename
            return base + new_extension
        psb_type_cache = {
            "scn": [],
            "pimg": [],
            "motion": []
        }
        
        def handle_data_item(data_item: dict):
            if data_item.get("name") in ("bgm", "live", "liveout") and "replay" in data_item.keys():
                # 获取背景音乐文件名  bgm
                filename = data_item["replay"]["filename"]
                if filename is not None:
                    self.filename_plaintexts.update([
                        f"{filename}.ogg",
                        f"{filename}.ogg.sli",
                        f"{filename}.opus",
                        f"{filename}.opus.sli",
                        f"{filename}.mchx",
                        f"{filename}.mchx.sli"
                    ])
            elif data_item.get("name") in ("lse", "lse2", "se") and "replay" in data_item.keys():
                # sound
                filename_raw: str = data_item["replay"]["filename"]
                if filename_raw is not None:
                    filenames = filename_raw.split("|")
                    for filename in filenames:
                        self.filename_plaintexts.update([
                            f"{filename}.ogg",
                            f"{filename}.ogg.sli"
                        ])
            elif data_item.get("name") == "stage" and "redraw" in data_item.keys():
                # 获取背景图片文件名  bgimage
                filename = data_item["redraw"]["imageFile"]["file"]
                self.filename_plaintexts.update([
                    f"{filename}.png"
                ])
            elif data_item.get("class") in ("msgwin", "character"):
                # 获取人物stand文件名  fgimage
                if "redraw" in data_item.keys():
                    filename_with_ext: str = data_item["redraw"]["imageFile"]["file"]
                    assert filename_with_ext.endswith(".stand")
                    self.filename_plaintexts.add(
                        f"{filename_with_ext}"
                    )
                elif "stand" in data_item.keys():
                    filename_with_ext: str = data_item["stand"]["file"]
                    assert filename_with_ext.endswith(".stand")
                    self.filename_plaintexts.add(
                        f"{filename_with_ext}"
                    )
            elif data_item.get("class") == "event":
                if data_item.get("name") == "ev" and "redraw" in data_item.keys():
                    # 在lines中获取image
                    filename = data_item["redraw"]["imageFile"]["file"]
                    self.filename_plaintexts.add(
                        f"{filename}.png"
                    )
                elif data_item.get("name") == "bg_voice" and "redraw" in data_item.keys():
                    # 背景对话文件 bg_voice (e.g. bgv007_07_歓声.csv)
                    filename_with_ext = data_item["redraw"]["imageFile"]["file"]["storage"]
                    self.filename_plaintexts.add(
                        f"{filename_with_ext}"
                    )
            elif data_item.get("class") == "phonechat" and data_item.get("name") == "phonescreen" and "redraw" in data_item.keys():
                # 获取气泡聊天背景图片
                filename = data_item["redraw"]["imageFile"]["file"]
                self.filename_plaintexts.add(
                    f"{filename}.tlg"
                )
            elif data_item.get("class") == "sdlayer" and "redraw" in data_item.keys():
                # sd图层
                filename = data_item["redraw"]["imageFile"]["file"]
                self.filename_plaintexts.add(
                    f"{filename}.png"
                )
            elif data_item.get("class") == "event2" and "redraw" in data_item.keys():
                # 
                filename = data_item["redraw"]["clip"]["image"]
                self.filename_plaintexts.add(
                    f"{filename}.png"
                )

        def handle_data_block(data_block: list):
            # lines和texts里某些data字段结构是一致的，因此可以封装成一个共同方法进行处理
            for data in data_block:
                if type(data) == list:
                    for data_item in data:
                        if type(data_item) == dict:
                            handle_data_item(data_item)
                            
        def handle_voice(voice_filenames_raw: str):  # fanB_412_0012.ogg|DL_回想
            base_voice_extensions = {"ogg", "ogg.sli", "opus", "opus.sli", "ini"}
            voice_filenames = voice_filenames_raw.split("|")
            for voice_filename in voice_filenames:
                if "." in voice_filename:
                    if voice_filename.count(".") > 1:
                        print(f"warning: multiple extensions file - {voice_filename}")
                    voice_name, extension = voice_filename.split(".", 1)
                else:
                    voice_name, extension = voice_filename, None
                voice_extensions = base_voice_extensions.copy()
                if extension is not None:
                    voice_extensions.add(extension)
                for voice_extension in voice_extensions:
                    self.filename_plaintexts.add(
                        f"{voice_name}.{voice_extension}"
                    )
                            
        if not os.path.exists(config.psb_type_cache_json):
            open(config.psb_type_cache_json, mode="w", encoding="UTF-8")
        with suppress(JSONDecodeError):
            with open(config.psb_type_cache_json, mode="r", encoding="UTF-8") as ptcf:
                ptcj: dict = json.load(ptcf)
                for key in psb_type_cache.keys():
                    psb_type_cache[key] = ptcj.get(key, [])

        for root, dirs, files in os.walk(scn_dir):
            for file in files:
                if is_psb_file(filepath := os.path.join(root, file))\
                        and file not in psb_type_cache["pimg"]\
                        and file not in psb_type_cache["motion"]:
                    try:
                        json_filename = convert_to_custom_extension(file, ".json")
                        json_filepath = os.path.join(config.temp_dir, json_filename)

                        if not os.path.exists(json_filepath):
                            shutil.copy(filepath, temp_filepath := os.path.join(config.temp_dir, file))
                            subprocess.run([config.psbdecompile_exe, '-raw', temp_filepath], check=True)
                            os.remove(temp_filepath)
                            resx_json_filename = convert_to_custom_extension(file, ".resx.json")
                            resx_json_filepath = os.path.join(config.temp_dir, resx_json_filename)
                            os.remove(resx_json_filepath)

                        json_f = open(json_filepath, mode="r", encoding="UTF-8")
                        psb_json: dict = json.load(json_f)
                        if "scenes" in psb_json and "name" in psb_json:
                            # scn psb
                            psb_type_cache["scn"].append(file)

                            # 从name字段获取scn原文件名
                            self.filename_plaintexts.add(f"{psb_json['name']}.scn")

                            for scene in psb_json["scenes"]:
                                if "texts" in scene.keys():
                                    for text in scene["texts"]:
                                        for text_item in text:
                                            if type(text_item) == list:
                                                for text_item_item in text_item:
                                                    if type(text_item_item) == dict and "voice" in text_item_item.keys():
                                                        # 获取语音文件名  voice
                                                        voice_source = text_item_item
                                                        handle_voice(voice_source["voice"])
                                                             
                                            elif type(text_item) == dict:
                                                if "data" in text_item.keys():
                                                    handle_data_block(text_item["data"])
                                                if "phonechat" in text_item.keys():
                                                    for chat in text_item["phonechat"]:
                                                        assert type(chat) == dict
                                                        icon = chat["icon"]
                                                        self.filename_plaintexts.add(
                                                            f"chaticon_{icon}.png"
                                                        )

                                for line in scene["lines"]:  # 0000
                                    if type(line) == list:
                                        for index, line_item in enumerate(line):
                                            if type(line_item) == dict and "data" in line_item.keys():
                                                handle_data_block(line_item["data"])
                                                    
                                            elif type(line_item) == list:
                                                for item in line_item:
                                                    if type(item) == dict:
                                                        handle_data_item(item)
                                                        
                                            elif type(line_item) == str:
                                                if line[index-1] == "voice":
                                                    # 某些语音藏在lines的playvoice行中... (e.g. anj_102_0016)
                                                    handle_voice(line_item)
                                                

                        elif "height" in psb_json and "width" in psb_json:  # and "layers" in psb_json
                            # pimg psb
                            psb_type_cache["pimg"].append(file)
                            json_f.close()
                            os.remove(json_filepath)

                        elif psb_json.get("id") == "motion":
                            # motion psb
                            psb_type_cache["motion"].append(file)
                            json_f.close()
                            os.remove(json_filepath)

                        else:
                            json_f.close()
                            os.remove(json_filepath)
                            raise NotImplementedError(f"{file}\n{psb_json.keys()}")
                        json_f.close()
                    except Exception:
                        traceback.print_exc()
        with open(config.psb_type_cache_json, mode="w", encoding="UTF-8") as ptcf:
            json.dump(psb_type_cache, ptcf, indent=4)
        for root, dirs, files in os.walk(config.temp_dir):
            for d in dirs:
                shutil.rmtree(os.path.join(config.temp_dir, d))
        return self

    """
    从base.stage文件中获取背景图片文件名bgimage
    """
    def from_base_stage(self, base_stage_filepath: str):
        with open(base_stage_filepath, mode="r", encoding="utf-16le") as f:
            base_stage: dict = json5.loads(parse_base_stage_to_json5(f.read()))
        time_prefixes, season_prefixes = {""}, {""}  # 保证至少一个默认值，避免无法循环
        for key, value in base_stage.items():
            if type(value) == dict:
                if key == "times":
                    for time in value.values():
                        time_prefixes.add(time.get("prefix"))
                elif key == "seasons":
                    for season in value.values():
                        season_prefixes.add(season.get("prefix"))
                elif key != "stages":
                    pass  # unknown classification...?
        for stage in base_stage["stages"].values():
            image_filename_template: str = stage["image"]
            for time_prefix, season_prefix in product(time_prefixes, season_prefixes):
                if all((time_prefix is not None, season_prefix is not None)):
                    image_filename = (image_filename_template
                                      .replace("TIME", time_prefix)
                                      .replace("SEASON", season_prefix))
                    self.filename_plaintexts.add(f"{image_filename}.png")
        return self

    """
    从cglist.csv文件中获取cg缩略图thum及sd文件
    """
    def from_cglist_csv(self, cglist_csv_filepath: str):
        with open(cglist_csv_filepath, mode="r", encoding="utf-16le") as f:
            cglist_csv = csv.reader(f)
            for row in cglist_csv:
                cg_filename = row[0].strip()
                if cg_filename.startswith("#"):
                    continue
                if ":" in cg_filename:
                    print(f"bad cg_filename, ignored: {cg_filename} in {cglist_csv_filepath}")
                    continue
                cg_name = cg_filename.replace("thum_", "")
                # ev: 
                self.filename_plaintexts.update([
                    # ev部分文件名迁移至from_imagediffmap_csv()
                    f"{cg_filename}.jpg",
                    f"{cg_filename}.png",
                    f"{cg_filename}_censored.jpg",
                    f"{cg_filename}_censored.png",
                ])
                if cg_filename.startswith("thum_"):
                    self.filename_plaintexts.update([
                        # savethum必定censored
                        f"save{cg_filename}.jpg",
                        f"save{cg_filename}.png"
                    ])
                if cg_filename.startswith("thum_ev"):
                    for cg_diffs in row[1:]:
                        for cg_diff in cg_diffs.replace("*", "").split("|"):
                            if not cg_diff.startswith(cg_name):
                                print(f"bad cg_diff with cg_name, ignored: {cg_diff}, {cg_name}")
                                continue
                            cg_name_last_pos = cg_diff.find(cg_name) + len(cg_name)
                            for cg_diff_last_pos in range(cg_name_last_pos, len(cg_diff)+1):
                                filename = f"{cg_name}{cg_diff[cg_name_last_pos:cg_diff_last_pos]}"
                                self.filename_plaintexts.update([
                                    f"{filename}.pimg",
                                    f"{filename}_censored.pimg",
                                    f"thum_{filename}.png",
                                    f"thum_{filename}.jpg",
                                    f"thum_{filename}_censored.png",
                                    f"thum_{filename}_censored.jpg",
                                    f"savethum_{filename}.png",
                                    f"savethum_{filename}.jpg",
                                ])
                            
                # sd: 
                if cg_filename.startswith("thum_sd"):  # thum_sd001
                    sd_name = cg_filename[5:]  # sd001
                    self.filename_plaintexts.update((
                        f"{sd_name}.mtn",
                        f"{sd_name}.psb"
                    ))
                    for sd_diff in row[1:]:
                        sd_diff = sd_diff.strip()  # sd001a01
                        self.filename_plaintexts.update((
                            f"{sd_diff}.jpg",
                            f"{sd_diff}.png",
                            f"{sd_diff}.asd"
                        ))
        return self

    """
    从soundlist.csv文件中获取bgm文件名
    """
    def from_soundlist_csv(self, soundlist_csv_filepath):
        with open(soundlist_csv_filepath, mode="r", encoding="utf-16le") as f:
            soundlist_csv = csv.reader(f)
            for row in soundlist_csv:
                if len(row) > 0:
                    header = row[0]
                    if not header.startswith("#"):
                        self.filename_plaintexts.update((
                            f"{header}.opus",
                            f"{header}.opus.sli",
                            f"{header}.ogg",
                            f"{header}.ogg.sli",
                            f"{header}.mchx",
                            f"{header}.mchx.sli"
                        ))
        return self

    """
    从KrkrDump的log中获取文件名
    适用于从未在之前发行的游戏中出现的、以及无规律可获取其文件名的文件，动态运行一下也许有意外收获...?
    """
    def from_krkrdump_logs(self, krkrdump_dir):
        for filename in os.listdir(krkrdump_dir):
            if all((filename.startswith("KrkrDump-"), filename.endswith(".log"))):
                print(f"current log: {filename}")
                filepath = os.path.join(krkrdump_dir, filename)
                with open(filepath, mode="r", encoding="UTF-8") as log_f:
                    krkrdump_log = log_f.readlines()
                for line in krkrdump_log:
                        match = re.search(r'"([^"]*)"', line)
                        if match:
                            content = match.group(1)
                            if "NameHash: " in line:
                                self.filename_plaintexts.add(content)
                            elif "PathHash: " in line:
                                self.pathname_plaintexts.add(content)
        return self

    """
    添加各人物的系统语音，从charvoice.csv获取人物前缀名，语音后缀名来自天使嚣嚣trial，可能涵盖不全
    """
    def add_char_sys_voices(self, charvoice_csv_filepath):
        sys_voice_suffixes = (
            "after",
            "attention0",
            "attention1",
            "attention2",
            "attention3",
            "backlog",
            "chart",
            "config",
            "config_easy",
            "custom",
            "dialog",
            "end",
            "extra",
            "extra_bu",
            "extra_cg",
            "extra_scene",
            "game",
            "game2",
            "goodbye",
            "jump",
            "load",
            "mouse",
            "pad",
            "rec",
            "reset",
            "save",
            "shortcut",
            "sound",
            "text",
            "tittle",
            "tittleback",
            "voice",
            "volume",
            "window",
            "yuzu",

            "title",
            "titleback"
        )
        with open(charvoice_csv_filepath, mode="r", encoding="utf-16le") as f:
            charvoice_csv = csv.reader(f)
            for row in charvoice_csv:
                if len(row) > 0:
                    header = row[0].replace("\ufeff", "")  # remove bom
                    if not header.startswith("#") and not header.startswith("DEFAULT"):
                        char_prefix = row[1].split("_")[0]
                        for sys_voice_suffix in sys_voice_suffixes:
                            self.filename_plaintexts.add(f"{char_prefix}_{sys_voice_suffix}.ogg")
        return self

    """
    从imagediffmap.csv文件中获取cg文件名evimage
    """
    def from_imagediffmap_csv(self, imagediffmap_csv_filepath):
        with open(imagediffmap_csv_filepath, mode="r", encoding="utf-16le") as f:
            imagediffmap_csv = csv.reader(f)
            for row in imagediffmap_csv:
                if len(row) > 0:
                    header = row[0].replace("\ufeff", "")  # remove bom
                    if not header.startswith("#"):
                        filename = row[1]
                        if "." in filename:
                            if filename.count(".") > 1:
                                print(f"warning: multiple extensions file - {filename}")
                            names, extension = filename.split(".", 1)
                            names = names.split("|")
                            for name in names:
                                self.filename_plaintexts.add(
                                    f"{name}.{extension}"
                                )
                        else:
                            self.filename_plaintexts.update([
                                f"{filename}.pimg",
                                f"{filename}_censored.pimg",
                                f"savethum_{filename}.jpg",
                                f"savethum_{filename}.png"
                            ])
        return self
    
    """
    从背景对话文件 (e.g. bgv102_02_恵凪会話.csv) 中获取语音文件名
    此文件名分布在各个scn中，因此需先跑一遍scan_psb_and_decompile()
    此文件一般位于voice包中，因此需指定跑过一遍脚本后的voice文件夹
    """
    def from_bgv_csv(self, voice_dir):
        for child in Path(voice_dir).iterdir():
            # 假设文件名以bgv开头，扩展名为.csv
            if all([child.is_file(), child.stem.startswith("bgv"), child.suffix == ".csv"]):
                with open(child, mode="r", encoding="utf-16le") as f:
                    bgv_csv = csv.reader(f)
                    for row in bgv_csv:
                        if len(row) > 0 and not row[0].replace("\ufeff", "").startswith("#"):
                            voice_name = row[2]
                            self.filename_plaintexts.update([
                                f"{voice_name}.ogg",
                                f"{voice_name}.ogg.sli",
                                f"{voice_name}.opus",
                                f"{voice_name}.opus.sli",
                                f"{voice_name}.ini"
                            ])
        return self
    
    """
    从savelist.csv文件中获取存档图片savethum
    """
    def from_savelist_csv(self, savelist_csv_filepath):
        with open(savelist_csv_filepath, mode="r", encoding="utf-16le") as f:
            savelist_csv = csv.reader(f)
            for row in savelist_csv:
                if len(row) > 0:
                    header = row[0].replace("\ufeff", "")  # remove bom
                    if not header.startswith("#"):
                        filename = row[0]
                        self.filename_plaintexts.update([
                            f"{filename}.jpg",
                            f"{filename}.png",
                            f"{filename.replace("savethum_", "thum_")}.jpg",
                            f"{filename.replace("savethum_", "thum_")}.png",
                        ])
        return self
    
    """
    从scenelist.csv中获取cg缩略图thum
    此来源可以获取到影片movie缩略图movthum
    """
    def from_scenelist_csv(self, scenelist_csv_filepath):
        with open(scenelist_csv_filepath, mode="r", encoding="utf-16le") as f:
            scenelist_csv = csv.reader(f)
            for row in scenelist_csv:
                if len(row) > 0:
                    header = row[0].replace("\ufeff", "")  # remove bom
                    if not header.startswith("#"):
                        if ":" in header:
                            print(f"bad cg_filename, ignored: {header} in {scenelist_csv_filepath}")
                            continue
                        filenames = row[0].split("|")
                        for filename in filenames:
                            self.filename_plaintexts.update([
                                f"{filename}.jpg",
                                f"{filename}.png",
                                f"{filename}_censored.jpg",
                                f"{filename}_censored.png"
                            ])
        return self
    
    """
    寻找可能遗漏的语音文件
    某些语音存在于voice目录中，但未被任何scn引用，根本不可能在正常游戏流程中出现（即“废案语音”，例如宁宁有30个左右），
    这时即可利用语音文件名编号连续的特点，来尽可能寻找这些语音。
    """
    def find_missing_voices(self, voice_dirs: Iterable):
        prefix_maxnum_map = {}  # anj_000: 90
        for voice_dir in voice_dirs:
            for child in Path(voice_dir).iterdir():
                if all((child.is_file(), child.suffix in (".ogg", ".sli"), child.stem.count("_") == 2)):  # anj_000_0090.ogg
                    prefix, num = child.stem.rsplit("_", 1)  # anj_000, 0090
                    if result := re.match(r'^(\d{4})', num):
                        num = int(result.group(1))  # 90
                        if prefix not in prefix_maxnum_map:
                            prefix_maxnum_map[prefix] = 1
                        if num > prefix_maxnum_map[prefix]:
                            prefix_maxnum_map[prefix] = num
        for prefix, maxnum in prefix_maxnum_map.items():
            for num in range(1, maxnum+1):
                voice_name = f"{prefix}_{num:04d}"
                if not any(((Path(vd) / f"{voice_name}.ogg").exists() for vd in voice_dirs)):
                    print(f"found possible missing voice: {voice_name}")
                    self.filename_plaintexts.update([
                        f"{voice_name}.ogg",
                        f"{voice_name}.ogg.sli"
                    ])
        return self
                            
if __name__ == "__main__":
    for root, dirs, files in os.walk(config.temp_dir):
        for d in dirs:
            shutil.rmtree(os.path.join(config.temp_dir, d))
