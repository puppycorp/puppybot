#!/usr/bin/env python3
"""Start the unmodified stereo worker after a controlled host delay."""
import os
from pathlib import Path
import runpy
import sys
import time

delay, request, output = sys.argv[1:]
if delay not in ('0', '1'):
    raise ValueError('unexpected delay')
time.sleep(float(delay))
import cv2
cv2.ocl.setUseOpenCL(False)
if cv2.ocl.useOpenCL():
    raise RuntimeError('OpenCL is active')
worker = Path(__file__).resolve().parents[2] / 'flex/vision/discovery.py'
sys.argv = [str(worker), '--request', request, '--output', output]
runpy.run_path(str(worker), run_name='__main__')
