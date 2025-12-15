# Using AI voice generation

GEX as of m76T130 supports AI text to speech generation using a local LLM model via the Coqui-AI open source local model AI tool.

## How does it work?

The core TTS support in GremlinEx is based on the windows API built-in text to speech API which is a legacy system.  It has the advantage of generating sound in real time, however the sound quality is limited, as is the choice of voices.

The new AI model supported by GEX via the Open Source Coqui TTS (called here KTTS) runs locally.  KTTS supports different accent and languages and a more natural sounding voice generated from text.  It does not require a license for non-commercial use and importantly compared to other LLM models out there, does not require an account or a subscription nor the purchase of tokens. 

The caveat is this model is not real time, which is not a problem if text doesn't change, which in most cases it does not. GEX will cache the generated audio files, will facilitate the creation of these files, and manage the cache.  

The conversion is performed once, but will require some manual management as for example.

## Installation

1. Install Python 3.13.x
2. Install pytorch with CUDA enabled if you have an Nvidia GPU (note that this is recommended for speed of processing).  If you do not have an NVidia GPU, the CPU model will be used.  Follow the instructions on the Pytorch website https://pytorch.org/
3. Ensure you have the Nvidia CUDA toolkit installed for the CUDA version of Pytorch used.  Nvidia CUDA toolkit will likely have more recent versions than that supported by PyTorch - ensure you use the one matching the Pytorch install. https://developer.nvidia.com/cuda-downloads
4. Install coqui-tts (pip install coqui-tts)
5. Install rubberband command line interface (CLI) (download the "Rubber Band Library v4.0.0 command-line utility" from https://breakfastquay.com/rubberband/.  Install and add to windows PATH.
6. Install pyrubberband (pip install pyrubberband)


Generating AI audio files from text requires steps 1 to 4.
Resampling (changing the playback speed) requires rubberband steps 5 and 6.

