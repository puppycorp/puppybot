#!/bin/bash
set -a
source .env
set +a

idf.py -DPROJECT_VER="${VERSION:-1}" build
idf.py flash monitor