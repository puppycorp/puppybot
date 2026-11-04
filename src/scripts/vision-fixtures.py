#!/usr/bin/env python3
"""Build an ignored, repeatable browser camera fixture from the sample image."""
from pathlib import Path

import numpy as np
from PIL import Image

assets = Path(__file__).resolve().parents[2]/'build/flex/vision'
image = Image.open(assets/'bus.jpg').convert('RGB')
image.thumbnail((640,480))
frame = Image.new('RGB',(640,480))
frame.paste(image,((640-image.width)//2,(480-image.height)//2))
frame.save(assets/'live-test.jpg',quality=70)
yuv = np.asarray(frame.convert('YCbCr'))
y = yuv[:,:,0].tobytes()
u,v = (np.asarray(Image.fromarray(yuv[:,:,c]).resize((320,240),Image.Resampling.BOX)).tobytes() for c in (1,2))
with (assets/'camera.y4m').open('wb') as output:
    output.write(b'YUV4MPEG2 W640 H480 F10:1 Ip A1:1 C420jpeg\n')
    for _ in range(30):
        output.write(b'FRAME\n'+y+u+v)
