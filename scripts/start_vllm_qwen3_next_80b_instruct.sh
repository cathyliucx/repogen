#!/bin/bash
# start_80b_instruct_8gpu.sh

MODEL_PATH="/vol/models/Qwen/models-Qwen-Qwen3-Next-80B-A3B-Instruct/"

# 指定 8 张卡
export CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7

python3 -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_PATH" \
    --served-model-name "my-model" \
    --tensor-parallel-size 8 \
    --port 8000 \
    --dtype bfloat16 \
    --max-model-len 32768 \
    --gpu-memory-utilization 0.70 \
    --trust-remote-code