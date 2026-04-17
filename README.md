# Competitive Lst-40k Base: LUA scripts
Hutber Map Base LUA Scripts

This is a fork of the original hutber/ftc table, modified to remove any telemetry and some additional features.
This repo now contains the actual TTS JSON file.

## Compiling

- Requirements: PowerShell (Windows PowerShell or PowerShell Core `pwsh`) installed.
- Run from the `Compiler/` directory so relative paths to `..\TTSLUA` and `..\TTSJSON` resolve.

Examples:

To run the compiler via python run this from the Compiler folder
python3 compile.py --test 

- Windows PowerShell:

  ```powershell
  cd Compiler
  powershell -ExecutionPolicy Bypass -File .\compile.ps1
  ```

- macOS / Linux (PowerShell Core):

  ```bash
  cd Compiler
  pwsh -File ./compile.ps1
  ```

- To run a test build that copies the compiled JSON to the local TTS saves path (uses the `-test` switch):

  ```powershell
  cd Compiler
  pwsh -File ./compile.ps1 -test
  # The script will prompt for a version string; leave blank for no version.
  ```

Output: the script writes `ftc_base_compiled.json` (or `ftc_base_<version>_compiled.json`) in the `Compiler/` folder.

The base was completely built upon the FTC map!!!! And Continues to receive updates from it, thank you eternally for their help!
