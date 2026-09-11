import PyInstaller.archive.readers
# Path to your generated .exe or binary file
reader = PyInstaller.archive.readers.CArchiveReader("dist/gremlinEx/gremlinEx.exe")

# Print all bundled Python modules
print("Files found in the archive:")
for entry_name in reader.toc:
    print(f" - {entry_name}")