# Using AI voice generation

GEX as of m76T130 supports AI text to speech generation using a local LLM model via the Coqui-AI open source local model AI tool.

GEX adds this functionality through the Play Sound action.

The complete set of files needed for this is some 3.5 to 4Gb of dependencies and data files, so this is not included (packaged) with the standard GEX installation.  It is also extremely difficult to package the AI model because some files are system dependent.  Some of the required tools, such as the Nvidia CUDA toolkit that allows the model to generate audio files extremely quickly over the CPU model, have licensing and terms that you must agree to that is different from the GEX licensing as well.  It is thus not possible to deliver the AI model functionality with GEX.

Consequently, the functionality is available, but GEX must run as a script from VSCode.

Running GEX as a script in VSCode is only needed to generate (or convert) TTS actions to Sound and generate audio from text using the AI model.   Once the files are generated and the profile saved, you do not need to run GEX in VSCode and it is not recommended.  You should use the regular .EXE as once the files are created, the AI model does not need to run.  This will also ensure that dependencies only used to generate audio files are not loaded, which will reduced the memory footprint used by GEX.



## How does it work?

The core TTS support in GremlinEx is based on the windows API built-in text to speech API which is a legacy system.  It has the advantage of generating sound in real time, however the sound quality is limited, as is the choice of voices.

The new AI model supported by GEX via the Open Source Coqui TTS (called here KTTS) runs locally.  KTTS supports different accent and languages and a more natural sounding voice generated from text.  It does not require a license for non-commercial use and importantly compared to other LLM models out there, does not require an account or a subscription nor the purchase of tokens. 

The caveat is this model is not real time, which is not a problem if text doesn't change, which in most cases it does not. GEX will cache the generated audio files, will facilitate the creation of these files, and manage the cache.  

The conversion is performed once, but will require some manual management as for example.

## Installation of the AI model


These instructions will get the LLM model installed locally on your system.  You will need approximately 4Gb of available disk space.

Some of these steps can be quite lengthy to execute as there are a significant number of downloads involved.

1. Install 64 bit Python 3.13.x.  The recommended folder is C:\Python\Python313 for easy access (the default folder is usually difficult to get to). The version should match the Python version used by GEX version (first line of the log file).

2. Install pytorch with CUDA enabled if you have an Nvidia GPU (note that this is recommended for speed of processing).  If you do not have an NVidia GPU, the CPU model will be used.  Follow the instructions on the Pytorch website:
 
```
https://pytorch.org/
```  

The easiest is to open a command line:

```
Windows Key + R to open a run window
type cmd and press the enter key to open the command line
```

At the command prompt, change to the python folder:
```
cd c:\python\python313
```
Run pip to install the correct version of torch - the link will be listed on the web site based on the version you have selected.  The example below we're installing Torch for CUDA 13.0.
```
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130
```

Keep the command window open.

3. Install the NVidia CUDA toolkit matching the exact version you selected in the PyTorch (in the example above, 13.0).  This has to match exactly or CUDA will not function in Torch. It is very likely that the Nvidia CUDA toolkit download page will have a more recent version than that supported by PyTorch.  However the installed version must match what PyTorch was compiled against. 
```
 https://developer.nvidia.com/cuda-downloads
```
4. Install coqui-tts.  Note the TTS below is case sensitive.

```
python -m pip install TTS
```
5. If you intend to change the rate of playback from the AI generated voice, you also need to install the rubberband command line interface (CLI).  Download the "Rubber Band Library v4.0.0 command-line utility" from:
```
https://breakfastquay.com/rubberband/.
```
Add the contents of the zip archive to a folder (example C:\Rubberband).
Add that path to the PATH environment variable in Windows.  This is needed or the next step will not find the Rubberband CLI at runtime from Python.

7. Install pyrubberband.
```
python -m pip install pyrubberband
```

![warning](assets/warning.png) Generating AI audio files from text requires steps 1 to 4.

![warning](assets/warning.png) Resampling (changing the playback speed from default) requires rubberband steps 5 and 6.

8. Install additional dependencies

```
python -m pip install pydub
python -m pip install soundfile

```

9. The following dependencies should be installed by the items above:  scipy, numba and a few others.


## Installation of GEX scripting environment

These instructions are to setup Visual Studio Code to run GEX as a script.  This is needed for the AI version to function.
Note: this is not a guide on how to use VSCode, is it only listing the steps needed.

![warning](assets/warning.png) It is assumed you already have VJOY and other tools installed as part as running GEX on your system.

1. Install the current version of 64 bit Visual Studio Code.  Recommend using the installer version. 

```
https://code.visualstudio.com/download
```

2. Add the Python development extensions to Visual Studio Code.

```
Python (by Microsoft)
Pylance (by Microsoft)
Python Debugger (by Microsoft)
Python Environments (by Microsoft)
Python Indent (by Kevin Rose)
```

3. Clone the GEX repository (recommend using Github desktop or Git command line tools).  [See instructions on GitHub](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository).  Recommend the cloning location to be C:\GEX-develop or something along those lines, not in a protected folder and not in a folder that is six levels deep as Windows often likes to find.  The reason is that path length does matter and you want GEX at a top level folder to eliminate long path issues in some compilation steps.

4. Open a command line window
```
Windows Key + R to open a run window
type cmd and press the enter key to open the command line
```

5. Install GEX Python dependencies.  The easiest is to use the requirements.txt file located where you cloned GEX to in the root folder.

```
python -m pip install -r c:\gex-develop\requirements.txt
```

6. In VSCode, open a folder, in our example:

```
C:\gex-development
```

Trust the folder contents to avoid being prompted all the time.

7. Run GEX by using the F5 key with debugging (helpful the first time in case some dependency or other issue exists) or Ctrl-F5 to run without the debugger.


This by no means is a guide on how to use VSCode.