import toml

# 读取版本号文件
with open("version.txt", "r") as f:
    version = f.read().strip()

# 更新 Cargo.toml
cargo = toml.load("Cargo.toml")
cargo['package']['version'] = version
with open("Cargo.toml", "w") as f:
    toml.dump(cargo, f)

# 更新 pyproject.toml
pyproject = toml.load("pyproject.toml")
pyproject['package']['version'] = version  # 这里改为访问 package
with open("pyproject.toml", "w") as f:
    toml.dump(pyproject, f)
