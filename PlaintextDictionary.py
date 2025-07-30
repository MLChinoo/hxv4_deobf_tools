import os

from utils.check_hash import is_path_hash, is_name_hash

class PlaintextDictionary:
    pathname_plaintexts, filename_plaintexts = [], []

    def __init__(self, pathnames: list | tuple = (), filenames: list | tuple = ()):
        self.pathname_plaintexts.extend(pathnames)
        self.filename_plaintexts.extend(filenames)

    """
    从已有的目录名和文件名提取filename和pathname
    此来源generator多用于从同游戏的体验版或加密较弱的初始发行版的明文目录结构获取明文信息
    """
    def from_unobfuscated_directory(self, base_dir):
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
                    self.pathname_plaintexts.append(full_path)
                else:
                    break

            for i in range(len(levels)):
                suffix_levels = levels[i:]
                if all(not is_path_hash(l) for l in suffix_levels):
                    self.pathname_plaintexts.append("/".join(suffix_levels) + "/")

            for file in files:
                if not is_name_hash(file.split(".")[0]):
                    self.filename_plaintexts.append(file)

        return self

if __name__ == "__main__":
    pass
