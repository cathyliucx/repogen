#!/bin/bash
# start_80b_thinking_8gpu.sh

MODEL_PATH="/home/sanyaxueyuan/liuchenxi/models/models-Qwen-Qwen3-Next-80B-A3B-Thinking"

export CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7

python3 -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_PATH" \
    --served-model-name "qwen3-80b-thinking" \
    --tensor-parallel-size 8 \
    --port 8001 \
    --dtype bfloat16 \
    --max-model-len 32768 \
    --gpu-memory-utilization 0.7 \
    --enable-chunked-prefill \
    --trust-remote-code