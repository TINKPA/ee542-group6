#!/usr/bin/env python3
"""EE542 Lab 8 Step 2.1: export torchvision ResNet-18 to ONNX in FP32 and FP16,
with a dynamic batch dimension.

  python3 export_onnx.py            -> resnet18_fp32.onnx(.data), resnet18_fp16.onnx(.data)

The FP16 file is exported from model.half() with a half-precision example input,
so every weight and activation in the graph is float16. TensorRT 11 builds
strongly typed networks, so this FP16 graph is what yields the FP16 engine.
"""
import argparse
import torch
import torchvision


def export(model, dtype, path):
    m = model.to(dtype)
    x = torch.randn(1, 3, 224, 224, device="cuda", dtype=dtype)
    torch.onnx.export(
        m, x, path,
        input_names=["input"], output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=18)
    print(f"wrote {path} ({dtype})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=".")
    a = ap.parse_args()
    model = torchvision.models.resnet18(weights="DEFAULT").eval().cuda()
    with torch.no_grad():
        export(model, torch.float32, f"{a.out_dir}/resnet18_fp32.onnx")
        export(model, torch.float16, f"{a.out_dir}/resnet18_fp16.onnx")


if __name__ == "__main__":
    main()
