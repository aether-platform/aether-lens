import os

root = r"c:\workspace\vibecoding-platform\aether-lens"
files_to_remove = [
    "ai-agent.py",
    "ai_agent.py",
    "entrypoint.py",
    "entrypoint.sh",
    "kilo-agent.py",
]

for file_name in files_to_remove:
    file_path = os.path.join(root, file_name)
    if os.path.exists(file_path):
        print(f"Removing {file_path}")
        os.remove(file_path)
    else:
        print(f"File not found: {file_path}")
