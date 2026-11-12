Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
strCurDir = FSO.GetParentFolderName(WScript.ScriptFullName)

' Prioritize native compiled GUI executable (already windowed with zero console clutter)
If FSO.FileExists(strCurDir & "\Urban Flow.exe") Then
    WshShell.Run """" & strCurDir & "\Urban Flow.exe""", 1, False
ElseIf FSO.FileExists(strCurDir & "\Urban Flow.bat") Then
    ' Use standard window style 1 (never hidden 0) to avoid antivirus/EDR dropper heuristics
    WshShell.Run """" & strCurDir & "\Urban Flow.bat""", 1, False
ElseIf FSO.FileExists(strCurDir & "\frontend\node_modules\electron\dist\electron.exe") Then
    WshShell.CurrentDirectory = strCurDir & "\frontend"
    WshShell.Run """" & strCurDir & "\frontend\node_modules\electron\dist\electron.exe"" .", 1, False
End If
