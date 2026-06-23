ARG APP_IMAGE=continuumio/miniconda3
FROM ${APP_IMAGE}
ARG APP_IMAGE
ENV PATH="/root/miniconda3/bin:${PATH}"

RUN if [ "$APP_IMAGE" = "nvidia/cuda:12.0.0-devel-ubuntu22.04" ]; then \
    echo "Using CUDA image" && \
    apt-get update && \
    apt-get install -y unzip sudo git g++ libglm-dev libglew-dev libglfw3-dev libgles2-mesa-dev zlib1g-dev wget cmake vim libxi6 libgconf-2-4 && \
    wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh && \
    mkdir /root/.conda && \
    bash Miniconda3-latest-Linux-x86_64.sh -b && \
    rm -f Miniconda3-latest-Linux-x86_64.sh && \
    apt-get install -y libxkbcommon-x11-0; \
else \
    echo "Using Conda image" && \
    apt-get update -yq && \
    apt-get install -yq cmake g++ libgconf-2-4 libgles2-mesa-dev libglew-dev libglfw3-dev libglm-dev libxi6 sudo unzip vim zlib1g-dev && \
    apt-get install -y libxkbcommon-x11-0; \
fi

# ========== 清理频道配置 ==========
RUN conda config --remove-key channels && \
    conda config --add channels conda-forge && \
    conda config --set channel_priority strict

# ========== 接受 Anaconda TOS（双重保险） ==========
RUN conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r || true

RUN mkdir /opt/infinigen
WORKDIR /opt/infinigen
COPY . .

# ========== 修改点：创建环境时包含 pip ==========
RUN conda create -c conda-forge --name infinigen python=3.11 pip -y && \
    /root/miniconda3/envs/infinigen/bin/python -m pip install -e ".[dev]"
