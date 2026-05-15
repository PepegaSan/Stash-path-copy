#Requires AutoHotkey v2.0

; Stash Path Copy — paste helper for Windows file-open dialogs.
; Only runs when a classic file dialog is active (class #32770).
; Default hotkey: F20 — change below if needed (e.g. F8:: or ^!v::).

F20:: {
    if !WinActive("ahk_class #32770") {
        return
    }

    path := A_Clipboard
    if (path == "") {
        return
    }

    ; Paste full path into the file name field and confirm.
    ControlSetText(path, "Edit1", "A")
    ControlSend("{Enter}", "Edit1", "A")
}
