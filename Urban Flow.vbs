Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
strCurDir = FSO.GetParentFolderName(WScript.ScriptFullName)

If FSO.FileExists(strCurDir & "\Urban Flow.exe") Then
    WshShell.Run """" & strCurDir & "\Urban Flow.exe""", 1, False
ElseIf FSO.FileExists(strCurDir & "\Urban Flow.bat") Then
    WshShell.Run """" & strCurDir & "\Urban Flow.bat""", 0, False
Else
    WshShell.CurrentDirectory = strCurDir & "\frontend"
    WshShell.Run """" & strCurDir & "\frontend\node_modules\electron\dist\electron.exe"" .", 1, False
End If
