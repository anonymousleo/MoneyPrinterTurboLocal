# GPU Memory Management

The validated 8 GB CogVideoX profile uses:

- PyTorch 2.6.0 + CUDA 12.4 wheels
- CogVideoX1.5-5B
- TorchAO INT8
- CPU-side T5 prompt embedding generation
- T5 release before denoising
- sequential CPU offload
- VAE tiling/slicing where enabled by the worker
- 33 frames
- 20 inference steps

The local runtime should avoid keeping Ollama, Chatterbox, and CogVideoX
resident on the GPU simultaneously. MoneyPrinterTurbo-LocalAI's runtime
orchestration is responsible for handing GPU memory between stages.
