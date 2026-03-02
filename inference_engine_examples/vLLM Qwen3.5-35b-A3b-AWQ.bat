@echo off
:: Sample vLLM (WSL Docker w/ enabled HW CUDA passthrough) launch command for Qwen3-30B-A3B 4bit-AWQ. Runs up to 256 parallel requests on a pair of RTX 3090 (48GB total VRAM)
:: This automatically downloads the model on the first load.
:: vLLM strongly recommended for ResearchParça initial classification/verification as it's optimized for heavy continuous batching. Tested >15x faster against llama.cpp (real world, in this very application)
:: Keep machine mostly unnattended during vLLM inference via WSL, or have a separate GPU/iGPU for display on the host, otherwise performance will go straight down to zero during interaction due to context shift between VM and host.
:: This is set up for headless (or iGPU display). Reduce --gpu-memory-utilization if the same GPU runs vLLM and a display.

:: tested with vLLM 0.16 nightly

:: 1.  Start Docker Desktop if it isn’t running yet
tasklist /FI "IMAGENAME eq Docker Desktop.exe" 2>NUL | find /I "Docker Desktop.exe" >NUL
if errorlevel 1 (
    echo Starting Docker Desktop ...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
)

:: 2.  Wait until the Linux engine answers
:wait_engine
echo Waiting for Docker engine ...
docker version >NUL 2>&1
if errorlevel 1 (
    timeout /t 3 >NUL
    goto :wait_engine
)

:: 3.  Run the container
:: --enforce-eager mode is required for at least v0.15.1 and newer in the tested hardware due to a ridiculous 200x throughput regression
:: -e VLLM_ATTENTION_BACKEND=FLASHINFER is deprecated, but it uses flashinfer by default in v0.16 anyway.
:: --max-num-batched-tokens 4096  required to allow for ENABLE_PREFIX_CACHING, otherwise disabled by default for Qwen3.5
:: --speculative-config "{\"method\":\"mtp\",\"num_speculative_tokens\":1}" massively reduces throughput () due to reduced context size.

docker run --rm -it --gpus all ^
  -e VLLM_SLEEP_WHEN_IDLE=1 ^
  -e ENABLE_PREFIX_CACHING=1 ^
  -e HF_HUB_OFFLINE=1 ^
  -v /mnt/host/d/AI/weights/vLLM/HuggingFaceCache:/root/.cache/huggingface ^
  -p 127.0.0.1:8086:8086 --ipc=host ^
  vllm/vllm-openai:nightly ^
  cyankiwi/Qwen3.5-35B-A3B-AWQ-4bit ^
  --host 0.0.0.0 --port 8086 ^
  --max-num-seqs 512 ^
  --max-num-batched-tokens 4096 ^
  --enable-prefix-caching ^
  --enable-expert-parallel ^
  --language-model-only ^
  --enforce-eager ^
  --tensor-parallel-size 2 ^
  --gpu-memory-utilization 0.93 ^
  --reasoning-parser qwen3 ^
  --max_model_len 81920 ^
  --disable-custom-all-reduce ^
  --kv_cache_dtype fp8_e4m3
  
pause

