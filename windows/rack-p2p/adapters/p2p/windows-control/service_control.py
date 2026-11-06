"""Ask only the P2P console service to shut down gracefully."""
import win32event

handle = win32event.OpenEvent(win32event.EVENT_MODIFY_STATE, False, "Local\\NVISP2PConsoleStop")
try:
    win32event.SetEvent(handle)
finally:
    handle.Close()
