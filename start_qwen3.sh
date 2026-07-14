docker run --rm -it --gpus all \
  -e VLLM_ATTENTION_BACKEND=FLASHINFER \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -p 127.0.0.1:8086:8086 --ipc=host \
  vllm/vllm-openai:v0.11.0 \
  --host 0.0.0.0 --port 8086 \
  --model cyankiwi/Qwen3-30B-A3B-Thinking-2507-AWQ-4bit \
  --gpu-memory-utilization 0.82 \
  --reasoning-parser deepseek_r1 \
  --max_model_len 65536 \
  --dtype float16 \
  --kv_cache_dtype fp8_e4m3
