import toml

# 读取 version.txt
with open("version.txt", "r") as f:
    version = f.read().strip()

# 更新 Cargo.toml 中的 [package].version
cargo = toml.load("Cargo.toml")
cargo['package']['version'] = version
with open("Cargo.toml", "w") as f:
    toml.dump(cargo, f)

# 更新 pyproject.toml 中的 [project].version
pyproject = toml.load("pyproject.toml")
pyproject['project']['version'] = version  # ✅ 改这里
with open("pyproject.toml", "w") as f:
    toml.dump(pyproject, f)
