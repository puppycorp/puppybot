#!/usr/bin/env python3
"""Import a static YOLO26 export into Pup and a named FP32 checkpoint.

ONNX is a preparation dependency only. No Torch or inference runtime is used.
Unsupported operators/attributes fail rather than silently changing the model.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
import onnx
from onnx import helper, numpy_helper


def convert(source, output, model_path=None):
    model = onnx.shape_inference.infer_shapes(onnx.load(source))
    shapes = {v.name: [d.dim_value for d in v.type.tensor_type.shape.dim]
              for v in [*model.graph.input, *model.graph.value_info, *model.graph.output]}
    constants = {v.name: numpy_helper.to_array(v) for v in model.graph.initializer}
    for node in model.graph.node:
        if node.op_type == 'Constant':
            constants[node.output[0]] = numpy_helper.to_array(helper.get_attribute_value(node.attribute[0]))
    target = '/model.23/Concat_3_output_0'
    if shapes.get(target) != [1, 84, 8400] or shapes.get('images') != [1, 3, 640, 640]:
        raise ValueError('Expected the official static YOLO26n 640 FP32 detection export')
    needed = {target}
    for node in reversed(model.graph.node):
        if needed.intersection(node.output):
            needed.update(node.input)
    lines = ['# YOLO26n, imported from the official v8.4.0 ONNX release.',
             '# Backbone, attention, multi-scale head and box decoding execute in Pup.',
             '# The host selects the final top 300 class/anchor scores (no NMS).',
             'images = input("images",[1,3,640,640])']
    names = {'images': 'images'}
    weights = {}
    payload = bytearray()

    def weight(name, value):
        value = np.asarray(value, dtype='<f4')
        if not np.isfinite(value).all():
            raise ValueError('Nonfinite checkpoint tensor')
        if name not in weights:
            weights[name] = dict(shape=list(value.shape), offset=len(payload), bytes=value.nbytes)
            payload.extend(value.tobytes())

    def ref(name):
        if name not in names:
            value = constants[name]
            var = f'v{len(names)}'
            names[name] = var
            key = f'constant.{var}'
            weight(key, value)
            lines.append(f'{var} = tensor({json.dumps(key)},{list(value.shape)})')
        return names[name]

    for node in model.graph.node:
        if not needed.intersection(node.output) or node.op_type == 'Constant':
            continue
        a = {v.name: helper.get_attribute_value(v) for v in node.attribute}
        op = node.op_type
        x = ref(node.input[0])
        expressions = []
        if op == 'Conv':
            w = constants[node.input[1]]
            k = list(w.shape[2:])
            s, p = a.get('strides', [1, 1]), a.get('pads', [0]*4)
            if k[0] != k[1] or s[0] != s[1] or len(set(p)) != 1 or a.get('dilations', [1, 1]) != [1, 1]:
                raise ValueError('Unsupported convolution geometry')
            key = node.input[1].removesuffix('.weight')
            weight(key+'.weight', w)
            bias = len(node.input) == 3
            if bias:
                weight(key+'.bias', constants[node.input[2]])
            expressions = [f'conv2d({x},{json.dumps(key)},{w.shape[0]},{k[0]},{s[0]},{p[0]},{int(bias)},{a.get("group",1)})']
        elif op in ('Add', 'Sub', 'Mul', 'Div'):
            symbol = dict(Add='+', Sub='-', Mul='*', Div='/')[op]
            expressions = [f'{x}{symbol}{ref(node.input[1])}']
        elif op == 'Sigmoid':
            expressions = [f'sigmoid({x})']
        elif op == 'Reshape':
            expressions = [f'reshape({x},{shapes[node.output[0]]})']
        elif op == 'Transpose':
            expressions = [f'permute({x},{a["perm"]})']
        elif op == 'MatMul':
            expressions = [f'batch_matmul({x},{ref(node.input[1])})']
        elif op == 'Softmax':
            expressions = [f'softmax({x},{a["axis"]})']
        elif op == 'MaxPool':
            k, s, p = a['kernel_shape'], a['strides'], a['pads']
            if k[0] != k[1] or s[0] != s[1] or len(set(p)) != 1 or a.get('ceil_mode', 0):
                raise ValueError('Unsupported pooling geometry')
            expressions = [f'maxpool2d({x},{k[0]},{s[0]},{p[0]})']
        elif op == 'Resize':
            scales = constants[node.input[2]].tolist()
            if scales != [1, 1, 2, 2] or a['mode'] != b'nearest' or a['coordinate_transformation_mode'] != b'asymmetric' or a['nearest_mode'] != b'floor':
                raise ValueError('Unsupported resize semantics')
            expressions = [f'upsample2d({x},2)']
        elif op == 'Concat':
            for i, other in enumerate(node.input[1:]):
                last = f'cat{len(names)}_{i}'
                lines.append(f'{last} = concat({x},{ref(other)},{a["axis"]})')
                x = last
            expressions = [x]
        elif op == 'Split':
            sizes = constants[node.input[1]].tolist()
            start = 0
            for size in sizes:
                expressions.append(f'slice({x},{a["axis"]},{start},{start+size})')
                start += size
        elif op == 'Slice':
            start, end, axes = (constants[n].tolist() for n in node.input[1:4])
            if len(start) != 1 or (len(node.input) > 4 and constants[node.input[4]].tolist() != [1]):
                raise ValueError('Only one-axis unit-step slices are supported')
            axis = axes[0]
            end = min(end[0], shapes[node.input[0]][axis])
            expressions = [f'slice({x},{axis},{start[0]},{end})']
        else:
            raise ValueError(f'Unsupported YOLO operation: {node.name} ({op})')
        if len(expressions) != len(node.output):
            raise ValueError('Operator output arity mismatch')
        for name, expression in zip(node.output, expressions):
            var = f'v{len(names)}'
            names[name] = var
            lines.append(f'{var} = {expression}')
    lines.append('output '+names[target])
    text = '\n'.join(lines)+'\n'
    output.mkdir(parents=True, exist_ok=True)
    path = model_path or output/'model.pup'
    path.write_text(text)
    # Fixed-size named tensor directory; native loading needs no ONNX parser.
    header = bytearray(struct.pack('<8sQQQ', b'PUPV0001', len(weights), 32+256*len(weights), len(payload)))
    for name, entry in weights.items():
        encoded = name.encode()
        if len(encoded) > 191 or len(entry['shape']) > 4:
            raise ValueError('Checkpoint tensor name/rank limit exceeded')
        dims = entry['shape']+[1]*(4-len(entry['shape']))
        header.extend(struct.pack('<192sQQQ4q8x', encoded, len(entry['shape']),
                                  entry['bytes']//4, entry['offset'], *dims))
    checkpoint = header+payload
    (output/'weights.bin').write_bytes(checkpoint)
    metadata = {p.key: p.value for p in model.metadata_props}
    labels = ast.literal_eval(metadata['names'])
    manifest = dict(schema='puppybot.detector.v1', id='yolo26n-coco', runtime='pup',
                    decoder='xyxy-class-scores', input=dict(width=640, height=640),
                    classes=[labels[i] for i in range(len(labels))], confidence=.25,
                    maxDetections=300, suppression='none', weights='weights.bin',
                    source='https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.onnx',
                    sourceSha256=hashlib.sha256(Path(source).read_bytes()).hexdigest(),
                    weightsSha256=hashlib.sha256(checkpoint).hexdigest(),
                    modelSha256=hashlib.sha256(text.encode()).hexdigest(), license=metadata['license'])
    (output/'model.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'Imported {len(weights)} named tensors, {len(payload)} bytes; {len(lines)} Pup lines')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--model', type=Path)
    args = parser.parse_args()
    convert(args.source, args.output, args.model)
