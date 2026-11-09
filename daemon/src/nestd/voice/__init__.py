"""Voice input (B154, D183): speech to text with a local Whisper model, for clients with no
dictation of their own (the phone and the Linux app). The engine lives in its own Python
environment in `<data_dir>/voice/`, fetched the first time it is wanted, and runs in a
worker process the daemon starts and stops.
"""
