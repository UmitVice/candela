# 0601 — Candela Spark quantisation-aware training and int4 export

- Status: accepted
- Date: 2026-10-23

## Context

The owner wants Spark trained "knowing it will run in Q4", so that int4 is its native format with no quality loss. MLX's 4-bit export is affine: per group of 32 values in a row, `w ≈ scale · q + bias`, with `q ∈ [0, 15]` and scale and bias stored in the model dtype. llama.cpp's Q4_1 is the same formula (`d · q + m`, blocks of 32, fp16 `d` and `m`). Q4_0 is symmetric (`d · (q − 8)`) with no offset.

## Decision

- **Fake quantisation on the export grid**: every block linear weight (q, k, v, o, gate, up, down) and the tied embedding/LM head pass through `mx.dequantize(mx.quantize(w.astype(bf16), group_size=32, bits=4))` in the forward pass. The forward pass is therefore bit-for-bit the grid that `mx.quantize` writes at export, with no reimplementation that could drift.
- **Straight-through estimator**: `w_q = w + stop_gradient(grid(w) − w)`. The gradient goes to the fp32 master weights unchanged. Min–max groups never clip, so a clipped STE would add nothing.
- **Coverage**: everything that is a matrix, including the tied embedding and head (12.6M of the 35M parameters), is int4 with group 32. Norm gains stay in bf16, as in every MLX and llama.cpp 4-bit model. All weights are int4 because Q4_1 maps exactly. An int8 embedding (MLX affine 8-bit) has no exact GGUF equivalent (Q8_0 is symmetric), so it would break the "same model in every runtime" property for a few hundred KB of savings.
- **Schedule**: QAT is on from step 0, with no bf16 warm-up. The whole trajectory is int4-aware, the overhead is under 2 % at this size (31.8k vs 32.6k tokens/s), and nothing then has to adapt mid-run.
- **Monitoring**: every validation pass reports per-source loss for the bf16 master weights (fake-quant off) and for the int4 forward pass, plus their relative gap. The release gate is a gap under 1 %.
- **Export**: `spark export` writes:
  1. MLX int4: packed `uint32` weights with bf16 scales and biases, produced by `mx.quantize` on the same bf16 cast. This is the primary artifact.
  2. bf16 reference weights.
  3. GGUF Q4_1 for llama.cpp under architecture `gemma3`: MLX nibbles are repacked into Q4_1 blocks, scale and bias go to fp16, norm gains are stored as `1 + w`. Exporting bf16 scales as fp16 is exact for normal fp16 values; the exporter reports the maximum deviation.

  The exporter reloads the int4 MLX export, runs it through `mx.quantized_matmul`, and checks that its logits match the QAT forward pass within bf16 tolerance.
- **No GGUF Q4_0**: it has no offset, so MLX's affine grid cannot be expressed in it without requantising, which would discard what QAT learned. Q4_1 is exact at about 5.0 bits per weight against Q4_0's 4.5.

## Consequences

- The int4 model is the trained model; the bf16 master weights become the derived artifact and serve as a reference.
- Inference everywhere (MLX, llama.cpp, and later the browser) uses the same 4-bit numbers.
- If MLX changes its quantisation rounding, an older QAT run would no longer match newer exports exactly. The exporter's logits check would catch it, and the MLX pin prevents it.

## Alternatives considered

- Post-training quantisation: rejected by the owner and lossy at small sizes.
- Learned scales (LSQ/PACT): would not match MLX's min–max grid, so a second quantisation step would be needed at export.
- Symmetric int4 (Q4_0/MXFP4) QAT: possible, but MLX's default 4-bit path, and with it the mlx-community ecosystem, is affine.
- BitNet/ternary: research-heavy, and no int4 runtime path.
