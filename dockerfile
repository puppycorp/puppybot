# syntax=docker/dockerfile:1

FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    bash \
    sudo \
    curl \
    git \
    wget \
    unzip \
    openjdk-17-jdk \
    python3 \
    python3-pip \
    python3-venv \
    cmake \
    ninja-build \
    ccache \
    libffi-dev \
    libssl-dev \
    dfu-util \
    libusb-1.0-0 \
    flex \
    bison \
    gperf \
    clang-format \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://bun.sh/install | bash && \
    ln -sf /root/.bun/bin/bun /usr/local/bin/bun

ENV PATH="/root/.bun/bin:${PATH}"

WORKDIR /workspace

COPY . .

ENV ANDROID_HOME="" \
    ANDROID_SDK_ROOT=""

RUN chmod +x prepare-agent.sh
RUN ./prepare-agent.sh
