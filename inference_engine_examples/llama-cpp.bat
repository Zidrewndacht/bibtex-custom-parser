@echo off
:: The sample code below requires model to be previously downloaded to the specified folder
:: Sampple llama.cpp (Windows native) launch command for Qwen3-30B-A3B Q4, 4 parallel requests on a single RTX 5000 Ada (32GB VRAM)
:: llama-server --model "C:\llama.cpp\models\Qwen3-30B-A3B-Instruct-2507-UD-Q4_K_XL.gguf" --n-gpu-layers 99 --jinja --no-mmap --temp 0.6 --ctx_size 131072 -np 4 --alias Qwen30b-A3b-Q4 --cache-reuse 256 --reasoning-format deepseek

::  Sample llama.cpp (Windows native) launch command for Qwen3-30B-A3B Q6, 8 parallel requests on a pair of RTX 3090 (48GB total VRAM), where the GPU 1 also runs the monitors (so nas less VRAM available):
llama-server.exe --main-gpu 0 --model "Qwen3-30B-A3B-Thinking-2507-UD-Q6_K_XL.gguf" --tensor-split 57,43 --n-gpu-layers 99 --temp 0.6 --ctx-size 163840 --flash-attn on --no-mmap -np 8 --alias "Qwen30b-Thinking-Q6" --jinja --reasoning-format deepseek

pause
