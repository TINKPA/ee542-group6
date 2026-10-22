"""EE542 Lab 8 Step 2.3: run a TensorRT engine on buffers that already live in
GPU memory. No host copies: the caller passes a CUDA tensor in and gets a CUDA
tensor out. Shared by Part 2 (benchmark) and Part 5 (classify received images).
"""
import tensorrt as trt
import torch

_TRT2TORCH = {
    trt.DataType.FLOAT: torch.float32,
    trt.DataType.HALF: torch.float16,
    trt.DataType.INT32: torch.int32,
    trt.DataType.INT8: torch.int8,
    trt.DataType.BOOL: torch.bool,
}
_logger = trt.Logger(trt.Logger.WARNING)


class TrtRunner:
    def __init__(self, engine_path, in_name="input", out_name="logits"):
        self.runtime = trt.Runtime(_logger)
        with open(engine_path, "rb") as f:
            self.engine = self.runtime.deserialize_cuda_engine(f.read())
        self.ctx = self.engine.create_execution_context()
        self.in_name, self.out_name = in_name, out_name
        self.in_dtype = _TRT2TORCH[self.engine.get_tensor_dtype(in_name)]
        self.out_dtype = _TRT2TORCH[self.engine.get_tensor_dtype(out_name)]
        self._out = None

    def __call__(self, inp, stream=None):
        """inp: contiguous CUDA tensor (B,3,224,224) of self.in_dtype.
        Queues inference on `stream` (default: torch's current stream) and
        returns the output tensor. The caller synchronizes before reading it."""
        assert inp.is_cuda and inp.is_contiguous(), "input must be a contiguous CUDA tensor"
        assert inp.dtype == self.in_dtype, f"engine wants {self.in_dtype}, got {inp.dtype}"
        stream = stream or torch.cuda.current_stream()
        self.ctx.set_input_shape(self.in_name, tuple(inp.shape))
        out_shape = tuple(self.ctx.get_tensor_shape(self.out_name))
        if self._out is None or tuple(self._out.shape) != out_shape:
            self._out = torch.empty(out_shape, dtype=self.out_dtype, device="cuda")
        self.ctx.set_tensor_address(self.in_name, inp.data_ptr())
        self.ctx.set_tensor_address(self.out_name, self._out.data_ptr())
        # The input was produced on the same stream (or the caller synchronized),
        # so stream order guarantees it is ready before the engine reads it.
        if not self.ctx.execute_async_v3(stream.cuda_stream):
            raise RuntimeError("execute_async_v3 failed")
        return self._out
