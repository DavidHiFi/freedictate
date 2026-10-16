# Contributing

Thanks for helping FreeDictate get better. Bug reports, fixes and small ideas all count.

## Ways to help

- Report dictation bugs, wrong transcriptions and push-to-talk problems
- Send fixes for the Python engine and the Windows installer
- Test on other Windows 11 setups and share what breaks

## Getting set up

FreeDictate is a Python project. Install the dependencies with:

```
pip install -r requirements.txt
```

To build the app, which runs the tests, freezes with PyInstaller, self-tests and produces the Inno installer and a portable zip, use:

```
pwsh -File scripts\build.ps1
```

Useful flags: `-SkipInstaller` skips the Inno step, `-SkipTests` skips the test run and `-Python <path>` points at a specific Python.

## Checks before a pull request

- Run the build script without `-SkipTests` so the test suite passes
- Say which Windows build and audio setup you tested on

## Where to submit

Open issues and pull requests in this repository. Keep pull requests small so they are easy to review.