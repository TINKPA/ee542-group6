#!/usr/bin/env python3
"""EE542 Lab 8 Step 2.2: build a TensorRT engine from an ONNX file, with an
optimization profile covering batch sizes 1 to 32 (optimized for 8).

  python3 build_engine.py resnet18_fp32.onnx resnet18_fp32.engine
  python3 build_engine.py resnet18_fp16.onnx resnet18_fp16.engine

Precision comes from the ONNX file itself (strongly typed network): no
BuilderFlag.FP16. TF32 stays at its default (on), as the handout notes.
"""
import argparse
import sys
import tensorrt as trt

MIN, OPT, MAX = 1, 8, 32


def create_network(builder):
    # TensorRT 11: create_network() takes no flags and is always strongly typed.
    # TensorRT 10 still accepts a flags int; ask for STRONGLY_TYPED there so both
    # versions honour the ONNX dtypes the same way.
    if int(trt.__version__.split(".")[0]) >= 11:
        return builder.create_network()
    return builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.STRONGLY_TYPED))


def build(onnx_path, engine_path, workspace_gb=4, opt=OPT):
    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    network = create_network(builder)
    parser = trt.OnnxParser(network, logger)
    if not parser.parse_from_file(onnx_path):
        for i in range(parser.num_errors):
            print(parser.get_error(i), file=sys.stderr)
        sys.exit(f"failed to parse {onnx_path}")
    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, workspace_gb << 30)

    # The TODO from the handout: one profile, batch 1..32, tuned for 8.
    profile = builder.create_optimization_profile()
    inp = network.get_input(0)
    c, h, w = inp.shape[1:]
    profile.set_shape(inp.name, (MIN, c, h, w), (opt, c, h, w), (MAX, c, h, w))
    config.add_optimization_profile(profile)

    print(f"input {inp.name} {inp.shape} {inp.dtype}; "
          f"output {network.get_output(0).name} {network.get_output(0).dtype}")
    engine = builder.build_serialized_network(network, config)
    if engine is None:
        sys.exit("engine build failed")
    with open(engine_path, "wb") as f:
        f.write(engine)
    print(f"wrote {engine_path} ({engine.nbytes / 1e6:.1f} MB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("onnx")
    ap.add_argument("engine")
    ap.add_argument("--opt", type=int, default=OPT, help="batch size the profile is tuned for")
    a = ap.parse_args()
    build(a.onnx, a.engine, opt=a.opt)
