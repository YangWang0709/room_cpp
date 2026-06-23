# Infinigen 环境配置踩坑记录

> 环境信息：Ubuntu Linux x86_64, Conda, Python 3.11, Infinigen v1.19.1
>
> 配置日期：2025-06-15

---

## 1. GitHub 网络连接超时

### 问题描述

执行 `git submodule update --init --recursive` 时，GitHub 连接超时：

```
fatal: 无法访问 'https://github.com/princeton-vl/OcMesher.git/'：
Failed to connect to github.com port 443 after 135794 ms: 连接超时
```

### 原因

国内网络无法直连 GitHub，需要配置代理。

### 解决方法

1. **检测本地代理端口**：通过 `ss -tlnp` 查找 Clash Verge 代理端口（本机为 `7897`）
2. **配置 git 代理**：

```bash
git config --global http.proxy http://127.0.0.1:7897
git config --global https.proxy http://127.0.0.1:7897
```

3. **验证连通性**：

```bash
git ls-remote https://github.com/princeton-vl/OcMesher.git HEAD
```

> **注意**：配置完成后如不再需要，记得清除代理：
> ```bash
> git config --global --unset http.proxy
> git config --global --unset https.proxy
> ```

---

## 2. pip 下载超时 / PyPI 无法访问

### 问题描述

`pip install` 时出现 `ReadTimeoutError`，无法从 pypi.org 下载包。

### 解决方法

为 pip 配置代理：

```bash
pip config set global.proxy http://127.0.0.1:7897
```

> **清除**：`pip config unset global.proxy`

---

## 3. Git Submodule 克隆不完整

### 问题描述

使用第三方镜像（如 ghproxy.com、gitclone.com）克隆 submodule 时，部分仓库克隆为空仓库或内容不完整，导致后续编译失败：

```
fatal error: ../../../../infinigen_gpl/bnodes/utils/nodes_util.h: No such file or directory
```

### 原因

- 镜像站点不稳定，部分仓库返回 502 或克隆为空
- 之前用镜像克隆的 `infinigen_gpl` 目录文件被标记为 deleted（staged deletion）

### 解决方法

1. **恢复被删除的 submodule 文件**：

```bash
cd infinigen/infinigen_gpl
git restore --staged .
git restore .
```

2. **清理损坏的 submodule 目录后重新克隆**：

```bash
rm -rf infinigen/OcMesher
git submodule update --init infinigen/OcMesher
```

3. **务必使用代理直连 GitHub**，不要使用第三方镜像

---

## 4. scikit-learn<1.4.0 在 Python 3.11 上安装失败

### 问题描述

```
ERROR: Could not find a version that satisfies the requirement scikit-learn<1.4.0
```

### 原因

pip 因网络超时无法获取 PyPI 版本列表，误以为没有兼容版本。实际上 scikit-learn 1.3.2 支持 Python 3.11。

### 解决方法

先通过 conda 安装需要编译的科学计算包，避免 pip 从源码编译：

```bash
conda install -n infinigen -c conda-forge scikit-learn=1.3 scikit-image=0.19 numpy=1.26 matplotlib pandas scipy -y
```

然后再用 pip 安装 infinigen，此时这些包已存在，pip 会跳过。

---

## 5. setuptools 82 移除 pkg_resources 导致 landlab 报错

### 问题描述

```
ModuleNotFoundError: No module named 'pkg_resources'
```

### 原因

conda 创建的 Python 3.11 环境默认安装 setuptools 82.x，该版本移除了 `pkg_resources` 模块。而 landlab 2.6.0 依赖 `pkg_resources`。

### 解决方法

降级 setuptools：

```bash
pip install "setuptools<70"
```

---

## 6. libstdc++ 版本冲突

### 问题描述

