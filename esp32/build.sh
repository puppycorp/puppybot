#!/bin/bash
set -a
source .env
set +a

idf.py -DPROJECT_VER="3" build
idf.py flash monitor