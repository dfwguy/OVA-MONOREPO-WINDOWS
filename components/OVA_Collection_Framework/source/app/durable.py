"""Unique temporary files, durable payloads and directory entry commits."""
import os, tempfile
from pathlib import Path

def sync_directory(directory):
    fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)

def atomic_write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(data.encode() if isinstance(data,str) else data);f.flush();os.fsync(f.fileno())
        os.replace(name,path);sync_directory(path.parent)
    finally:Path(name).unlink(missing_ok=True)

def sync_file(path):
    with open(path,'rb') as f:os.fsync(f.fileno())
