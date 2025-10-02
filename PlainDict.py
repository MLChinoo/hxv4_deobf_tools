import csv
import json
import os
import re
import shutil
import subprocess
import traceback
from json import JSONDecodeError
from pathlib import Path
from contextlib import suppress

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
                    if "|" in filename_raw:
                        filenames = filename_raw.split("|")
                    else:
                        filenames = [filename_raw]
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
                    # 1.在texts中获取cg文件名 evimage
                    # from_cglist_csv()已实现此来源 故略
                    # 2.在lines中获取image
                    filename = data_item["redraw"]["imageFile"]["file"]
                    self.filename_plaintexts.add(
                        f"{filename}.png"
                    )
                elif data_item.get("name") == "bg_voice" and "redraw" in data_item.keys():
                    # vlist (e.g. bgv007_07_歓声.csv)
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

        def handle_data_block(data_block: list):
            # lines和texts里某些data字段结构是一致的，因此可以封装成一个共同方法进行处理
            for data in data_block:
                if type(data) == list:
                    for data_item in data:
                        if type(data_item) == dict:
                            handle_data_item(data_item)
                            
        def handle_voice(voice_name_raw: str):
            if "|" in voice_name_raw:
                voice_names = voice_name_raw.split("|")
            else:
                voice_names = [voice_name_raw]
            for voice_name in voice_names:
                self.filename_plaintexts.update([
                    f"{voice_name}.ogg",
                    f"{voice_name}.ogg.sli",
                    f"{voice_name}.opus",
                    f"{voice_name}.opus.sli",
                    f"{voice_name}.ini"
                ])
                            
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
                                                             
                                            elif type(text_item) == dict and "data" in text_item.keys():
                                                handle_data_block(text_item["data"])

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
    需要运行两次脚本
    """
    def from_base_stage(self, base_stage_filepath: str):
        with open(base_stage_filepath, mode="r", encoding="utf-16le") as f:
            base_stage: dict = json5.loads(parse_base_stage_to_json5(f.read()))
        prefixes = set()
        for key, value in base_stage.items():
            if type(value) == dict:
                if key == "times":
                    for time in base_stage["times"].values():
                        prefixes.add(time.get("prefix"))
                elif key != "stages":
                    prefixes.add(base_stage[key].get("prefix"))
        for stage in base_stage["stages"].values():
            image_file_string: str = stage["image"]
            for prefix in prefixes:
                if prefix is not None:
                    image_file = image_file_string.replace("TIME", prefix)
                    self.filename_plaintexts.add(f"{image_file}.png")
        return self

    """
    从cglist.csv文件中获取cg文件名evimage和sd
    需要运行两次脚本
    """
    def from_cglist_csv(self, cglist_csv_filepath: str):
        with open(cglist_csv_filepath, mode="r", encoding="utf-16le") as f:
            cglist_csv = csv.reader(f)
            for row in cglist_csv:
                header = row[0]
                if header.startswith("thum_"):
                    # assert len(header) == 10  # thum_EV101, thum_SD001
                    cg_name = header[5:]  # EV101, SD001
                    cg_type = cg_name[:2]  # EV, SD
                    match cg_type.lower():
                        case "ev":
                            self.filename_plaintexts.update((
                                f"{cg_name}a.pimg",
                                f"{cg_name}b.pimg",
                                f"{cg_name}mm.pimg",
                                f"{cg_name}a_censored.pimg",
                                f"{cg_name}b_censored.pimg",
                                f"{cg_name}mm_censored.pimg",
                                f"{cg_name}_a.pimg",
                                f"{cg_name}_b.pimg",
                                f"{cg_name}_mm.pimg",
                                f"{cg_name}_a_censored.pimg",
                                f"{cg_name}_b_censored.pimg",
                                f"{cg_name}_mm_censored.pimg",
                                f"thum_{cg_name}.jpg",
                                f"thum_{cg_name}.png",
                                f"thum_{cg_name}_censored.jpg",
                                f"thum_{cg_name}_censored.png",
                                f"savethum_{cg_name}.jpg",
                                f"savethum_{cg_name}.png"
                            ))
                        case "sd":
                            self.filename_plaintexts.update((
                                f"{cg_name}.mtn",
                                f"{cg_name}.psb",
                                f"thum_{cg_name}.jpg",
                                f"thum_{cg_name}.png"
                            ))
                            for cg_diff in row[2:]:
                                cg_diff = cg_diff.strip()
                                self.filename_plaintexts.update((
                                    f"{cg_diff}.jpg",
                                    f"{cg_diff}.png",
                                    f"{cg_diff}.asd",
                                ))
        return self

    """
    从soundlist.csv文件中获取bgm文件名
    需要运行两次脚本
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

if __name__ == "__main__":
    for root, dirs, files in os.walk(config.temp_dir):
        for d in dirs:
            shutil.rmtree(os.path.join(config.temp_dir, d))
