"""Optional full YOLO26n numerical validation with tinygrad; no Torch or ORT."""
import json
import os
from pathlib import Path
import subprocess
import time

import numpy as np
import onnx
from PIL import Image, ImageOps
from tinygrad import Tensor
from tinygrad.nn.onnx import OnnxRunner

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT/'build/flex/vision'


def main():
    model = onnx.load(ASSETS/'yolo26n.onnx')
    target = '/model.23/Concat_3_output_0'
    needed = {target}
    nodes = []
    for node in reversed(model.graph.node):
        if needed.intersection(node.output):
            nodes.append(node)
            needed.update(node.input)
    del model.graph.node[:]
    model.graph.node.extend(reversed(nodes))
    weights = [tensor for tensor in model.graph.initializer if tensor.name in needed]
    del model.graph.initializer[:]
    model.graph.initializer.extend(weights)
    del model.graph.output[:]
    model.graph.output.append(onnx.helper.make_tensor_value_info(target,onnx.TensorProto.FLOAT,[1,84,8400]))
    reference_path = ASSETS/'tinygrad-reference.onnx'
    onnx.save(model,reference_path)
    runner = OnnxRunner(str(reference_path))
    bus = Image.open(ASSETS/'bus.jpg').convert('RGB')
    report = []
    for name, image in [('bus',bus),('flipped',ImageOps.mirror(bus)),('blank',Image.new('RGB',(320,240)))]:
        source = ASSETS/(name+'-validation.png')
        image.save(source)
        result_path, input_path, raw_path = (ASSETS/(name+suffix) for suffix in ('.json','-input.bin','-raw.bin'))
        command = [str(ROOT/'build/flex/puppybot-vision'),'--model',str(ASSETS/'yolo26n/model.json'),
                   '--image',str(source),'--kernel',str(ROOT/'build/flex/vision-kernel.hip'),
                   '--output',str(result_path),'--input-tensor',str(input_path),'--raw-output',str(raw_path)]
        subprocess.run(command,cwd=ROOT,check=True,capture_output=True,timeout=30)
        x = np.fromfile(input_path,'<f4').reshape(1,3,640,640)
        start = time.monotonic()
        expected = next(iter(runner({'images':Tensor(x,device='CPU')}).values())).numpy()
        actual = np.fromfile(raw_path,'<f4').reshape(expected.shape)
        assert np.isfinite(actual).all()
        np.testing.assert_allclose(actual[:,:4],expected[:,:4],atol=.003,rtol=3e-5)
        np.testing.assert_allclose(actual[:,4:],expected[:,4:],atol=3e-5,rtol=3e-4)
        result = json.loads(result_path.read_text())
        assert result['runtime'] == 'pup' and result['backend'] == 'hip'
        assert result['frame']['width'] == image.width and result['frame']['height'] == image.height
        scores = expected[0,4:]
        indices = np.argsort(-scores.ravel(),kind='stable')[:300]
        indices = [index for index in indices if scores.ravel()[index] >= .25]
        scale = min(640/image.width,640/image.height)
        left, top = (640-round(image.width*scale))//2,(640-round(image.height*scale))//2
        expected_detections = []
        for index in indices:
            cls, anchor = divmod(int(index),8400)
            box = (expected[0,:4,anchor]-[left,top,left,top])/scale
            box = np.clip(box,0,[image.width,image.height,image.width,image.height])
            if box[2] > box[0] and box[3] > box[1]:
                expected_detections.append((cls,scores.ravel()[index],box))
        assert len(result['detections']) == len(expected_detections)
        for detection, (cls, score, box) in zip(result['detections'],expected_detections):
            assert detection['classId'] == cls
            np.testing.assert_allclose(detection['confidence'],score,atol=1e-5)
            np.testing.assert_allclose(detection['box'],box,atol=.01,rtol=3e-5)
        if name == 'bus':
            assert {'bus','person'} <= {d['label'] for d in result['detections']}
        if name == 'blank':
            assert not result['detections']
        report.append(dict(case=name,comparedElements=actual.size,
                           boxMaxAbsoluteError=float(abs(actual[:,:4]-expected[:,:4]).max()),
                           scoreMaxAbsoluteError=float(abs(actual[:,4:]-expected[:,4:]).max()),
                           detections=len(result['detections']),tinygradSeconds=time.monotonic()-start))
    (ASSETS/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    print('Native Pup YOLO: 2,116,800 outputs and final boxes match independent tinygrad; positive/flipped/negative images pass')


if __name__ == '__main__':
    os.environ.setdefault('DEV','CPU')
    main()