```
ImportError: /lib/x86_64-linux-gnu/libstdc++.so.6: version `CXXABI_1.3.15' not found
```

### 原因

conda 环境中的 matplotlib 等包需要较新的 libstdc++，但系统默认的 `/lib/x86_64-linux-gnu/libstdc++.so.6` 版本太旧。Python 优先加载了系统库而非 conda 环境中的库。

### 解决方法

设置 `LD_LIBRARY_PATH` 让 conda 环境的库优先加载。在 conda 环境的激活脚本中自动配置：

```bash
mkdir -p $CONDA_PREFIX/etc/conda/activate.d
cat > $CONDA_PREFIX/etc/conda/activate.d/env_vars.sh << 'EOF'
#!/bin/sh
export C_INCLUDE_PATH=$CONDA_PREFIX/include:${C_INCLUDE_PATH:-}
export CPLUS_INCLUDE_PATH=$CONDA_PREFIX/include:${CPLUS_INCLUDE_PATH:-}
export LIBRARY_PATH=$CONDA_PREFIX/lib:${LIBRARY_PATH:-}
export LD_LIBRARY_PATH=$CONDA_PREFIX/lib:${LD_LIBRARY_PATH:-}
export QT_PLUGIN_PATH=$CONDA_PREFIX/lib/qt6/plugins
EOF
chmod +x $CONDA_PREFIX/etc/conda/activate.d/env_vars.sh
```

---

## 7. OpenCV Qt 插件崩溃

### 问题描述

运行室内场景生成时，程序在 `solve_medium` 阶段崩溃：

```
qt.qpa.plugin: Could not find the Qt platform plugin "offscreen" in ""
This application failed to start because no Qt platform plugin could be initialized.
已中止 (核心已转储)
```

### 原因

1. `opencv-python`（非 headless 版本）内置了 Qt 依赖，会尝试初始化 Qt GUI
2. conda 环境中安装了 Qt6，但 Qt 插件路径未配置，导致找不到 `libqoffscreen.so`

### 解决方法

**步骤一**：替换为 headless 版本的 OpenCV：

```bash
pip uninstall opencv-python opencv-python-headless -y
pip install opencv-python-headless==4.8.1.78
```

**步骤二**：配置 Qt 插件路径（已在 activate.d/env_vars.sh 中配置）：

```bash
export QT_PLUGIN_PATH=$CONDA_PREFIX/lib/qt6/plugins
```

> **重要**：`opencv-python-headless` 不含 Qt/GUI 功能，适合服务器和无头环境运行。如果需要 OpenCV 的 GUI 功能（如 `cv2.imshow`），则需保留 `opencv-python` 并正确配置 `QT_PLUGIN_PATH`。

---

## 8. 正确的命令行入口

### 问题描述

```
python -m infinigen.infinigen_generate --help
# No module named infinigen.infinigen_generate
```

### 原因

Infinigen 的命令行入口不在 `infinigen.infinigen_generate`，而是在 `infinigen_examples` 包下。

### 解决方法

| 功能 | 命令 |
|------|------|
| 室内场景生成 | `python -m infinigen_examples.generate_indoors` |
| 自然场景生成 | `python -m infinigen_examples.generate_nature` |
| 单独资产生成 | `python -m infinigen_examples.generate_individual_assets` |

---

## 完整安装流程（最终版）

```bash
# 1. 创建 conda 环境
conda create --name infinigen python=3.11 -y
conda activate infinigen

# 2. 安装系统依赖（conda 方式，无需 sudo）
conda install -n infinigen conda-forge::gxx=11.4.0 mesalib glew glm menpo::glfw3 -y

# 3. 配置代理（如需要）
git config --global http.proxy http://127.0.0.1:7897
git config --global https.proxy http://127.0.0.1:7897
pip config set global.proxy http://127.0.0.1:7897

# 4. 初始化 submodule
cd /path/to/infinigen
git submodule update --init --recursive

# 5. 用 conda 预装科学计算包（避免 pip 源码编译）
conda install -n infinigen -c conda-forge scikit-learn=1.3 scikit-image=0.19 numpy=1.26 matplotlib pandas scipy -y

# 6. 降级 setuptools（landlab 兼容性）
pip install "setuptools<70"

# 7. 安装 infinigen（Full install with terrain & vis）
pip install -e ".[terrain,vis]"

# 8. 替换 OpenCV 为 headless 版本
pip uninstall opencv-python opencv-python-headless -y
pip install opencv-python-headless==4.8.1.78

# 9. 配置环境变量自动激活脚本
mkdir -p $CONDA_PREFIX/etc/conda/activate.d
cat > $CONDA_PREFIX/etc/conda/activate.d/env_vars.sh << 'ENVEOF'
#!/bin/sh
export C_INCLUDE_PATH=$CONDA_PREFIX/include:${C_INCLUDE_PATH:-}
export CPLUS_INCLUDE_PATH=$CONDA_PREFIX/include:${CPLUS_INCLUDE_PATH:-}
export LIBRARY_PATH=$CONDA_PREFIX/lib:${LIBRARY_PATH:-}
export LD_LIBRARY_PATH=$CONDA_PREFIX/lib:${LD_LIBRARY_PATH:-}
export QT_PLUGIN_PATH=$CONDA_PREFIX/lib/qt6/plugins
ENVEOF
chmod +x $CONDA_PREFIX/etc/conda/activate.d/env_vars.sh

# 10. 运行 Hello Room Demo
python -m infinigen_examples.generate_indoors \
    --seed 0 --task coarse \
    --output_folder outputs/indoors/coarse \
    -g fast_solve.gin singleroom.gin \
    -p compose_indoors.terrain_enabled=False \
    restrict_solving.restrict_parent_rooms=\[\"DiningRoom\"\]
```

---

## 运行结果

Hello Room Demo 成功运行，生成了 DiningRoom 场景：

```
outputs/indoors/coarse/
├── assets/              # 生成的资产文件
├── MaskTag.json         # 掩码标签
├── optim_records.csv    # 优化记录
├── optim_records.png    # 优化过程可视化
├── pipeline_coarse.csv  # 流水线配置
├── polycounts.txt       # 多边形统计
├── scene.blend          # Blender 场景文件 (347MB)
├── solve_state.json     # 求解器状态
└── version.txt          # 版本信息
```

总耗时约 10 分钟 50 秒（CPU: solve_rooms 4s + solve_large 3m45s + solve_medium 2m36s + populate_assets 2m + 其他）。
